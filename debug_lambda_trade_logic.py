#!/usr/bin/env python3
"""Debug which Fibonacci function is actually being called"""

import requests
import json

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🔍 Debugging Lambda Trade Setup Logic Flow")
print("=" * 60)

# Test the full analytics endpoint
params = {
    'timeframe': 'M5',
    'instruments': 'EUR_USD'
}

print("Testing /analytics/all-signals endpoint...")
response = requests.get(
    f"{LAMBDA_URL}/analytics/all-signals",
    params=params,
    timeout=30
)

if response.status_code == 200:
    data = response.json()
    eur_usd = data['data']['EUR_USD']
    
    print(f"\n📊 EUR_USD Fibonacci Analysis (all-signals):")
    print(f"Direction: {eur_usd['fibonacci']['direction']}")
    print(f"High: {eur_usd['fibonacci']['high']}")
    print(f"Low: {eur_usd['fibonacci']['low']}")
    
    # Check if trade_setups are in fibonacci data
    if 'trade_setups' in eur_usd['fibonacci']:
        print(f"Trade setups in fibonacci data: {len(eur_usd['fibonacci']['trade_setups'])}")
        for i, setup in enumerate(eur_usd['fibonacci']['trade_setups'][:2]):
            print(f"  Setup {i+1}: {setup['direction']} at {setup.get('fibonacci_level', 'unknown level')}")
    else:
        print("No trade_setups in fibonacci data")
    
    # Check if trade_setups are at top level
    if 'trade_setups' in eur_usd:
        print(f"Trade setups at top level: {len(eur_usd['trade_setups'])}")
        for i, setup in enumerate(eur_usd['trade_setups'][:2]):
            print(f"  Setup {i+1}: {setup.get('direction', 'unknown')} at {setup.get('fibonacci_level', 'unknown level')}")
    else:
        print("No trade_setups at top level")

print("\n" + "=" * 60)
print("Testing /analytics/trade-setups endpoint...")

response2 = requests.get(
    f"{LAMBDA_URL}/analytics/trade-setups",
    params=params,
    timeout=30
)

if response2.status_code == 200:
    data2 = response2.json()
    setups = data2.get('trade_setups', [])
    
    print(f"\n📈 Trade Setups Endpoint Results: {len(setups)} setups")
    for i, setup in enumerate(setups):
        print(f"  Setup {i+1}: {setup['direction']} at {setup.get('fibonacci_level', setup.get('retracement_level', 'unknown'))}")
        print(f"    Strategy: {setup.get('strategy', 'Unknown')}")
        print(f"    Setup Type: {setup.get('setup_type', 'Unknown')}")
        
print("\n💡 Analysis:")
print("- If trade_setups exist in fibonacci data → using improved analysis")
print("- If no trade_setups in fibonacci → falling back to old fibonacci_trade_setups.py")
print("- Different directions between endpoints → different functions being used")