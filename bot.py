import os
import time
import pandas as pd
import sys
import ccxt

class OKXDynamicGridBot:
    def __init__(self):
        # SECURE API CONFIGURATION
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',  # Forces Spot market execution
            }
        })
        
        # Enforce the Demo Trading environment cleanly
        self.exchange.set_sandbox_mode(True)
        
        # Safely append the simulated flag without wiping out CCXT's default headers
        if self.exchange.headers is None:
            self.exchange.headers = {}
        self.exchange.headers['x-simulated-trading'] = '1'
        
        self.symbol = 'DOGE/USDT'
        self.order_amount = 371.0  # Dogecoin trade sizing
        
        # Grid parameters: 1.5% away from the moving average anchor line
        self.grid_percentage = 0.015 
        
        # Memory storage for active order structures
        self.current_buy_order = None
        self.current_sell_order = None

    def get_moving_average_center(self):
        """Fetches recent candles and calculates the 20-period SMA anchor line."""
        try:
            # Pull 1-hour candles
            candles = self.exchange.fetch_ohlcv(self.symbol, timeframe='1h', limit=30)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calculate standard moving average center
            sma = df['close'].rolling(window=20).mean().iloc[-1]
            return float(sma)
        except Exception as e:
            print(f"Error extracting price matrix data: {e}")
            return None

    def cancel_safe(self, order_id):
        """Helper to cancel an order without throwing a script-stopping error."""
        if order_id:
            try:
                self.exchange.cancel_order(order_id, self.symbol)
            except Exception:
                pass # Order might have already filled or expired naturally

    def update_grid_positions(self):
        """Calculates new levels and moves orders if the market trend shifted."""
        center_line = self.get_moving_average_center()
        if not center_line:
            return
            
        # Mathematically map out the dynamic grid coordinates
        target_buy_price = round(center_line * (1 - self.grid_percentage), 5)
        target_sell_price = round(center_line * (1 + self.grid_percentage), 5)
        
        print(f"\n[MA Anchor Center]: ${center_line:.5f}")
        print(f" -> Desired Buy Grid: ${target_buy_price:.5f}")
        print(f" -> Desired Sell Grid: ${target_sell_price:.5f}")

        # Check existing Buy Order state
        if self.current_buy_order:
            try:
                order = self.exchange.fetch_order(self.current_buy_order, self.symbol)
                if order['status'] == 'closed':
                    print(f"💥 [FILL EVENT] Buy Order hit at ${order['price']}! Re-centering grid.")
                    self.current_buy_order = None
            except Exception as e:
                print(f"Error checking buy status: {e}")

        # Check existing Sell Order state
        if self.current_sell_order:
            try:
                order = self.exchange.fetch_order(self.current_sell_order, self.symbol)
                if order['status'] == 'closed':
                    print(f"💥 [FILL EVENT] Sell Order hit at ${order['price']}! Profit locked in.")
                    self.current_sell_order = None
            except Exception as e:
                print(f"Error checking sell status: {e}")

        # If a buy order isn't active, deploy one at the updated coordinate line
        if not self.current_buy_order:
            print(f"Placing Dynamic Buy Limit Order at ${target_buy_price}")
            order = self.exchange.create_limit_buy_order(self.symbol, self.order_amount, target_buy_price)
            self.current_buy_order = order['id']
            
        # If a sell order isn't active, deploy one at the updated coordinate line
        if not self.current_sell_order:
            print(f"Placing Dynamic Sell Limit Order at ${target_sell_price}")
            order = self.exchange.create_limit_sell_order(self.symbol, self.order_amount, target_sell_price)
            self.current_sell_order = order['id']

    def start_loop(self):
        print("Starting Dynamic Tracking Grid Bot...")
        while True:
            try:
                self.update_grid_positions()
            except Exception as e:
                print(f"Main loop exception triggered: {e}")
            
            # Sleep for 15 minutes before re-checking the moving average path
            print("Waiting 15 minutes before checking the moving average path...")
            time.sleep(900)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        print("\nStopping bot instance cleanly.")
        sys.exit(0)
