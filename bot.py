import ccxt
import os
import sys

print("=== OKX API Diagnostic Test (with regional fixes) ===")

api_key = os.getenv('OKX_API_KEY')
api_secret = os.getenv('OKX_API_SECRET')
passphrase = os.getenv('OKX_PASSPHRASE')

print(f"API Key:     {'✅ Loaded' if api_key else '❌ MISSING'}")
print(f"Secret:      {'✅ Loaded' if api_secret else '❌ MISSING'}")
print(f"Passphrase:  {'✅ Loaded' if passphrase else '❌ MISSING'}")

if not all([api_key, api_secret, passphrase]):
    print("❌ Missing credentials!")
    sys.exit(1)

# Try different hostnames - this fixes most 50119 errors
configs_to_try = [
    {},  # default
    {'hostname': 'my.okx.com'},      # EEA / Europe
    {'hostname': 'us.okx.com'},      # USA
    {'hostname': 'app.okx.com'},     # Alternative US
]

for i, extra in enumerate(configs_to_try):
    print(f"\n--- Attempt {i+1} ---")
    try:
        exchange = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
                'headers': {'x-simulated-trading': '1'}   # Demo mode
            },
            **extra
        })

        print(f"Using hostname: {extra.get('hostname', 'default')}")
        exchange.load_markets()
        print("✅ load_markets() successful")

        balance = exchange.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        print(f"✅ Balance fetched! USDT: {usdt}")

        ticker = exchange.fetch_ticker('DOGE/USDT')
        print(f"✅ DOGE Price: {ticker['last']}")

        print("🎉 SUCCESS! Use this config.")
        break

    except Exception as e:
        print(f"❌ Failed: {e}")
