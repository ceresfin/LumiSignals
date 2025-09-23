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
            print(f"\n🔸 {timeframe} Setup #{i}: {setup.get('instrument')}")
            print(f"   Direction: {setup.get('direction')} at {setup.get('fibonacci_level')}")
            print(f"   Entry: {setup.get('entry_price')}")
            print(f"   Target: {setup.get('target_price')}")
            print(f"   Stop: {setup.get('stop_loss')}")
            print(f"   R:R: {setup.get('risk_reward_ratio')}")
            print(f"   Distance: {setup.get('distance_to_entry_pips')} pips")
            print(f"   Quality: {setup.get('setup_quality')}/100")
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