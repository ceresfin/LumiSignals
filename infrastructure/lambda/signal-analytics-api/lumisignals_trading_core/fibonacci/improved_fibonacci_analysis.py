#!/usr/bin/env python3
"""
LumiSignals Trading Core - Improved Fibonacci Analysis with Major Swing Detection

This improved version focuses on finding major structural levels instead of
recent local highs/lows, providing more accurate Fibonacci retracements.
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from .atr_calculator import calculate_atr, get_atr_multipliers_by_strategy
from .timeframe_config import get_timeframe_parameters, get_timeframe_fibonacci_ratios

# Timeframe-adaptive settings for trade setup generation
TIMEFRAME_SETTINGS = {
    'M5': {
        'entry_distance_pips': 10,     # Very close entries for scalping
        'stop_buffer_pips': 3,         # Minimal buffer for low noise
        'trade_type': 'scalp'
    },
    'M15': {
        'entry_distance_pips': 20,     # Short-term entry tolerance
        'stop_buffer_pips': 5,         # Small buffer for quick moves
        'trade_type': 'short_term'
    },
    'M30': {
        'entry_distance_pips': 35,     # Intraday entry flexibility
        'stop_buffer_pips': 8,         # Medium buffer for volatility
        'trade_type': 'intraday'
    },
    'H1': {
        'entry_distance_pips': 50,     # Current working setting
        'stop_buffer_pips': 15,        # Current working setting
        'trade_type': 'intraday'
    },
    'H4': {
        'entry_distance_pips': 100,    # Wide entry range for swing trades
        'stop_buffer_pips': 25,        # Larger buffer for volatility
        'trade_type': 'swing'
    },
    'D1': {
        'entry_distance_pips': 200,    # Very wide for position trades
        'stop_buffer_pips': 50,        # Large buffer for daily noise
        'trade_type': 'position'
    }
}

def get_timeframe_settings(timeframe: str = 'M5') -> Dict:
    """Get settings for specific timeframe - no fallback defaults"""
    if timeframe not in TIMEFRAME_SETTINGS:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Supported: {list(TIMEFRAME_SETTINGS.keys())}")
    
    return TIMEFRAME_SETTINGS[timeframe]

def detect_major_swing_points(price_data: List[Dict], 
                             lookback_periods: int = 50,
                             min_swing_size_pips: int = 15,
                             is_jpy: bool = False) -> Dict[str, Any]:
    """
    TRUE lookback swing detection - analyzes only recent lookback_periods candles.
    
    Args:
        price_data: List of candles with 'high', 'low', etc.
        lookback_periods: How many recent candles to analyze for swings
        min_swing_size_pips: Minimum size in pips to be considered major swing
        is_jpy: True for JPY pairs
        
    Returns:
        Dictionary with major swing highs and lows from recent data only
    """
    
    if len(price_data) < max(lookback_periods, 20):
        return {'swing_highs': [], 'swing_lows': [], 'message': 'Insufficient data'}
    
    # CRITICAL FIX: Use only the most recent lookback_periods candles
    recent_data = price_data[-lookback_periods:] if len(price_data) >= lookback_periods else price_data
    
    highs = [float(candle.get('h', candle.get('high', 0))) for candle in recent_data]
    lows = [float(candle.get('l', candle.get('low', 0))) for candle in recent_data]
    
    major_highs = []
    major_lows = []
    
    pip_value = 0.01 if is_jpy else 0.0001
    min_price_move = min_swing_size_pips * pip_value
    
    # Find max/min within RECENT data only (not global dataset)
    local_max_high = max(highs)
    local_min_low = min(lows)
    local_max_index = highs.index(local_max_high)
    local_min_index = lows.index(local_min_low)
    
    # Adaptive window size for prominence detection within recent data
    prominence_window = min(10, len(highs) // 4)  # Smaller window for recent data
    if prominence_window < 3:
        prominence_window = 3
    
    # Method 1: Find swing highs using prominence within recent data
    for i in range(prominence_window, len(highs) - prominence_window):
        current_high = highs[i]
        
        # Check prominence within recent data only
        left_range = highs[max(0, i - prominence_window):i]
        right_range = highs[i + 1:min(len(highs), i + prominence_window + 1)]
        
        # Must be highest in proximity AND significant within recent range
        is_major_high = (current_high >= max(left_range) and 
                        current_high >= max(right_range) and
                        current_high >= local_max_high * 0.85)  # Within 15% of recent max
        
        if is_major_high:
            # Check if it's big enough move from previous swing
            if len(major_highs) == 0 or abs(current_high - major_highs[-1]['price']) >= min_price_move:
                # Calculate actual index in original dataset
                actual_index = len(price_data) - len(recent_data) + i
                
                major_highs.append({
                    'price': current_high,
                    'index': actual_index,
                    'timestamp': recent_data[i].get('time', recent_data[i].get('timestamp', '')),
                    'method': 'recent_prominence',
                    'lookback_used': lookback_periods,
                    'prominence_score': min(current_high - max(left_range), current_high - max(right_range))
                })
    
    # Method 2: Find swing lows using prominence within recent data
    for i in range(prominence_window, len(lows) - prominence_window):
        current_low = lows[i]
        
        # Check prominence within recent data only
        left_range = lows[max(0, i - prominence_window):i]
        right_range = lows[i + 1:min(len(lows), i + prominence_window + 1)]
        
        # Must be lowest in proximity AND significant within recent range
        is_major_low = (current_low <= min(left_range) and 
                       current_low <= min(right_range) and
                       current_low <= local_min_low * 1.15)  # Within 15% of recent min
        
        if is_major_low:
            if len(major_lows) == 0 or abs(current_low - major_lows[-1]['price']) >= min_price_move:
                # Calculate actual index in original dataset
                actual_index = len(price_data) - len(recent_data) + i
                
                major_lows.append({
                    'price': current_low,
                    'index': actual_index,
                    'timestamp': recent_data[i].get('time', recent_data[i].get('timestamp', '')),
                    'method': 'recent_prominence',
                    'lookback_used': lookback_periods,
                    'prominence_score': min(min(left_range) - current_low, min(right_range) - current_low)
                })
    
    # Always include the recent highest and lowest points if significant
    if not any(h['price'] == local_max_high for h in major_highs):
        actual_max_index = len(price_data) - len(recent_data) + local_max_index
        major_highs.append({
            'price': local_max_high,
            'index': actual_max_index,
            'timestamp': recent_data[local_max_index].get('time', recent_data[local_max_index].get('timestamp', '')),
            'method': 'recent_absolute_high',
            'prominence_score': local_max_high - local_min_low
        })
    
    if not any(l['price'] == local_min_low for l in major_lows):
        actual_min_index = len(price_data) - len(recent_data) + local_min_index
        major_lows.append({
            'price': local_min_low,
            'index': actual_min_index,
            'timestamp': recent_data[local_min_index].get('time', recent_data[local_min_index].get('timestamp', '')),
            'method': 'recent_absolute_low',
            'prominence_score': local_max_high - local_min_low
        })
    
    # Sort by prominence score (most prominent first)
    major_highs.sort(key=lambda x: x['prominence_score'], reverse=True)
    major_lows.sort(key=lambda x: x['prominence_score'], reverse=True)
    
    return {
        'swing_highs': major_highs,
        'swing_lows': major_lows,
        'total_highs': len(major_highs),
        'total_lows': len(major_lows),
        'dataset_range_pips': (local_max_high - local_min_low) / pip_value,
        'method': 'true_recent_lookback',
        'recent_data_used': len(recent_data),
        'parameters': {
            'lookback_periods': lookback_periods,
            'min_swing_size_pips': min_swing_size_pips,
            'pip_value': pip_value,
            'recent_candles_analyzed': len(recent_data),
            'prominence_window': prominence_window
        }
    }

def find_best_fibonacci_swing_pair(major_swings: Dict, current_price: float) -> Dict[str, Any]:
    """
    Find the best swing high/low pair for Fibonacci analysis.
    
    Args:
        major_swings: Output from detect_major_swing_points
        current_price: Current market price
        
    Returns:
        Best swing pair for Fibonacci retracement
    """
    
    swing_highs = major_swings['swing_highs']
    swing_lows = major_swings['swing_lows']
    
    if not swing_highs or not swing_lows:
        return {'error': 'Insufficient swing data'}
    
    # Get the most prominent high and low
    best_high = swing_highs[0]  # Already sorted by prominence
    best_low = swing_lows[0]    # Already sorted by prominence
    
    # Determine trend direction based on which occurred more recently
    # Use timestamps for more reliable chronological comparison
    # If high came after low → price moved up → uptrend
    # If low came after high → price moved down → downtrend
    
    # Get timestamps, fallback to index if timestamps unavailable
    high_timestamp = best_high.get('timestamp', '')
    low_timestamp = best_low.get('timestamp', '')
    
    if high_timestamp and low_timestamp:
        # Use timestamp comparison for chronological order
        try:
            # Handle Oanda nanosecond timestamps (numeric strings)
            if str(high_timestamp).isdigit() and str(low_timestamp).isdigit():
                # Nanosecond timestamps - compare as integers
                high_ns = int(high_timestamp)
                low_ns = int(low_timestamp)
                trend_direction = 'uptrend' if high_ns > low_ns else 'downtrend'
            else:
                # ISO format timestamps - parse as datetime
                from datetime import datetime
                high_dt = datetime.fromisoformat(str(high_timestamp).replace('Z', '+00:00'))
                low_dt = datetime.fromisoformat(str(low_timestamp).replace('Z', '+00:00'))
                trend_direction = 'uptrend' if high_dt > low_dt else 'downtrend'
        except (ValueError, AttributeError):
            # Fallback to string comparison
            trend_direction = 'uptrend' if str(high_timestamp) > str(low_timestamp) else 'downtrend'
    else:
        # Fallback to index comparison
        trend_direction = 'uptrend' if best_high['index'] > best_low['index'] else 'downtrend'
    
    # Calculate swing range in pips
    pip_value = major_swings['parameters']['pip_value']
    swing_range_pips = abs(best_high['price'] - best_low['price']) / pip_value
    
    # Calculate current retracement level using CORRECT FROM/TO logic
    # DOWNTREND: FROM swing high (100%) TO swing low (0%) 
    # UPTREND: FROM swing low (100%) TO swing high (0%)
    if best_high['price'] != best_low['price']:
        if trend_direction == 'downtrend':
            # DOWNTREND: High=100%, Low=0%. Current closer to low = smaller retracement %
            current_retracement = (current_price - best_low['price']) / (best_high['price'] - best_low['price'])
        else:  # uptrend
            # UPTREND: Low=100%, High=0%. Current closer to low = larger retracement %
            current_retracement = (best_high['price'] - current_price) / (best_high['price'] - best_low['price'])
        current_retracement = max(0, min(1, current_retracement))  # Clamp between 0-1
    else:
        current_retracement = 0.5
    
    # Calculate relevance score based on:
    # 1. Swing size (larger = more relevant)
    # 2. Prominence (more prominent = more relevant) 
    # 3. Current price proximity to the swing range
    size_score = min(swing_range_pips / 100, 1.0)  # Normalize to max of 1.0 for 100+ pip swings
    prominence_score = (best_high['prominence_score'] + best_low['prominence_score']) / 2
    
    # Proximity score - price within the swing range is more relevant
    if best_low['price'] <= current_price <= best_high['price']:
        proximity_score = 1.0  # Price is within the swing range
    else:
        distance_from_range = min(abs(current_price - best_high['price']), abs(current_price - best_low['price']))
        proximity_score = 1.0 / (1.0 + distance_from_range * 1000)  # Closer = higher score
    
    relevance_score = (size_score + prominence_score + proximity_score) / 3
    
    return {
        'high_swing': best_high,
        'low_swing': best_low,
        'trend_direction': trend_direction,
        'swing_range_pips': swing_range_pips,
        'current_retracement': current_retracement,
        'relevance_score': relevance_score,
        'size_score': size_score,
        'prominence_score': prominence_score,
        'proximity_score': proximity_score
    }

def generate_improved_fibonacci_levels(swing_pair: Dict, timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Generate Fibonacci levels from the best swing pair.
    
    Args:
        swing_pair: Output from find_best_fibonacci_swing_pair
        timeframe: Timeframe for level selection
        
    Returns:
        Fibonacci levels optimized for the timeframe
    """
    
    if 'error' in swing_pair:
        return swing_pair
    
    high_price = swing_pair['high_swing']['price']
    low_price = swing_pair['low_swing']['price']
    
    # Get timeframe-specific Fibonacci ratios
    timeframe_ratios = get_timeframe_fibonacci_ratios(timeframe)
    ratios = timeframe_ratios.get('retracement', [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0])
    
    price_range = high_price - low_price
    
    detailed_levels = []
    trend_direction = swing_pair['trend_direction']
    
    for ratio in ratios:
        # Fix Problem 1: Proper FROM/TO Fibonacci calculation based on trend
        if trend_direction == 'downtrend':
            # Downtrend: FROM high (1.0) TO low (0.0)
            # 0.618 retracement = 61.8% back UP from low toward high
            level_price = low_price + (price_range * ratio)
        else:  # uptrend
            # Uptrend: FROM low (1.0) TO high (0.0)  
            # 0.618 retracement = 61.8% back DOWN from high toward low
            level_price = high_price - (price_range * ratio)
            
        detailed_levels.append({
            'ratio': ratio,
            'price': round(level_price, 5),
            'description': f'{ratio:.1%} Retracement'
        })
    
    # Determine key level based on current retracement - Fix Problem 2: Add 0.5 for trend continuation
    current_ret = swing_pair['current_retracement']
    if current_ret < 0.382:
        key_level = 0.382
    elif current_ret < 0.5:
        key_level = 0.5
    elif current_ret < 0.618:
        key_level = 0.618
    else:
        key_level = 0.786
    
    return {
        'levels': ratios,
        'high': high_price,
        'low': low_price,
        'direction': swing_pair['trend_direction'],
        'current_retracement': current_ret,
        'key_level': key_level,
        'detailed_levels': detailed_levels,
        'swing_range_pips': swing_pair['swing_range_pips'],
        'relevance_score': swing_pair['relevance_score'],
        'swing_analysis': {
            'high_swing': {
                'method': swing_pair['high_swing']['method'],
                'prominence': swing_pair['high_swing']['prominence_score'],
                'timestamp': swing_pair['high_swing'].get('timestamp', ''),
                'index': swing_pair['high_swing'].get('index', 0),
                'price': swing_pair['high_swing']['price']
            },
            'low_swing': {
                'method': swing_pair['low_swing']['method'],
                'prominence': swing_pair['low_swing']['prominence_score'], 
                'timestamp': swing_pair['low_swing'].get('timestamp', ''),
                'index': swing_pair['low_swing'].get('index', 0),
                'price': swing_pair['low_swing']['price']
            }
        }
    }

def analyze_fibonacci_levels_improved(instrument: str, current_price: float = None, 
                                    price_data: List[Dict] = None, mode: str = 'fixed', 
                                    timeframe: str = 'H1', include_trade_setups: bool = False,
                                    include_confluence: bool = False, 
                                    institutional_levels: Dict = None) -> Dict[str, Any]:
    """
    Improved Fibonacci analysis with major swing detection and optional trade setups.
    
    Args:
        instrument: Currency pair (e.g., 'EUR_USD')
        current_price: Current market price
        price_data: Historical price data
        mode: 'fixed' or 'atr'
        timeframe: Timeframe for analysis
        include_trade_setups: Generate actionable trade setups with smart stop loss/targets
        include_confluence: Include institutional level confluence analysis
        institutional_levels: Dict of institutional levels for confluence
        
    Returns:
        Enhanced Fibonacci analysis with optional trade setups and detailed breakdowns
    """
    
    # Determine if JPY pair
    is_jpy = 'JPY' in instrument
    
    if not price_data:
        return {'error': 'No price data provided'}
    
    if current_price is None:
        current_price = float(price_data[-1].get('c', price_data[-1].get('close', 0)))
    
    # Get parameters based on mode
    if mode == 'atr':
        strategy = 'balanced'
        strategy_params = get_atr_multipliers_by_strategy(strategy)
        lookback_periods = max(20, strategy_params['window'] * 8)  # Larger lookback for major swings
        atr_analysis = calculate_atr(price_data, period=14)
        current_atr = atr_analysis['current_atr']
        
        # Use ATR to determine minimum swing size
        atr_multiplier = strategy_params['swing_multiplier']
        min_swing_pips = int((current_atr * atr_multiplier) / (0.01 if is_jpy else 0.0001))
        min_swing_pips = max(min_swing_pips, 20)  # Minimum 20 pips
        
        mode_info = {
            'mode': 'atr',
            'strategy': strategy,
            'current_atr': current_atr,
            'swing_threshold': current_atr * atr_multiplier,
            'atr_multiplier': atr_multiplier,
            'min_pip_distance': min_swing_pips
        }
    else:  # mode == 'fixed'
        params = get_timeframe_parameters(timeframe)
        # Use larger lookback for major swings
        lookback_periods = max(50, params['window'] * 10)
        min_swing_pips = params['min_pip_distance']  # Use timeframe-specific pip distance
        
        mode_info = {
            'mode': 'fixed',
            'timeframe': timeframe,
            'min_pip_distance': min_swing_pips,
            'description': params['description'],
            'lookback_periods': lookback_periods
        }
    
    # Detect major swing points
    major_swings = detect_major_swing_points(
        price_data, 
        lookback_periods=lookback_periods,
        min_swing_size_pips=min_swing_pips,
        is_jpy=is_jpy
    )
    
    if major_swings.get('total_highs', 0) == 0 or major_swings.get('total_lows', 0) == 0:
        return {
            'error': 'No major swing points detected',
            'mode_info': mode_info,
            'swing_detection': major_swings
        }
    
    # Find best swing pair for Fibonacci analysis
    swing_pair = find_best_fibonacci_swing_pair(major_swings, current_price)
    
    if 'error' in swing_pair:
        return {
            'error': swing_pair['error'],
            'mode_info': mode_info,
            'swing_detection': major_swings
        }
    
    # Generate Fibonacci levels
    fibonacci_result = generate_improved_fibonacci_levels(swing_pair, timeframe)
    
    if 'error' in fibonacci_result:
        return {
            'error': fibonacci_result['error'],
            'mode_info': mode_info,
            'swing_detection': major_swings
        }
    
    # Add mode info and debugging data
    fibonacci_result['mode'] = mode
    fibonacci_result['mode_info'] = mode_info
    fibonacci_result['swing_detection_summary'] = {
        'total_highs': major_swings['total_highs'],
        'total_lows': major_swings['total_lows'],
        'dataset_range_pips': major_swings['dataset_range_pips'],
        'method': major_swings['method']
    }
    
    # Generate trade setups if requested
    if include_trade_setups:
        trade_setups = generate_enhanced_trade_setups(
            fibonacci_result, 
            current_price, 
            instrument,
            timeframe,
            include_confluence,
            institutional_levels
        )
        fibonacci_result['trade_setups'] = trade_setups
    
    return fibonacci_result


def generate_enhanced_trade_setups(fibonacci_data: Dict, current_price: float, 
                                 instrument: str, timeframe: str,
                                 include_confluence: bool = False,
                                 institutional_levels: Dict = None) -> List[Dict]:
    """
    Generate proper Fibonacci trade setups with three distinct trade types:
    1. TREND EXTENSION (0-23.6%): Enter at 0%, targets start at 138.2%
    2. TREND CONTINUATION (23.6-78.6%): Enter at 38.2/50/61.8%, targets at 127.2%
    3. TREND REVERSAL (78.6%+): Enter at 100%, reversal targets
    """
    
    is_jpy = 'JPY' in instrument
    pip_value = 0.01 if is_jpy else 0.0001
    decimal_places = 2 if is_jpy else 4
    
    timeframe_settings = get_timeframe_settings(timeframe)
    max_distance_pips = timeframe_settings['entry_distance_pips']
    max_distance = max_distance_pips * pip_value
    
    # Extract Fibonacci data
    high_price = fibonacci_data['high']
    low_price = fibonacci_data['low']
    swing_range = high_price - low_price
    direction = fibonacci_data['direction']
    current_retracement = fibonacci_data.get('current_retracement', 0.0)
    
    # Determine trade type based on current retracement depth
    if current_retracement <= 0.236:
        trade_type = "TREND_EXTENSION"
        entry_level = 0.0  # Enter at swing point (0%)
    elif current_retracement <= 0.786:
        trade_type = "TREND_CONTINUATION"
        # Find closest continuation level
        if current_retracement <= 0.40:
            entry_level = 0.382
        elif current_retracement <= 0.55:
            entry_level = 0.500
        else:
            entry_level = 0.618
    else:
        trade_type = "TREND_REVERSAL"
        entry_level = 1.0  # Enter at full retracement (100%)
    
    # Calculate entry price based on trend direction
    if direction == 'downtrend':
        if entry_level == 0.0:
            entry_price = low_price  # 0% = swing low
        elif entry_level == 1.0:
            entry_price = high_price  # 100% = swing high
        else:
            entry_price = low_price + (swing_range * entry_level)
    else:  # uptrend
        if entry_level == 0.0:
            entry_price = high_price  # 0% = swing high
        elif entry_level == 1.0:
            entry_price = low_price  # 100% = swing low
        else:
            entry_price = high_price - (swing_range * entry_level)
    
    # Distance filter
    distance_to_entry = abs(current_price - entry_price)
    if distance_to_entry > max_distance:
        return []  # Too far from entry
    
    # Generate trade setup
    setup = create_proper_fibonacci_setup(
        trade_type, entry_level, entry_price, high_price, low_price,
        current_price, direction, instrument, timeframe,
        include_confluence, institutional_levels,
        pip_value, decimal_places, distance_to_entry,
        current_retracement
    )
    
    return [setup] if setup else []


def create_enhanced_setup(level: float, entry_price: float, high_price: float, 
                         low_price: float, current_price: float, direction: str,
                         instrument: str, timeframe: str, include_confluence: bool,
                         institutional_levels: Dict, pip_value: float, 
                         decimal_places: int, distance_to_entry: float,
                         current_retracement: float) -> Dict:
    """
    Create a single enhanced trade setup with detailed breakdowns.
    """
    
    # Determine trade direction based on Fibonacci level and trend
    swing_range = high_price - low_price
    
    # ONE TRUE LOGIC: Determine trade type based on ACTUAL current retracement position
    # Use current_retracement (where price actually is) not level (potential entry)
    if current_retracement <= 0.786:  # Continuation zone: 0% to 78.6%
        setup_type_override = 'Trend Continuation'
        # CORRECT Fibonacci retracement trading logic:
        # Uptrend: Buy retracements (dips) to continue trend upward
        # Downtrend: Sell retracements (bounces) to continue trend downward
        if direction in ['uptrend', 'bullish']:
            trade_direction = 'BUY'  # Buy the retracement in uptrend
            trade_type = 'long'
        else:  # downtrend
            trade_direction = 'SELL'  # Sell the retracement bounce in downtrend  
            trade_type = 'short'
    else:  # Reversal zone: >78.6%
        setup_type_override = 'Trend Reversal'
        if direction in ['uptrend', 'bullish']:
            # In uptrend but deep retracement - expect reversal (sell the high)
            trade_direction = 'SELL'
            trade_type = 'short'
        else:  # downtrend
            # In downtrend but deep retracement - expect reversal (buy the low)
            trade_direction = 'BUY'
            trade_type = 'long'
    
    # Calculate stop loss and targets based on trade type with Fibonacci level labels
    stop_loss, stop_fibonacci_level = calculate_smart_stop_loss_with_level(entry_price, high_price, low_price, level, trade_type, pip_value, timeframe)
    targets, target_fibonacci_levels = calculate_smart_targets_with_levels(entry_price, high_price, low_price, trade_type, pip_value)
    
    # Calculate risk/reward ratios for all targets
    risk_pips = abs(entry_price - stop_loss) / pip_value
    
    if risk_pips == 0:
        return None  # Invalid setup
    
    risk_reward_ratios = []
    reward_pips_array = []
    
    for target in targets:
        reward_pips = abs(target - entry_price) / pip_value
        reward_pips_array.append(reward_pips)
        rr_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
        risk_reward_ratios.append(round(rr_ratio, 2))
    
    # Use first target for primary R:R (most conservative)
    primary_rr = risk_reward_ratios[0] if risk_reward_ratios else 0
    best_rr = max(risk_reward_ratios) if risk_reward_ratios else 0
    
    # Validate minimum risk/reward ratio (1.5 for conservative target)
    if primary_rr < 1.5:
        return None  # Skip setups that don't meet minimum R:R requirement
    
    # Confluence analysis
    confluence_data = None
    confluence_summary = None
    
    if include_confluence and institutional_levels:
        confluence_data = check_enhanced_confluence(entry_price, institutional_levels, pip_value)
        confluence_summary = create_confluence_summary(confluence_data)
    
    # Quality scoring with detailed breakdown
    quality_breakdown = calculate_enhanced_quality(
        primary_rr, confluence_data, distance_to_entry, pip_value
    )
    
    # Generate strategy metadata
    setup_type = setup_type_override  # Use the type we determined based on level and trend
    strategy_name = generate_strategy_name(level, timeframe, direction, setup_type)
    
    # Create setup
    setup = {
        'setup_id': f'fibonacci_{level:.1%}_{timeframe}',
        'strategy': strategy_name,
        'setup_type': setup_type,
        'direction': trade_direction,
        'fibonacci_level': f'{current_retracement:.1%} Retracement',
        'entry_price': round(entry_price, decimal_places),
        'stop_loss': round(stop_loss, decimal_places),
        'target_price': round(targets[0], decimal_places) if targets else 0,
        'targets': [round(t, decimal_places) for t in targets],
        'stop_fibonacci_level': stop_fibonacci_level,
        'target_fibonacci_levels': target_fibonacci_levels,
        'risk_pips': round(risk_pips, 1),
        'reward_pips': [round(r, 1) for r in reward_pips_array],
        'risk_reward_ratios': risk_reward_ratios,
        'primary_rr': primary_rr,
        'best_rr': best_rr,
        'risk_reward_ratio': risk_reward_ratios[0] if risk_reward_ratios else 0,  # Most conservative R:R
        'distance_to_entry_pips': round(distance_to_entry / pip_value, 1),
        'setup_quality': quality_breakdown['total'],
        'quality_breakdown': quality_breakdown,
        'confluence': confluence_data,
        'confluence_summary': confluence_summary,
        'entry_reason': f'{current_retracement:.1%} Fibonacci retracement in {direction}',
        'invalidation': f'Close {"below" if trade_direction == "BUY" else "above"} {round(stop_loss, decimal_places)}',
        'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    return setup


def calculate_smart_stop_loss_with_level(entry_price: float, high_price: float, low_price: float,
                             level: float, trade_direction: str, pip_value: float, timeframe: str) -> tuple[float, str]:
    """
    Calculate intelligent stop loss placement using next Fibonacci level + timeframe buffer.
    Returns: (stop_price, fibonacci_level_description)
    """
    
    swing_range = high_price - low_price
    # Get timeframe-specific buffer
    timeframe_settings = get_timeframe_settings(timeframe)
    buffer_pips = timeframe_settings['stop_buffer_pips']
    buffer = buffer_pips * pip_value
    
    if trade_direction == 'long':
        # For BUY signals: Stop at the next Fibonacci level BELOW entry + buffer
        next_level_down = get_next_fib_level_down(level)
        if next_level_down == 0.0:
            # If we're at 23.6% and next is 0%, use swing low
            stop_level = low_price - buffer
            fibonacci_label = "Swing Low + Buffer"
        else:
            # Use next Fibonacci level below
            stop_level = low_price + (swing_range * next_level_down) - buffer
            fibonacci_label = f"{next_level_down:.1%} Level + Buffer"
        
        return stop_level, fibonacci_label
    
    else:  # short trades
        # For SELL signals: Stop at the next Fibonacci level ABOVE entry + buffer
        next_level_up = get_next_fib_level_up(level)
        if next_level_up == 1.0:
            # If we're at 78.6% and next is 100%, use swing high
            stop_level = high_price + buffer
            fibonacci_label = "Swing High + Buffer"
        else:
            # Use next Fibonacci level above
            stop_level = high_price - (swing_range * next_level_up) + buffer
            fibonacci_label = f"{next_level_up:.1%} Level + Buffer"
            
        return stop_level, fibonacci_label


def calculate_smart_stop_loss(entry_price: float, high_price: float, low_price: float,
                             level: float, trade_direction: str, pip_value: float, timeframe: str) -> float:
    """
    Calculate intelligent stop loss placement using next Fibonacci level + timeframe buffer.
    """
    
    swing_range = high_price - low_price
    # Get timeframe-specific buffer
    timeframe_settings = get_timeframe_settings(timeframe)
    buffer_pips = timeframe_settings['stop_buffer_pips']
    buffer = buffer_pips * pip_value
    
    if trade_direction == 'long':
        # For BUY signals: Stop at the next Fibonacci level BELOW entry + buffer
        next_level_down = get_next_fib_level_down(level)
        if next_level_down == 0.0:
            # If we're at 23.6% and next is 0%, use swing low
            stop_level = low_price - buffer
        else:
            # Use next Fibonacci level below
            stop_level = low_price + (swing_range * next_level_down) - buffer
        
        return stop_level
    
    else:  # short trades
        # For SELL signals: Stop at the next Fibonacci level ABOVE entry + buffer
        next_level_up = get_next_fib_level_up(level)
        if next_level_up == 1.0:
            # If we're at 78.6% and next is 100%, use swing high
            stop_level = high_price + buffer
        else:
            # Use next Fibonacci level above
            stop_level = high_price - (swing_range * next_level_up) + buffer
            
        return stop_level


def calculate_smart_targets_with_levels(entry_price: float, high_price: float, low_price: float,
                           trade_direction: str, pip_value: float) -> tuple[List[float], List[str]]:
    """
    Calculate multiple intelligent targets using Fibonacci extensions with level labels.
    Returns: (target_prices, fibonacci_level_descriptions)
    """
    
    swing_range = high_price - low_price
    targets = []
    target_labels = []
    
    if trade_direction == 'long':
        # Long targets: break above swing high, then extensions
        targets.append(high_price + (10 * pip_value))  # T1: Break swing high
        target_labels.append("Swing High Break")
        
        targets.append(high_price + (swing_range * 0.272))  # T2: 127.2% extension
        target_labels.append("127.2% Extension")
        
        targets.append(high_price + (swing_range * 0.382))  # T3: 138.2% extension
        target_labels.append("138.2% Extension")
    
    else:  # short targets
        # Short targets: break below swing low, then extensions  
        targets.append(low_price - (10 * pip_value))   # T1: Break swing low
        target_labels.append("Swing Low Break")
        
        targets.append(low_price - (swing_range * 0.272))  # T2: 127.2% extension
        target_labels.append("127.2% Extension")
        
        targets.append(low_price - (swing_range * 0.382))  # T3: 138.2% extension
        target_labels.append("138.2% Extension")
    
    return targets, target_labels


def calculate_smart_targets(entry_price: float, high_price: float, low_price: float,
                           trade_direction: str, pip_value: float) -> List[float]:
    """
    Calculate multiple intelligent targets using Fibonacci extensions.
    """
    
    swing_range = high_price - low_price
    targets = []
    
    if trade_direction == 'long':
        # Long targets: break above swing high, then extensions
        targets.append(high_price + (10 * pip_value))  # T1: Break swing high
        targets.append(high_price + (swing_range * 0.272))  # T2: 127.2% extension
        targets.append(high_price + (swing_range * 0.382))  # T3: 138.2% extension
    
    else:  # short targets
        # Short targets: break below swing low, then extensions  
        targets.append(low_price - (10 * pip_value))   # T1: Break swing low
        targets.append(low_price - (swing_range * 0.272))  # T2: 127.2% extension
        targets.append(low_price - (swing_range * 0.382))  # T3: 138.2% extension
    
    return targets


def check_enhanced_confluence(price: float, institutional_levels: Dict, 
                             pip_value: float, tolerance_pips: int = 10) -> List[Dict]:
    """
    Enhanced confluence analysis with detailed breakdowns.
    """
    
    if not institutional_levels:
        return None
    
    tolerance = tolerance_pips * pip_value
    confluences = []
    
    for level_type, levels in institutional_levels.items():
        for level in levels:
            distance = abs(price - level)
            if distance <= tolerance:
                distance_pips = distance / pip_value
                strength = 1.0 / (1.0 + distance * 10000)  # Closer = stronger
                
                confluences.append({
                    'level_type': level_type,
                    'level_price': round(level, 5),
                    'distance_pips': round(distance_pips, 1),
                    'strength': round(strength, 3)
                })
    
    return confluences if confluences else None


def create_confluence_summary(confluence_data: List[Dict]) -> Dict:
    """
    Create confluence summary for easy interpretation.
    """
    
    if not confluence_data:
        return None
    
    total_confluences = len(confluence_data)
    
    # Find strongest confluence
    strongest = max(confluence_data, key=lambda x: x['strength'])
    strongest_desc = f"{strongest['level_type']} ({strongest['distance_pips']:.1f} pips)"
    
    # Calculate confluence score for quality rating
    confluence_score = min(total_confluences * 10, 30)  # Max 30 points
    
    return {
        'total_confluences': total_confluences,
        'strongest_confluence': strongest_desc,
        'confluence_score': confluence_score,
        'all_types': [c['level_type'] for c in confluence_data]
    }


def calculate_enhanced_quality(risk_reward_ratio: float, confluence_data: List[Dict],
                              distance_to_entry: float, pip_value: float) -> Dict:
    """
    Calculate setup quality with detailed component breakdown.
    """
    
    breakdown = {
        'risk_reward_score': 0,
        'confluence_score': 0, 
        'distance_score': 0,
        'total': 0
    }
    
    # Risk/reward component (0-50 points)
    if risk_reward_ratio >= 3.0:
        breakdown['risk_reward_score'] = 50
    elif risk_reward_ratio >= 2.0:
        breakdown['risk_reward_score'] = 35
    elif risk_reward_ratio >= 1.5:
        breakdown['risk_reward_score'] = 25
    elif risk_reward_ratio >= 1.0:
        breakdown['risk_reward_score'] = 15
    
    # Confluence component (0-30 points)
    if confluence_data:
        confluence_count = len(confluence_data)
        breakdown['confluence_score'] = min(confluence_count * 10, 30)
    
    # Distance component (0-20 points)
    distance_pips = distance_to_entry / pip_value
    if distance_pips <= 10:
        breakdown['distance_score'] = 20
    elif distance_pips <= 25:
        breakdown['distance_score'] = 15
    elif distance_pips <= 50:
        breakdown['distance_score'] = 10
    
    # Calculate total
    breakdown['total'] = (breakdown['risk_reward_score'] + 
                         breakdown['confluence_score'] + 
                         breakdown['distance_score'])
    
    # Add descriptive details
    breakdown['risk_reward_rating'] = get_rr_rating(risk_reward_ratio)
    breakdown['distance_rating'] = get_distance_rating(distance_pips)
    
    return breakdown


def determine_setup_type(level: float, risk_reward_ratio: float) -> str:
    """
    Determine setup type based on Fibonacci level and R:R.
    """
    
    if level >= 0.786:
        return 'Deep Retracement'
    elif risk_reward_ratio >= 2.5:
        return 'High Probability Retracement'
    else:
        return 'Standard Retracement'


def generate_strategy_name(level: float, timeframe: str, direction: str, setup_type: str) -> str:
    """
    Generate descriptive strategy name.
    """
    
    return f"Fibonacci {setup_type} {level:.1%} {timeframe} {direction.title()}"


def get_rr_rating(rr: float) -> str:
    """Get risk/reward rating description."""
    if rr >= 3.0:
        return 'Excellent'
    elif rr >= 2.0:
        return 'Good'
    elif rr >= 1.5:
        return 'Acceptable'
    else:
        return 'Poor'


def get_distance_rating(distance_pips: float) -> str:
    """Get distance rating description."""
    if distance_pips <= 10:
        return 'Immediate'
    elif distance_pips <= 25:
        return 'Near'
    else:
        return 'Distant'

# ===== ENHANCED FUNCTIONS MERGED FROM fibonacci_trade_setups.py =====

def check_institutional_confluence(price: float, institutional_levels: Dict[str, List[float]], 
                                  pip_value: float, tolerance_pips: int = 10) -> List[Dict[str, Any]]:
    """
    Check if Fibonacci level aligns with institutional levels (quarters, pennies, dimes).
    
    Args:
        price: The Fibonacci level price to check
        institutional_levels: Dict with 'quarters', 'pennies', 'dimes' level arrays
        pip_value: Pip value for the instrument
        tolerance_pips: Tolerance in pips for confluence detection
        
    Returns:
        List of confluence matches with details
    """
    if not institutional_levels:
        return []
    
    tolerance = tolerance_pips * pip_value
    confluences = []
    
    # Check all institutional level types
    for level_type, levels in institutional_levels.items():
        if not levels:
            continue
            
        for level in levels:
            if abs(price - level) <= tolerance:
                distance_pips = int(abs(price - level) / pip_value)
                confluences.append({
                    'level_type': level_type,
                    'level_price': round(level, 5),
                    'distance_pips': distance_pips,
                    'strength': 'high' if distance_pips <= 5 else 'medium' if distance_pips <= 10 else 'low'
                })
    
    # Sort by distance (closest first)
    confluences.sort(key=lambda x: x['distance_pips'])
    return confluences

def calculate_enhanced_setup_quality(risk_reward_ratio: float, confluence: List[Dict], 
                                   distance_to_entry_pips: float, fibonacci_level: float,
                                   timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Calculate comprehensive setup quality score with detailed breakdown.
    
    Args:
        risk_reward_ratio: Risk to reward ratio
        confluence: List of confluence matches
        distance_to_entry_pips: Distance from current price to entry in pips
        fibonacci_level: Fibonacci retracement level (0.382, 0.618, etc.)
        timeframe: Trading timeframe
        
    Returns:
        Dictionary with total score and detailed breakdown
    """
    breakdown = {
        'risk_reward_score': 0,
        'confluence_score': 0,
        'distance_score': 0,
        'fibonacci_level_score': 0,
        'timeframe_bonus': 0
    }
    
    # 1. Risk/Reward component (0-40 points)
    if risk_reward_ratio >= 3.0:
        breakdown['risk_reward_score'] = 40
    elif risk_reward_ratio >= 2.5:
        breakdown['risk_reward_score'] = 35
    elif risk_reward_ratio >= 2.0:
        breakdown['risk_reward_score'] = 30
    elif risk_reward_ratio >= 1.5:
        breakdown['risk_reward_score'] = 20
    elif risk_reward_ratio >= 1.0:
        breakdown['risk_reward_score'] = 10
    
    # 2. Confluence component (0-25 points)
    if confluence:
        high_strength_count = sum(1 for c in confluence if c['strength'] == 'high')
        medium_strength_count = sum(1 for c in confluence if c['strength'] == 'medium')
        
        confluence_score = (high_strength_count * 10) + (medium_strength_count * 5)
        breakdown['confluence_score'] = min(confluence_score, 25)
    
    # 3. Distance to entry component (0-20 points)
    timeframe_settings = get_timeframe_settings(timeframe)
    max_distance = timeframe_settings['entry_distance_pips']
    
    if distance_to_entry_pips <= max_distance * 0.2:  # Very close
        breakdown['distance_score'] = 20
    elif distance_to_entry_pips <= max_distance * 0.5:  # Close
        breakdown['distance_score'] = 15
    elif distance_to_entry_pips <= max_distance * 0.8:  # Reasonable
        breakdown['distance_score'] = 10
    elif distance_to_entry_pips <= max_distance:  # Max acceptable
        breakdown['distance_score'] = 5
    
    # 4. Fibonacci level quality (0-10 points)
    # Golden ratio levels get higher scores
    if abs(fibonacci_level - 0.618) < 0.01:  # 61.8% - Golden ratio
        breakdown['fibonacci_level_score'] = 10
    elif abs(fibonacci_level - 0.382) < 0.01:  # 38.2% - Golden ratio
        breakdown['fibonacci_level_score'] = 9
    elif abs(fibonacci_level - 0.786) < 0.01:  # 78.6% - Deep retracement
        breakdown['fibonacci_level_score'] = 8
    elif abs(fibonacci_level - 0.5) < 0.01:    # 50% - Psychological level
        breakdown['fibonacci_level_score'] = 7
    else:
        breakdown['fibonacci_level_score'] = 5
    
    # 5. Timeframe bonus (0-5 points)
    timeframe_bonuses = {
        'M5': 1,    # Scalping gets small bonus
        'M15': 2,   # Short-term gets medium bonus  
        'M30': 3,   # Intraday gets good bonus
        'H1': 4,    # Hour gets high bonus
        'H4': 5,    # 4-hour gets highest bonus
        'D1': 5     # Daily gets highest bonus
    }
    breakdown['timeframe_bonus'] = timeframe_bonuses.get(timeframe, 3)
    
    # Calculate total score
    total_score = sum(breakdown.values())
    
    # Determine quality rating
    if total_score >= 85:
        quality_rating = 'excellent'
    elif total_score >= 70:
        quality_rating = 'good'
    elif total_score >= 55:
        quality_rating = 'fair'
    elif total_score >= 40:
        quality_rating = 'poor'
    else:
        quality_rating = 'very_poor'
    
    return {
        'total': total_score,
        'rating': quality_rating,
        'breakdown': breakdown,
        'max_possible': 100
    }

def generate_extension_targets(high_price: float, low_price: float, entry_price: float,
                             trade_direction: str, decimal_places: int) -> List[float]:
    """
    Generate Fibonacci extension targets for trade setups.
    
    Args:
        high_price: Swing high price
        low_price: Swing low price  
        entry_price: Trade entry price
        trade_direction: 'long' or 'short'
        decimal_places: Decimal places for rounding
        
    Returns:
        List of extension target prices
    """
    swing_range = high_price - low_price
    extension_ratios = [1.272, 1.382, 1.618, 2.000, 2.618]
    targets = []
    
    for ratio in extension_ratios:
        if trade_direction.lower() == 'long':
            target = high_price + (swing_range * (ratio - 1.0))
            if target > entry_price:  # Only targets above entry for long trades
                targets.append(round(target, decimal_places))
        else:  # short
            target = low_price - (swing_range * (ratio - 1.0))  
            if target < entry_price:  # Only targets below entry for short trades
                targets.append(round(target, decimal_places))
    
    return targets[:3]  # Maximum 3 extension targets

def determine_smart_stop_placement(entry_price: float, high_price: float, low_price: float,
                                 fibonacci_level: float, trade_direction: str, pip_value: float,
                                 timeframe: str) -> tuple[float, str]:
    """
    Determine intelligent stop loss placement using next Fibonacci level + timeframe buffer.
    
    Returns:
        (stop_price, fibonacci_level_description)
    """
    swing_range = high_price - low_price
    timeframe_settings = get_timeframe_settings(timeframe)
    buffer_pips = timeframe_settings['stop_buffer_pips']
    buffer = buffer_pips * pip_value
    
    if trade_direction.lower() == 'long':
        # For BUY signals: Stop at the next Fibonacci level BELOW entry + buffer
        next_level_down = get_next_fib_level_down(fibonacci_level)
        if next_level_down == 0.0:
            # If we're at 23.6% and next is 0%, use swing low
            stop_price = low_price - buffer
            stop_description = 'Swing Low + Buffer'
        else:
            # Use next Fibonacci level below
            stop_price = low_price + (swing_range * next_level_down) - buffer
            stop_description = f'{next_level_down:.1%} Level + Buffer'
    else:
        # For SELL signals: Stop at the next Fibonacci level ABOVE entry + buffer
        next_level_up = get_next_fib_level_up(fibonacci_level)
        if next_level_up == 1.0:
            # If we're at 78.6% and next is 100%, use swing high
            stop_price = high_price + buffer
            stop_description = 'Swing High + Buffer'
        else:
            # Use next Fibonacci level above
            stop_price = high_price - (swing_range * next_level_up) + buffer
            stop_description = f'{next_level_up:.1%} Level + Buffer'
    
    return stop_price, stop_description

def generate_institutional_levels(current_price: float, instrument: str) -> Dict[str, List[float]]:
    """
    Generate institutional levels (quarters, pennies, dimes) around current price.
    
    Args:
        current_price: Current market price
        instrument: Currency pair (for JPY detection)
        
    Returns:
        Dictionary with institutional level arrays
    """
    is_jpy = 'JPY' in instrument
    
    if is_jpy:
        # JPY pairs: Use whole numbers and half numbers
        base_level = round(current_price)
        level_range = 10
        
        levels = {
            'quarters': [],  # Not applicable for JPY
            'pennies': [base_level + i for i in range(-level_range, level_range + 1)],  # Whole numbers
            'dimes': [base_level + (i * 10) for i in range(-3, 4)]  # Every 10 yen
        }
    else:
        # Non-JPY pairs: Use decimal levels
        # Quarters: Every 0.0025 (quarter pennies)
        quarter_base = round(current_price * 4000) / 4000
        quarters = [quarter_base + (i * 0.0025) for i in range(-20, 21)]
        
        # Pennies: Every 0.01 
        penny_base = round(current_price * 100) / 100
        pennies = [penny_base + (i * 0.01) for i in range(-10, 11)]
        
        # Dimes: Every 0.10
        dime_base = round(current_price * 10) / 10
        dimes = [dime_base + (i * 0.10) for i in range(-5, 6)]
        
        levels = {
            'quarters': quarters,
            'pennies': pennies,
            'dimes': dimes
        }
    
    # Filter positive levels only
    for level_type in levels:
        levels[level_type] = [level for level in levels[level_type] if level > 0]
    
    return levels

def create_proper_fibonacci_setup(trade_type: str, entry_level: float, entry_price: float, 
                                  high_price: float, low_price: float, current_price: float, 
                                  direction: str, instrument: str, timeframe: str, 
                                  include_confluence: bool, institutional_levels: Dict,
                                  pip_value: float, decimal_places: int, distance_to_entry: float,
                                  current_retracement: float) -> Dict:
    """
    Create proper Fibonacci trade setup with correct entry, targets, and stops.
    """
    
    swing_range = high_price - low_price
    timeframe_settings = get_timeframe_settings(timeframe)
    stop_buffer_pips = timeframe_settings['stop_buffer_pips']
    
    # Determine trade direction and calculate targets/stops with proper Fibonacci logic
    if trade_type == "TREND_EXTENSION":
        # TREND EXTENSION: Riding momentum further
        if direction == 'downtrend':
            trade_direction = 'SELL'
            targets = calculate_extension_targets(low_price, swing_range, 'down', decimal_places)
            # Stop at next Fibonacci level ABOVE entry (23.6% level) + buffer
            stop_fib_level = get_next_fib_level_up(entry_level)
            stop_loss = high_price - (swing_range * stop_fib_level) + (stop_buffer_pips * pip_value)
        else:  # uptrend
            trade_direction = 'BUY'
            targets = calculate_extension_targets(high_price, swing_range, 'up', decimal_places)
            # Stop at next Fibonacci level BELOW entry (23.6% level) + buffer
            stop_fib_level = get_next_fib_level_down(entry_level)
            stop_loss = low_price + (swing_range * stop_fib_level) - (stop_buffer_pips * pip_value)
    
    elif trade_type == "TREND_CONTINUATION":
        # TREND CONTINUATION: Standard Fib trading - FIXED LOGIC
        # Uptrend: Buy the retracement (dip), targets up
        # Downtrend: Sell the retracement (bounce), targets down
        if direction == 'uptrend':
            trade_direction = 'BUY'  # Buy the retracement in uptrend
            targets = calculate_continuation_targets(high_price, low_price, 'up', decimal_places)
            # Stop at next Fib level BELOW entry + buffer
            next_fib_down = get_next_fib_level_down(entry_level)
            stop_loss = low_price + (swing_range * next_fib_down) - (stop_buffer_pips * pip_value)
        else:  # downtrend
            trade_direction = 'SELL'  # Sell the retracement in downtrend
            targets = calculate_continuation_targets(high_price, low_price, 'down', decimal_places)
            # Stop at next Fib level ABOVE entry + buffer
            next_fib_up = get_next_fib_level_up(entry_level)
            stop_loss = high_price - (swing_range * next_fib_up) + (stop_buffer_pips * pip_value)
    
    else:  # TREND_REVERSAL
        # TREND REVERSAL: Counter-trend trade
        if direction == 'downtrend':
            trade_direction = 'BUY'  # Reversing downtrend
            targets = calculate_reversal_targets(high_price, low_price, 'up', decimal_places)
            # Stop beyond 100% level (swing low) + buffer
            stop_loss = low_price - (stop_buffer_pips * pip_value)
        else:  # uptrend
            trade_direction = 'SELL'  # Reversing uptrend
            targets = calculate_reversal_targets(high_price, low_price, 'down', decimal_places)
            # Stop beyond 100% level (swing high) + buffer
            stop_loss = high_price + (stop_buffer_pips * pip_value)
    
    # Calculate risk/reward metrics
    risk_pips = abs(entry_price - stop_loss) / pip_value
    reward_pips = [abs(target - entry_price) / pip_value for target in targets]
    risk_reward_ratio = reward_pips[0] / risk_pips if risk_pips > 0 else 0
    
    # Calculate setup quality
    quality_data = calculate_enhanced_setup_quality(
        risk_reward_ratio, [], distance_to_entry / pip_value, entry_level, timeframe
    )
    
    return {
        'instrument': instrument,
        'direction': trade_direction,
        'trade_type': trade_type,
        'entry_price': round(entry_price, decimal_places),
        'stop_loss': round(stop_loss, decimal_places),
        'targets': [round(t, decimal_places) for t in targets],
        'current_price': round(current_price, decimal_places),
        'fibonacci_level': f'{entry_level:.1%} Entry',
        'stop_fibonacci_level': get_stop_fib_description(trade_type, entry_level, direction),
        'target_fibonacci_levels': get_target_fib_descriptions(trade_type),
        'risk_pips': round(risk_pips, 1),
        'reward_pips': [round(r, 1) for r in reward_pips],
        'risk_reward_ratio': round(risk_reward_ratio, 2),
        'distance_to_entry_pips': round(distance_to_entry / pip_value, 1),
        'setup_quality': quality_data['total'],
        'timeframe': timeframe,
        'swing_high': high_price,
        'swing_low': low_price,
        'current_retracement_pct': round(current_retracement * 100, 1)
    }

def calculate_extension_targets(base_price: float, swing_range: float, direction: str, decimal_places: int) -> List[float]:
    """Calculate extension targets starting at 138.2%"""
    extension_levels = [1.382, 1.618, 2.0]  # Start at 138.2%, then 161.8%, 200%
    
    targets = []
    for level in extension_levels:
        if direction == 'down':
            target = base_price - (swing_range * level)
        else:  # up
            target = base_price + (swing_range * level)
        targets.append(round(target, decimal_places))
    
    return targets

def calculate_continuation_targets(high_price: float, low_price: float, direction: str, decimal_places: int) -> List[float]:
    """Calculate continuation targets (swing break + 127.2%)"""
    swing_range = high_price - low_price
    
    if direction == 'up':
        swing_break = high_price
        extension_127 = high_price + (swing_range * 0.272)
    else:  # down
        swing_break = low_price
        extension_127 = low_price - (swing_range * 0.272)
    
    return [round(swing_break, decimal_places), round(extension_127, decimal_places)]

def calculate_reversal_targets(high_price: float, low_price: float, direction: str, decimal_places: int) -> List[float]:
    """Calculate reversal targets (major Fib levels in opposite direction)"""
    swing_range = high_price - low_price
    reversal_levels = [0.382, 0.618, 0.786]  # Major Fib levels
    
    targets = []
    for level in reversal_levels:
        if direction == 'up':
            target = low_price + (swing_range * level)
        else:  # down  
            target = high_price - (swing_range * level)
        targets.append(round(target, decimal_places))
    
    return targets

def get_next_fib_level_down(current_level: float) -> float:
    """Get next Fibonacci level down for stop placement"""
    fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    current_idx = min(range(len(fib_levels)), key=lambda i: abs(fib_levels[i] - current_level))
    return fib_levels[max(0, current_idx - 1)]

def get_next_fib_level_up(current_level: float) -> float:
    """Get next Fibonacci level up for stop placement"""
    fib_levels = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    current_idx = min(range(len(fib_levels)), key=lambda i: abs(fib_levels[i] - current_level))
    return fib_levels[min(len(fib_levels) - 1, current_idx + 1)]

def get_stop_fib_description(trade_type: str, entry_level: float, direction: str = None) -> str:
    """Get stop loss Fibonacci description"""
    if trade_type == "TREND_EXTENSION":
        # For trend extension, stop is at next Fibonacci level in opposite direction
        if direction == 'uptrend':
            next_level = get_next_fib_level_down(entry_level)
        else:
            next_level = get_next_fib_level_up(entry_level) 
        return f"{next_level:.1%} Level + Buffer"
    elif trade_type == "TREND_REVERSAL":
        return "Beyond 100% Level + Buffer"
    else:  # TREND_CONTINUATION
        if direction == 'uptrend':
            next_level = get_next_fib_level_down(entry_level)
        else:
            next_level = get_next_fib_level_up(entry_level)
        return f"{next_level:.1%} Level + Buffer"

def get_target_fib_descriptions(trade_type: str) -> List[str]:
    """Get target Fibonacci descriptions"""
    if trade_type == "TREND_EXTENSION":
        return ["138.2% Extension", "161.8% Extension", "200% Extension"]
    elif trade_type == "TREND_CONTINUATION":
        return ["Swing Break", "127.2% Extension"]
    else:  # TREND_REVERSAL
        return ["38.2% Reversal", "61.8% Reversal", "78.6% Reversal"]