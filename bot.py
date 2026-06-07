import asyncio
import ccxt.pro as ccxt
import os
import logging
from sqlalchemy import create_engine, text

# ====================== CONFIGURATION ======================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GridBot")

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg2://", "postgresql://")
engine = create_engine(DATABASE_URL)

BOT_NAME = "okx_grid_bot"
SYMBOL = "DOGE/USDT"
GRID_LEVELS = 5
GRID_SPACING = 0.01
BASE_ORDER_SIZE = 100
MIN_PRICE = 0.08
MAX_PRICE = 0.12

# ====================== DATABASE HELPERS ======================
def get_bot_status():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT status FROM bot_status WHERE bot_name = :name"), {"name": BOT_NAME})
        row = result.fetchone()
        return {"status": row[0] if row else "STOP"}

# ====================== GRID BOT ======================
class GridBot:
    def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'hostname': 'app.okx.com',
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        self.active_orders = {}
        self.running = True

    async def place_order(self, side, price, amount):
        try:
            # Magic Header to force Simulation on Production infrastructure
            params = {'postOnly': True, 'headers': {'x-simulated-trading': '1'}}
            order = await self.exchange.create_order(SYMBOL, 'limit', side, amount, price, params)
            self.active_orders[order['id']] = {'side': side, 'price': price, 'amount': amount}
            logger.info(f"Placed {side} {amount:.2f} @ {price:.6f}")
            return order
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None

    async def cancel_all_orders(self):
        for oid in list(self.active_orders.keys()):
            try:
                await self.exchange.cancel_order(oid, SYMBOL)
            except:
                pass
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
                        del self.active_orders[order['id']]
                        new_price = filled_price * (1 + GRID_SPACING) if side == 'buy' else filled_price * (1 - GRID_SPACING)
                        await self.place_order('sell' if side == 'buy' else 'buy', new_price, amount)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)

    async def deploy_initial_grid(self):
        ticker = await self.exchange.fetch_ticker(SYMBOL)
        mid = ticker['last']
        for i in range(1, GRID_LEVELS + 1):
            amount = BASE_ORDER_SIZE / mid
            await self.place_order('buy', mid * (1 - i * GRID_SPACING), amount)
            await self.place_order('sell', mid * (1 + i * GRID_SPACING), amount)

    async def run(self):
        try:
            # Use fetch_market instead of load_markets to avoid private endpoint auth errors
            await self.exchange.fetch_market(SYMBOL)
            logger.info(f"Bot started: {BOT_NAME}")
            
            if get_bot_status()['status'] == 'RUNNING':
                await self.deploy_initial_grid()
                await self.watch_orders()
        finally:
            await self.cancel_all_orders()
            await self.exchange.close()

if __name__ == "__main__":
    bot = GridBot()
    asyncio.run(bot.run())
