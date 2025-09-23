#!/usr/bin/env python3
"""Test trade logic across multiple currency pairs to find uptrends"""

import requests

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

print("🧪 Testing Trade Logic Across Multiple Pairs")
print("=" * 60)

# Test multiple pairs to find one in uptrend
pairs = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'AUD_USD', 'USD_CAD', 'GBP_JPY']

for pair in pairs:
    params = {
        'timeframe': 'M5',
        'instruments': pair
    }
    
    try:
        response = requests.get(
            f"{LAMBDA_URL}/analytics/all-signals",
            params=params,
            timeout=20
        )
        
        if response.status_code == 200:
            data = response.json()
            pair_data = data['data'][pair]
            
            direction = pair_data['fibonacci']['direction']
            
            print(f"\n📊 {pair}:")
            print(f"  Direction: {direction}")
            
            if 'trade_setups' in pair_data['fibonacci']:
                setups = pair_data['fibonacci']['trade_setups']
                print(f"  Trade setups: {len(setups)}")
                
                for setup in setups[:2]:  # Show first 2 setups
                    fib_level = setup.get('fibonacci_level', 'unknown')
                    trade_dir = setup.get('direction', 'unknown')
                    print(f"    {trade_dir} at {fib_level}")
                    
                # Check if logic is correct
                if direction == 'uptrend':
                    buy_setups = [s for s in setups if s.get('direction') == 'BUY']
                    sell_setups = [s for s in setups if s.get('direction') == 'SELL']
                    print(f"    ✓ BUY setups: {len(buy_setups)}, SELL setups: {len(sell_setups)}")
                    
                    if sell_setups:
                        # Check if SELL setups are only at reversal levels (88.6%+)
                        for setup in sell_setups:
                            level_str = setup.get('fibonacci_level', '')
                            if '88.6%' in level_str or '100%' in level_str:
                                print(f"    ✅ SELL at reversal level: {level_str}")
                            else:
                                print(f"    ⚠️  SELL at continuation level: {level_str} (should be BUY)")
                                
                elif direction == 'downtrend':
                    buy_setups = [s for s in setups if s.get('direction') == 'BUY']
                    sell_setups = [s for s in setups if s.get('direction') == 'SELL']
                    print(f"    ✓ BUY setups: {len(buy_setups)}, SELL setups: {len(sell_setups)}")
            else:
                print(f"  No trade setups found")
        else:
            print(f"  Error: {response.status_code}")
            
    except Exception as e:
        print(f"  Error: {str(e)}")

print(f"\n💡 Expected Logic:")
print(f"  UPTREND: BUY at 38.2%, 50%, 61.8%, 78.6% | SELL at 88.6%+")
print(f"  DOWNTREND: SELL at 38.2%, 50%, 61.8%, 78.6% | BUY at 88.6%+")