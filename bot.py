import asyncio
import ccxt
import os
import logging
import sys
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("ReactiveGridBot")

# ====================== CONFIG ======================
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL and "psycopg2" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///grid_bot.db"

engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

BOT_NAME = "okx_grid_bot"
SYMBOL = "DOGE/USDT"

GRID_LEVELS = 6
BASE_ORDER_SIZE_USDT = 80
MIN_PRICE = 0.07
MAX_PRICE = 0.14

RECENTER_THRESHOLD_PCT = 0.009
CHECK_INTERVAL = 60
MIN_REDEPLOY_COOLDOWN = 300

STOP_LOSS_AMOUNT = -80
TAKE_PROFIT_AMOUNT = 180
MAX_DAILY_LOSS_USDT = 150
MAX_DRAWDOWN_PCT = 12

# ====================== DATABASE HELPERS ======================
def init_db():
    try:
        with engine.connect() as conn:
            # bot_status
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_status (
                    bot_name TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'STOP',
                    daily_loss NUMERIC DEFAULT 0,
                    daily_loss_limit NUMERIC DEFAULT 100
                );
            """))
            
            # trades - PostgreSQL compatible
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
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # bot_errors
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_errors (
                    id SERIAL PRIMARY KEY,
                    bot_name TEXT,
                    error_message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            
            # Add last_reset column if not exists
            try:
                conn.execute(text("ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS last_reset TIMESTAMP"))
                conn.commit()
            except Exception:
                pass  # Column may already exist or not supported (SQLite)
            
            conn.execute(text("""
                INSERT INTO bot_status (bot_name, status) 
                VALUES (:name, 'RUNNING')
                ON CONFLICT (bot_name) DO NOTHING;
            """), {"name": BOT_NAME})
            
            conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"DB init failed: {e}")
        raise

def log_trade(bot_name, exchange, symbol, side, price, quantity, value, fee, order_id):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
                VALUES (:bot, :ex, :sym, :side, :price, :qty, :val, :fee, :oid, CURRENT_TIMESTAMP)
            """), {"bot": bot_name, "ex": exchange, "sym": symbol, "side": side,
                   "price": price, "qty": quantity, "val": value, "fee": fee, "oid": order_id})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")

def update_daily_loss(amount):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE bot_status SET daily_loss = daily_loss + :amt WHERE bot_name = :name
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
    return {"status": "RUNNING", "daily_loss": 0, "daily_loss_limit": 100}

def log_error(msg):
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO bot_errors (bot_name, error_message, timestamp)
                VALUES (:name, :msg, CURRENT_TIMESTAMP)
            """), {"name": BOT_NAME, "msg": msg})
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error: {e}")

# ====================== REACTIVE GRID BOT ======================
class ReactiveGridBot:
    def __init__(self):
        logger.info("=== Starting Reactive Chasing Grid Bot ===")

        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'app.okx.com',
            'options': {'defaultType': 'spot', 'x-simulated-trading': '1'}
        })
        self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()
        logger.info("✅ OKX Connected")

        self.active_orders = {}
        self.running = True
        self.net_pnl = 0.0
        self.peak_equity = None
        self.last_grid_center = None
        self.last_redeploy_time = 0

    async def _run_sync(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    async def fetch_ticker(self):
        return await self._run_sync(self.exchange.fetch_ticker, SYMBOL)

    async def fetch_ohlcv(self, limit=100):
        data = await self._run_sync(self.exchange.fetch_ohlcv, SYMBOL, '5m', limit=limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    async def place_order(self, side, price, amount):
        try:
            params = {'postOnly': True}
            order = await self._run_sync(self.exchange.create_order, SYMBOL, 'limit', side, amount, price, params)
            self.active_orders[order['id']] = {'side': side, 'price': price, 'amount': amount}
            logger.info(f"✅ Placed {side.upper()} {amount:.4f} @ {price:.6f}")
            return order
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            log_error(str(e))
            return None

    async def cancel_all_orders(self):
        for oid in list(self.active_orders.keys()):
            try:
                await self._run_sync(self.exchange.cancel_order, oid, SYMBOL)
                logger.info(f"Cancelled order {oid}")
            except Exception as e:
                logger.warning(f"Could not cancel {oid}: {e}")
        self.active_orders.clear()

    async def deploy_grid(self, mid_price: float):
        self.last_grid_center = mid_price
        self.last_redeploy_time = datetime.now().timestamp()

        df = await self.fetch_ohlcv(80)
        atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        volatility = atr / mid_price
        spacing = max(0.008, min(0.035, volatility * 2.1))

        amount = BASE_ORDER_SIZE_USDT / mid_price

        logger.info(f"🔄 Deploying Reactive Grid | Center: {mid_price:.6f} | Spacing: {spacing:.4f}")

        await self.cancel_all_orders()

        for i in range(1, GRID_LEVELS + 1):
            buy_price = mid_price * (1 - i * spacing)
            sell_price = mid_price * (1 + i * spacing)
            if MIN_PRICE <= buy_price <= MAX_PRICE:
                await self.place_order('buy', buy_price, amount)
            if MIN_PRICE <= sell_price <= MAX_PRICE:
                await self.place_order('sell', sell_price, amount)

    async def monitor_orders(self):
        while self.running:
            await asyncio.sleep(2)
            try:
                for oid in list(self.active_orders.keys()):
                    order = await self._run_sync(self.exchange.fetch_order, oid, SYMBOL)
                    if order.get('status') == 'closed' and oid in self.active_orders:
                        filled_price = float(order.get('average') or order.get('price'))
                        amount = float(order.get('filled'))
                        side = order['side']
                        fee = float(order.get('fee', {}).get('cost', 0) if order.get('fee') else 0)
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

    async def place_opposite_order(self, filled_side, price, amount):
        multiplier = (1 + 0.012) if filled_side == 'buy' else (1 - 0.012)
        new_price = price * multiplier
        if MIN_PRICE <= new_price <= MAX_PRICE:
            new_side = 'sell' if filled_side == 'buy' else 'buy'
            await self.place_order(new_side, new_price, amount)

    async def safety_monitor(self):
        while self.running:
            await asyncio.sleep(10)
            try:
                status = get_bot_status()
                if status['status'] != 'RUNNING':
                    logger.info("Bot stopped via dashboard")
                    self.running = False
                    break
                if status.get('daily_loss', 0) <= -MAX_DAILY_LOSS_USDT:
                    logger.warning("Daily loss limit reached!")
                    self.running = False
                    break
            except Exception as e:
                logger.warning(f"Safety monitor error: {e}")

    async def chase_monitor(self):
        while self.running:
            try:
                ticker = await self.fetch_ticker()
                current = ticker['last']
                now = datetime.now().timestamp()

                if (self.last_grid_center is None or 
                    abs(current - self.last_grid_center) / self.last_grid_center > RECENTER_THRESHOLD_PCT) and \
                   (now - self.last_redeploy_time > MIN_REDEPLOY_COOLDOWN):

                    logger.info(f"📈 Price moved → Recentering grid at {current:.6f}")
                    await self.deploy_grid(current)

                await asyncio.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Chase monitor error: {e}")
                await asyncio.sleep(30)

    # ====================== NEW FIXES ======================
    def reset_daily_loss_if_new_day(self):
        """Reset daily_loss to 0 if it's a new calendar day."""
        try:
            with engine.connect() as conn:
                # Ensure last_reset column exists (already handled in init_db, but safe)
                try:
                    conn.execute(text("ALTER TABLE bot_status ADD COLUMN IF NOT EXISTS last_reset TIMESTAMP"))
                    conn.commit()
                except:
                    pass
                
                row = conn.execute(
                    text("SELECT last_reset FROM bot_status WHERE bot_name = :name"),
                    {"name": BOT_NAME}
                ).fetchone()
                
                today = datetime.now().date()
                should_reset = False
                if not row or row[0] is None:
                    should_reset = True
                else:
                    last_reset_date = row[0].date() if isinstance(row[0], datetime) else row[0]
                    should_reset = today > last_reset_date
                
                if should_reset:
                    conn.execute(
                        text("UPDATE bot_status SET daily_loss = 0, last_reset = CURRENT_TIMESTAMP WHERE bot_name = :name"),
                        {"name": BOT_NAME}
                    )
                    conn.commit()
                    logger.info("🔄 Daily loss reset for new day")
        except Exception as e:
            logger.error(f"Failed to reset daily loss: {e}")

    async def fetch_account_state(self):
        """Get current balances and open orders from exchange."""
        try:
            # Get spot balance
            balance = await self._run_sync(self.exchange.fetch_balance)
            usdt_balance = balance['USDT']['free'] if 'USDT' in balance else 0
            doge_balance = balance['DOGE']['free'] if 'DOGE' in balance else 0
            
            # Get open orders
            open_orders = await self._run_sync(self.exchange.fetch_open_orders, SYMBOL)
            
            logger.info(f"💰 Balance: USDT {usdt_balance:.2f}, DOGE {doge_balance:.2f}")
            if open_orders:
                logger.info(f"📋 Found {len(open_orders)} open orders on exchange")
                for o in open_orders:
                    self.active_orders[o['id']] = {
                        'side': o['side'],
                        'price': o['price'],
                        'amount': o['amount']
                    }
            
            return usdt_balance, doge_balance
        except Exception as e:
            logger.error(f"Failed to fetch account state: {e}")
            return 0, 0

    async def sync_daily_loss_from_trades(self):
        """Recalculate daily_loss based on today's actual trades."""
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COALESCE(SUM(
                            CASE WHEN side = 'buy' THEN -value 
                                 ELSE value 
                            END
                        ), 0) as total_pnl
                        FROM trades 
                        WHERE bot_name = :name AND timestamp >= :today
                    """),
                    {"name": BOT_NAME, "today": today_start}
                )
                row = result.fetchone()
                actual_pnl = float(row[0]) if row else 0
                
                # Update database
                conn.execute(
                    text("UPDATE bot_status SET daily_loss = :pnl WHERE bot_name = :name"),
                    {"pnl": actual_pnl, "name": BOT_NAME}
                )
                conn.commit()
                self.net_pnl = actual_pnl
                logger.info(f"📊 Synced daily loss to {actual_pnl:.2f} from trade history")
                return actual_pnl
        except Exception as e:
            logger.error(f"Failed to sync daily loss: {e}")
            return 0

    async def run(self):
        try:
            logger.info(f"🚀 Starting Reactive Chasing Grid Bot on {SYMBOL}")
            init_db()
            
            # Reset daily loss at midnight
            self.reset_daily_loss_if_new_day()
            
            # Sync actual P&L from trades
            await self.sync_daily_loss_from_trades()
            
            # Check safety after sync
            # Check safety after sync
            status = get_bot_status()
            if status['status'] != 'RUNNING':
                logger.warning("Bot is STOPPED in database.")
                return
            
            if status.get('daily_loss', 0) <= -MAX_DAILY_LOSS_USDT:
                logger.error(f"Daily loss {status['daily_loss']:.2f} exceeds limit {MAX_DAILY_LOSS_USDT}. Entering IDLE mode.")
                # Instead of crashing the container, we pause indefinitely.
                # This keeps the container "Healthy" (exit code 0) so it doesn't restart.
                while True:
                    await asyncio.sleep(86400) # Sleeps for 24 hours, effectively pausing the bot
            
            # Fetch existing open orders and balances
            await self.fetch_account_state()
            
            # If there's a grid center in active orders, recover it
            if self.active_orders:
                # Estimate center from first order price (simplified)
                prices = [o['price'] for o in self.active_orders.values()]
                if prices:
                    mid_estimate = sum(prices) / len(prices)
                    self.last_grid_center = mid_estimate
                    self.last_redeploy_time = datetime.now().timestamp()
                    logger.info(f"🔁 Recovered grid center at {mid_estimate:.6f}")
            
            ticker = await self.fetch_ticker()
            
            # Only redeploy if no active orders OR price moved significantly
            if not self.active_orders or (self.last_grid_center and 
                abs(ticker['last'] - self.last_grid_center) / self.last_grid_center > RECENTER_THRESHOLD_PCT):
                await self.deploy_grid(ticker['last'])
            else:
                logger.info("✅ Using existing grid orders from previous session")
            
            await asyncio.gather(
                self.monitor_orders(),
                self.safety_monitor(),
                self.chase_monitor(),
                return_exceptions=True
            )
            
        except Exception as e:
            logger.error(f"Critical error: {e}")
            log_error(str(e))
        finally:
            await self.cancel_all_orders()
            # If we stopped due to daily loss, exit with error to prevent restart loops
            status = get_bot_status()
            if status.get('daily_loss', 0) <= -MAX_DAILY_LOSS_USDT:
                logger.error("Exiting due to daily loss limit. Will not auto-restart.")
                sys.exit(1)

if __name__ == "__main__":
    bot = ReactiveGridBot()
    asyncio.run(bot.run())
