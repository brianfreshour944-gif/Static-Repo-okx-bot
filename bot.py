#!/usr/bin/env python3
import os
import time
import logging
import pandas as pd
import ccxt
import psycopg2
import sys
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

# --- DATABASE LOGGING ENGINE ---
def log_trade_to_db(bot_name, symbol, side, price, quantity, value, order_id):
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, order_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (bot_name, 'OKX', symbol, side, float(price), float(quantity), float(value), str(order_id)))
                conn.commit()
    except Exception as e:
        logger.error(f"Database write error: {e}")

def check_status(bot_name):
    """Heartbeat and Kill Switch check for the bot_status table."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                # 1. Heartbeat
                cur.execute('''
                    INSERT INTO bot_status (bot_name, last_update, status)
                    VALUES (%s, NOW(), 'RUNNING')
                    ON CONFLICT (bot_name) 
                    DO UPDATE SET last_update = NOW(), status = EXCLUDED.status;
                ''', (bot_name,))
                
                # 2. Kill Switch
                cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (bot_name,))
                row = cur.fetchone()
                if row and row[0] == 'STOP':
                    logger.warning(f"🛑 Kill switch activated for {bot_name}. Shutting down.")
                    sys.exit(0)
                conn.commit()
    except Exception as e:
        logger.error(f"Heartbeat failed: {e}")

class OKXDynamicGridBot:
    def __init__(self):
        self.bot_name = os.getenv('BOT_NAME', 'OKX_Grid_Bot_01')
        logger.info(f"--- Initializing {self.bot_name} ---")

        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'us.okx.com',
            'options': {'defaultType': 'spot'}
        })
        self.exchange.set_sandbox_mode(True)
        
        self.symbol = 'DOGE/USDT'
        # Perform initial health check
        check_status(self.bot_name)

    def get_moving_average_center(self):
        try:
            candles = self.exchange.fetch_ohlcv(self.symbol, timeframe='1h', limit=30)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return float(df['close'].rolling(window=20).mean().iloc[-1])
        except Exception as e:
            logger.error(f"Error fetching MA: {e}")
            return None

    def start_loop(self):
        logger.info(f"Starting {self.bot_name} loop...")
        while True:
            try:
                # HEARTBEAT & KILL SWITCH CHECK
                check_status(self.bot_name)
                
                # ... [Grid logic here]
                
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
