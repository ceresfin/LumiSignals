#!/usr/bin/env python3
"""Debug M5 batch processing"""

import requests
import json

LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🔍 Debugging M5 Batch Processing")
print("=" * 50)

# Test individual pairs that worked in H1
test_pairs = ['EUR_USD', 'GBP_USD', 'USD_JPY']

for pair in test_pairs:
    print(f"\n📊 Testing {pair} M5 individually")
    try:
        response = requests.get(
            f"{LAMBDA_URL}/analytics/trade-setups",
            params={'timeframe': 'M5', 'instruments': pair},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            setups = data.get('data', {}).get('trade_setups', [])
            print(f"   ✅ {len(setups)} setups found")
            if setups:
                for setup in setups:
                    print(f"      {setup.get('direction')} at {setup.get('fibonacci_level')} (Entry: {setup.get('entry_price')})")
        else:
            print(f"   ❌ Failed: {response.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")

# Test batch of 3
print(f"\n📊 Testing batch of 3 pairs M5")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'M5', 'instruments': ','.join(test_pairs)},
        timeout=45
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"   ✅ Batch: {len(setups)} setups found")
        
        response_data = data.get('data', {})
        print(f"   Details: {response_data.get('instruments_analyzed')} analyzed, {response_data.get('setups_found')} found")
        
        if setups:
            for setup in setups:
                print(f"      {setup.get('instrument')}: {setup.get('direction')} at {setup.get('fibonacci_level')}")
    else:
        print(f"   ❌ Batch failed: {response.status_code}")
        print(f"   Response: {response.text}")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Test with M5 default (no instruments specified)
print(f"\n📊 Testing M5 default instruments")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'M5'},
        timeout=45
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"   ✅ Default M5: {len(setups)} setups found")
        
        response_data = data.get('data', {})
        print(f"   Details: {response_data.get('instruments_analyzed')} analyzed, {response_data.get('setups_found')} found")
        
        if setups:
            for setup in setups[:3]:
                print(f"      {setup.get('instrument')}: {setup.get('direction')} at {setup.get('fibonacci_level')}")
    else:
        print(f"   ❌ Default M5 failed: {response.status_code}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 50)
print("🔍 SUMMARY")
print("Testing if M5 timeframe has data issues vs H1")