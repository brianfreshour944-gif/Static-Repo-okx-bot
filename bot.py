import os
import time
import ccxt

class OKXDynamicGridBot:
    def __init__(self):
        # Initialize the exchange
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',
            'options': {'defaultType': 'spot'}
        })

        self.symbol = 'DOGE/USDT'
        self.total_bot_budget = 100.0
        # Dynamically set these based on your current market view
        self.lower_bound = 0.08200 
        self.upper_bound = 0.08800
        self.grid_count = 3
        
        # Grid state
        self.grid_prices = self.calculate_grid_prices()
        self.capital_per_grid = self.total_bot_budget / len(self.grid_prices)
        self.active_buy_orders = {}  # Format: {price: order_id}
        self.active_sell_orders = {} # Format: {price: order_id}
        
        self.bot_cash = 50.0  # Initialized example balance
        self.bot_doge = 500.0 # Initialized example balance

    def calculate_grid_prices(self):
        # Creates equally spaced levels between bounds
        step = (self.upper_bound - self.lower_bound) / (self.grid_count - 1)
        return [self.lower_bound + (i * step) for i in range(self.grid_count)]

    def cancel_stale_orders(self):
        """Removes orders that are no longer relevant to current market price."""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']
            threshold = 0.02 # 2% deviation threshold
            
            # Cancel stale buys
            for price, order_id in list(self.active_buy_orders.items()):
                if price < current_price * (1 - threshold):
                    self.exchange.cancel_order(order_id, self.symbol)
                    del self.active_buy_orders[price]
                    print(f"Cleanup: Cancelled stale BUY at {price}")

            # Cancel stale sells
            for price, order_id in list(self.active_sell_orders.items()):
                if price > current_price * (1 + threshold):
                    self.exchange.cancel_order(order_id, self.symbol)
                    del self.active_sell_orders[price]
                    print(f"Cleanup: Cancelled stale SELL at {price}")
        except Exception as e:
            print(f"Cleanup Error: {e}")

    def sync_and_check_fills(self):
        """Updates internal balances based on filled orders."""
        # Logic to check exchange for filled orders and update self.bot_cash/doge
        # ... (Include your existing fill-checking logic here)
        pass

    def deploy_missing_grid_lines(self):
        """Places new orders where gaps exist in the grid."""
        try:
            current_price = self.exchange.fetch_ticker(self.symbol)['last']
            for price in self.grid_prices:
                if price < current_price:
                    if price not in self.active_buy_orders:
                        # Logic to place buy order
                        pass
                elif price > current_price:
                    if price not in self.active_sell_orders:
                        # Logic to place sell order
                        pass
        except Exception as e:
            print(f"Deployment Error: {e}")

    def start_loop(self):
        print("Bot active. Maintaining grid...")
        while True:
            try:
                self.cancel_stale_orders()       # 1. Clean house
                self.sync_and_check_fills()      # 2. Update balances
                self.deploy_missing_grid_lines() # 3. Re-fill grid
            except Exception as e:
                print(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    bot.start_loop()
