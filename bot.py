import os
import time
import ccxt
import psycopg2  # Make sure this is installed via requirements.txt
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
        
        self.symbol = 'DOGE/USDT'
        self.total_budget = 100.0
        self.grid_count = 4
        self.grid_spacing = 0.004

        self.active_buys = {}
        self.active_sells = {}

        self.test_connection()

    def log_trade_to_postgres(self, side, price, qty, order_id="N/A"):
        """Logs trades directly to your Coolify PostgreSQL database."""
        db_url = os.getenv('DATABASE_URL')
        try:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO trades 
                (bot_name, exchange, symbol, side, price, quantity, value, order_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                "DOGE_GRID", "OKX", self.symbol, side, price, qty, 
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
            orders = self.exchange.fetch_orders(self.symbol, limit=100)
            for order in orders:
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    order_id = order['id']
                    
                    if order['side'] == 'buy' and price in self.active_buys:
                        print(f"✅ BUY FILLED @ {price:.5f}")
                        self.log_trade_to_postgres('BUY', price, qty, order_id)
                        del self.active_buys[price]
                        
                    elif order['side'] == 'sell' and price in self.active_sells:
                        print(f"✅ SELL FILLED @ {price:.5f}")
                        self.log_trade_to_postgres('SELL', price, qty, order_id)
                        del self.active_sells[price]
        except Exception as e:
            print(f"Sync error: {e}")

    # ... (Keep your existing cancel_stale_orders and manage_grid methods here) ...

    def run(self):
        print("🤖 OKX Grid Bot Running\n")
        while True:
            try:
                price = self.get_current_price()
                if price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Price: {price:.5f}")
                    self.sync_filled_orders()
                    # self.cancel_stale_orders(price)
                    # self.manage_grid(price)
                time.sleep(25)
            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
