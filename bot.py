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
        
        self.active_orders = {} 
        self.processed_order_ids = deque(maxlen=100) 
        
        self.test_connection()
        self.clear_all_orders()

    def clear_all_orders(self):
        """Force clear all orders for the symbol."""
        try:
            # OKX requires the symbol and often returns a limited set
            # We loop to ensure we catch everything
            while True:
                open_orders = self.exchange.fetch_open_orders(self.symbol)
                if not open_orders:
                    break
                print(f"🧹 Found {len(open_orders)} orders. Cancelling batch...")
                for order in open_orders:
                    self.exchange.cancel_order(order['id'], self.symbol)
                time.sleep(1) # Give exchange time to process
            print("✅ All orders cleared.")
        except Exception as e:
            print(f"⚠️ Error during clear: {e}")

    def update_grid_orders(self):
        # 1. Fetch current live state
        try:
            open_orders = self.exchange.fetch_open_orders(self.symbol)
            # IMPORTANT: We ONLY care about orders the BOT placed
            # If you have manual orders, this logic might conflict
            self.active_orders = {round(float(o['price']), 8): o['id'] for o in open_orders}
        except Exception as e:
            return
        
        price = self.get_current_price()
        if not price: return
        
        grid = self.calculate_grid_prices(price)
        
        for side, p in grid:
            p = round(p, 8)
            # Check if this specific price point is occupied
            if p not in self.active_orders:
                qty = round(33.33 / p, 2)
                # Before placing, check if we have too many orders total
                if len(self.active_orders) < 50: 
                    order = self.place_single_order(side, p, qty)
                    if order:
                        self.active_orders[p] = order['id']
                        time.sleep(0.5)
                else:
                    print("⚠️ Order limit reached, skipping...")

    # ---------- CORE LOGIC ----------
    def update_grid_orders(self):
        # 1. Refresh active orders from the exchange
        try:
            open_orders = self.exchange.fetch_open_orders(self.symbol)
            # We build a 'current_state' dictionary from the exchange
            current_state = {round(float(o['price']), 8): o['id'] for o in open_orders}
            # Update our master record
            self.active_orders = current_state
        except Exception as e:
            print(f"⚠️ Error fetching open orders: {e}")
            return
        
        price = self.get_current_price()
        if not price: return
        
        grid = self.calculate_grid_prices(price)
        cost_per_trade = 33.33 
        
        for side, p in grid:
            p = round(p, 8) 
            # 2. Check if the price exists in our updated master record
            if p not in self.active_orders:
                qty = round(cost_per_trade / p, 2)
                print(f"🚀 Attempting to place {side.upper()} order at {p:.8f}...")
                order = self.place_single_order(side, p, qty)
                
                # 3. IMMEDIATELY update our local record so the next check knows it exists
                if order:
                    self.active_orders[p] = order['id']
                    time.sleep(0.5)

    def place_single_order(self, side, price, qty):
        try:
            params = {'postOnly': True}
            if side == 'buy':
                order = self.exchange.create_limit_buy_order(self.symbol, qty, price, params=params)
            else:
                order = self.exchange.create_limit_sell_order(self.symbol, qty, price, params=params)
            print(f"📌 Placed {side.upper()} @ {price:.8f}")
            return order
        except Exception as e:
            self.log_error_to_db(f"Failed to place {side} order: {e}")
            return None

    def sync_filled_orders(self):
        try:
            orders = self.exchange.fetch_closed_orders(self.symbol, limit=20)
            for order in orders:
                if order['id'] not in self.processed_order_ids:
                    self.processed_order_ids.append(order['id'])
                    price, qty, side = float(order['price']), float(order['amount']), order['side']
                    
                    self.log_trade_to_postgres(side.upper(), price, qty, order['id'], float(order.get('fee', {}).get('cost', 0.0)))
                    
                    # Replenishment
                    new_side = 'sell' if side == 'buy' else 'buy'
                    offset = self.grid_step_percent / 100
                    new_price = round(price * (1 + offset), 8) if side == 'buy' else round(price * (1 - offset), 8)
                    self.place_single_order(new_side, new_price, qty)
                    self.active_orders.pop(round(price, 8), None)
        except Exception as e:
            self.log_error_to_db(f"Sync error: {e}")

    # ---------- HELPERS ----------
    def log_error_to_db(self, error_msg):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)", (self.bot_name, str(error_msg)))
                    conn.commit()
        except Exception as e:
            print(f"❌ Failed to log error: {e}")

    def log_trade_to_postgres(self, side, price, qty, order_id, fee):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, fee, order_id, timestamp) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())", 
                                (self.bot_name, "OKX", self.symbol, side, price, qty, (price * qty), fee, order_id))
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
                    if row and row[0] == 'STOP': exit(0)
        except Exception as e:
            self.log_error_to_db(f"Status check error: {e}")

    def get_current_price(self):
        try: return self.exchange.fetch_ticker(self.symbol)['last']
        except Exception as e:
            self.log_error_to_db(f"Price fetch error: {e}")
            return None

    def calculate_grid_prices(self, center_price):
        grid_prices = []
        for i in range(1, self.grid_levels + 1):
            grid_prices.append(('buy', round(center_price * (1 - (self.grid_step_percent / 100) * i), 8)))
            grid_prices.append(('sell', round(center_price * (1 + (self.grid_step_percent / 100) * i), 8)))
        return grid_prices

    def test_connection(self):
        try: print(f"✅ Connected! USDT balance: {self.exchange.fetch_balance().get('USDT', {}).get('free', 0):.2f}")
        except Exception as e:
            self.log_error_to_db(f"Connection failed: {e}")
            raise

    def run(self):
        print(f"🤖 {self.bot_name} - Event-Driven Grid Bot Started")
        while True:
            self.check_status()
            self.update_grid_orders()
            self.sync_filled_orders()
            time.sleep(5)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
