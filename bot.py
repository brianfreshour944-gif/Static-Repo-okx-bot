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
            'hostname': 'app.okx.com',
            'options': {
                'defaultType': 'unified',
            }
        })
        
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        self.total_budget = 100.0
        self.grid_count = 5
        self.grid_spacing = 0.002

        self.active_buys = {}
        self.active_sells = {}

        self.test_connection()

    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            doge = balance.get('DOGE', {}).get('free', 0)
            print(f"✅ Connected Successfully!")
            print(f"   USDT Balance: {usdt:.4f}")
            print(f"   DOGE Balance: {doge:.4f}\n")
        except Exception as e:
            print(f"❌ Connection Error: {e}")

    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            print(f"❌ Price fetch error: {e}")
            return None

    def cancel_stale_orders(self, current_price):
        threshold = 0.008
        for price in list(self.active_buys.keys()):
            if abs(price - current_price) / current_price > threshold:
                try:
                    self.exchange.cancel_order(self.active_buys[price], self.symbol)
                    del self.active_buys[price]
                    print(f"🗑️ Cancelled stale BUY  @ {price}")
                except:
                    pass

        for price in list(self.active_sells.keys()):
            if abs(price - current_price) / current_price > threshold:
                try:
                    self.exchange.cancel_order(self.active_sells[price], self.symbol)
                    del self.active_sells[price]
                    print(f"🗑️ Cancelled stale SELL @ {price}")
                except:
                    pass

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
                    print(f"🟢 BUY  placed @ {price} | Qty: {qty} DOGE")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"⚠️  Buy failed @ {price}: {e}")

            elif price > current_price and price not in self.active_sells:
                try:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                    self.active_sells[price] = order['id']
                    print(f"🔴 SELL placed @ {price} | Qty: {qty} DOGE")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"⚠️  Sell failed @ {price}: {e}")

    def run(self):
        print("🤖 OKX Grid Bot Started (Enhanced Logging Mode)\n")
        
        while True:
            try:
                price = self.get_current_price()
                if price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Current Price: {price:.5f} | "
                          f"Buys: {len(self.active_buys)} | Sells: {len(self.active_sells)}")
                    
                    self.cancel_stale_orders(price)
                    self.manage_grid(price)
                    print("-" * 80)

                time.sleep(30)

            except Exception as e:
                print(f"❌ Loop Error: {e}")
                time.sleep(10)


if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
