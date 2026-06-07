#!/usr/bin/env python3
import os
import time
import ccxt
import psycopg2
from dotenv import load_dotenv
from collections import deque

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
        self.grid_levels = 3
        self.grid_step_percent = 4.0
        self.order_amount_usdt = 10
        
        # Use a deque to keep track of processed orders without growing infinitely
        self.processed_order_ids = deque(maxlen=100) 
        self.test_connection()

    # ---------- DATABASE HELPERS ----------
    def log_error_to_db(self, error_msg):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                                (self.bot_name, str(error_msg)))
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
                    cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (self.bot_name,))
                    row = cur.fetchone()
                    if row and row[0] == 'STOP':
                        exit(0)
        except Exception as e:
            self.log_error_to_db(f"Status check error: {e}")

    # ---------- GRID LOGIC ----------
    def get_current_price(self):
        try:
            return self.exchange.fetch_ticker(self.symbol)['last']
        except Exception as e:
            self.log_error_to_db(f"Price fetch error: {e}")
            return None

    def calculate_grid_prices(self, center_price):
        grid_prices = []
        for i in range(1, self.grid_levels + 1):
            grid_prices.append(('buy', round(center_price * (1 - (self.grid_step_percent / 100) * i), 8)))
        for i in range(1, self.grid_levels + 1):
            grid_prices.append(('sell', round(center_price * (1 + (self.grid_step_percent / 100) * i), 8)))
        return grid_prices

    def place_single_order(self, side, price, qty):
        try:
            params = {'postOnly': True} # Ensures Maker status
            if side == 'buy':
                order = self.exchange.create_limit_buy_order(self.symbol, qty, price, params=params)
            else:
                order = self.exchange.create_limit_sell_order(self.symbol, qty, price, params=params)
            print(f"📌 Placed {side.upper()} @ {price:.8f}")
            return order
        except Exception as e:
            self.log_error_to_db(f"Failed to place {side} order: {e}")
            return None

    def update_grid_orders(self):
        price = self.get_current_price()
        if not price: return
        grid = self.calculate_grid_prices(price)
        for side, p in grid:
            self.place_single_order(side, p, round(self.order_amount_usdt / p, 2))
        print(f"🌐 Initial grid populated around {price:.8f}")

    def sync_filled_orders(self):
        try:
            orders = self.exchange.fetch_closed_orders(self.symbol, limit=20)
            for order in orders:
                if order['id'] not in self.processed_order_ids:
                    self.processed_order_ids.append(order['id'])
                    
                    price, qty, side = float(order['price']), float(order['amount']), order['side']
                    fee = float(order.get('fee', {}).get('cost', 0.0))
                    
                    self.log_trade_to_postgres(side.upper(), price, qty, order['id'], fee)
                    
                    # Replenishment Logic
                    if side == 'buy':
                        self.place_single_order('sell', round(price * (1 + (self.grid_step_percent / 100)), 8), qty)
                    else:
                        self.place_single_order('buy', round(price * (1 - (self.grid_step_percent / 100)), 8), qty)
        except Exception as e:
            self.log_error_to_db(f"Sync error: {e}")

    def test_connection(self):
        try:
            print(f"✅ Connected! USDT balance: {self.exchange.fetch_balance().get('USDT', {}).get('free', 0):.2f}")
        except Exception as e:
            self.log_error_to_db(f"Connection failed: {e}")
            raise

    def run(self):
        print(f"🤖 {self.bot_name} - Event-Driven Grid Bot Started")
        self.update_grid_orders()
        while True:
            self.check_status()
            self.sync_filled_orders()
            time.sleep(5)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
