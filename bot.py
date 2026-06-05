import os
import time
import sys
import ccxt

class OKXAdaptiveGridBot:
    def __init__(self):
        print("--- STARTING ADAPTIVE GRID BOT ---")
        
        # Correctly initialize the exchange with your US credentials
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',  # Mandatory for OKX US
            'options': {
                'defaultType': 'spot',
                'fetchCurrencies': False
            }
        })

        self.symbol = "DOGE/USDT"

        # ---------------------------
        # GRID SETTINGS
        # ---------------------------
        self.grid_count = 10
        self.grid_percent_range = 0.06
        self.recenter_threshold = 0.03

        # State
        self.grid_prices = []
        self.active_buy_orders = {}
        self.active_sell_orders = {}
        self.bot_cash = 100.0
        self.bot_doge = 0.0
        self.last_center_price = None

        self.initialize()

    # ---------------------------
    # GRID GENERATION
    # ---------------------------
    def generate_grid(self, center_price):
        half_range = center_price * (self.grid_percent_range / 2)
        lower = center_price - half_range
        upper = center_price + half_range
        step = (upper - lower) / (self.grid_count - 1)
        prices = [round(lower + i * step, 6) for i in range(self.grid_count)]
        self.grid_prices = prices
        self.last_center_price = center_price
        print(f"\nGRID RECENTERED AROUND: {center_price:.6f}")
        print(f"GRID RANGE: {prices[0]} → {prices[-1]}")

    # ---------------------------
    # INIT
    # ---------------------------
    def initialize(self):
        ticker = self.exchange.fetch_ticker(self.symbol)
        price = ticker["last"]
        self.generate_grid(price)
        seed_cash = self.bot_cash / 2
        self.bot_cash -= seed_cash
        approx_doge = seed_cash / price
        self.bot_doge += approx_doge
        print(f"Seeded: {approx_doge:.2f} DOGE")

    # ---------------------------
    # BALANCE SAFETY CHECK
    # ---------------------------
    def sync_balances(self):
        try:
            bal = self.exchange.fetch_balance()
            if "USDT" in bal:
                self.bot_cash = bal["USDT"]["free"]
            if "DOGE" in bal:
                self.bot_doge = bal["DOGE"]["free"]
        except Exception as e:
            print(f"Balance sync error: {e}")

    # ---------------------------
    # RECENTER LOGIC
    # ---------------------------
    def check_recenter(self, current_price):
        if self.last_center_price is None:
            return
        drift = abs(current_price - self.last_center_price) / self.last_center_price
        if drift > self.recenter_threshold:
            print("\n🔄 RECENTERING GRID")
            self.generate_grid(current_price)
            self.active_buy_orders.clear()
            self.active_sell_orders.clear()

    # ---------------------------
    # ORDER CHECK
    # ---------------------------
    def check_fills(self):
        for price, order_id in list(self.active_buy_orders.items()):
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order["status"] == "closed":
                    self.bot_doge += float(order["filled"])
                    del self.active_buy_orders[price]
            except: pass

        for price, order_id in list(self.active_sell_orders.items()):
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order["status"] == "closed":
                    self.bot_cash += float(order["filled"]) * price
                    self.bot_doge -= float(order["filled"])
                    del self.active_sell_orders[price]
            except: pass

    # ---------------------------
    # PLACE GRID ORDERS
    # ---------------------------
    def place_orders(self, current_price):
        for price in self.grid_prices:
            if price < current_price:
                if price not in self.active_buy_orders and self.bot_cash > 5:
                    spend = self.bot_cash / 10
                    amount = spend / price
                    try:
                        order = self.exchange.create_limit_buy_order(self.symbol, amount, price)
                        self.active_buy_orders[price] = order["id"]
                        self.bot_cash -= spend
                        print(f"BUY placed @ {price}")
                    except Exception as e: print(f"BUY error: {e}")

            elif price > current_price:
                if price not in self.active_sell_orders:
                    amount = (self.bot_doge / self.grid_count)
                    if amount > 0:
                        try:
                            order = self.exchange.create_limit_sell_order(self.symbol, amount, price)
                            self.active_sell_orders[price] = order["id"]
                            print(f"SELL placed @ {price}")
                        except Exception as e: print(f"SELL error: {e}")

    # ---------------------------
    # MAIN LOOP
    # ---------------------------
    def run(self):
        while True:
            try:
                ticker = self.exchange.fetch_ticker(self.symbol)
                price = ticker["last"]
                print(f"\nPRICE: {price}")
                self.sync_balances()
                self.check_recenter(price)
                self.check_fills()
                self.place_orders(price)
                print(f"Cash: {self.bot_cash:.2f} | DOGE: {self.bot_doge:.2f}")
            except Exception as e:
                print(f"Loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    bot = OKXAdaptiveGridBot()
    bot.run()
