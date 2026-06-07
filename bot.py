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

def log_error_to_db(bot_name, error_msg):
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)", (bot_name, str(error_msg)))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log error to DB: {e}")

def log_trade_to_db(bot_name, symbol, side, price, quantity, value, order_id):
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Update order status in tracking table
                cur.execute("UPDATE bot_orders SET status = 'CLOSED' WHERE order_id = %s", (str(order_id),))
                # Insert record into history
                cur.execute("""
                    INSERT INTO trades (bot_name, exchange, symbol, side, price, quantity, value, order_id, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, (bot_name, 'OKX', symbol, side, float(price), float(quantity), float(value), str(order_id)))
                conn.commit()
    except Exception as e:
        logger.error(f"Database write error: {e}")

def register_order_in_db(bot_name, order_id, symbol, side, price):
    """Tags a new order as OPEN in the central tracker."""
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO bot_orders (order_id, bot_name, symbol, side, price, status)
                    VALUES (%s, %s, %s, %s, %s, 'OPEN')
                ''', (str(order_id), bot_name, symbol, side, float(price)))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to register order in DB: {e}")

def check_status(bot_name):
    db_url = os.getenv('DATABASE_URL')
    if not db_url: return
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO bot_status (bot_name, last_update, status)
                    VALUES (%s, NOW(), 'RUNNING')
                    ON CONFLICT (bot_name) 
                    DO UPDATE SET last_update = NOW(), status = EXCLUDED.status;
                ''', (bot_name,))
                cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (bot_name,))
                row = cur.fetchone()
                if row and row[0] == 'STOP':
                    logger.warning(f"🛑 Kill switch activated for {bot_name}.")
                    sys.exit(0)
                conn.commit()
    except Exception as e:
        logger.error(f"Heartbeat failed: {e}")

# --- BOT CLASS ---
class OKXDynamicGridBot:
    def __init__(self):
        self.bot_name = os.getenv('BOT_NAME', 'OKX_Grid_Bot_01')
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
        check_status(self.bot_name)

    def execute_and_track(self, side, amount, price):
        """Helper to create order and register in DB."""
        order = self.exchange.create_order(self.symbol, 'market', side, amount)
        register_order_in_db(self.bot_name, order['id'], self.symbol, side.upper(), price)
        return order

    def sync_orders(self):
        """Polls exchange for status updates on open orders."""
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT order_id, symbol FROM bot_orders WHERE bot_name = %s AND status = 'OPEN'", (self.bot_name,))
                for (oid, symbol) in cur.fetchall():
                    order_data = self.exchange.fetch_order(oid, symbol)
                    if order_data['status'] == 'closed':
                        log_trade_to_db(self.bot_name, symbol, order_data['side'], order_data['average'], order_data['amount'], 0.0, oid)

    def start_loop(self):
        logger.info(f"Starting {self.bot_name} loop...")
        while True:
            try:
                check_status(self.bot_name)
                self.sync_orders()
                # ... [Grid logic continues here]
            except Exception as e:
                error_msg = f"Main loop error: {str(e)}"
                logger.error(error_msg)
                log_error_to_db(self.bot_name, error_msg)
            time.sleep(15)

if __name__ == '__main__':
    bot = OKXDynamicGridBot()
    try:
        bot.start_loop()
    except KeyboardInterrupt:
        sys.exit(0)
