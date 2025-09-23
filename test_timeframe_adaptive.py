#!/usr/bin/env python3
"""Test timeframe-adaptive logic in deployed Lambda"""

import requests
import json
import time

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🧪 Testing Timeframe-Adaptive Logic")
print("=" * 80)

# Test different timeframes
timeframes_to_test = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1']
instruments = 'EUR_USD,GBP_USD,USD_JPY,GBP_JPY'

results = {}

for timeframe in timeframes_to_test:
    print(f"\n📊 Testing {timeframe} timeframe...")
    
    params = {
        'timeframe': timeframe,
        'instruments': instruments
    }
    
    try:
        response = requests.get(
            f"{LAMBDA_URL}/analytics/trade-setups",
            params=params,
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            setups = data.get('trade_setups', [])
            
            # Analyze distances
            distances = []
            stop_buffers = []
            
            for setup in setups:
                # Distance to entry
                distance = setup.get('distance_to_entry_pips', 0)
                distances.append(distance)
                
                # Try to calculate stop buffer from risk_pips
                # This is approximate since we don't have the exact Fibonacci level price
                
            results[timeframe] = {
                'total_setups': len(setups),
                'distances': distances,
                'avg_distance': sum(distances) / len(distances) if distances else 0,
                'max_distance': max(distances) if distances else 0
            }
            
            print(f"✅ Found {len(setups)} setups")
            if distances:
                print(f"   Distance to entry: min={min(distances):.1f}, max={max(distances):.1f}, avg={results[timeframe]['avg_distance']:.1f} pips")
            
        else:
            print(f"❌ Error: Status code {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    
    time.sleep(0.5)  # Be nice to the API

# Expected values according to TIMEFRAME_SETTINGS
expected_distances = {
    'M5': 10,    # Very close entries for scalping
    'M15': 20,   # Short-term entry tolerance
    'M30': 35,   # Intraday entry flexibility
    'H1': 50,    # Current working setting
    'H4': 100,   # Wide entry range for swing trades
    'D1': 200    # Very wide for position trades
}

print("\n" + "=" * 80)
print("📈 SUMMARY: Timeframe-Adaptive Distance Analysis")
print("=" * 80)

for tf, expected_max in expected_distances.items():
    if tf in results:
        actual_max = results[tf]['max_distance']
        status = "✅" if actual_max <= expected_max else "⚠️"
        print(f"{tf}: Expected max={expected_max} pips, Actual max={actual_max:.1f} pips {status}")
    else:
        print(f"{tf}: No data")

print("\n💡 NOTE: Setups are only generated when price is within the max distance")
print("         If no setups found, price might be too far from Fibonacci levels")