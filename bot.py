#!/usr/bin/env python3
import os
import time
import ccxt
import psycopg2
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'hostname': 'app.okx.com',
            'options': {'defaultType': 'spot', 'x-simulated-trading': '1'}
        })
        self.exchange.set_sandbox_mode(True)

        self.bot_name = os.getenv('BOT_NAME', 'DOGE_GRID_BOT')
        self.symbol = 'DOGE/USDT'
        self.grid_levels = 5          # number of buy/sell orders on each side
        self.grid_step_percent = 0.5  # 0.5% between levels
        self.order_amount_usdt = 10   # amount in USDT per order (adjust based on your balance)
        
        # Track open order IDs to avoid duplicates
        self.active_order_ids = set()
        self.processed_order_ids = set()  # for logging already filled orders

        self.test_connection()
        self.update_grid_orders()

    # ---------- DATABASE HELPERS ----------
    def log_error_to_db(self, error_msg):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                        (self.bot_name, str(error_msg))
                    )
                    conn.commit()
        except Exception as e:
            print(f"❌ Failed to log error: {e}")

    def log_trade_to_postgres(self, side, price, qty, order_id="N/A"):
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO trades 
                        (bot_name, exchange, symbol, side, price, quantity, value, order_id, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """, (self.bot_name, "OKX", self.symbol, side, price, qty, (price * qty), order_id))
                    conn.commit()
        except Exception as e:
            self.log_error_to_db(f"Trade log error: {e}")

    def check_status(self):
        """Stop bot if database status == 'STOP'"""
        db_url = os.getenv('DATABASE_URL')
        if not db_url: return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO bot_status (bot_name, last_update, status)
                        VALUES (%s, NOW(), 'RUNNING')
                        ON CONFLICT (bot_name) 
                        DO UPDATE SET last_update = NOW(), status = EXCLUDED.status
                    """, (self.bot_name,))
                    cur.execute("SELECT status FROM bot_status WHERE bot_name = %s", (self.bot_name,))
                    row = cur.fetchone()
                    if row and row[0] == 'STOP':
                        print(f"🛑 Kill switch activated. Shutting down.")
                        exit(0)
        except Exception as e:
            print(f"⚠️ Status check failed: {e}")

    # ---------- GRID LOGIC ----------
    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return ticker['last']
        except Exception as e:
            self.log_error_to_db(f"Price fetch error: {e}")
            return None

    def calculate_grid_prices(self, center_price):
        grid_prices = []
        # Buy levels (below center)
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 - (self.grid_step_percent / 100) * i)
            grid_prices.append(('buy', round(price, 8)))
        # Sell levels (above center)
        for i in range(1, self.grid_levels + 1):
            price = center_price * (1 + (self.grid_step_percent / 100) * i)
            grid_prices.append(('sell', round(price, 8)))
        return grid_prices

    def cancel_all_open_orders(self):
        try:
            self.exchange.cancel_all_orders(self.symbol)
            self.active_order_ids.clear()
            print("✅ Cancelled all open orders")
        except Exception as e:
            self.log_error_to_db(f"Cancel orders error: {e}")

    def place_grid_orders(self, grid_prices):
        """Place limit orders for each grid level"""
        for side, price in grid_prices:
            # Calculate quantity based on fixed USDT amount
            qty = round(self.order_amount_usdt / price, 2)  # DOGE decimals: 2 is safe
            try:
                if side == 'buy':
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                else:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                self.active_order_ids.add(order['id'])
                print(f"📌 Placed {side.upper()} order @ {price:.8f} (qty {qty})")
            except Exception as e:
                self.log_error_to_db(f"Failed to place {side} order at {price}: {e}")

    def update_grid_orders(self):
        """Refresh the entire grid (cancel old, place new based on current price)"""
        price = self.get_current_price()
        if not price:
            return
        self.cancel_all_open_orders()
        grid = self.calculate_grid_prices(price)
        self.place_grid_orders(grid)
        print(f"🌐 Grid refreshed. Center price: {price:.8f}")

    def sync_filled_orders(self):
        """Check for filled orders and replace them with opposite orders"""
        try:
            closed_orders = self.exchange.fetch_closed_orders(self.symbol, limit=50)
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.processed_order_ids:
                    continue
                if order['status'] == 'closed' and order.get('price'):
                    price = float(order['price'])
                    qty = float(order['amount'])
                    side = order['side'].upper()
                    self.log_trade_to_postgres(side, price, qty, order_id)
                    self.processed_order_ids.add(order_id)
                    print(f"✅ {side} FILLED @ {price:.8f} (qty {qty})")

                    # --- Re‑place opposite order to keep grid alive ---
                    opposite_side = 'buy' if side == 'SELL' else 'sell'
                    # Use the same price (fill price) for the new limit order
                    try:
                        if opposite_side == 'buy':
                            new_order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                        else:
                            new_order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                        self.active_order_ids.add(new_order['id'])
                        print(f"🔄 Replaced {side} order with new {opposite_side.upper()} @ {price:.8f}")
                    except Exception as e:
                        self.log_error_to_db(f"Failed to replace order: {e}")
        except Exception as e:
            self.log_error_to_db(f"Sync error: {e}")

    # ---------- MAIN LOOP ----------
    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get('USDT', {}).get('free', 0)
            print(f"✅ Connected! USDT balance: {usdt:.2f}")
        except Exception as e:
            self.log_error_to_db(f"Connection failed: {e}")
            raise

    def run(self):
        print(f"🤖 {self.bot_name} - Grid Bot Started")
        print(f"   Levels: {self.grid_levels} | Step: {self.grid_step_percent}% | Amount per order: {self.order_amount_usdt} USDT")
        last_grid_refresh = time.time()
        while True:
            try:
                self.check_status()
                current_price = self.get_current_price()
                if current_price:
                    print(f"📊 [{time.strftime('%H:%M:%S')}] Price: {current_price:.8f}")

                # Sync filled orders every cycle
                self.sync_filled_orders()

                # Refresh the entire grid every 60 seconds (in case price moves too far)
                if time.time() - last_grid_refresh > 60:
                    self.update_grid_orders()
                    last_grid_refresh = time.time()

                time.sleep(10)  # check every 10 seconds
            except Exception as e:
                self.log_error_to_db(f"Main loop error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
