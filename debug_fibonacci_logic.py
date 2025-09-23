#!/usr/bin/env python3
"""Debug Fibonacci trade direction logic"""

import requests

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🔍 Debugging Fibonacci Trade Direction Logic")
print("=" * 60)

# Get the raw analytics data
params = {
    'timeframe': 'H1'  # Use H1 to see the full Fibonacci data
}

response = requests.get(
    f"{LAMBDA_URL}/analytics/all-signals",
    params=params,
    timeout=30
)

if response.status_code == 200:
    data = response.json()
    eur_usd = data['data']['EUR_USD']
    
    print(f"\n📊 EUR_USD Analysis:")
    print(f"Direction: {eur_usd['fibonacci']['direction']}")
    print(f"High: {eur_usd['fibonacci']['high']}")
    print(f"Low: {eur_usd['fibonacci']['low']}")
    print(f"Current Price: {eur_usd['current_price']}")
    print(f"Current Retracement: {eur_usd['fibonacci']['current_retracement']:.2%}")
    
    # Get trade setups for M5
    params_m5 = {
        'timeframe': 'M5',
        'instruments': 'EUR_USD'
    }
    
    response_m5 = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params=params_m5,
        timeout=30
    )
    
    if response_m5.status_code == 200:
        data_m5 = response_m5.json()
        setups = data_m5.get('trade_setups', [])
        
        print(f"\n📈 M5 Trade Setups: {len(setups)} found")
        for setup in setups:
            print(f"\n Setup at {setup['entry_price']}:")
            print(f"   Direction: {setup['direction']}")
            print(f"   Fibonacci Level: {setup['fibonacci_level']}")
            print(f"   Setup Type: {setup.get('setup_type', 'Unknown')}")
            print(f"   Strategy: {setup.get('strategy', 'Unknown')}")
            
    # Check what levels are being used
    if 'detailed_levels' in eur_usd['fibonacci']:
        print(f"\n🎯 Available Fibonacci Levels:")
        for level in eur_usd['fibonacci']['detailed_levels']:
            print(f"   {level['ratio']:.1%}: {level['price']:.4f}")
            
print("\n💡 Expected Behavior:")
print("   - In UPTREND: BUY at 38.2%, 50%, 61.8%, 78.6%")
print("   - In UPTREND: SELL at 88.6%+ (reversal)")
print("   - In DOWNTREND: SELL at 38.2%, 50%, 61.8%, 78.6%") 
print("   - In DOWNTREND: BUY at 88.6%+ (reversal)")