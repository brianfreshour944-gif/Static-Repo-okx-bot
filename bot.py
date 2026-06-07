#!/usr/bin/env python3
"""
OKX Grid Bot – Fee‑Aware Version
- Places limit orders around the current price
- Logs filled trades with exact exchange fees
- Supports kill switch (bot_status.status = 'STOP')
- Refreshes grid every 60 seconds
"""

import os
import time
import logging
import ccxt
import psycopg2
import sys
from dotenv import load_dotenv

load_dotenv()

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ---------- DATABASE HELPERS (with fee support) ----------
def log_error_to_db(bot_name, error_msg):
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                            (bot_name, str(error_msg)))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error to DB: {e}")

def log_trade_to_db(bot_name, symbol, side, price, quantity, value, fee, order_id):
    """Logs a filled trade including the fee."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Mark order as closed in bot_orders
                cur.execute("UPDATE bot_orders SET status = 'CLOSED' WHERE order_id = %s", (str(order_id),))
                # Insert into trades with fee column
                cur.execute("""
                    INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
                    VALUES (%s, 'OKX', %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (bot_name, symbol, side, float(price), float(quantity), float(value), float(fee), str(order_id)))
                conn.commit()
                logger.info(f"Trade logged: {side} {quantity} {symbol} @ {price} (fee: {fee})")
    except Exception as e:
        logger.error(f"Database write error: {e}")

def register_order_in_db(bot_name, order_id, symbol, side, price):
    """Registers a new open order in bot_orders."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_orders (order_id, bot_name, symbol, side, price, status)
                    VALUES (%s, %s, %s, %s, %s, 'OPEN')
                """, (str(order_id), bot_name, symbol, side, float(price)))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to register order: {e}")

def check_status(bot_name):
    """Kill switch: exit if bot_status.status = 'STOP'."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO bot_status (bot_name, last_update, status)
                    VALUES (%s, NOW(), 'RUNNING')
                    ON CONFLICT (bot_name) 
                    DO UPDATE SET last_update = NOW(), status = EXCLUDED.status
                """, (bot_name,))
                cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (bot_name,))
                row = cur.fetchone()
                if row and row[0] == 'STOP':
                    logger.warning(f"Kill switch activated for {bot_name}. Shutting down.")
                    sys.exit(0)
                conn.commit()
    except Exception as e:
        logger.error(f"Status check failed: {e}")

# ---------- BOT CLASS ----------
class OKXGridBot:
    def __init__(self):
        self.bot_name = os.getenv('BOT_NAME', 'OKX_Grid_Bot')
        self.symbol = 'DOGE/USDT'
        self.grid_levels = 5
        self.grid_step_percent = 1.25
        self.order_amount_usdt = 10

        self.active_order_ids = set()
        self.processed_order_ids = set()

        # Initialize exchange (sandbox)
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'app.okx.com',
            'options': {'defaultType': 'spot', 'x-simulated-trading': '1'}
        })
        self.exchange.set_sandbox_mode(True)

        self.test_connection()
        self.update_grid_orders()
        check_status(self.bot_name)

    # ---------- GRID LOGIC ----------
    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            logger.info(f"Connected! USDT balance: {usdt:.2f}")
        except Exception as e:
            log_error_to_db(self.bot_name, f"Connection failed: {e}")
            raise

    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            log_error_to_db(self.bot_name, f"Price fetch error: {e}")
            return None

    def calculate_grid_prices(self, center_price):
        grid_prices = []
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 - (self.grid_step_percent / 100) * i)
            grid_prices.append(('buy', round(price, 8)))
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 + (self.grid_step_percent / 100) * i)
            grid_prices.append(('sell', round(price, 8)))
        return grid_prices

    def cancel_all_open_orders(self):
        try:
            self.exchange.cancel_all_orders(self.symbol)
            self.active_order_ids.clear()
            # Mark old orders as cancelled in DB
            db_url = os.getenv('DATABASE_URL')
            if db_url:
                with psycopg2.connect(db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE bot_orders SET status = 'CANCELLED' WHERE bot_name = %s AND status = 'OPEN'", (self.bot_name,))
                        conn.commit()
            logger.info("Cancelled all open orders")
        except Exception as e:
            log_error_to_db(self.bot_name, f"Cancel orders error: {e}")

    def place_grid_orders(self, grid_prices):
        for side, price in grid_prices:
            qty = round(self.order_amount_usdt / price, 2)
            try:
                if side == 'buy':
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                else:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)

                register_order_in_db(self.bot_name, order['id'], self.symbol, side, price)
                self.active_order_ids.add(order['id'])
                logger.info(f"Placed {side.upper()} order @ {price:.8f} (qty {qty})")
            except Exception as e:
                log_error_to_db(self.bot_name, f"Failed to place {side} order: {e}")

    def update_grid_orders(self):
        price = self.get_current_price()
        if not price:
            return
        self.cancel_all_open_orders()
        grid = self.calculate_grid_prices(price)
        self.place_grid_orders(grid)
        logger.info(f"Grid refreshed. Center price: {price:.8f}")

    # ---------- ORDER SYNC & FEE EXTRACTION ----------
    def sync_filled_orders(self):
        """Fetch closed orders, log them with fees, and replace opposite order."""
        try:
            closed_orders = self.exchange.fetch_closed_orders(self.symbol, limit=50)
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.processed_order_ids:
                    continue
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    side = order['side'].upper()

                    # Extract fee from CCXT order object
                    fee_info = order.get('fee', {})
                    fee = float(fee_info.get('cost', 0.0)) if fee_info else 0.0

                    # Log trade with fee
                    log_trade_to_db(self.bot_name, self.symbol, side, price, qty, price * qty, fee, order_id)

                    self.processed_order_ids.add(order_id)
                    logger.info(f"Filled {side} @ {price:.8f} (qty {qty}, fee {fee:.6f})")

                    # Replace opposite order to keep grid alive
                    opposite_side = 'buy' if side == 'SELL' else 'sell'
                    try:
                        if opposite_side == 'buy':
                            new_order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                        else:
                            new_order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                        register_order_in_db(self.bot_name, new_order['id'], self.symbol, opposite_side, price)
                        logger.info(f"Replaced {side} with {opposite_side.upper()} @ {price:.8f}")
                    except Exception as e:
                        log_error_to_db(self.bot_name, f"Failed to replace order: {e}")
        except Exception as e:
            log_error_to_db(self.bot_name, f"Sync error: {e}")

    # ---------- MAIN LOOP ----------
    def run(self):
        logger.info(f"{self.bot_name} - Grid Bot Started")
        last_grid_refresh = time.time()
        while True:
            try:
                check_status(self.bot_name)
                current_price = self.get_current_price()
                if current_price:
                    self.sync_filled_orders()
                    if time.time() - last_grid_refresh > 60:
                        self.update_grid_orders()
                        last_grid_refresh = time.time()
                time.sleep(10)
            except Exception as e:
                log_error_to_db(self.bot_name, f"Main loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
