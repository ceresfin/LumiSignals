#!/usr/bin/env python3
"""Debug batch vs single instrument requests"""

import requests
import json

LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🔍 Testing Batch vs Single Instrument Requests")
print("=" * 60)

# Test 1: Single instrument
print("\n📊 Test 1: Single EUR_USD request")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'H1', 'instruments': 'EUR_USD'},
        timeout=30
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"✅ Single request: {len(setups)} setups")
        if setups:
            setup = setups[0]
            print(f"   Setup: {setup.get('direction')} at {setup.get('fibonacci_level')}")
    else:
        print(f"❌ Single request failed: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error in single request: {e}")

# Test 2: Batch with EUR_USD only
print("\n📊 Test 2: Batch with only EUR_USD")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'H1', 'instruments': 'EUR_USD'},
        timeout=30
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"✅ Batch request (1 pair): {len(setups)} setups")
        if setups:
            setup = setups[0]
            print(f"   Setup: {setup.get('direction')} at {setup.get('fibonacci_level')}")
    else:
        print(f"❌ Batch request failed: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error in batch request: {e}")

# Test 3: Batch with 6 instruments (like the test script)
print("\n📊 Test 3: Batch with 6 instruments")
batch = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'USD_CHF', 'AUD_USD']
instruments_str = ','.join(batch)

try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'H1', 'instruments': instruments_str},
        timeout=45
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"✅ Batch request (6 pairs): {len(setups)} setups")
        
        # Show detailed response structure
        response_data = data.get('data', {})
        print(f"   Response details:")
        print(f"     Instruments analyzed: {response_data.get('instruments_analyzed')}")
        print(f"     Setups found: {response_data.get('setups_found')}")
        print(f"     Timeframe: {response_data.get('timeframe')}")
        
        if setups:
            for i, setup in enumerate(setups[:3]):
                print(f"   Setup {i+1}: {setup.get('instrument')} {setup.get('direction')} at {setup.get('fibonacci_level')}")
        else:
            print(f"   No setups in response")
    else:
        print(f"❌ Batch request failed: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error in batch request: {e}")

# Test 4: Default instruments (what trade-setups uses when no instruments specified)
print("\n📊 Test 4: Default instruments (no instruments parameter)")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'H1'},
        timeout=45
    )
    
    if response.status_code == 200:
        data = response.json()
        setups = data.get('data', {}).get('trade_setups', [])
        print(f"✅ Default request: {len(setups)} setups")
        
        response_data = data.get('data', {})
        print(f"   Instruments analyzed: {response_data.get('instruments_analyzed')}")
        print(f"   Setups found: {response_data.get('setups_found')}")
        
        if setups:
            for i, setup in enumerate(setups[:3]):
                print(f"   Setup {i+1}: {setup.get('instrument')} {setup.get('direction')} at {setup.get('fibonacci_level')}")
    else:
        print(f"❌ Default request failed: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error in default request: {e}")

print("\n" + "=" * 60)
print("🔍 ANALYSIS")
print("=" * 60)
print("Testing if the issue is with:")
print("1. Single vs batch processing")
print("2. Number of instruments in batch")
print("3. Parameter handling differences")