 #!/usr/bin/env python3
import os
import time
import ccxt
import psycopg2
from dotenv import load_dotenv
from collections import deque

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

        self.bot_name     = os.getenv('BOT_NAME', 'Static-Repo-okx-bot')
        self.symbol       = 'DOGE/USDT'
        self.grid_levels  = 3
        self.grid_step_percent = 4.0

        # Only recalculate grid if price moves more than this % from last center.
        # 2% is wide enough that normal DOGE noise doesn't trigger constant rebuilds.
        self.grid_buffer  = 0.02

        # Hard floor — bot will not place any BUY below this price.
        # Set to ~15% below a typical entry; adjust to your comfort level.
        self.min_price    = float(os.getenv('GRID_MIN_PRICE', '0.060'))

        # Hard ceiling — bot will not place any SELL above this price.
        self.max_price    = float(os.getenv('GRID_MAX_PRICE', '0.130'))

        self.active_orders       = {}          # price -> order_id
        self.processed_order_ids = deque(maxlen=200)
        self.last_grid_center    = 0.0

        self.test_connection()
        self.clear_all_orders()

    # ------------------------------------------------------------------
    # ORDER MANAGEMENT
    # ------------------------------------------------------------------

    def clear_all_orders(self):
        """Cancel every open order and reset active_orders tracking."""
        try:
            while True:
                open_orders = self.exchange.fetch_open_orders(self.symbol)
                if not open_orders:
                    break
                print(f"🧹 Found {len(open_orders)} open orders. Clearing...")
                for order in open_orders:
                    try:
                        self.exchange.cancel_order(order['id'], self.symbol)
                    except Exception as e:
                        print(f"⚠️ Could not cancel {order['id']}: {e}")
                time.sleep(1)
            self.active_orders = {}
            print("✅ All orders cleared.")
        except Exception as e:
            print(f"⚠️ Error during clear: {e}")

    def refresh_active_orders(self):
        """Re-sync active_orders dict from the exchange (source of truth)."""
        try:
            open_orders = self.exchange.fetch_open_orders(self.symbol)
            self.active_orders = {
                round(float(o['price']), 8): o['id']
                for o in open_orders
            }
        except Exception as e:
            self.log_error_to_db(f"refresh_active_orders error: {e}")

    def update_grid_orders(self):
        """
        Place the initial grid of limit orders around the current price.
        Only rebuilds if price has moved more than grid_buffer % from
        the last center — prevents constant order churn on small moves.
        """
        price = self.get_current_price()
        if not price:
            return

        # Grid lock: skip if price hasn't moved enough
        if self.last_grid_center != 0:
            price_diff = abs(price - self.last_grid_center) / self.last_grid_center
            if price_diff < self.grid_buffer:
                return

        self.last_grid_center = price
        self.refresh_active_orders()

        grid = self.calculate_grid_prices(price)
        for side, p in grid:
            p = round(p, 8)

            # Respect price floor and ceiling
            if side == 'buy'  and p < self.min_price:
                print(f"⛔ Skipping BUY @ {p:.8f} — below min_price {self.min_price}")
                continue
            if side == 'sell' and p > self.max_price:
                print(f"⛔ Skipping SELL @ {p:.8f} — above max_price {self.max_price}")
                continue

            # Don't duplicate an order that already exists at this level
            if p in self.active_orders:
                continue

            qty = round(33.33 / p, 2)
            order = self.place_single_order(side, p, qty)
            if order:
                self.active_orders[p] = order['id']
                time.sleep(0.5)

    def place_single_order(self, side, price, qty):
        try:
            params = {'postOnly': True}
            if side == 'buy':
                order = self.exchange.create_limit_buy_order(
                    self.symbol, qty, price, params=params)
            else:
                order = self.exchange.create_limit_sell_order(
                    self.symbol, qty, price, params=params)
            print(f"📌 Placed {side.upper()} @ {price:.8f}")
            return order
        except Exception as e:
            self.log_error_to_db(f"Failed to place {side} order @ {price}: {e}")
            return None

    # ------------------------------------------------------------------
    # FILL HANDLING
    # ------------------------------------------------------------------

    def sync_filled_orders(self):
        """
        Detect newly filled orders and place the counter-order on the
        opposite side.  Checks that the counter-price isn't already
        occupied before placing to prevent duplicate orders.
        """
        try:
            orders = self.exchange.fetch_closed_orders(self.symbol, limit=20)
        except Exception as e:
            self.log_error_to_db(f"fetch_closed_orders error: {e}")
            return

        for order in orders:
            oid = order['id']
            if oid in self.processed_order_ids:
                continue

            # Only handle fully-filled orders
            if order.get('status') != 'closed' or float(order.get('filled', 0)) == 0:
                continue

            self.processed_order_ids.append(oid)

            price = float(order['price'])
            qty   = float(order['amount'])
            side  = order['side']
            fee   = float(order.get('fee', {}).get('cost', 0.0))

            self.log_trade_to_postgres(side.upper(), price, qty, oid, fee)
            print(f"✅ Fill detected: {side.upper()} {qty} @ {price:.8f}")

            # Remove from local tracking
            self.active_orders.pop(round(price, 8), None)

            # Calculate counter-order price
            offset      = self.grid_step_percent / 100
            new_side    = 'sell' if side == 'buy' else 'buy'
            new_price   = round(
                price * (1 + offset) if side == 'buy' else price * (1 - offset),
                8
            )

            # Respect floor / ceiling
            if new_side == 'buy' and new_price < self.min_price:
                print(f"⛔ Counter BUY @ {new_price:.8f} skipped — below min_price")
                continue
            if new_side == 'sell' and new_price > self.max_price:
                print(f"⛔ Counter SELL @ {new_price:.8f} skipped — above max_price")
                continue

            # Re-sync before checking for duplicates so we have fresh data
            self.refresh_active_orders()
            if round(new_price, 8) in self.active_orders:
                print(f"⚠️ Counter {new_side.upper()} @ {new_price:.8f} already exists — skipping")
                continue

            counter = self.place_single_order(new_side, new_price, qty)
            if counter:
                self.active_orders[round(new_price, 8)] = counter['id']
                # Small pause so exchange state settles before next iteration
                time.sleep(1)

    # ------------------------------------------------------------------
    # DATABASE HELPERS
    # ------------------------------------------------------------------

    def log_error_to_db(self, error_msg):
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO bot_errors (bot_name, error_message) VALUES (%s, %s)",
                        (self.bot_name, str(error_msg))
                    )
                    conn.commit()
        except Exception:
            pass

    def log_trade_to_postgres(self, side, price, qty, order_id, fee):
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO trades
                           (bot_name, exchange, symbol, side, price, quantity,
                            value, fee, order_id, timestamp)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
                        (self.bot_name, "OKX", self.symbol, side,
                         price, qty, price * qty, fee, order_id)
                    )
                    conn.commit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # MISC HELPERS
    # ------------------------------------------------------------------

    def check_status(self):
        db_url = os.getenv('DATABASE_URL')
        if not db_url:
            return
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM bot_status WHERE bot_name = %s",
                        (self.bot_name,)
                    )
                    row = cur.fetchone()
                    if row and row[0] == 'STOP':
                        print("🛑 STOP signal received. Shutting down.")
                        exit(0)
        except Exception:
            pass

    def get_current_price(self):
        try:
            return self.exchange.fetch_ticker(self.symbol)['last']
        except Exception as e:
            self.log_error_to_db(f"get_current_price error: {e}")
            return None

    def calculate_grid_prices(self, center_price):
        """Return list of (side, price) tuples for every grid level."""
        grid_prices = []
        step = self.grid_step_percent / 100
        for i in range(1, self.grid_levels + 1):
            grid_prices.append(('buy',  round(center_price * (1 - step * i), 8)))
            grid_prices.append(('sell', round(center_price * (1 + step * i), 8)))
        return grid_prices

    def test_connection(self):
        try:
            balance = self.exchange.fetch_balance().get('USDT', {}).get('free', 0)
            print(f"✅ Connected! USDT balance: {balance:.2f}")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            raise

    # ------------------------------------------------------------------
    # MAIN LOOP
    # ------------------------------------------------------------------

    def run(self):
        print(f"🤖 {self.bot_name} started | symbol={self.symbol} | "
              f"levels={self.grid_levels} | step={self.grid_step_percent}% | "
              f"floor={self.min_price} | ceiling={self.max_price}")
        while True:
            self.check_status()
            self.update_grid_orders()
            self.sync_filled_orders()
            time.sleep(5)


if __name__ == "__main__":
    bot = OKXGridBot()
    bot.run()
