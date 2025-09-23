#!/usr/bin/env python3
"""Debug why trade-setups endpoint returns 0 setups when all-signals has data"""

import requests
import json

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

# Test with EUR_USD on M5 (default for trade-setups)
instrument = "EUR_USD"
timeframe = "M5"

print("🔍 Debugging Trade Setups Endpoint Data Flow")
print("=" * 60)

# Step 1: Check all-signals data structure
print(f"\n📊 Step 1: Checking all-signals data structure for {instrument} {timeframe}")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/all-signals",
        params={'timeframe': timeframe, 'instruments': instrument},
        timeout=30
    )
    
    if response.status_code == 200:
        all_signals_data = response.json()
        
        # Find EUR_USD data
        eur_usd_data = None
        for pair_data in all_signals_data.get('data', {}).get('instruments', []):
            if pair_data.get('instrument') == instrument:
                eur_usd_data = pair_data
                break
        
        if eur_usd_data:
            print(f"✅ Found {instrument} data in all-signals")
            
            # Check fibonacci data structure
            fibonacci_data = eur_usd_data.get('fibonacci', {})
            print(f"   Fibonacci data keys: {list(fibonacci_data.keys())}")
            
            # Check if trade_setups exist in fibonacci data
            fib_trade_setups = fibonacci_data.get('trade_setups', [])
            print(f"   Trade setups in fibonacci: {len(fib_trade_setups)}")
            
            # Check top-level trade_setups
            top_level_setups = eur_usd_data.get('trade_setups', [])
            print(f"   Trade setups at top level: {len(top_level_setups)}")
            
            if fib_trade_setups:
                print(f"   📋 Fibonacci trade setups:")
                for i, setup in enumerate(fib_trade_setups[:2]):
                    print(f"      Setup {i+1}: {setup.get('direction')} at {setup.get('fibonacci_level')} (Entry: {setup.get('entry_price')})")
            
            if top_level_setups:
                print(f"   📋 Top-level trade setups:")
                for i, setup in enumerate(top_level_setups[:2]):
                    print(f"      Setup {i+1}: {setup.get('direction')} at {setup.get('fibonacci_level')} (Entry: {setup.get('entry_price')})")
        else:
            print(f"❌ No {instrument} data found in all-signals")
    else:
        print(f"❌ All-signals request failed: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error in all-signals request: {e}")

# Step 2: Check trade-setups endpoint
print(f"\n📈 Step 2: Checking trade-setups endpoint for {instrument} {timeframe}")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': timeframe, 'instruments': instrument},
        timeout=30
    )
    
    if response.status_code == 200:
        trade_setups_data = response.json()
        setups = trade_setups_data.get('data', {}).get('trade_setups', [])
        print(f"✅ Trade-setups endpoint returned {len(setups)} setups")
        
        if setups:
            for i, setup in enumerate(setups[:2]):
                print(f"   Setup {i+1}: {setup.get('direction')} at {setup.get('fibonacci_level')} (Entry: {setup.get('entry_price')})")
        else:
            print(f"   📊 Response data structure:")
            print(f"      Success: {trade_setups_data.get('success')}")
            print(f"      Instruments analyzed: {trade_setups_data.get('data', {}).get('instruments_analyzed')}")
            print(f"      Setups found: {trade_setups_data.get('data', {}).get('setups_found')}")
    else:
        print(f"❌ Trade-setups request failed: {response.status_code}")
        print(f"   Response: {response.text}")
        
except Exception as e:
    print(f"❌ Error in trade-setups request: {e}")

# Step 3: Test with H1 timeframe (what all-signals uses by default)
print(f"\n📊 Step 3: Testing trade-setups with H1 timeframe (all-signals default)")
try:
    response = requests.get(
        f"{LAMBDA_URL}/analytics/trade-setups",
        params={'timeframe': 'H1', 'instruments': instrument},
        timeout=30
    )
    
    if response.status_code == 200:
        trade_setups_data = response.json()
        setups = trade_setups_data.get('data', {}).get('trade_setups', [])
        print(f"✅ Trade-setups H1 returned {len(setups)} setups")
        
        if setups:
            for i, setup in enumerate(setups[:2]):
                print(f"   Setup {i+1}: {setup.get('direction')} at {setup.get('fibonacci_level')} (Entry: {setup.get('entry_price')})")
    else:
        print(f"❌ Trade-setups H1 failed: {response.status_code}")
        
except Exception as e:
    print(f"❌ Error in trade-setups H1 request: {e}")

print("\n" + "=" * 60)
print("🔍 ANALYSIS SUMMARY")
print("=" * 60)
print("This debug script checks if:")
print("1. All-signals has trade setups in fibonacci data vs top-level")
print("2. Trade-setups endpoint can access the same data")
print("3. Timeframe differences (M5 vs H1) affect data availability")