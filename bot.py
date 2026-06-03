import os
import time
import sys
import ccxt

class OKXNativeClassicGridBot:
    def __init__(self):
        print("--- RUNTIME DIAGNOSTIC CHECK ---")
        print(f"OKX_API_KEY Found: {bool(os.getenv('OKX_API_KEY'))}")
        print(f"OKX_API_SECRET Found: {bool(os.getenv('OKX_API_SECRET'))}")
        print(f"OKX_PASSPHRASE Found: {bool(os.getenv('OKX_PASSPHRASE'))}")
        print("--------------------------------")

        # SECURE API CONFIGURATION
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',  
            'options': {
                'defaultType': 'spot',  
            }
        })
        
        # Keep sandbox mode active for validation safety
        self.exchange.set_sandbox_mode(True)
        self.symbol = 'DOGE/USDT'
        
        # EXACT MATCH NATIVE OKX BOT CONFIGURATION
        self.total_bot_budget = 100.0   # Total Investment: $100.00
        self.lower_bound = 0.08900      # Lower floor target
        self.upper_bound = 0.09500      # Higher ceiling target
        self.grid_count = 3             # Keeps your 3-tier structure
        
        # Calculate the exact mathematical spacing grid geometry
        self.grid_prices = self.calculate_grid_prices()
        self.capital_per_grid = self.total_bot_budget / len(self.grid_prices)
        
        # Tracking dictionaries for simultaneous live limit positions
        self.active_buy_orders = {}   # structure: {price: order_id}
        self.active_sell_orders = {}  # structure: {price: order_id}
        
        # Initial Balance State Seeding
        self.bootstrap_initial_balances()

    def calculate_grid_prices(self):
        """Generates the array of exact pricing intervals for the grid matrix."""
        prices = []
        step = (self.upper_bound - self.lower_bound) / (self.grid_count - 1)
        for i in range(self.grid_count):
            price = self.lower_bound + (step * i)
            prices.append(round(price, 5))
        print(f"Generated Grid Price Structure Matrix: {prices}")
        return prices

    def bootstrap_initial_balances(self):
        """Mimics OKX bot initialization by buying 50% asset inventory at market on boot."""
        print("\n--- INITIALIZING GRID BALANCES (OKX STYLE SEEDING) ---")
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']
            print(f"Current DOGE Market Spot Price: ${current_price:.5f}")
            
            # Spend half the budget immediately on a market order to balance inventory
            seed_fiat_allocation = self.total_bot_budget / 2.0
            approx_tokens = round(seed_fiat_allocation / current_price, 1)
            
            print(f"Executing initial balance allocation: Buying {approx_tokens} DOGE at market...")
            # Un-comment the line below when migrating from paper testing to production
            # order = self.exchange.create_market_buy_order(self.symbol, approx_tokens)
            
            # Setup localized internal ledger accounts based on the execution seed split
            self.bot_cash = self.total_bot_budget - seed_fiat_allocation
            self.bot_doge = approx_tokens
            print(f"Initialization Seed Complete! Ledger Ready.")
        except Exception as e:
            print(f"🚨 Failed to execute initialization balancing: {e}")
            print("Falling back to safe baseline asset state defaults.")
            self.bot_cash = 100.0
            self.bot_doge = 0.0

    def sync_and_check_fills(self):
        """Scans all active orders on the exchange to catch filled events simultaneously."""
        # 1. SCAN LIVE BUY ORDERS
        still_active_buys = {}
        for price, order_id in self.active_buy_orders.items():
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    filled_amount = float(order['filled'])
                    self.bot_doge += filled_amount
                    print(f"💥 [FILL EVENT] Buy Grid Line Hit at ${price}! Acquired +{filled_amount} DOGE.")
                else:
                    still_active_buys[price] = order_id
            except Exception as e:
                print(f"Error checking buy line ${price}: {e}")
                still_active_buys[price] = order_id
        self.active_buy_orders = still_active_buys

        # 2. SCAN LIVE SELL ORDERS
        still_active_sells = {}
        for price, order_id in self.active_sell_orders.items():
            try:
                order = self.exchange.fetch_order(order_id, self.symbol)
                if order['status'] == 'closed':
                    tokens_sold = float(order['filled'])
                    usd_returned = round(price * tokens_sold, 4)
                    self.bot_cash += usd_returned
                    print(f"💥 [FILL EVENT] Sell Grid Line Hit at ${price}! Locked In +${usd_returned:.2f} USDT.")
                else:
                    still_active_sells[price] = order_id
            except Exception as e:
                print(f"Error checking sell line ${price}: {e}")
                still_active_sells[price] = order_id
        self.active_sell_orders = still_active_sells

    def deploy_missing_grid_lines(self):
        """Maintains the grid matrix by planting limit orders on all unfilled rungs."""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            current_price = ticker['last']
        except Exception as e:
            print(f"Error retrieving pricing data ticker metrics: {e}")
            return

        for price in self.grid_prices:
            # Drop down a Buy Limit if the grid target sits below current market price
            if price < current_price:
                if price not in self.active_buy_orders and price not in self.active_sell_orders:
                    if self.bot_cash >= self.capital_per_grid:
                        tokens_to_buy = round(self.capital_per_grid / price, 1)
                        try:
                            print(f"Placing Buy Grid Limit Line: {tokens_to_buy} DOGE at ${price}")
                            order = self.exchange.create_limit_buy_order(self.symbol, tokens_to_buy, price)
                            self.active_buy_orders[price] = order['id']
                            self.bot_cash -= self.capital_per_grid
                        except Exception as e:
                            print(f"Failed to place buy rung at ${price}: {e}")

            # Raise up a Sell Limit if the grid target sits above current market price
            elif price > current_price:
                if price not in self.active_buy_orders and price not in self.active_sell_orders:
                    tokens_to_sell = round(self.capital_per_grid / price, 1)
                    if self.bot_doge >= tokens_to_sell:
                        try:
                            print(f"Placing Sell Grid Limit Line: {tokens_to_sell} DOGE at ${price}")
                            order = self.exchange.create_limit_sell_order(self.symbol, tokens_to_sell, price)
                            self.active_sell_orders[price] = order['id']
                            self.bot_doge -= tokens_to_sell
                        except Exception as e:
                            print(f"Failed to place sell rung at ${price}: {e}")

    def run_grid_cycle(self):
        """Executes the concurrent multi-grid tracking routine."""
        print(f"\n--- [NATIVE MULTI-GRID STATIC MATRIX RUNNER] ---")
        print(f" -> Current Active Buy Lines: {list(self.active_buy_orders.keys())}")
        print(f" -> Current Active Sell Lines: {list(self.active_sell_orders.keys())}")
        print(f" -> INTERNAL BALANCE SHEET: ${self.bot_cash:.2f} Free Cash | {self.bot_doge:.1f} Seeded DOGE Tokens")

        # Process fills and deploy missing lines
        self.sync_and_check_fills()
        self.deploy_missing_grid_lines()

    def start_loop(self):
        print("Deploying Multi-Tiered Native Grid Emulation Matrix...")
        while True:
            try:
                self.run_grid_cycle()
            except Exception as e:
                print(f"Loop runtime exception caught: {e}")
            
            print("Checking order matrix states flags in 60 seconds...")
            time.sleep(60)

if __name__ == '__main__':
    bot = OKXNativeClassicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        print("\nStopping bot engine structure cleanly.")
        sys.exit(0)
