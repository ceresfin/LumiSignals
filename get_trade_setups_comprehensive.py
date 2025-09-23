#!/usr/bin/env python3
"""
Comprehensive Trade Setups Analysis
Replaces: get_all_h1_trade_setups.py, get_all_m5_trade_setups.py, get_current_trade_setups_summary.py

Usage:
  python get_trade_setups_comprehensive.py                    # Both timeframes, all pairs
  python get_trade_setups_comprehensive.py --timeframe H1    # H1 only, all pairs
  python get_trade_setups_comprehensive.py --timeframe M5    # M5 only, all pairs
  python get_trade_setups_comprehensive.py --summary         # Quick summary, default pairs
"""

import requests
import time
import argparse
import sys

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

# Default pairs (what the endpoint uses when no instruments specified)
DEFAULT_PAIRS = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'USD_CHF', 'AUD_USD', 'NZD_USD']

def get_trade_setups(timeframe, instruments=None, use_all_pairs=True):
    """Get trade setups for specified timeframe and instruments"""
    if instruments is None:
        if use_all_pairs:
            instruments = ALL_PAIRS
        else:
            # Use default pairs (let endpoint decide)
            params = {'timeframe': timeframe}
            try:
                response = requests.get(
                    f"{LAMBDA_URL}/analytics/trade-setups",
                    params=params,
                    timeout=45
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get('data', {}).get('trade_setups', []), None
                else:
                    return [], f"Status {response.status_code}"
            except Exception as e:
                return [], str(e)
    
    all_setups = []
    errors = []
    
    # Process in batches for all pairs
    batch_size = 6
    for i in range(0, len(instruments), batch_size):
        batch = instruments[i:i+batch_size]
        instruments_str = ','.join(batch)
        
        params = {
            'timeframe': timeframe,
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
                setups = data.get('data', {}).get('trade_setups', [])
                all_setups.extend(setups)
            else:
                errors.append(f"Batch {i//batch_size + 1}: Status {response.status_code}")
                
        except Exception as e:
            errors.append(f"Batch {i//batch_size + 1}: {str(e)}")
        
        # Small delay between batches
        time.sleep(1)
    
    return all_setups, errors

def get_fibonacci_level_description(fib_level, setup_type):
    """Get descriptive text for Fibonacci level and trade type"""
    level_map = {
        '0.0%': '0.0% (Swing Low/High)',
        '23.6%': '23.6% Retracement',
        '38.2%': '38.2% Retracement', 
        '50.0%': '50.0% Retracement',
        '61.8%': '61.8% Retracement (Golden Ratio)',
        '78.6%': '78.6% Retracement',
        '88.6%': '88.6% Retracement',
        '100.0%': '100.0% (Full Retracement)',
        '127.2%': '127.2% Extension',
        '138.2%': '138.2% Extension',
        '161.8%': '161.8% Extension (Golden Ratio)',
        '200.0%': '200.0% Extension',
        '261.8%': '261.8% Extension'
    }
    
    description = level_map.get(fib_level, f"{fib_level}")
    
    # Add trade type context
    if 'Reversal' in setup_type:
        trade_context = "Trend Reversal"
    elif 'Continuation' in setup_type:
        trade_context = "Trend Continuation"
    elif 'Extension' in setup_type:
        trade_context = "Trend Extension"
    else:
        trade_context = "Trend Analysis"
    
    return f"{description} - {trade_context}"

def get_stop_target_levels(setup):
    """Show actual Fibonacci levels for stops and targets from Lambda function"""
    # Get stop Fibonacci level details
    stop_fibonacci_level = setup.get('stop_fibonacci_level', 'Unknown')
    risk_pips = setup.get('risk_pips', 0)
    stop_info = f"{stop_fibonacci_level} ({risk_pips:.0f} pip risk)"
    
    # Get target Fibonacci level details
    targets = setup.get('targets', [])
    target_fibonacci_levels = setup.get('target_fibonacci_levels', [])
    
    if len(targets) == 1:
        target_fib = target_fibonacci_levels[0] if target_fibonacci_levels else "Unknown"
        target_info = f"{target_fib}"
    elif len(targets) > 1:
        target_info = f"{target_fibonacci_levels[0] if target_fibonacci_levels else 'Unknown'} (Primary)"
        
        # Add other targets
        other_targets = []
        for i in range(1, len(targets)):
            target_fib = target_fibonacci_levels[i] if i < len(target_fibonacci_levels) else "Unknown"
            rr = setup.get('risk_reward_ratios', [])[i] if i < len(setup.get('risk_reward_ratios', [])) else 0
            other_targets.append(f"T{i+1}: {target_fib} (R:R {rr})")
        
        if other_targets:
            target_info += f" | {' | '.join(other_targets)}"
    else:
        target_info = "No targets"
    
    return stop_info, target_info

def get_trend_direction_description(direction):
    """Convert direction to descriptive text"""
    direction_map = {
        'BUY': ('Upward', 'Buy'),
        'SELL': ('Downward', 'Sell'),
        'LONG': ('Upward', 'Buy'),
        'SHORT': ('Downward', 'Sell')
    }
    return direction_map.get(direction.upper(), ('Unknown', direction))

def print_setups_summary(setups, timeframe, show_details=True):
    """Print formatted summary of trade setups"""
    if not setups:
        print(f"❌ No {timeframe} setups found")
        return
    
    # Sort by quality score
    setups.sort(key=lambda x: x.get('setup_quality', 0), reverse=True)
    
    print(f"✅ Found {len(setups)} {timeframe} setups")
    
    if show_details:
        for i, setup in enumerate(setups, 1):
            # Get enhanced descriptions
            fib_level = setup.get('fibonacci_level', 'Unknown')
            setup_type = setup.get('setup_type', 'Unknown')
            direction = setup.get('direction', 'Unknown')
            
            fib_description = get_fibonacci_level_description(fib_level, setup_type)
            trend_dir, trade_signal = get_trend_direction_description(direction)
            stop_level, target_level = get_stop_target_levels(setup)
            
            print(f"\n🔸 Setup #{i}: {setup.get('instrument')}")
            print(f"  - Fibonacci Level: {fib_description}")
            print(f"  - Direction: {trend_dir}, Trade Signal: {trade_signal}")
            print(f"  - Entry: {setup.get('entry_price')} ({fib_level})")
            print(f"  - Target: {setup.get('target_price')} ({target_level})")
            print(f"  - Stop Loss: {setup.get('stop_loss')} ({stop_level})")
            print(f"  - R:R: {setup.get('risk_reward_ratio')}")
            print(f"  - Distance: {setup.get('distance_to_entry_pips')} pips")
            print(f"  - Quality: {setup.get('setup_quality')}/100")
            
            # Show additional targets if available
            targets = setup.get('targets', [])
            if len(targets) > 1:
                print(f"  - Additional Targets:")
                risk_reward_ratios = setup.get('risk_reward_ratios', [])
                reward_pips = setup.get('reward_pips', [])
                for j, (target, rr, pips) in enumerate(zip(targets[1:], risk_reward_ratios[1:], reward_pips[1:]), 2):
                    print(f"    Target {j}: {target} (R:R {rr}, +{pips:.0f} pips)")
            
            # Show entry reason and invalidation
            entry_reason = setup.get('entry_reason', '')
            invalidation = setup.get('invalidation', '')
            if entry_reason:
                print(f"  - Entry Reason: {entry_reason}")
            if invalidation:
                print(f"  - Invalidation: {invalidation}")
                
            print(f"  - Strategy: {setup.get('strategy', 'Unknown')}")
    else:
        # Quick summary
        pairs_with_setups = list(set(setup.get('instrument') for setup in setups))
        print(f"   Pairs: {', '.join(pairs_with_setups)}")

def main():
    parser = argparse.ArgumentParser(description='Comprehensive Trade Setups Analysis')
    parser.add_argument('--timeframe', choices=['M5', 'H1', 'both'], default='both',
                       help='Timeframe to analyze (default: both)')
    parser.add_argument('--summary', action='store_true',
                       help='Quick summary using default pairs only')
    parser.add_argument('--pairs', choices=['all', 'default'], default='all',
                       help='Pair selection: all 28 pairs or default 7 pairs')
    
    args = parser.parse_args()
    
    print("🚀 Comprehensive Trade Setups Analysis")
    print("=" * 60)
    
    timeframes = ['M5', 'H1'] if args.timeframe == 'both' else [args.timeframe]
    use_all_pairs = (args.pairs == 'all') and not args.summary
    
    for timeframe in timeframes:
        print(f"\n📊 {timeframe} TIMEFRAME SETUPS")
        if timeframe == 'M5':
            print("    (Scalping - 10 pip distance filter)")
        else:
            print("    (Swing Trading - 50 pip distance filter)")
        print("-" * 60)
        
        setups, errors = get_trade_setups(timeframe, use_all_pairs=use_all_pairs)
        
        if errors:
            print(f"⚠️  Errors encountered: {', '.join(errors)}")
        
        show_details = not args.summary
        print_setups_summary(setups, timeframe, show_details)
    
    print("\n" + "=" * 60)
    print("📋 ANALYSIS COMPLETE")
    print("=" * 60)
    
    if args.summary:
        print("✅ Quick summary completed using default pairs")
    elif use_all_pairs:
        print("✅ Full analysis completed across all 28 currency pairs")
    else:
        print("✅ Analysis completed using default pairs")
    
    print(f"🕐 Completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()