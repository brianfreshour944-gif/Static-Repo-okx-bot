import os
import time
import ccxt
from dotenv import load_dotenv

load_dotenv()

class OKXGridBot:
    def __init__(self):
        # Ensure these match exactly your OKX API setup
        self.exchange = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_API_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'), # Ensure this is in your .env
            'enableRateLimit': True,
            'hostname': 'app.okx.com',
            'options': {'defaultType': 'spot'}
        })
        
        # IF you are using LIVE keys, set this to False.
        # IF you are using DEMO/SANDBOX keys, set this to True.
        self.exchange.set_sandbox_mode(False) 
        
        self.symbol = 'DOGE/USDT'
        self.total_budget = 100.0
        self.grid_count = 4
        self.grid_spacing = 0.004

        self.active_buys = {}
        self.active_sells = {}

        self.test_connection()
    
    # ... (Rest of your methods: test_connection, get_current_price, etc.)
