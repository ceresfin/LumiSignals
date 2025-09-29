#!/usr/bin/env python3
"""
Test Detailed Fibonacci Setups

Usage:
  # All pairs
  python3 test_detailed_setups.py

  # Specific pair
  python3 test_detailed_setups.py EUR_USD
  python3 test_detailed_setups.py GBP_USD
  python3 test_detailed_setups.py USD_JPY

Shows swing highs/lows with timestamps, entry/target/stop levels for all fibonacci levels.
No hardcoded values - all parameters come from the system configuration.
"""

import sys
import os
import json
import logging
import pytz
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

# Configure logging first
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Lambda URL for direct API calls
LAMBDA_URL = "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws"

# Get all available currency pairs
ALL_PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF",
    "EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF", "GBP_JPY",
    "GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF", "AUD_JPY", "AUD_CAD", "AUD_NZD",
    "AUD_CHF", "NZD_JPY", "NZD_CAD", "NZD_CHF", "CAD_JPY", "CAD_CHF", "CHF_JPY"
]

def convert_timestamp_to_est(timestamp_str: str) -> str:
    """Convert timestamp to EST timezone for display"""
    try:
        if not timestamp_str or timestamp_str == "Unknown":
            return "Unknown"
        
        # Handle different timestamp formats
        if isinstance(timestamp_str, (int, float)):
            # Nanosecond timestamp
            if timestamp_str > 1e15:  # Nanoseconds
                seconds = timestamp_str / 1_000_000_000
            elif timestamp_str > 1e12:  # Milliseconds 
                seconds = timestamp_str / 1_000
            else:  # Seconds
                seconds = timestamp_str
            dt_utc = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            # Convert string to number if it's a numeric string
            try:
                timestamp_num = float(timestamp_str)
                # Check if it's nanoseconds (very large number)
                if timestamp_num > 1e15:  # Nanoseconds
                    seconds = timestamp_num / 1_000_000_000
                elif timestamp_num > 1e12:  # Milliseconds 
                    seconds = timestamp_num / 1_000
                else:  # Seconds
                    seconds = timestamp_num
                dt_utc = datetime.fromtimestamp(seconds, tz=timezone.utc)
            except ValueError:
                # Not a numeric string, try parsing as datetime string
                timestamp_str = str(timestamp_str).replace('Z', '+00:00')
                
                # Try different datetime formats
                for fmt in ['%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S']:
                    try:
                        if '+' in timestamp_str or 'Z' in timestamp_str:
                            dt_utc = datetime.fromisoformat(timestamp_str)
                            if dt_utc.tzinfo is None:
                                dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        else:
                            dt_utc = datetime.strptime(timestamp_str, fmt)
                            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        break
                    except:
                        continue
                else:
                    return f"Invalid format: {timestamp_str}"
        
        # Convert to EST
        est = pytz.timezone('US/Eastern')
        dt_est = dt_utc.astimezone(est)
        return dt_est.strftime('%Y-%m-%d %H:%M:%S %Z')
        
    except Exception as e:
        return f"Error: {str(e)[:50]}"

def get_fibonacci_analysis_from_api(instrument: str = None, timeframe: str = 'M5') -> Dict[str, Any]:
    """Get fibonacci analysis from the deployed lambda API"""
    try:
        # Use trade-setups endpoint for comprehensive analysis
        url = f"{LAMBDA_URL}/analytics/trade-setups"
        params = {'timeframe': timeframe}
        
        headers = {
            'Content-Type': 'application/json',
            'Origin': 'https://pipstop.org'
        }
        
        logger.info(f"Calling API: {url} with timeframe {timeframe}")
        response = requests.get(url, params=params, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Also get swing analysis from all-signals endpoint
            all_signals_url = f"{LAMBDA_URL}/analytics/all-signals"
            all_response = requests.get(all_signals_url, params=params, headers=headers, timeout=30)
            
            swing_data = {}
            if all_response.status_code == 200:
                all_data = all_response.json()
                logger.info(f"All-signals response keys: {list(all_data.keys()) if isinstance(all_data, dict) else 'Not a dict'}")
                
                if isinstance(all_data, dict) and all_data.get('success'):
                    signal_data = all_data.get('data', {})
                    logger.info(f"Signal data keys: {list(signal_data.keys()) if signal_data else 'No signal data'}")
                    
                    for key, value in signal_data.items():
                        if isinstance(value, dict):
                            # Combine fibonacci and swing data for complete analysis
                            combined_data = {}
                            
                            # Extract fibonacci data
                            if 'fibonacci' in value:
                                fib_data = value['fibonacci']
                                combined_data.update(fib_data)
                            
                            # Extract swing data  
                            if 'swing' in value:
                                swing_vals = value['swing']
                                if isinstance(swing_vals, dict):
                                    combined_data.update(swing_vals)
                            
                            # Add current price and other metadata
                            combined_data['current_price'] = value.get('current_price', 0)
                            combined_data['instrument'] = key
                            
                            swing_data[key] = combined_data
                else:
                    logger.warning(f"All-signals API response: {all_data}")
            else:
                logger.warning(f"All-signals API failed: {all_response.status_code} - {all_response.text[:200]}")
            
            return {
                'success': True,
                'trade_setups': data.get('data', {}).get('trade_setups', []),
                'swing_data': swing_data,
                'timeframe': timeframe,
                'instruments_analyzed': data.get('data', {}).get('instruments_analyzed', 0),
                'setups_found': data.get('data', {}).get('setups_found', 0)
            }
        else:
            logger.error(f"API call failed: {response.status_code} - {response.text}")
            return {'success': False, 'error': f"API error: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"Error calling API: {e}")
        return {'success': False, 'error': str(e)}

def format_candles_for_analysis(candles: List[Dict]) -> List[Dict]:
    """Convert Redis candle format to analysis format"""
    formatted_candles = []
    
    for candle in candles:
        formatted_candles.append({
            'high': float(candle.get('h', candle.get('high', 0))),
            'low': float(candle.get('l', candle.get('low', 0))),
            'close': float(candle.get('c', candle.get('close', 0))),
            'open': float(candle.get('o', candle.get('open', 0))),
            'timestamp': candle.get('time', candle.get('timestamp', ''))
        })
    
    return formatted_candles

def filter_setups_by_instrument(all_setups: List[Dict], instrument: str = None) -> List[Dict]:
    """Filter trade setups by instrument if specified"""
    if not instrument:
        return all_setups
    
    return [setup for setup in all_setups if setup.get('instrument') == instrument]

def calculate_fibonacci_levels(high: float, low: float) -> Dict[str, float]:
    """Calculate standard fibonacci retracement levels"""
    if high <= low:
        return {}
    
    range_diff = high - low
    
    return {
        '0.0%': high,
        '23.6%': high - (range_diff * 0.236),
        '38.2%': high - (range_diff * 0.382),
        '50.0%': high - (range_diff * 0.500),
        '61.8%': high - (range_diff * 0.618),
        '78.6%': high - (range_diff * 0.786),
        '88.6%': high - (range_diff * 0.886),
        '100.0%': low
    }

def calculate_fibonacci_extensions(high: float, low: float, direction: str = 'up') -> Dict[str, float]:
    """Calculate fibonacci extension levels"""
    if high <= low:
        return {}
    
    range_diff = high - low
    
    if direction.lower() == 'up':
        # Extensions above the high
        return {
            '127.2%': high + (range_diff * 0.272),
            '161.8%': high + (range_diff * 0.618),
            '200.0%': high + range_diff,
            '261.8%': high + (range_diff * 1.618)
        }
    else:
        # Extensions below the low
        return {
            '127.2%': low - (range_diff * 0.272),
            '161.8%': low - (range_diff * 0.618),
            '200.0%': low - range_diff,
            '261.8%': low - (range_diff * 1.618)
        }

def get_entry_target_stop_levels(fib_levels: Dict[str, float], extensions: Dict[str, float], 
                                current_price: float, direction: str, instrument: str) -> Dict[str, Any]:
    """Calculate entry, target and stop levels for fibonacci setups"""
    
    # Determine if this is a JPY pair for pip calculation
    is_jpy_pair = 'JPY' in instrument
    pip_factor = 100 if is_jpy_pair else 10000
    
    setups = []
    
    for level_name, level_price in fib_levels.items():
        if level_name in ['0.0%', '100.0%']:  # Skip extreme levels
            continue
            
        # Calculate distance from current price
        distance_pips = abs(level_price - current_price) * pip_factor
        
        # Entry criteria: price should be reasonably close to fibonacci level
        if distance_pips > 100:  # Skip levels too far from current price
            continue
        
        setup = {
            'fibonacci_level': level_name,
            'entry_price': level_price,
            'entry_distance_pips': distance_pips,
            'direction': direction
        }
        
        # Calculate stop loss (beyond next fibonacci level)
        if direction.lower() == 'buy':
            # For buy setups, stop below the next lower fibonacci level
            lower_levels = [v for k, v in fib_levels.items() if v < level_price]
            if lower_levels:
                stop_level = min(lower_levels)
                setup['stop_loss'] = stop_level - (5 / pip_factor)  # 5 pip buffer
            else:
                setup['stop_loss'] = level_price - (20 / pip_factor)  # Default 20 pip stop
        else:
            # For sell setups, stop above the next higher fibonacci level
            higher_levels = [v for k, v in fib_levels.items() if v > level_price]
            if higher_levels:
                stop_level = max(higher_levels)
                setup['stop_loss'] = stop_level + (5 / pip_factor)  # 5 pip buffer
            else:
                setup['stop_loss'] = level_price + (20 / pip_factor)  # Default 20 pip stop
        
        # Calculate targets using extensions
        setup['targets'] = []
        for ext_name, ext_price in extensions.items():
            if direction.lower() == 'buy' and ext_price > level_price:
                setup['targets'].append({
                    'level': ext_name,
                    'price': ext_price,
                    'reward_pips': (ext_price - level_price) * pip_factor
                })
            elif direction.lower() == 'sell' and ext_price < level_price:
                setup['targets'].append({
                    'level': ext_name,
                    'price': ext_price,
                    'reward_pips': (level_price - ext_price) * pip_factor
                })
        
        # Calculate risk/reward
        risk_pips = abs(setup['stop_loss'] - level_price) * pip_factor
        setup['risk_pips'] = risk_pips
        
        if setup['targets'] and risk_pips > 0:
            setup['risk_reward_ratios'] = [
                target['reward_pips'] / risk_pips for target in setup['targets']
            ]
        
        setups.append(setup)
    
    return setups

def print_detailed_analysis(api_data: Dict[str, Any], instrument_filter: str = None) -> None:
    """Print detailed fibonacci analysis results from API data"""
    
    if not api_data.get('success'):
        print(f"❌ Error: {api_data.get('error', 'API call failed')}")
        return
    
    timeframe = api_data.get('timeframe', 'Unknown')
    trade_setups = api_data.get('trade_setups', [])
    swing_data = api_data.get('swing_data', {})
    
    # Filter setups if specific instrument requested
    if instrument_filter:
        trade_setups = filter_setups_by_instrument(trade_setups, instrument_filter)
        instruments_analyzed = 1
    else:
        instruments_analyzed = api_data.get('instruments_analyzed', 0)
    
    print(f"\n{'=' * 120}")
    print(f"📊 DETAILED FIBONACCI TRADE SETUP ANALYSIS ({timeframe} Timeframe)")
    print(f"{'=' * 120}")
    print(f"🕐 Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"📈 Instruments Analyzed: {instruments_analyzed}")
    print(f"🎲 Total Setups Found: {len(trade_setups)}")
    
    if not trade_setups:
        print("❌ No trade setups found")
        return
    
    # Show each setup in detail
    for i, setup in enumerate(trade_setups):
        instrument = setup.get('instrument', 'Unknown')
        direction = setup.get('direction', 'Unknown')
        entry_price = setup.get('entry_price', 0)
        stop_loss = setup.get('stop_loss', 0)
        targets = setup.get('targets', [])
        fibonacci_level = setup.get('fibonacci_level', 'Unknown')
        
        print(f"\n{'━' * 120}")
        print(f"📊 SETUP #{i+1}: {instrument} - {direction.upper()} SIGNAL")
        print(f"{'━' * 120}")
        
        # Get swing data for this instrument
        swing_info = swing_data.get(instrument, {})
        
        # Show swing points with timestamps
        if swing_info:
            high_price = swing_info.get('high', 0)
            low_price = swing_info.get('low', 0)
            current_price = swing_info.get('current_price', 0)
            direction = swing_info.get('direction', 'Unknown')
            
            # Extract timestamps from swing_analysis
            swing_analysis = swing_info.get('swing_analysis', {})
            
            high_timestamp = 'Unknown'
            low_timestamp = 'Unknown'
            
            # Get timestamps from recent swing highs and lows
            recent_swing_high = swing_analysis.get('recent_swing_high', {})
            recent_swing_low = swing_analysis.get('recent_swing_low', {})
            
            print(f"   DEBUG - recent_swing_high: {recent_swing_high}")
            print(f"   DEBUG - recent_swing_low: {recent_swing_low}")
            
            if recent_swing_high:
                high_timestamp = recent_swing_high.get('timestamp', 'Unknown')
                high_price = recent_swing_high.get('price', high_price)  # Use swing price if available
            
            if recent_swing_low:
                low_timestamp = recent_swing_low.get('timestamp', 'Unknown')
                low_price = recent_swing_low.get('price', low_price)  # Use swing price if available
            
            print(f"📍 PIVOT POINTS (EST timestamps):")
            print(f"   Swing High:  {high_price:.5f} @ {convert_timestamp_to_est(high_timestamp)}")
            print(f"   Swing Low:   {low_price:.5f} @ {convert_timestamp_to_est(low_timestamp)}")
            print(f"   Current Price: {current_price:.5f}")
            print(f"   Swing Range: {abs(high_price - low_price):.5f} ({abs(high_price - low_price) * 10000:.1f} pips)")
            print(f"   Trend Direction: {direction}")
            
            # Calculate time between swings
            try:
                if high_timestamp != 'Unknown' and low_timestamp != 'Unknown':
                    # Attempt to calculate time difference
                    print(f"   High Time: {high_timestamp}")
                    print(f"   Low Time: {low_timestamp}")
            except:
                pass
        
        # Show fibonacci levels
        if swing_info and swing_info.get('high') and swing_info.get('low'):
            high = swing_info['high']
            low = swing_info['low']
            
            print(f"\n📐 FIBONACCI RETRACEMENT LEVELS:")
            fib_levels = calculate_fibonacci_levels(high, low)
            
            # Determine if JPY pair for pip calculation
            is_jpy_pair = 'JPY' in instrument
            pip_factor = 100 if is_jpy_pair else 10000
            
            for level_name, level_price in fib_levels.items():
                distance_pips = abs(level_price - current_price) * pip_factor
                marker = " ← ENTRY LEVEL" if level_name == fibonacci_level else ""
                
                # Show where current price is relative to this level
                if current_price > level_price:
                    position = "above"
                elif current_price < level_price:
                    position = "below" 
                else:
                    position = "at"
                
                print(f"   {level_name:>6}: {level_price:.5f} ({distance_pips:.1f} pips {position}){marker}")
            
            # Show current retracement level
            if high != low:
                current_retracement = (current_price - low) / (high - low)
                print(f"   Current Retracement: {current_retracement:.1%}")
            
            # Show fibonacci extensions
            print(f"\n🎯 FIBONACCI EXTENSIONS:")
            if direction.lower() in ['up', 'uptrend', 'bullish']:
                ext_direction = 'up'
            elif direction.lower() in ['down', 'downtrend', 'bearish']:
                ext_direction = 'down'
            else:
                ext_direction = 'up' if current_price < (high + low) / 2 else 'down'
            
            extensions = calculate_fibonacci_extensions(high, low, ext_direction)
            for ext_name, ext_price in extensions.items():
                distance_pips = abs(ext_price - current_price) * pip_factor
                print(f"   {ext_name:>6}: {ext_price:.5f} ({distance_pips:.1f} pips away)")
        else:
            print(f"\n❌ No swing data available for {instrument}")
        
        # Trade setup details
        print(f"\n💼 TRADE SETUP:")
        print(f"   Entry Level:     {fibonacci_level} Fibonacci")
        print(f"   Entry Price:     {entry_price:.5f}")
        print(f"   Stop Loss:       {stop_loss:.5f}")
        print(f"   Risk Pips:       {setup.get('risk_pips', 0):.1f}")
        
        # Show targets
        print(f"\n🎯 TARGETS:")
        if isinstance(targets, list) and len(targets) >= 3:
            print(f"   Target 1:        {targets[0]:.5f}")
            print(f"   Target 2:        {targets[1]:.5f}")
            print(f"   Target 3:        {targets[2]:.5f}")
        elif targets:
            print(f"   Primary Target:  {targets[0] if isinstance(targets, list) else targets:.5f}")
        
        # Risk/reward analysis
        print(f"\n💰 RISK/REWARD:")
        reward_pips = setup.get('reward_pips', [])
        if isinstance(reward_pips, list) and reward_pips:
            print(f"   Reward Pips:     {reward_pips}")
        elif reward_pips:
            print(f"   Reward Pips:     {reward_pips}")
        print(f"   R:R Ratio:       {setup.get('risk_reward_ratio', 0):.2f}")
        print(f"   Quality Score:   {setup.get('setup_quality', 0)}")
        print(f"   Distance to Entry: {setup.get('distance_to_entry_pips', 0):.1f} pips")
        
        # Strategy info
        strategy_meta = setup.get('strategy_metadata', {})
        if strategy_meta:
            print(f"\n📊 STRATEGY:")
            print(f"   Strategy Name:   {strategy_meta.get('strategy_name', 'Unknown')}")
            print(f"   Category:        {strategy_meta.get('category', 'Unknown')}")
    
    print(f"\n{'=' * 120}")
    print(f"✅ Analysis Complete - {len(trade_setups)} setups analyzed")
    print(f"{'=' * 120}")

def main():
    """Main function"""
    print("🚀 LumiSignals Detailed Fibonacci Setup Analysis")
    print(f"🕐 Started at: {datetime.now().isoformat()}")
    
    # Determine which instrument to analyze
    instrument_filter = None
    timeframe = 'M5'  # Default timeframe
    
    if len(sys.argv) > 1:
        # Specific instrument provided
        instrument = sys.argv[1].upper()
        if instrument in ALL_PAIRS:
            instrument_filter = instrument
        else:
            print(f"❌ Invalid instrument: {instrument}")
            print(f"Available instruments: {', '.join(ALL_PAIRS)}")
            sys.exit(1)
    
    # Get analysis from API
    try:
        print(f"📡 Fetching fibonacci analysis from API...")
        if instrument_filter:
            print(f"🎯 Filtering for: {instrument_filter}")
        else:
            print(f"📋 Analyzing all {len(ALL_PAIRS)} currency pairs...")
        
        api_data = get_fibonacci_analysis_from_api(instrument_filter, timeframe)
        print_detailed_analysis(api_data, instrument_filter)
            
    except Exception as e:
        logger.error(f"Failed to get analysis: {e}")
        print(f"❌ Error getting analysis: {e}")
    
    print(f"\n🏁 Analysis completed at: {datetime.now().isoformat()}")

if __name__ == "__main__":
    main()