import os
import time
import ccxt

class OKXDynamicGridBot:
   def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            # REMOVE 'hostname': 'us.okx.com'
            'options': {
                'defaultType': 'spot',
                'x-simulated-trading': 1  # Mandatory: This tells OKX you are using Demo keys
            }
        })
        
        # This tells CCXT to use the Sandbox endpoints
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        self.total_bot_budget = 100.0
        # ... rest of your __init__ variables
        
        # This tells CCXT to map your requests to the Testnet
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        self.total_bot_budget = 100.0
        self.lower_bound = 0.08200 
        self.upper_bound = 0.08800
        self.grid_count = 3
        self.grid_prices = self.calculate_grid_prices()
        self.active_buy_orders = {}  # {price: order_id}
        self.active_sell_orders = {} # {price: order_id}

    def calculate_grid_prices(self):
        step = (self.upper_bound - self.lower_bound) / (self.grid_count - 1)
        return [round(self.lower_bound + (i * step), 5) for i in range(self.grid_count)]

    def cancel_stale_orders(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']
            threshold = 0.02
            for price, order_id in list(self.active_buy_orders.items()):
                if price < current_price * (1 - threshold):
                    self.exchange.cancel_order(order_id, self.symbol)
                    del self.active_buy_orders[price]
                    print(f"Cleanup: Cancelled stale BUY at {price}")
            for price, order_id in list(self.active_sell_orders.items()):
                if price > current_price * (1 + threshold):
                    self.exchange.cancel_order(order_id, self.symbol)
                    del self.active_sell_orders[price]
                    print(f"Cleanup: Cancelled stale SELL at {price}")
        except Exception as e:
            print(f"Cleanup Error: {e}")

    def sleep_until_next_interval(self, interval_minutes=15):
        now = time.localtime()
        minutes_past = now.tm_min % interval_minutes
        wait_minutes = interval_minutes - minutes_past - 1
        wait_seconds = 60 - now.tm_sec
        total_sleep = (wait_minutes * 60) + wait_seconds
        print(f"Aligning to {interval_minutes}m candle. Sleeping for {total_sleep}s...")
        time.sleep(total_sleep)

    def sync_and_check_fills(self):
        try:
            # Check Buy Fills
            for price, order_id in list(self.active_buy_orders.items()):
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    print(f"Fill confirmed: Bought at {price}")
                    del self.active_buy_orders[price]
            # Check Sell Fills
            for price, order_id in list(self.active_sell_orders.items()):
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    print(f"Fill confirmed: Sold at {price}")
                    del self.active_sell_orders[price]
        except Exception as e:
            print(f"Sync Error: {e}")

    def deploy_missing_grid_lines(self):
        try:
            # Calculate amount per grid (using roughly 33 USDT per grid for a 100 USDT budget)
            amount_per_grid = (self.total_bot_budget / len(self.grid_prices))
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']

            for price in self.grid_prices:
                # Need to calculate quantity based on price
                qty = round(amount_per_grid / price, 1)
                
                if price < current_price and price not in self.active_buy_orders:
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                    self.active_buy_orders[price] = order['id']
                    print(f"Placed Buy at {price}")
                elif price > current_price and price not in self.active_sell_orders:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                    self.active_sell_orders[price] = order['id']
                    print(f"Placed Sell at {price}")
        except Exception as e:
            print(f"Deployment Error: {e}")

    def start_loop(self):
        print("Bot active. Maintaining grid...")
        while True:
            try:
                self.cancel_stale_orders()
                self.sync_and_check_fills()
                self.deploy_missing_grid_lines()
            except Exception as e:
                print(f"Loop Error: {e}")
            
            self.sleep_until_next_interval(15)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    bot.start_loop()
