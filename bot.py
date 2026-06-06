
#!/usr/bin/env python3
import os
import time
import ccxt
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    def __init__(self):
        # Configuration from Environment Variables
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
        
        # Track processed orders
        self.processed_order_ids = set()
        
        # INITIALIZATION
        self.test_connection()

    def check_status(self):
        """Heartbeat and Kill Switch check for the bot_status table."""
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            
            # 1. Update Heartbeat (Upsert)
            cur.execute('''
                INSERT INTO bot_status (bot_name, last_update, status)
                VALUES (%s, NOW(), 'RUNNING')
                ON CONFLICT (bot_name) 
                DO UPDATE SET last_update = NOW(), status = EXCLUDED.status;
            ''', (self.bot_name,))
            
            # 2. Check for Kill Switch
            cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (self.bot_name,))
            row = cur.fetchone()
            if row and row[0] == 'STOP':
                print(f"🛑 Kill switch activated for {self.bot_name}. Shutting down.")
                cur.close()
                conn.close()
                exit(0) # Terminate the process
                
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"❌ Heartbeat/Kill-Switch failed: {e}")

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
            """, (
                self.bot_name, "OKX", self.symbol, side, price, qty, 
                (price * qty), order_id
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Database logging failed: {e}")

    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            print(f"✅ Connected! USDT: {usdt:.2f}\n")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

    def get_current_price(self):
        try:
            return self.exchange.fetch_ticker(self.symbol)['last']
        except:
            return None

    def sync_filled_orders(self):
        try:
            closed_orders = self.exchange.fetch_closed_orders(self.symbol, limit=20)
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.processed_order_ids:
                    continue
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    side = order['side'].upper()
                    
                    self.log_trade_to_postgres(side, price, qty, order_id)
                    self.processed_order_ids.add(order_id)
                    print(f"✅ {side} FILLED & LOGGED @ {price:.5f}")
        except Exception as e:
            print(f"Sync error: {e}")

    def run(self):
        print(f"🤖 {self.bot_name} Running\n")
        while True:
            try:
                # HEARTBEAT & KILL SWITCH CHECK
                self.check_status()
                
                price = self.get_current_price()
                if price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Price: {price:.5f}")
                    self.sync_filled_orders()
                time.sleep(25)
            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
