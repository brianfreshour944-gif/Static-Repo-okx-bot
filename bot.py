import os
import time
import ccxt
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'unified',   # Important for your account type
            }
        })
        
        # This must be right after creating the exchange
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        self.total_budget = 100.0
        self.grid_count = 5
        self.grid_spacing = 0.002   # ~0.2% spacing

        self.active_buys = {}
        self.active_sells = {}

        self.test_connection()

    def test_connection(self):
        try:
            print("🔍 Testing connection to OKX Sandbox (Unified Account)...")
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            print(f"✅ Connected successfully! USDT Balance: {usdt}")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            print(f"Price error: {e}")
            return None

    def manage_grid(self, current_price):
        if not current_price:
            return

        amount_per_grid = self.total_budget / self.grid_count
        half = self.grid_count // 2

        for i in range(self.grid_count):
            price = round(current_price * (1 + (i - half) * self.grid_spacing), 5)
            qty = round(amount_per_grid / price, 2)

            if price < current_price and price not in self.active_buys:
                try:
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                    self.active_buys[price] = order['id']
                    print(f"✅ BUY order placed at {price}")
                except Exception as e:
                    print(f"Buy failed at {price}: {e}")

            elif price > current_price and price not in self.active_sells:
                try:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                    self.active_sells[price] = order['id']
                    print(f"✅ SELL order placed at {price}")
                except Exception as e:
                    print(f"Sell failed at {price}: {e}")

    def run(self):
        print("🤖 OKX Grid Bot Started - Unified Account Mode")
        while True:
            try:
                price = self.get_current_price()
                if price:
                    print(f"📊 Current DOGE/USDT: {price:.5f}")
                    self.manage_grid(price)

                time.sleep(30)

            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(10)


if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
