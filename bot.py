import os
import time
import sys
import ccxt

class OKXNativeClassicGridBot:
   def __init__(self):
        print("--- RUNTIME DIAGNOSTIC CHECK ---")
        print(f"OKX_API_KEY Found: {bool(os.getenv('OKX_API_KEY'))}")
        print("--------------------------------")

        # Initialize the exchange exactly once
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',  # REQUIRED for US users
            'options': {
                'defaultType': 'spot'
            }
        })

        # NOTE: Do NOT use self.exchange.set_sandbox_mode(True)
        # Production keys must be used against the production us.okx.com endpoint.

        self.symbol = 'DOGE/USDT'
        # ... (rest of your existing logic)
        self.initialize()
        
        # ... rest of your initialization ...

        self.symbol = 'DOGE/USDT'
        self.total_bot_budget = 100.0
        self.lower_bound = 0.08900
        self.upper_bound = 0.09500
        self.grid_count = 3
        
        self.grid_prices = self.calculate_grid_prices()
        self.capital_per_grid = self.total_bot_budget / len(self.grid_prices)
        self.active_buy_orders = {}
        self.active_sell_orders = {}

        self.bootstrap_initial_balances()

    def calculate_grid_prices(self):
        prices = []
        step = (self.upper_bound - self.lower_bound) / (self.grid_count - 1)
        for i in range(self.grid_count):
            price = self.lower_bound + (step * i)
            prices.append(round(price, 5))
        return prices

    def bootstrap_initial_balances(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']
            seed_fiat_allocation = self.total_bot_budget / 2.0
            approx_tokens = round(seed_fiat_allocation / current_price, 1)
            self.bot_cash = self.total_bot_budget - seed_fiat_allocation
            self.bot_doge = approx_tokens
        except Exception as e:
            print(f"Initialization Error: {e}")
            self.bot_cash = 100.0
            self.bot_doge = 0.0

    def sync_and_check_fills(self):
        # Scan Buys
        still_active_buys = {}
        for price, order_id in self.active_buy_orders.items():
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    self.bot_doge += float(order['filled'])
                else:
                    still_active_buys[price] = order_id
            except: still_active_buys[price] = order_id
        self.active_buy_orders = still_active_buys

        # Scan Sells
        still_active_sells = {}
        for price, order_id in self.active_sell_orders.items():
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    self.bot_cash += float(order['filled']) * price
                    self.bot_doge -= float(order['filled'])
                else:
                    still_active_sells[price] = order_id
            except: still_active_sells[price] = order_id
        self.active_sell_orders = still_active_sells

    def deploy_missing_grid_lines(self):
        try:
            current_price = self.exchange.fetch_ticker(self.symbol)['last']
        except: return

        for price in self.grid_prices:
            if price < current_price:
                if price not in self.active_buy_orders and price not in self.active_sell_orders:
                    if self.bot_cash >= self.capital_per_grid:
                        tokens = round(self.capital_per_grid / price, 1)
                        order = self.exchange.create_limit_buy_order(self.symbol, tokens, price)
                        self.active_buy_orders[price] = order['id']
                        self.bot_cash -= self.capital_per_grid
            elif price > current_price:
                if price not in self.active_buy_orders and price not in self.active_sell_orders:
                    tokens = round(self.capital_per_grid / price, 1)
                    if self.bot_doge >= tokens:
                        order = self.exchange.create_limit_sell_order(self.symbol, tokens, price)
                        self.active_sell_orders[price] = order['id']
                        self.bot_doge -= tokens

    def start_loop(self):
        while True:
            try:
                self.sync_and_check_fills()
                self.deploy_missing_grid_lines()
            except Exception as e:
                print(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    bot = OKXNativeClassicGridBot()
    bot.start_loop()
