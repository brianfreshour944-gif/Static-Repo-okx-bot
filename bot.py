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
        
        self.exchange.set_sandbox_mode(True)
        self.symbol = 'DOGE/USDT'
        
        # EXACT MATCH NATIVE OKX BOT CONFIGURATION
        self.total_bot_budget = 100.0   # Total Investment: 100.0000 USD
        self.lower_bound = 0.08847      # Bottom of the grid range
        self.upper_bound = 0.09211      # Top of the grid range
        self.grid_count = 3             # Grid lines: 3
        
        # Calculate standard allocation blocks ($100 / 2 intervals = $50 per grid line)
        self.capital_per_grid = self.total_bot_budget / (self.grid_count - 1)
        
        # SELF-CONTAINED INTERNAL LEDGER ENGINE
        self.bot_cash = 100.0           # Local initial fiat tracking
        self.bot_doge = 0.0             # Local initial token storage tracker
        
        # Fixed execution targets calculated at boot sequence
        self.buy_target_price = self.lower_bound
        self.sell_target_price = self.upper_bound
        
        # Order Tracking Slots
        self.current_buy_order = None
        self.current_sell_order = None

    def cancel_safe(self, order_id):
        """Helper to drop a trace block safely."""
        if order_id:
            try:
                self.exchange.cancel_order(order_id, self.symbol)
            except Exception:
                pass 

    def run_grid_cycle(self):
        """Executes locked range grid arbitrage round-trips matching native logic."""
        print(f"\n--- [NATIVE STYLE STATIC GRID RUNNER] ---")
        print(f" -> Configured Upper Boundaries: ${self.upper_bound:.5f}")
        print(f" -> Configured Lower Boundaries: ${self.lower_bound:.5f}")
        print(f" -> INTERNAL BALANCE SHEET: ${self.bot_cash:.2f} Free Cash | {self.bot_doge:.2f} Accumulated DOGE")

        # 1. PROCESS BUY FILLED EVENTS
        if self.current_buy_order:
            try:
                order = self.exchange.fetch_order(self.current_buy_order, self.symbol)
                if order['status'] == 'closed':
                    filled_amount = float(order['filled'])
                    self.bot_doge += filled_amount
                    print(f"💥 [FILL EVENT] Grid Buy Executed at ${order['price']}! Bought {filled_amount} DOGE.")
                    self.current_buy_order = None
            except Exception as e:
                print(f"Error reviewing buy structure: {e}")

        # 2. PROCESS SELL FILLED EVENTS (Profit Capture)
        if self.current_sell_order:
            try:
                order = self.exchange.fetch_order(self.current_sell_order, self.symbol)
                if order['status'] == 'closed':
                    sell_price = float(order['price'])
                    tokens_sold = float(order['filled'])
                    usd_returned = round(sell_price * tokens_sold, 4)
                    
                    # Return original trade capital block + profit directly back to internal cash vault
                    self.bot_cash += usd_returned
                    self.bot_doge -= tokens_sold
                    
                    print(f"💥 [FILL EVENT] Grid Sell Executed at ${sell_price}! Captured ${usd_returned:.2f} USDT.")
                    self.current_sell_order = None
            except Exception as e:
                print(f"Error reviewing sell structure: {e}")

        # 3. CONSTRUCT BUY LINE LIMIT ORDER
        if not self.current_buy_order:
            if self.bot_cash >= self.capital_per_grid:
                dynamic_buy_amount = round(self.capital_per_grid / self.buy_target_price, 1)
                try:
                    print(f"Placing Static Buy Order: Target {dynamic_buy_amount} DOGE at ${self.buy_target_price}")
                    order = self.exchange.create_limit_buy_order(self.symbol, dynamic_buy_amount, self.buy_target_price)
                    self.current_buy_order = order['id']
                    
                    # Freeze the allocation block internally
                    self.bot_cash -= self.capital_per_grid
                except Exception as e:
                    print(f"API failed to plant Buy target line: {e}")
            else:
                print(f"⚠️ Buy Side Idle: Budget locked down inside active asset holdings.")

        # 4. CONSTRUCT SELL LINE LIMIT ORDER
        if not self.current_sell_order:
            dynamic_sell_amount = round(self.capital_per_grid / self.sell_target_price, 1)
            if self.bot_doge >= dynamic_sell_amount:
                try:
                    print(f"Placing Static Sell Order: Target {dynamic_sell_amount} DOGE at ${self.sell_target_price}")
                    order = self.exchange.create_limit_sell_order(self.symbol, dynamic_sell_amount, self.sell_target_price)
                    self.current_sell_order = order['id']
                except Exception as e:
                    print(f"API failed to plant Sell target line: {e}")
            else:
                print(f"📌 Sell Side Idle: Waiting for price to tap ${self.buy_target_price} to clear inventory constraints.")

    def start_loop(self):
        print("Deploying Locked Native Grid Emulation Loop...")
        while True:
            try:
                self.run_grid_cycle()
            except Exception as e:
                print(f"Loop runtime exception caught: {e}")
            
            print("Checking order matching state flags in 60 seconds...")
            time.sleep(60)

if __name__ == '__main__':
    bot = OKXNativeClassicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        print("\nStopping bot engine structure cleanly.")
        sys.exit(0)
