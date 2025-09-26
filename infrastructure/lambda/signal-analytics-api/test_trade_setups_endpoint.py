#!/usr/bin/env python3
"""
Comprehensive Trade Setup Analysis
Gets all trade setups with complete information across all 28 pairs and both timeframes
Always provides: pivot high/low, entry/target/stop with fib levels, trend direction, buy/sell signal, trade type
"""

import requests
import json
from datetime import datetime

BASE_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

def get_trade_setups(timeframe: str = 'M5'):
    """Get trade setups from production Lambda"""
    url = f"{BASE_URL}/analytics/trade-setups?timeframe={timeframe}"
    response = requests.get(url, timeout=30)
    return response.json() if response.status_code == 200 else None

def get_fibonacci_details(timeframe: str = 'M5'):
    """Get Fibonacci analysis details including pivot points"""
    url = f"{BASE_URL}/analytics/all-signals?timeframe={timeframe}"
    response = requests.get(url, timeout=30)
    return response.json() if response.status_code == 200 else None

def main():
    """Systematically get all trade setup information"""
    
    print("=" * 80)
    print("SWING FROM/TO TIMESTAMP ANALYSIS")
    print(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # Debug specific pairs with timestamps
    debug_pairs = ['AUD_CAD', 'AUD_JPY', 'NZD_JPY']
    
    for pair in debug_pairs:
        print(f"\n{pair}:")
        print('-' * 30)
        
        try:
            # Get Fibonacci details
            fib_data = get_fibonacci_details('M5')
            
            if not fib_data or not fib_data.get('success'):
                print('  ❌ API Error')
                continue
                
            pair_data = fib_data.get('data', {}).get(pair, {})
            
            if 'error' in pair_data:
                print(f'  ❌ Error: {pair_data["error"]}')
                continue
                
            if 'fibonacci' not in pair_data:
                print('  ❌ No Fibonacci data')
                continue
                
            fib = pair_data['fibonacci']
            current_price = pair_data.get('current_price', 0)
            
            swing_high = fib.get('high', 0)
            swing_low = fib.get('low', 0)
            direction = fib.get('direction', 'unknown')
            current_retracement = fib.get('current_retracement', 0)
            
            # Try to get swing analysis details with timestamps
            swing_analysis = fib.get('swing_analysis', {})
            high_swing = swing_analysis.get('high_swing', {}) if swing_analysis else {}
            low_swing = swing_analysis.get('low_swing', {}) if swing_analysis else {}
            
            print(f'  Swing High: {swing_high}')
            high_timestamp = high_swing.get('timestamp', 'No timestamp')
            high_index = high_swing.get('index', 'No index')
            print(f'  High Timestamp: {high_timestamp}')
            print(f'  High Index: {high_index}')
            
            print(f'  Swing Low:  {swing_low}')
            low_timestamp = low_swing.get('timestamp', 'No timestamp')  
            low_index = low_swing.get('index', 'No index')
            print(f'  Low Timestamp: {low_timestamp}')
            print(f'  Low Index: {low_index}')
            
            print(f'  Direction:  {direction}')
            print(f'  Current:    {current_price}')
            
            # Determine FROM (Fib 1.0) and TO (Fib 0.0) based on direction
            if direction == 'downtrend':
                swing_from = swing_high  # Fib 1.0 (100%)
                swing_to = swing_low     # Fib 0.0 (0%)
                from_timestamp = high_timestamp
                to_timestamp = low_timestamp
                print(f'  FROM (Fib 1.0): {swing_from} (HIGH) at {from_timestamp}')
                print(f'  TO (Fib 0.0):   {swing_to} (LOW) at {to_timestamp}')
            elif direction == 'uptrend':
                swing_from = swing_low   # Fib 1.0 (100%)
                swing_to = swing_high    # Fib 0.0 (0%)
                from_timestamp = low_timestamp
                to_timestamp = high_timestamp
                print(f'  FROM (Fib 1.0): {swing_from} (LOW) at {from_timestamp}')
                print(f'  TO (Fib 0.0):   {swing_to} (HIGH) at {to_timestamp}')
            else:
                print(f'  ❌ Unknown direction: {direction}')
                continue
                
            print(f'  Retracement: {current_retracement * 100:.1f}%')
            
            # Verify chronological order
            if high_timestamp != 'No timestamp' and low_timestamp != 'No timestamp':
                if direction == 'downtrend':
                    print(f'  ✅ Chronological Check: High ({from_timestamp}) should come BEFORE Low ({to_timestamp})')
                else:
                    print(f'  ✅ Chronological Check: Low ({from_timestamp}) should come BEFORE High ({to_timestamp})')
            else:
                print('  ❌ Cannot verify chronological order - missing timestamps')
            
        except Exception as e:
            print(f'  ❌ Error: {e}')
    
    # Original trade setup logic for comparison
    for timeframe in ['M5', 'H1']:
        print(f"\n{'='*20} {timeframe} TIMEFRAME {'='*20}")
        
        # Get trade setups and Fibonacci details
        setups_data = get_trade_setups(timeframe)
        fib_data = get_fibonacci_details(timeframe)
        
        if not setups_data or not fib_data or not setups_data.get('success'):
            print(f"❌ Error getting {timeframe} data")
            continue
            
        setups = setups_data['data']['trade_setups']
        setups_found = setups_data['data']['setups_found']
        instruments_analyzed = setups_data['data']['instruments_analyzed']
        
        print(f"\n📊 Analyzed: {instruments_analyzed} pairs | Found: {setups_found} setups")
        
        if not setups:
            print("❌ No setups found for this timeframe")
            continue
            
        for i, setup in enumerate(setups, 1):
            instrument = setup['instrument']
            fib_info = fib_data.get('data', {}).get(instrument, {}).get('fibonacci', {})
            
            # Determine trade type
            trade_type = "Continuation"
            if "Reversal" in setup.get('strategy', ''):
                trade_type = "Reversal"
            elif "Extension" in setup.get('strategy', ''):
                trade_type = "Extension"
            
            print(f"\n{'─'*60}")
            print(f"🎯 SETUP {i}: {instrument} - {setup['direction']} ({trade_type}) - {timeframe}")
            print(f"{'─'*60}")
            
            # SYSTEMATIZED 6-POINT INFORMATION (NEVER CHANGE THIS FORMAT):
            
            # 1) Pivot Points with Timestamps
            print(f"📍 PIVOT POINTS WITH TIMESTAMPS:")
            
            # Get swing analysis for timestamps
            swing_analysis = fib_info.get('swing_analysis', {})
            high_swing = swing_analysis.get('high_swing', {}) if swing_analysis else {}
            low_swing = swing_analysis.get('low_swing', {}) if swing_analysis else {}
            
            high_price = fib_info.get('high', 'N/A')
            low_price = fib_info.get('low', 'N/A')
            high_timestamp = high_swing.get('timestamp', 'No timestamp') if high_swing else 'No timestamp'
            low_timestamp = low_swing.get('timestamp', 'No timestamp') if low_swing else 'No timestamp'
            
            # Format timestamps for better readability
            if high_timestamp and high_timestamp != 'No timestamp':
                try:
                    # Handle Oanda nanosecond timestamps
                    if str(high_timestamp).isdigit():
                        # Convert nanoseconds to readable format if it's a timestamp
                        high_readable = f"Index/Nano: {high_timestamp}"
                    else:
                        high_readable = str(high_timestamp)
                except:
                    high_readable = str(high_timestamp)
            else:
                high_readable = 'No timestamp available'
                
            if low_timestamp and low_timestamp != 'No timestamp':
                try:
                    if str(low_timestamp).isdigit():
                        low_readable = f"Index/Nano: {low_timestamp}"
                    else:
                        low_readable = str(low_timestamp)
                except:
                    low_readable = str(low_timestamp)
            else:
                low_readable = 'No timestamp available'
            
            print(f"   High: {high_price:.5f} @ {high_readable}")
            print(f"   Low:  {low_price:.5f} @ {low_readable}")
            
            # Show detection methods if available
            high_method = high_swing.get('method', 'Unknown') if high_swing else 'Unknown'
            low_method = low_swing.get('method', 'Unknown') if low_swing else 'Unknown'
            print(f"   High Method: {high_method} | Low Method: {low_method}")
            
            # 2) Entry, Target, Stop with their exact Fibonacci levels
            print(f"🎯 ENTRY/TARGET/STOP + FIBONACCI LEVELS:")
            print(f"   Entry: {setup['entry_price']:.5f} ({setup['fibonacci_level']})")
            print(f"   Stop:  {setup['stop_loss']:.5f} ({setup.get('stop_fibonacci_level', 'Calculated stop')})")
            targets_with_levels = setup.get('target_fibonacci_levels', [])
            if targets_with_levels and len(targets_with_levels) == len(setup['targets']):
                target_info = ', '.join([f"{t:.5f} ({fl})" for t, fl in zip(setup['targets'], targets_with_levels)])
            else:
                target_info = ', '.join([f"{t:.5f} (Extension target)" for t in setup['targets']])
            print(f"   Targets: {target_info}")
            
            # 3) Trend Direction
            print(f"📊 TREND DIRECTION:")
            print(f"   {fib_info.get('direction', 'N/A').upper()} (Current: {fib_info.get('current_retracement', 0) * 100:.1f}% retracement)")
            
            # 4) Buy/Sell Signal  
            print(f"💰 BUY/SELL SIGNAL:")
            print(f"   {setup['direction']}")
            
            # 5) Trade Type
            print(f"🔄 TRADE TYPE:")
            print(f"   {trade_type}")
            
            # 6) Timeframe
            print(f"⏰ TIMEFRAME:")
            print(f"   {timeframe}")
            
            # Additional metrics (always include for context)
            print(f"📏 RISK/REWARD:")
            print(f"   Current Price: {setup['current_price']:.5f}")
            print(f"   Risk: {setup['risk_pips']:.1f} pips | Reward: {setup['reward_pips'][0]:.1f} pips")
            print(f"   R:R Ratio: {setup['risk_reward_ratio']:.2f} | Distance: {setup['distance_to_entry_pips']:.1f} pips")

    # Add systematic debug for all pairs
    print(f"\n{'='*40}")
    print("SYSTEMATIC DEBUG - STEPS 1-4 FOR ALL PAIRS")
    print(f"{'='*40}")
    
    all_pairs = [
        'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD', 'USD_CHF',
        'EUR_GBP', 'EUR_JPY', 'EUR_CAD', 'EUR_AUD', 'EUR_NZD', 'EUR_CHF',
        'GBP_JPY', 'GBP_CAD', 'GBP_AUD', 'GBP_NZD', 'GBP_CHF',
        'AUD_JPY', 'AUD_CAD', 'AUD_NZD', 'AUD_CHF',
        'NZD_JPY', 'NZD_CAD', 'NZD_CHF',
        'CAD_JPY', 'CAD_CHF', 'CHF_JPY'
    ]
    
    for timeframe in ['M5', 'H1']:
        print(f"\n{'='*20} {timeframe} ANALYSIS {'='*20}")
        
        # Get all signals data
        all_fib_data = get_fibonacci_details(timeframe)
        if not all_fib_data or not all_fib_data.get('success'):
            print(f"❌ Failed to get {timeframe} data")
            continue
            
        working_pairs = []
        error_pairs = []
        
        for pair in all_pairs:
            pair_data = all_fib_data.get('data', {}).get(pair, {})
            
            if 'error' in pair_data:
                error_pairs.append((pair, pair_data['error']))
                continue
                
            if 'fibonacci' not in pair_data:
                error_pairs.append((pair, 'No Fibonacci data'))
                continue
                
            fib = pair_data['fibonacci']
            current_price = pair_data.get('current_price', 0)
            
            swing_high = fib.get('high', 0)
            swing_low = fib.get('low', 0)
            direction = fib.get('direction', 'unknown')
            current_retracement = fib.get('current_retracement', 0)
            
            # Calculate closest Fib level
            swing_range = abs(swing_high - swing_low)
            fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
            is_jpy = 'JPY' in pair
            pip_value = 0.01 if is_jpy else 0.0001
            
            closest_level = None
            closest_distance = float('inf')
            
            for level in fib_levels:
                if direction == 'downtrend':
                    level_price = swing_low + (swing_range * level)
                else:  # uptrend
                    level_price = swing_high - (swing_range * level)
                
                distance = abs(current_price - level_price) / pip_value
                if distance < closest_distance:
                    closest_distance = distance
                    closest_level = level
            
            # Check if within distance limit
            max_distance = 10 if timeframe == 'M5' else 50
            within_limit = closest_distance <= max_distance
            
            working_pairs.append({
                'pair': pair,
                'direction': direction,
                'retracement': current_retracement * 100,
                'closest_fib': closest_level,
                'distance_pips': closest_distance,
                'within_limit': within_limit
            })
        
        print(f"\n✅ WORKING PAIRS: {len(working_pairs)}")
        print(f"❌ ERROR PAIRS: {len(error_pairs)}")
        
        # Show pairs within distance limits
        close_pairs = [p for p in working_pairs if p['within_limit']]
        print(f"\n🎯 PAIRS WITHIN {timeframe} DISTANCE LIMIT ({10 if timeframe == 'M5' else 50} pips): {len(close_pairs)}")
        
        for p in close_pairs[:5]:  # Show first 5
            print(f"  {p['pair']}: {p['distance_pips']:.1f} pips from {p['closest_fib']:.1%} ({p['direction']}, {p['retracement']:.1f}% retracement)")
        
        if len(close_pairs) > 5:
            print(f"  ... and {len(close_pairs) - 5} more")
            
        # Show errors summary
        if error_pairs:
            print(f"\n❌ ERROR SUMMARY:")
            unique_errors = {}
            for pair, error in error_pairs:
                if error not in unique_errors:
                    unique_errors[error] = []
                unique_errors[error].append(pair)
            
            for error, pairs in unique_errors.items():
                print(f"  '{error}': {', '.join(pairs[:3])}{'...' if len(pairs) > 3 else ''} ({len(pairs)} pairs)")
    
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()