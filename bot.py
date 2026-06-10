import ccxt
import os

print("=== OKX Final Matching Test ===")

api_key = os.getenv('OKX_API_KEY')
api_secret = os.getenv('OKX_API_SECRET')
passphrase = os.getenv('OKX_PASSPHRASE')

configs = [
    {"name": "Live Mode - Default", "demo": False, "hostname": None},
    {"name": "Live Mode - my.okx.com (EEA)", "demo": False, "hostname": "my.okx.com"},
    {"name": "Live Mode - us.okx.com", "demo": False, "hostname": "us.okx.com"},
    {"name": "Live Mode - app.okx.com", "demo": False, "hostname": "app.okx.com"},
]

for cfg in configs:
    print(f"\n--- Trying: {cfg['name']} ---")
    try:
        options = {'defaultType': 'spot'}
        if cfg["demo"]:
            options['headers'] = {'x-simulated-trading': '1'}

        ex = ccxt.okx({
            'apiKey': api_key,
            'secret': api_secret,
            'password': passphrase,
            'enableRateLimit': True,
            'options': options,
            **({"hostname": cfg["hostname"]} if cfg["hostname"] else {})
        })

        ex.load_markets()
        print("✅ load_markets() OK")

        balance = ex.fetch_balance()
        usdt = balance.get('USDT', {}).get('free', 0)
        print(f"✅ Balance OK → USDT: {usdt}")

        ticker = ex.fetch_ticker('DOGE/USDT')
        print(f"✅ Ticker OK → Price: {ticker['last']}")

        print(f"🎉 SUCCESS! Use this config.")
        break

    except Exception as e:
        print(f"❌ Failed: {e}")
