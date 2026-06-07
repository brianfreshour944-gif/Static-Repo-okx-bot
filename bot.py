
import ccxt
import os

exchange = ccxt.okx({
    'apiKey': os.getenv('OKX_API_KEY'),
    'secret': os.getenv('OKX_API_SECRET'),
    'password': os.getenv('OKX_PASSPHRASE'),
    'options': {'defaultType': 'spot'}
})

# Enable sandbox if needed (comment out if using live)
exchange.set_sandbox_mode(True)

try:
    balance = exchange.fetch_balance()
    print("✅ Authentication successful!")
    print(f"USDT balance: {balance['USDT']['free']}")
except Exception as e:
    print(f"❌ Authentication failed: {e}")
