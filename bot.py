import ccxt
import os
import sys

print("=== OKX API Test - Matching Your Working Bot ===")

api_key = os.getenv('OKX_API_KEY')
api_secret = os.getenv('OKX_API_SECRET')
passphrase = os.getenv('OKX_PASSPHRASE')

print(f"Keys loaded: Yes")

configs = [
    {"name": "No demo header (most common for working bots)", 
     "options": {'defaultType': 'spot'}},
    
    {"name": "Demo header only", 
     "options": {'defaultType': 'spot', 'headers': {'x-simulated-trading': '1'}}},
    
    {"name": "US Region", 
     "options": {'defaultType': 'spot'}, "hostname": "us.okx.com"},
    
    {"name": "EEA / my.okx", 
     "options": {'defaultType': 'spot'}, "hostname": "my.okx.com"},
     
    {"name": "App OKX", 
     "options": {'defaultType': 'spot'}, "hostname": "app.okx.com"},
]

for cfg in configs:
    print(f"\n--- Trying: {cfg['name']} ---")
    try:
        ex = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': cfg["options"],
            **({"hostname": cfg["hostname"]} if "hostname" in cfg else {})
        })
        
        ex.load_markets()
        print("✅ load_markets() OK")
        
        balance = ex.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        print(f"✅ Balance OK → USDT: {usdt}")
        
        ticker = ex.fetch_ticker('DOGE/USDT')
        print(f"✅ Ticker OK → Price: {ticker['last']}")
        
        print(f"🎉 SUCCESS with {cfg['name']}")
        print("Use this configuration in your bot!")
        break
        
    except Exception as e:
        print(f"❌ Failed: {e}")
