import asyncio
import ccxt
import os
import logging
from sqlalchemy import create_engine, text
from datetime import datetime

# ====================== CONFIGURATION ======================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GridBot")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg2://", "postgresql://")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///grid_bot.db"  # fallback for local testing

engine = create_engine(DATABASE_URL, echo=False)

# Bot Settings
BOT_NAME = "okx_grid_bot"
SYMBOL = "DOGE/USDT"
GRID_LEVELS = 5
GRID_SPACING = 0.01          # 1% grid
BASE_ORDER_SIZE = 100        # USDT per order
MIN_PRICE = 0.08
MAX_PRICE = 0.12
POST_ONLY = True
STOP_LOSS_AMOUNT = -50
TAKE_PROFIT_AMOUNT = 100
MAX_DRAWDOWN_PCT = 15
CHECK_INTERVAL = 5

# ====================== DATABASE HELPERS ======================
def init_db():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_status (
                bot_name TEXT PRIMARY KEY,
                status TEXT DEFAULT 'STOP',
                daily_loss NUMERIC DEFAULT 0,
                daily_loss_limit NUMERIC DEFAULT 100,
                config TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS trades (
                id SERIAL PRIMARY KEY,
                bot_name TEXT,
                exchange TEXT,
                symbol TEXT,
                side TEXT,
                price NUMERIC,
                quantity NUMERIC,
                value NUMERIC,
                fee NUMERIC,
                order_id TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_errors (
                id SERIAL PRIMARY KEY,
                bot_name TEXT,
                error_message TEXT,
                timestamp TIMESTAMP DEFAULT NOW()
            );
        """))
        # Ensure bot status row exists
        conn.execute(text("""
            INSERT INTO bot_status (bot_name, status, daily_loss, daily_loss_limit)
            VALUES (:name, 'STOP', 0, 100)
            ON CONFLICT (bot_name) DO NOTHING;
        """), {"name": BOT_NAME})
        conn.commit()

def log_trade(bot_name, exchange, symbol, side, price, quantity, value, fee, order_id):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
                VALUES (:bot, :ex, :sym, :side, :price, :qty, :val, :fee, :oid, NOW())
            """), {"bot": bot_name, "ex": exchange, "sym": symbol, "side": side,
                   "price": price, "qty": quantity, "val": value, "fee": fee, "oid": order_id})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")

def update_daily_loss(amount):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE bot_status 
                SET daily_loss = daily_loss + :amt 
                WHERE bot_name = :name
            """), {"amt": amount, "name": BOT_NAME})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to update daily loss: {e}")

def get_bot_status():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT status, daily_loss, daily_loss_limit 
                FROM bot_status WHERE bot_name = :name
            """), {"name": BOT_NAME})
            row = result.fetchone()
            if row:
                return {"status": row[0], "daily_loss": float(row[1] or 0), "daily_loss_limit": float(row[2] or 100)}
    except Exception as e:
        logger.error(f"Failed to get bot status: {e}")
    
    # Fallback
    return {"status": "STOP", "daily_loss": 0, "daily_loss_limit": 100}

def log_error(msg):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO bot_errors (bot_name, error_message, timestamp)
                VALUES (:name, :msg, NOW())
            """), {"name": BOT_NAME, "msg": msg})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error: {e}")

# ====================== GRID BOT ======================
class GridBot:
    def __init__(self):
        # Debug API keys
        api_key = os.getenv('OKX_API_KEY')
        logger.info(f"OKX_API_KEY: {'SET' if api_key else 'MISSING'} ({(api_key[:8] + '...') if api_key else ''})")
        
        self.exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'headers': {'x-simulated-trading': '1'}   # OKX Demo/Simulated trading
            }
        })

        # Test connection
        try:
            self.exchange.load_markets()
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            logger.info(f"✅ Authentication successful! USDT balance: {usdt}")
        except Exception as e:
            logger.error(f"❌ Authentication failed: {e}")
            log_error(f"Auth failed: {e}")
            raise

        self.active_orders = {}
        self.running = True
        self.net_pnl = 0.0
        self.peak_equity = None

    async def _run_sync(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def place_order(self, side: str, price: float, amount: float):
        try:
            params = {'postOnly': True} if POST_ONLY else {}
            order = await self._run_sync(
                self.exchange.create_order, SYMBOL, 'limit', side, amount, price, params
            )
            self.active_orders[order['id']] = {'side': side, 'price': price, 'amount': amount}
            logger.info(f"✅ Placed {side.upper()} {amount:.4f} @ {price:.6f} | ID: {order['id']}")
            return order
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            log_error(f"place_order failed: {e}")
            return None

    async def cancel_all_orders(self):
        for oid in list(self.active_orders.keys()):
            try:
                await self._run_sync(self.exchange.cancel_order, oid, SYMBOL)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Could not cancel {oid}: {e}")
        self.active_orders.clear()

    async def fetch_balance(self):
        return await self._run_sync(self.exchange.fetch_balance)

    async def fetch_ticker(self):
        return await self._run_sync(self.exchange.fetch_ticker, SYMBOL)

    async def monitor_orders(self):
        while self.running:
            await asyncio.sleep(2)
            try:
                for oid in list(self.active_orders.keys()):
                    order = await self._run_sync(self.exchange.fetch_order, oid, SYMBOL)
                    if order['status'] == 'closed' and oid in self.active_orders:
                        filled_price = float(order['average'] or order['price'])
                        amount = float(order['filled'])
                        side = order['side']
                        fee = float(order.get('fee', {}).get('cost', 0))
                        value = amount * filled_price
                        trade_pnl = (-value - fee) if side == 'buy' else (value - fee)

                        self.net_pnl += trade_pnl
                        update_daily_loss(trade_pnl)
                        log_trade(BOT_NAME, 'OKX', SYMBOL, side, filled_price, amount, value, fee, oid)

                        logger.info(f"✅ Filled {side.upper()} | P&L: {trade_pnl:+.2f} | Total: {self.net_pnl:+.2f}")

                        del self.active_orders[oid]
                        await self.place_opposite_order(side, filled_price, amount)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)

    async def place_opposite_order(self, filled_side: str, price: float, amount: float):
        multiplier = (1 + GRID_SPACING) if filled_side == 'buy' else (1 - GRID_SPACING)
        new_price = price * multiplier

        if MIN_PRICE <= new_price <= MAX_PRICE:
            new_side = 'sell' if filled_side == 'buy' else 'buy'
            await self.place_order(new_side, new_price, amount)
        else:
            logger.warning(f"Boundary reached for opposite order: {new_price:.6f}")

    async def safety_monitor(self):
        while self.running:
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                status = get_bot_status()
                if status['status'] != 'RUNNING':
                    logger.info("Bot stopped via dashboard")
                    self.running = False
                    break

                if status['daily_loss'] <= -status['daily_loss_limit']:
                    logger.warning("Daily loss limit reached!")
                    self.running = False
                    break

                if self.net_pnl <= STOP_LOSS_AMOUNT:
                    logger.warning("Stop-loss triggered")
                    self.running = False
                    break

                if self.net_pnl >= TAKE_PROFIT_AMOUNT:
                    logger.info("Take-profit reached")
                    self.running = False
                    break

                # Drawdown check
                balance = await self.fetch_balance()
                ticker = await self.fetch_ticker()
                current_price = ticker['last']
                base = SYMBOL.split('/')[0]

                usdt = balance.get('USDT', {}).get('free', 0)
                base_bal = balance.get(base, {}).get('free', 0)
                equity = usdt + (base_bal * current_price)

                if self.peak_equity is None:
                    self.peak_equity = equity
                else:
                    self.peak_equity = max(self.peak_equity, equity)
                    dd = (self.peak_equity - equity) / self.peak_equity * 100
                    if dd >= MAX_DRAWDOWN_PCT:
                        logger.warning(f"Max drawdown reached: {dd:.1f}%")
                        self.running = False
            except Exception as e:
                logger.warning(f"Safety monitor error: {e}")

    async def deploy_initial_grid(self):
        ticker = await self.fetch_ticker()
        mid = ticker['last']
        logger.info(f"Deploying grid around price: {mid:.6f}")

        for i in range(1, GRID_LEVELS + 1):
            buy_price = mid * (1 - i * GRID_SPACING)
            sell_price = mid * (1 + i * GRID_SPACING)
            amount = BASE_ORDER_SIZE / mid

            if MIN_PRICE <= buy_price <= MAX_PRICE:
                await self.place_order('buy', buy_price, amount)
            if MIN_PRICE <= sell_price <= MAX_PRICE:
                await self.place_order('sell', sell_price, amount)

    async def run(self):
        try:
            logger.info(f"🚀 Starting {BOT_NAME} on {SYMBOL}")
            init_db()

            status = get_bot_status()
            if status['status'] != 'RUNNING':
                logger.info("Bot is STOPPED in database. Set status to RUNNING to start.")
                return

            await self.deploy_initial_grid()
            await asyncio.gather(self.monitor_orders(), self.safety_monitor())

        except Exception as e:
            logger.error(f"Critical error: {e}")
            log_error(str(e))
        finally:
            logger.info("Shutting down...")
            await self.cancel_all_orders()


if __name__ == "__main__":
    bot = GridBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt - shutting down gracefully")
        asyncio.run(bot.cancel_all_orders())
    except Exception as e:
        logger.error(f"Fatal startup error: {e}")
