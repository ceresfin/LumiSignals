#!/usr/bin/env python3
"""Get H1 trade setups for all 28 currency pairs"""

import requests
import time

# Lambda URL
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

# All 28 currency pairs 
ALL_PAIRS = [
    'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'USD_CHF', 'AUD_USD', 'NZD_USD',
    'EUR_GBP', 'EUR_JPY', 'EUR_CAD', 'EUR_CHF', 'EUR_AUD', 'EUR_NZD',
    'GBP_JPY', 'GBP_CAD', 'GBP_CHF', 'GBP_AUD', 'GBP_NZD',
    'AUD_JPY', 'AUD_CAD', 'AUD_CHF', 'AUD_NZD',
    'NZD_JPY', 'NZD_CAD', 'NZD_CHF',
    'CAD_JPY', 'CAD_CHF',
    'CHF_JPY'
]

print("🚀 Getting H1 Trade Setups for All 28 Currency Pairs")
print("=" * 80)

all_setups = []
pairs_with_setups = []
pairs_without_setups = []

# Process in smaller batches to avoid timeout
batch_size = 6
for i in range(0, len(ALL_PAIRS), batch_size):
    batch = ALL_PAIRS[i:i+batch_size]
    instruments_str = ','.join(batch)
    
    print(f"\n📡 Processing batch {i//batch_size + 1}: {', '.join(batch)}")
    
    params = {
        'timeframe': 'H1',
        'instruments': instruments_str
    }
    
    try:
        response = requests.get(
            f"{LAMBDA_URL}/analytics/trade-setups",
            params=params,
            timeout=45
        )
        
        if response.status_code == 200:
            data = response.json()
            setups = data.get('trade_setups', [])
            
            if setups:
                print(f"✅ Found {len(setups)} setups")
                all_setups.extend(setups)
                
                # Track which pairs have setups
                for setup in setups:
                    pair = setup.get('instrument', 'Unknown')
                    if pair not in pairs_with_setups:
                        pairs_with_setups.append(pair)
                        
                # Show brief summary for this batch
                for setup in setups:
                    pair = setup.get('instrument', 'Unknown')
                    direction = setup.get('direction', 'Unknown')
                    fib_level = setup.get('fibonacci_level', 'Unknown')
                    rr = setup.get('risk_reward_ratio', 'Unknown')
                    print(f"    {pair}: {direction} at {fib_level} (R:R {rr})")
            else:
                print(f"❌ No setups found")
                
        else:
            print(f"❌ Error: Status {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    
    # Small delay between batches
    time.sleep(1)

# Calculate pairs without setups
pairs_without_setups = [pair for pair in ALL_PAIRS if pair not in pairs_with_setups]

print("\n" + "=" * 80)
print("📊 H1 TRADE SETUPS SUMMARY")
print("=" * 80)

print(f"\n🎯 TOTAL RESULTS:")
print(f"   Total Pairs Analyzed: {len(ALL_PAIRS)}")
print(f"   Pairs with Setups: {len(pairs_with_setups)}")
print(f"   Pairs without Setups: {len(pairs_without_setups)}")
print(f"   Total Trade Setups: {len(all_setups)}")

if pairs_with_setups:
    print(f"\n✅ PAIRS WITH SETUPS ({len(pairs_with_setups)}):")
    for pair in pairs_with_setups:
        pair_setups = [s for s in all_setups if s.get('instrument') == pair]
        print(f"   {pair}: {len(pair_setups)} setup{'s' if len(pair_setups) > 1 else ''}")

if pairs_without_setups:
    print(f"\n❌ PAIRS WITHOUT SETUPS ({len(pairs_without_setups)}):")
    pairs_str = ', '.join(pairs_without_setups)
    if len(pairs_str) > 80:
        # Split long list into multiple lines
        chunks = [pairs_without_setups[i:i+6] for i in range(0, len(pairs_without_setups), 6)]
        for chunk in chunks:
            print(f"   {', '.join(chunk)}")
    else:
        print(f"   {pairs_str}")

if all_setups:
    print(f"\n" + "=" * 80)
    print("📋 DETAILED H1 TRADE SETUPS")
    print("=" * 80)
    
    # Sort by quality score (highest first)
    all_setups.sort(key=lambda x: x.get('setup_quality', 0), reverse=True)
    
    for i, setup in enumerate(all_setups, 1):
        print(f"\n🔸 Setup #{i}: {setup.get('instrument', 'Unknown')}")
        print(f"   Direction: {setup.get('direction', 'Unknown')}")
        print(f"   Entry: {setup.get('entry_price', 'Unknown')}")
        print(f"   Target: {setup.get('target_price', 'Unknown')}")
        print(f"   Stop Loss: {setup.get('stop_loss', 'Unknown')}")
        print(f"   Risk/Reward: {setup.get('risk_reward_ratio', 'Unknown')}")
        print(f"   Risk Pips: {setup.get('risk_pips', 'Unknown')}")
        print(f"   Reward Pips: {setup.get('reward_pips', ['Unknown'])[0] if setup.get('reward_pips') else 'Unknown'}")
        print(f"   Fibonacci Level: {setup.get('fibonacci_level', 'Unknown')}")
        print(f"   Distance to Entry: {setup.get('distance_to_entry_pips', 'Unknown')} pips")
        print(f"   Quality Score: {setup.get('setup_quality', 'Unknown')}/100")
        print(f"   Setup Type: {setup.get('setup_type', 'Unknown')}")
        print(f"   Strategy: {setup.get('strategy', 'Unknown')}")

print(f"\n💡 Note: H1 timeframe uses 50-pip distance filtering for intraday trading")
print(f"    More generous than M5 (10 pips) but still focused on quality setups")
print(f"    Suitable for swing trading and position holding")

print(f"\n🕐 Analysis completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")