import os
import time
import ccxt.pro as ccxt  # <-- Use ccxt.pro

class OKXDynamicGridBot:
    def __init__(self):
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',   # or 'unified'
            }
        })
        self.exchange.set_sandbox_mode(True)

        self.symbol = 'DOGE/USDT'
        self.total_bot_budget = 100.0
        self.grid_count = 5          # More grids = finer control
        self.grid_spacing = 0.003    # Price spacing (adjust based on volatility)
        
        self.active_buy_orders = {}   # {price: order_id}
        self.active_sell_orders = {}  # {price: order_id}
        self.position = 0.0           # Current DOGE holding

    async def watch_price_and_orders(self):
        """Main real-time loop using WebSockets"""
        print("Bot started with WebSocket monitoring...")
        
        while True:
            try:
                # Get latest price via WebSocket (non-blocking)
                ticker = await self.exchange.watch_ticker(self.symbol)
                current_price = ticker['last']
                
                print(f"Current price: {current_price:.5f}")

                # Check for filled orders in real-time
                orders = await self.exchange.watch_orders(self.symbol)
                self.handle_filled_orders(orders)

                # Maintain grid
                self.manage_grid(current_price)

            except Exception as e:
                print(f"WebSocket error: {e}")
                await asyncio.sleep(5)  # Brief backoff

    def manage_grid(self, current_price):
        """Dynamic grid around current price"""
        amount_per_grid = self.total_bot_budget / self.grid_count
        
        # Calculate dynamic grid levels
        half = self.grid_count // 2
        grid_prices = [
            round(current_price * (1 + (i - half) * self.grid_spacing), 5)
            for i in range(self.grid_count)
        ]

        for price in grid_prices:
            qty = round(amount_per_grid / price, 1)
            
            if price < current_price and price not in self.active_buy_orders:
                try:
                    order = self.exchange.create_limit_buy_order(self.symbol, qty, price)
                    self.active_buy_orders[price] = order['id']
                    print(f"Placed BUY grid at {price}")
                except Exception as e:
                    print(f"Buy order error: {e}")

            elif price > current_price and price not in self.active_sell_orders:
                try:
                    order = self.exchange.create_limit_sell_order(self.symbol, qty, price)
                    self.active_sell_orders[price] = order['id']
                    print(f"Placed SELL grid at {price}")
                except Exception as e:
                    print(f"Sell order error: {e}")

    def handle_filled_orders(self, orders):
        """Process filled orders from watch_orders"""
        for order in orders:
            if order['status'] == 'closed':
                price = order['price']
                side = order['side']
                
                if side == 'buy' and price in self.active_buy_orders:
                    print(f"BUY filled at {price}")
                    del self.active_buy_orders[price]
                    # Update position...
                elif side == 'sell' and price in self.active_sell_orders:
                    print(f"SELL filled at {price}")
                    del self.active_sell_orders[price]

    async def run(self):
        await self.watch_price_and_orders()


# Run the async bot
if __name__ == '__main__':
    import asyncio
    bot = OKXDynamicGridBot()
    asyncio.run(bot.run())
