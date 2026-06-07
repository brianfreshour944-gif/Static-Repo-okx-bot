#!/usr/bin/env python3
import os
import time
import ccxt
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'app.okx.com',
            'options': {'defaultType': 'spot', 'x-simulated-trading': '1'}
        })
        self.exchange.set_sandbox_mode(True)

        self.bot_name = os.getenv('BOT_NAME', 'Static-Repo-okx-bot')
        self.symbol = 'DOGE/USDT'
        self.grid_levels = 3               # only 3 levels each side
        self.grid_step_percent = 4.0       # wide enough for demo fees
        self.order_amount_usdt = 10
        
        self.processed_order_ids = set()
        self.test_connection()
        self.update_grid_orders()

    # ---------- DATABASE HELPERS ----------
    def log_error_to_db(self, error_msg):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                        (self.bot_name, str(error_msg))
                    )
                    conn.commit()
        except Exception as e:
            print(f"❌ Failed to log error: {e}")

    def log_trade_to_postgres(self, side, price, qty, order_id, fee=0.0):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO trades 
                        (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (self.bot_name, "OKX", self.symbol, side, price, qty, (price * qty), fee, order_id))
                    conn.commit()
        except Exception as e:
            self.log_error_to_db(f"Trade log error: {e}")

    def check_status(self):
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
                    """, (self.bot_name,))
                    cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (self.bot_name,))
                    row = cur.fetchone()
                    if row and row[0] == 'STOP':
                        print(f"🛑 Kill switch activated for {self.bot_name}. Shutting down.")
                        exit(0)
                    conn.commit()
        except Exception as e:
            self.log_error_to_db(f"Status check error: {e}")

    # ---------- GRID LOGIC ----------
    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            self.log_error_to_db(f"Price fetch error: {e}")
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
            print("✅ Cancelled all open orders")
        except Exception as e:
            self.log_error_to_db(f"Cancel orders error: {e}")

    def place_grid_orders(self, grid_prices):
        db_url = os.getenv('DATABASE_URL')
        for side, price in grid_prices:
            qty = round(self.order_amount_usdt / price, 2)
            try:
                if side == 'buy':
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                else:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                if db_url:
                    with psycopg2.connect(db_url) as conn:
                        with conn.cursor() as cur:
                            cur.execute("""
                                INSERT INTO bot_orders (order_id, bot_name, symbol, side, price, status)
                                VALUES (%s, %s, %s, %s, %s, 'OPEN')
                            """, (order['id'], self.bot_name, self.symbol, side, price))
                            conn.commit()
                print(f"📌 Placed {side.upper()} order @ {price:.8f} (qty {qty}) for {self.bot_name}")
            except Exception as e:
                self.log_error_to_db(f"Failed to place {side} order: {e}")

    def update_grid_orders(self):
        price = self.get_current_price()
        if not price:
            return
        self.cancel_all_open_orders()
        grid = self.calculate_grid_prices(price)
        self.place_grid_orders(grid)
        print(f"🌐 Grid refreshed. Center price: {price:.8f}")

    def sync_filled_orders(self):
        """Only log fills – NO replacement. Grid will refresh in 60 seconds."""
        try:
            closed_orders = self.exchange.fetch_closed_orders(self.symbol, limit=50)
            db_url = os.getenv('DATABASE_URL')
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.processed_order_ids:
                    continue
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    side = order['side'].upper()

                    fee_info = order.get('fee', {})
                    fee = float(fee_info.get('cost', 0.0)) if fee_info else 0.0

                    self.log_trade_to_postgres(side, price, qty, order_id, fee=fee)

                    if db_url:
                        with psycopg2.connect(db_url) as conn:
                            with conn.cursor() as cur:
                                cur.execute("UPDATE bot_orders SET status = 'CLOSED' WHERE order_id = %s", (order_id,))
                                conn.commit()

                    self.processed_order_ids.add(order_id)
                    print(f"✅ {side} FILLED @ {price:.8f} (qty {qty}, fee {fee:.6f})")
        except Exception as e:
            self.log_error_to_db(f"Sync error: {e}")

    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            print(f"✅ Connected! USDT balance: {usdt:.2f}")
        except Exception as e:
            self.log_error_to_db(f"Connection failed: {e}")
            raise

    def run(self):
        print(f"🤖 {self.bot_name} - Grid Bot Started")
        last_grid_refresh = time.time()
        while True:
            try:
                self.check_status()
                current_price = self.get_current_price()
                if current_price:
                    self.sync_filled_orders()
                    # Refresh grid every 60 seconds (moves with the market)
                    if time.time() - last_grid_refresh > 60:
                        self.update_grid_orders()
                        last_grid_refresh = time.time()
                time.sleep(10)
            except Exception as e:
                self.log_error_to_db(f"Main loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
