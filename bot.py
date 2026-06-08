import asyncio
import ccxt.pro as ccxt
import os
import logging
from sqlalchemy import create_engine, text

# ... (your existing config and DB helpers remain unchanged) ...

class GridBot:
    def __init__(self):
        # EXACTLY like the sync bot
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        # These two lines are critical – same as sync bot
        self.exchange.set_sandbox_mode(True)
        self.exchange.headers = {'x-simulated-trading': '1'}

        self.active_orders = {}
        self.running = True
        self.net_pnl = 0.0
        self.peak_equity = None

    # ... (all other methods exactly as before) ...

    async def place_order(self, side, price, amount):
        try:
            params = {'postOnly': True} if POST_ONLY else {}
            order = await self.exchange.create_order(SYMBOL, 'limit', side, amount, price, params)
            self.active_orders[order['id']] = {'side': side, 'price': price, 'amount': amount}
            logger.info(f"Placed {side} {amount:.2f} @ {price:.6f}")
            return order
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            log_error(f"place_order failed: {e}")
            return None

    async def cancel_all_orders(self):
        for oid in list(self.active_orders.keys()):
            try:
                await self.exchange.cancel_order(oid, SYMBOL)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Could not cancel {oid}: {e}")
        self.active_orders.clear()

    async def watch_orders(self):
        while self.running:
            try:
                orders = await self.exchange.watch_orders(SYMBOL)
                for order in orders:
                    if order['id'] in self.active_orders and order['status'] == 'closed':
                        filled_price = float(order['average'])
                        amount = float(order['filled'])
                        side = order['side']
                        fee = float(order['fee']['cost']) if order['fee'] else 0.0
                        value = amount * filled_price

                        trade_pnl = (-value - fee) if side == 'buy' else (value - fee)
                        self.net_pnl += trade_pnl
                        update_daily_loss(trade_pnl)

                        log_trade(BOT_NAME, 'OKX', SYMBOL, side, filled_price, amount, value, fee, order['id'])
                        logger.info(f"Filled {side} | P&L: {trade_pnl:.2f} | Total: {self.net_pnl:.2f}")

                        del self.active_orders[order['id']]
                        await self.place_opposite_order(side, filled_price, amount)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                log_error(f"watch_orders error: {e}")
                await asyncio.sleep(5)

    async def place_opposite_order(self, filled_side, price, amount):
        new_price = price * (1 + GRID_SPACING) if filled_side == 'buy' else price * (1 - GRID_SPACING)
        if MIN_PRICE <= new_price <= MAX_PRICE:
            new_side = 'sell' if filled_side == 'buy' else 'buy'
            await self.place_order(new_side, new_price, amount)
        else:
            logger.warning(f"Boundary reached: {new_price:.6f}")

    async def safety_monitor(self):
        while self.running:
            await asyncio.sleep(CHECK_INTERVAL)
            status = get_bot_status()
            if status['status'] != 'RUNNING':
                self.running = False
                break
            daily_loss = status['daily_loss']
            daily_limit = status['daily_loss_limit']
            if daily_loss <= -daily_limit or self.net_pnl <= STOP_LOSS_AMOUNT:
                self.running = False
                break
            if self.net_pnl >= TAKE_PROFIT_AMOUNT:
                self.running = False
                break
            # Drawdown check (optional, can be skipped for now)
            try:
                balance = await self.exchange.fetch_balance()
                usdt = balance['USDT']['free'] if 'USDT' in balance else 0
                ticker = await self.exchange.fetch_ticker(SYMBOL)
                base = SYMBOL.split('/')[0]
                base_bal = balance[base]['free'] if base in balance else 0
                equity = usdt + (base_bal * ticker['last'])
                if self.peak_equity is None: self.peak_equity = equity
                else:
                    self.peak_equity = max(self.peak_equity, equity)
                    dd = (self.peak_equity - equity) / self.peak_equity * 100
                    if dd >= MAX_DRAWDOWN_PCT:
                        self.running = False
            except Exception:
                pass

    async def deploy_initial_grid(self):
        ticker = await self.exchange.fetch_ticker(SYMBOL)
        mid = ticker['last']
        logger.info(f"Initial price: {mid:.6f}")
        for i in range(1, GRID_LEVELS + 1):
            buy = mid * (1 - i * GRID_SPACING)
            sell = mid * (1 + i * GRID_SPACING)
            amt = BASE_ORDER_SIZE / mid
            if MIN_PRICE <= buy <= MAX_PRICE:
                await self.place_order('buy', buy, amt)
            if MIN_PRICE <= sell <= MAX_PRICE:
                await self.place_order('sell', sell, amt)

    async def run(self):
        try:
            await self.exchange.load_markets()
            logger.info(f"Bot started: {BOT_NAME} on {SYMBOL}")
            # Test authentication
            bal = await self.exchange.fetch_balance()
            logger.info(f"✅ Auth OK! USDT balance: {bal['USDT']['free']}")
            status = get_bot_status()
            if status['status'] != 'RUNNING':
                logger.info("Bot is STOPPED in database. Exiting.")
                return
            await self.deploy_initial_grid()
            await asyncio.gather(self.watch_orders(), self.safety_monitor())
        except Exception as e:
            logger.error(f"Critical bot error: {e}")
            log_error(f"Critical error: {e}")
        finally:
            await self.cancel_all_orders()
            await self.exchange.close()

if __name__ == "__main__":
    bot = GridBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        asyncio.run(bot.cancel_all_orders())
