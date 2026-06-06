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
        
        self.bot_name = os.getenv('BOT_NAME', 'DOGE_GRID_BOT')
        self.symbol = 'DOGE/USDT'
        self.processed_order_ids = set()
        
        self.test_connection()

    # --- NEW: ERROR LOGGING HELPER ---
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
            print(f"❌ Critical failure logging error to DB: {e}")

    def check_status(self):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO bot_status (bot_name, last_update, status)
                VALUES (%s, NOW(), 'RUNNING')
                ON CONFLICT (bot_name) 
                DO UPDATE SET last_update = NOW(), status = EXCLUDED.status;
            ''', (self.bot_name,))
            cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (self.bot_name,))
            row = cur.fetchone()
            if row and row[0] == 'STOP':
                print(f"🛑 Kill switch activated for {self.bot_name}. Shutting down.")
                exit(0)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"❌ Heartbeat failed: {e}")

    def log_trade_to_postgres(self, side, price, qty, order_id="N/A"):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trades 
                (bot_name, exchange, symbol, side, price, quantity, value, order_id, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (self.bot_name, "OKX", self.symbol, side, price, qty, (price * qty), order_id))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            error_msg = f"Database logging failed: {e}"
            print(error_msg)
            self.log_error_to_db(error_msg)

    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            print(f"✅ Connected! USDT: {usdt:.2f}\n")
        except Exception as e:
            error_msg = f"Connection Error: {e}"
            print(f"❌ {error_msg}")
            self.log_error_to_db(error_msg)

    def get_current_price(self):
        try:
            return self.exchange.fetch_ticker(self.symbol)['last']
        except Exception as e:
            self.log_error_to_db(f"Price fetch error: {e}")
            return None

    def sync_filled_orders(self):
        try:
            closed_orders = self.exchange.fetch_closed_orders(self.symbol, limit=20)
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.processed_order_ids: continue
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    side = order['side'].upper()
                    self.log_trade_to_postgres(side, price, qty, order_id)
                    self.processed_order_ids.add(order_id)
                    print(f"✅ {side} FILLED & LOGGED @ {price:.5f}")
        except Exception as e:
            self.log_error_to_db(f"Sync error: {e}")

    def run(self):
        print(f"🤖 {self.bot_name} Running\n")
        while True:
            try:
                self.check_status()
                price = self.get_current_price()
                if price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Price: {price:.5f}")
                    self.sync_filled_orders()
                time.sleep(25)
            except Exception as e:
                error_msg = f"Loop error: {e}"
                print(f"❌ {error_msg}")
                self.log_error_to_db(error_msg)
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
