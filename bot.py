
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
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///grid_bot.db")
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

BOT_NAME = "okx_grid_bot"
SYMBOL = "DOGE/USDT"

GRID_LEVELS = 6
BASE_ORDER_SIZE_USDT = 80
MIN_PRICE = 0.07
MAX_PRICE = 0.14

# Reactivity Settings
RECENTER_THRESHOLD_PCT = 0.009     # 0.9% move → recenter (very reactive)
CHECK_INTERVAL = 60                # Check every 60 seconds
MIN_REDEPLOY_COOLDOWN = 300        # 5 minutes minimum between full redeploys

STOP_LOSS_AMOUNT = -80
TAKE_PROFIT_AMOUNT = 180
MAX_DAILY_LOSS_USDT = 150
MAX_DRAWDOWN_PCT = 12

# ====================== DATABASE HELPERS ======================
# Paste all your existing functions here (init_db, log_trade, update_daily_loss, get_bot_status, log_error)
# I'll assume you copy them from your working grid bot

def init_db():
    # ... (your existing init_db function)
    pass

# ... [Copy your log_trade, update_daily_loss, get_bot_status, log_error here] ...

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
            'options': {
                'defaultType': 'spot',
                'x-simulated-trading': '1'
            }
        })
        self.exchange.set_sandbox_mode(True)
        self.exchange.load_markets()

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

    async def deploy_grid(self, mid_price: float):
        self.last_grid_center = mid_price
        self.last_redeploy_time = datetime.now().timestamp()

        # Dynamic spacing
        df = await self.fetch_ohlcv(80)
        atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
        volatility = atr / mid_price
        spacing = max(0.008, min(0.035, volatility * 2.1))

        amount = BASE_ORDER_SIZE_USDT / mid_price

        logger.info(f"🔄 Deploying Reactive Grid | Center: {mid_price:.6f} | Spacing: {spacing:.4f} | Vol: {volatility:.1%}")

        await self.cancel_all_orders()

        for i in range(1, GRID_LEVELS + 1):
            buy_price = mid_price * (1 - i * spacing)
            sell_price = mid_price * (1 + i * spacing)

            if MIN_PRICE <= buy_price <= MAX_PRICE:
                await self.place_order('buy', buy_price, amount)
            if MIN_PRICE <= sell_price <= MAX_PRICE:
                await self.place_order('sell', sell_price, amount)

    async def chase_monitor(self):
        """Main reactive loop - makes the bot chase price movement"""
        while self.running:
            try:
                ticker = await self.fetch_ticker()
                current_price = ticker['last']

                now = datetime.now().timestamp()
                time_since_last = now - self.last_redeploy_time

                if (self.last_grid_center is None or 
                    abs(current_price - self.last_grid_center) / self.last_grid_center > RECENTER_THRESHOLD_PCT) and \
                   time_since_last > MIN_REDEPLOY_COOLDOWN:

                    logger.info(f"📈 Price moved → Recentering grid (move: {(abs(current_price - self.last_grid_center)/self.last_grid_center*100):.2f}%)")
                    await self.deploy_grid(current_price)

                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"Chase monitor error: {e}")
                await asyncio.sleep(30)

    # Keep your original methods: place_order, cancel_all_orders, monitor_orders, place_opposite_order, safety_monitor

    async def run(self):
        try:
            logger.info(f"🚀 Starting Reactive Chasing Grid Bot on {SYMBOL}")
            init_db()

            status = get_bot_status()
            if status['status'] != 'RUNNING':
                logger.warning("Bot is STOPPED in database.")
                return

            # Initial grid
            ticker = await self.fetch_ticker()
            await self.deploy_grid(ticker['last'])

            # Run all tasks together
            await asyncio.gather(
                self.monitor_orders(),
                self.safety_monitor(),
                self.chase_monitor(),
                return_exceptions=True
            )

        except Exception as e:
            logger.error(f"Critical error: {e}")
        finally:
            await self.cancel_all_orders()


if __name__ == "__main__":
    bot = ReactiveGridBot()
    asyncio.run(bot.run())
