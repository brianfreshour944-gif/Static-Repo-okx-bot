import os
import time
import pandas as pd
import sys
import ccxt

class OKXDynamicGridBot:
    def __init__(self):
        print("--- RUNTIME DIAGNOSTIC CHECK ---")
        print(f"OKX_API_KEY Found: {bool(os.getenv('OKX_API_KEY'))}")
        print(f"OKX_API_SECRET Found: {bool(os.getenv('OKX_API_SECRET'))}")
        print(f"OKX_PASSPHRASE Found: {bool(os.getenv('OKX_PASSPHRASE'))}")
        print("--------------------------------")

        # SECURE API CONFIGURATION WITH US DOMAIN OVERRIDE
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
        
        # Enforce the Demo Trading environment cleanly via CCXT native method
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        
        # OKX BOT BUDGET INVESTMENT STYLE
        self.total_bot_budget = 100.0  # Total budget allocated to this bot instance
        self.number_of_grids = 2       # 1 Buy level + 1 Sell level
        
        # Calculate capital allocated per grid line ($50.00 USDT per level)
        self.capital_per_grid = self.total_bot_budget / self.number_of_grids
        
        # Grid parameters: 1.5% away from the moving average anchor line
        self.grid_percentage = 0.015 
        
        # Memory storage for active order structures
        self.current_buy_order = None
        self.current_sell_order = None

    def get_moving_average_center(self):
        """Fetches recent candles and calculates the 20-period SMA anchor line."""
        try:
            candles = self.exchange.fetch_ohlcv(self.symbol, timeframe='1h', limit=30)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            sma = df['close'].rolling(window=20).mean().iloc[-1]
            return float(sma)
        except Exception as e:
            print(f"Error extracting price matrix data (Public Loop): {e}")
            return None

    def update_grid_positions(self):
        """Calculates new levels and moves orders using an OKX-style fixed investment allocation."""
        center_line = self.get_moving_average_center()
        if not center_line:
            return
            
        target_buy_price = round(center_line * (1 - self.grid_percentage), 5)
        target_sell_price = round(center_line * (1 + self.grid_percentage), 5)
        
        print(f"\n[MA Anchor Center]: ${center_line:.5f}")
        print(f" -> Desired Buy Grid: ${target_buy_price:.5f}")
        print(f" -> Desired Sell Grid: ${target_sell_price:.5f}")

        # Fetch wallet metrics
        try:
            balance = self.exchange.fetch_balance()
            doge_available = balance['free'].get('DOGE', 0.0)
            usdt_available = balance['free'].get('USDT', 0.0)
            print(f" -> Wallet Balance: {doge_available:.2f} DOGE | ${usdt_available:.2f} USDT")
        except Exception as e:
            print(f"Failed to fetch active wallet balance tracker: {e}")
            return

        # Check existing Buy Order state
        if self.current_buy_order:
            try:
                order = self.exchange.fetch_order(self.current_buy_order, self.symbol)
                if order['status'] == 'closed':
                    print(f"💥 [FILL EVENT] Buy Order hit at ${order['price']}! Allocated capital converted to DOGE.")
                    self.current_buy_order = None
            except Exception as e:
                print(f"Error checking buy status: {e}")

        # Check existing Sell Order state
        if self.current_sell_order:
            try:
                order = self.exchange.fetch_order(self.current_sell_order, self.symbol)
                if order['status'] == 'closed':
                    print(f"💥 [FILL EVENT] Sell Order hit at ${order['price']}! $50 allocation returned to cash + profit.")
                    self.current_sell_order = None
            except Exception as e:
                print(f"Error checking sell status: {e}")

        # OKX STYLE STEP 1: Process Buy Side Allocation
        if not self.current_buy_order:
            if usdt_available >= self.capital_per_grid:
                # Calculate exactly how many DOGE tokens $50 buys at this specific price target
                dynamic_buy_amount = round(self.capital_per_grid / target_buy_price, 1)
                
                try:
                    print(f"Placing Buy Grid Line: Spending ${self.capital_per_grid:.2f} to get {dynamic_buy_amount} DOGE at ${target_buy_price}")
                    order = self.exchange.create_limit_buy_order(self.symbol, dynamic_buy_amount, target_buy_price)
                    self.current_buy_order = order['id']
                except Exception as e:
                    print(f"Execution Engine failed to place Buy Grid Line: {e}")
            else:
                print(f"⚠️ Buy Grid Idle: Need minimum ${self.capital_per_grid:.2f} USDT available balance.")
            
        # OKX STYLE STEP 2: Process Sell Side Allocation (Inventory Safeguard)
        if not self.current_sell_order:
            # Calculate how many tokens represent our $50 grid block at the sell price target
            dynamic_sell_amount = round(self.capital_per_grid / target_sell_price, 1)
            
            # Check if our wallet contains enough acquired token holdings to satisfy the grid level
            if doge_available >= dynamic_sell_amount:
                try:
                    print(f"Placing Sell Grid Line: Selling {dynamic_sell_amount} DOGE at ${target_sell_price} (Target Value: ${self.capital_per_grid:.2f})")
                    order = self.exchange.create_limit_sell_order(self.symbol, dynamic_sell_amount, target_sell_price)
                    self.current_sell_order = order['id']
                except Exception as e:
                    print(f"Execution Engine failed to place Sell Grid Line: {e}")
            else:
                print(f"📌 Sell Grid Idle: Waiting for Buy Grid to execute first to fund the required {dynamic_sell_amount} DOGE.")

    def start_loop(self):
        print("Starting Dynamic Tracking Grid Bot...")
        while True:
            try:
                self.update_grid_positions()
            except Exception as e:
                print(f"Main loop exception triggered: {e}")
            
            print("Waiting 15 minutes before checking the moving average path...")
            time.sleep(900)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        print("\nStopping bot instance cleanly.")
        sys.exit(0)
