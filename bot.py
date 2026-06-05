import os
import time
import ccxt
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    self.exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_API_SECRET'),
    'password': os.getenv('OKX_PASSPHRASE'),
    'enableRateLimit': True,
    'hostname': 'app.okx.com',  # <--- Ensure this is set
    'options': {'defaultType': 'spot'}
})
        
        # Set sandbox mode (remove this line when switching to Live)
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        self.total_budget = 100.0
        self.grid_count = 4
        self.grid_spacing = 0.004

        self.active_buys = {}
        self.active_sells = {}

        self.test_connection()

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
            # Increased limit to 100 to catch all recent fills in high-frequency trading
            orders = self.exchange.fetch_orders(self.symbol, limit=100)
            for order in orders:
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    if order['side'] == 'buy' and price in self.active_buys:
                        print(f"✅ BUY FILLED @ {price:.5f}")
                        del self.active_buys[price]
                    elif order['side'] == 'sell' and price in self.active_sells:
                        print(f"✅ SELL FILLED @ {price:.5f}")
                        del self.active_sells[price]
        except:
            pass

    def cancel_stale_orders(self, current_price):
        threshold = 0.007
        for price in list(self.active_buys.keys()):
            if abs(price - current_price) / current_price > threshold:
                try:
                    self.exchange.cancel_order(self.active_buys[price], self.symbol)
                    del self.active_buys[price]
                    print(f"🗑️ Cancelled stale BUY @ {price:.5f}")
                except: pass
        for price in list(self.active_sells.keys()):
            if abs(price - current_price) / current_price > threshold:
                try:
                    self.exchange.cancel_order(self.active_sells[price], self.symbol)
                    del self.active_sells[price]
                    print(f"🗑️ Cancelled stale SELL @ {price:.5f}")
                except: pass

    def manage_grid(self, current_price):
        if not current_price: return

        amount_per_grid = self.total_budget / self.grid_count
        half = self.grid_count // 2

        # Dynamically calculate grid levels based on current price
        target_prices = [
            round(current_price * (1 + (i - half) * self.grid_spacing), 5)
            for i in range(self.grid_count)
        ]

        for price in target_prices:
            qty = round(amount_per_grid / price, 2)

            # Buy side: Place only if no order currently exists at this level
            if price < current_price and price not in self.active_buys:
                try:
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                    self.active_buys[price] = order['id']
                    print(f"🟢 BUY  @ {price:.5f} | Qty: {qty}")
                except Exception as e:
                    pass

            # Sell side: Place only if no order currently exists at this level
            elif price > current_price and price not in self.active_sells:
                try:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                    self.active_sells[price] = order['id']
                    print(f"🔴 SELL @ {price:.5f} | Qty: {qty}")
                except Exception as e:
                    pass

    def run(self):
        print("🤖 OKX Grid Bot Running (Optimized Logic)\n")
        while True:
            try:
                price = self.get_current_price()
                if price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Price: {price:.5f} | "
                          f"Buys: {len(self.active_buys)} | Sells: {len(self.active_sells)}")
                    self.sync_filled_orders()
                    self.cancel_stale_orders(price)
                    self.manage_grid(price)
                    print("-" * 85)
                time.sleep(25)
            except Exception as e:
                print(f"Loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
