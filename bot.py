
import os
import time
import pandas as pd
import sys
import ccxt
import logging

# Configure logging for better visibility in Coolify/Terminal
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

class OKXDynamicGridBot:
    def __init__(self):
        self.bot_name = os.getenv('BOT_NAME', 'OKX_Grid_Bot_01')
        logger.info(f"--- Initializing {self.bot_name} ---")

        # SECURE API CONFIGURATION
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',  # Ensure this matches your region
            'options': {'defaultType': 'spot'}
        })
        
        self.exchange.set_sandbox_mode(True)
        self.symbol = 'DOGE/USDT'
        
        # BUDGET MANAGEMENT
        self.total_bot_budget = 100.0  
        self.number_of_grids = 4
        self.capital_per_grid = self.total_bot_budget / self.number_of_grids  
        
        self.bot_cash = 100.0          
        self.bot_doge = 0.0            
        self.purchased_batches = []
        self.grid_percentage = 0.015  
        self.current_buy_order = None
        self.current_sell_order = None

        # LOG STARTUP HEARTBEAT
        self.log_bot_startup()

    def log_bot_startup(self):
        """Signals to database/logs that this specific bot is live."""
        logger.info(f"[{self.bot_name}] Heartbeat: Bot System Active.")
        # If you have your database logging function here, call it:
        # log_trade_to_db(..., 'SYSTEM', 'BOT_STARTED')

    def get_moving_average_center(self):
        try:
            candles = self.exchange.fetch_ohlcv(self.symbol, timeframe='1h', limit=30)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return float(df['close'].rolling(window=20).mean().iloc[-1])
        except Exception as e:
            logger.error(f"Error fetching MA: {e}")
            return None

    # ... [Keep your existing sync_and_audit_fills and update_grid_positions methods]

    def start_loop(self):
        logger.info(f"Starting {self.bot_name} loop...")
        last_ma_update_time = 0
        ma_update_interval = 900 

        while True:
            try:
                if time.time() - last_ma_update_time >= ma_update_interval:
                    self.update_grid_positions()
                    last_ma_update_time = time.time()
                else:
                    self.sync_and_audit_fills()
            except Exception as e:
                logger.error(f"Main loop error: {e}")
            
            time.sleep(15)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        logger.info("Stopping bot instance.")
        sys.exit(0)
