#!/usr/bin/env python3
"""Debug target_price and risk_reward_ratio fields"""

import requests
import json

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🔍 Debugging Target Price and Risk/Reward Ratio")
print("=" * 60)

# Test the raw fibonacci data from all-signals 
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
    
    print(f"\n📊 EUR_USD Raw Fibonacci Data:")
    
    if 'trade_setups' in eur_usd['fibonacci']:
        setups = eur_usd['fibonacci']['trade_setups']
        print(f"Trade setups in fibonacci data: {len(setups)}")
        
        for i, setup in enumerate(setups[:2]):
            print(f"\n  Setup {i+1} RAW DATA:")
            print(f"    direction: {setup.get('direction')}")
            print(f"    entry_price: {setup.get('entry_price')}")
            print(f"    stop_loss: {setup.get('stop_loss')}")
            print(f"    target_price: {setup.get('target_price')}")  # Should NOT be 0
            print(f"    targets: {setup.get('targets', [])}")
            print(f"    risk_reward_ratio: {setup.get('risk_reward_ratio')}")  # Should NOT be 0
            print(f"    risk_reward_ratios: {setup.get('risk_reward_ratios', [])}")
            print(f"    risk_pips: {setup.get('risk_pips')}")
            print(f"    reward_pips: {setup.get('reward_pips', [])}")

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
    
    print(f"\nTrade Setups Endpoint: {len(setups)} setups")
    for i, setup in enumerate(setups[:2]):
        print(f"\n  Setup {i+1} PROCESSED DATA:")
        print(f"    direction: {setup.get('direction')}")
        print(f"    entry_price: {setup.get('entry_price')}")
        print(f"    stop_loss: {setup.get('stop_loss')}")
        print(f"    target_price: {setup.get('target_price')}")  # Check if different
        print(f"    targets: {setup.get('targets', [])}")
        print(f"    risk_reward_ratio: {setup.get('risk_reward_ratio')}")
        print(f"    risk_pips: {setup.get('risk_pips')}")
        print(f"    reward_pips: {setup.get('reward_pips', [])}")

print("\n💡 Analysis:")
print("- If raw fibonacci data has correct values → issue in trade-setups processing")
print("- If raw fibonacci data has 0 values → issue in improved_fibonacci_analysis.py")
print("- Check if field names match between data structures")