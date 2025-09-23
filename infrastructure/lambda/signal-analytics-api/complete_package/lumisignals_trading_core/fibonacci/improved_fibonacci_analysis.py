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
                             min_swing_size_pips: int = 30,
                             is_jpy: bool = False) -> Dict[str, Any]:
    """
    Improved swing detection that finds major structural levels.
    
    Args:
        price_data: List of candles with 'high', 'low', etc.
        lookback_periods: How far back to look for major swings
        min_swing_size_pips: Minimum size in pips to be considered major swing
        is_jpy: True for JPY pairs
        
    Returns:
        Dictionary with major swing highs and lows
    """
    
    if len(price_data) < lookback_periods:
        return {'swing_highs': [], 'swing_lows': [], 'message': 'Insufficient data'}
    
    highs = [float(candle.get('h', candle.get('high', 0))) for candle in price_data]
    lows = [float(candle.get('l', candle.get('low', 0))) for candle in price_data]
    
    major_highs = []
    major_lows = []
    
    pip_value = 0.01 if is_jpy else 0.0001
    min_price_move = min_swing_size_pips * pip_value
    
    # Find absolute highest and lowest points
    max_high_price = max(highs)
    min_low_price = min(lows)
    max_high_index = highs.index(max_high_price)
    min_low_index = lows.index(min_low_price)
    
    # Method 1: Find major swing highs using prominence
    for i in range(lookback_periods, len(highs) - lookback_periods):
        current_high = highs[i]
        
        # Check if this is a major high (highest in lookback range)
        left_range = highs[i - lookback_periods:i]
        right_range = highs[i + 1:i + lookback_periods + 1]
        
        # Must be highest in the lookback range AND significant compared to global high
        is_major_high = (current_high >= max(left_range) and 
                        current_high >= max(right_range) and
                        current_high >= max_high_price * 0.9)  # Within 10% of absolute high
        
        if is_major_high:
            # Check if it's big enough move from previous major high
            if len(major_highs) == 0 or abs(current_high - major_highs[-1]['price']) >= min_price_move:
                major_highs.append({
                    'price': current_high,
                    'index': i,
                    'timestamp': price_data[i].get('time', price_data[i].get('timestamp', '')),
                    'method': 'prominence',
                    'lookback_used': lookback_periods,
                    'prominence_score': min(current_high - max(left_range), current_high - max(right_range))
                })
    
    # Method 2: Find major swing lows using prominence  
    for i in range(lookback_periods, len(lows) - lookback_periods):
        current_low = lows[i]
        
        # Check if this is a major low
        left_range = lows[i - lookback_periods:i]
        right_range = lows[i + 1:i + lookback_periods + 1]
        
        is_major_low = (current_low <= min(left_range) and 
                       current_low <= min(right_range) and
                       current_low <= min_low_price * 1.1)  # Within 10% of absolute low
        
        if is_major_low:
            if len(major_lows) == 0 or abs(current_low - major_lows[-1]['price']) >= min_price_move:
                major_lows.append({
                    'price': current_low,
                    'index': i,
                    'timestamp': price_data[i].get('time', price_data[i].get('timestamp', '')),
                    'method': 'prominence',
                    'lookback_used': lookback_periods,
                    'prominence_score': min(min(left_range) - current_low, min(right_range) - current_low)
                })
    
    # Always include the absolute highest and lowest points if they're not already included
    if not any(h['price'] == max_high_price for h in major_highs):
        major_highs.append({
            'price': max_high_price,
            'index': max_high_index,
            'timestamp': price_data[max_high_index].get('time', price_data[max_high_index].get('timestamp', '')),
            'method': 'absolute_high',
            'prominence_score': max_high_price - min_low_price
        })
    
    if not any(l['price'] == min_low_price for l in major_lows):
        major_lows.append({
            'price': min_low_price,
            'index': min_low_index,
            'timestamp': price_data[min_low_index].get('time', price_data[min_low_index].get('timestamp', '')),
            'method': 'absolute_low',
            'prominence_score': max_high_price - min_low_price
        })
    
    # Sort by prominence score (most prominent first)
    major_highs.sort(key=lambda x: x['prominence_score'], reverse=True)
    major_lows.sort(key=lambda x: x['prominence_score'], reverse=True)
    
    return {
        'swing_highs': major_highs,
        'swing_lows': major_lows,
        'total_highs': len(major_highs),
        'total_lows': len(major_lows),
        'dataset_range_pips': (max_high_price - min_low_price) / pip_value,
        'method': 'improved_prominence',
        'parameters': {
            'lookback_periods': lookback_periods,
            'min_swing_size_pips': min_swing_size_pips,
            'pip_value': pip_value
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
    trend_direction = 'downtrend' if best_high['index'] > best_low['index'] else 'uptrend'
    
    # Calculate swing range in pips
    pip_value = major_swings['parameters']['pip_value']
    swing_range_pips = abs(best_high['price'] - best_low['price']) / pip_value
    
    # Calculate current retracement level
    if best_high['price'] != best_low['price']:
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
    for ratio in ratios:
        level_price = high_price - (price_range * ratio)
        detailed_levels.append({
            'ratio': ratio,
            'price': round(level_price, 5),
            'description': f'{ratio:.1%} Retracement'
        })
    
    # Determine key level based on current retracement
    current_ret = swing_pair['current_retracement']
    if current_ret < 0.382:
        key_level = 0.382
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
            'high_method': swing_pair['high_swing']['method'],
            'low_method': swing_pair['low_swing']['method'],
            'high_prominence': swing_pair['high_swing']['prominence_score'],
            'low_prominence': swing_pair['low_swing']['prominence_score']
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
        min_swing_pips = max(params['min_pip_distance'] * 2, 30)  # Double the threshold for major swings
        
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
    Generate enhanced trade setups with detailed breakdowns.
    """
    
    is_jpy = 'JPY' in instrument
    pip_value = 0.01 if is_jpy else 0.0001
    decimal_places = 2 if is_jpy else 4
    
    # Distance filter based on timeframe
    timeframe_settings = get_timeframe_settings(timeframe)
    max_distance_pips = timeframe_settings['entry_distance_pips']
    max_distance = max_distance_pips * pip_value
    
    trade_setups = []
    
    # Extract Fibonacci data
    high_price = fibonacci_data['high']
    low_price = fibonacci_data['low']
    levels = fibonacci_data['levels']
    swing_range = high_price - low_price
    direction = fibonacci_data['direction']
    
    # Key trading levels (including reversal zone)
    key_levels = [0.382, 0.500, 0.618, 0.786, 0.886]
    
    for level in key_levels:
        if level in levels:
            # Calculate entry price
            entry_price = high_price - (swing_range * level)
            
            # Distance filter
            distance_to_entry = abs(current_price - entry_price)
            if distance_to_entry <= max_distance:
                
                # Generate trade setup
                setup = create_enhanced_setup(
                    level, entry_price, high_price, low_price,
                    current_price, direction, instrument, timeframe,
                    include_confluence, institutional_levels,
                    pip_value, decimal_places, distance_to_entry
                )
                
                if setup:
                    trade_setups.append(setup)
    
    # Sort by setup quality (highest first)
    trade_setups.sort(key=lambda x: x['setup_quality'], reverse=True)
    
    return trade_setups


def create_enhanced_setup(level: float, entry_price: float, high_price: float, 
                         low_price: float, current_price: float, direction: str,
                         instrument: str, timeframe: str, include_confluence: bool,
                         institutional_levels: Dict, pip_value: float, 
                         decimal_places: int, distance_to_entry: float) -> Dict:
    """
    Create a single enhanced trade setup with detailed breakdowns.
    """
    
    # Determine trade direction based on Fibonacci level and trend
    swing_range = high_price - low_price
    
    # Determine trade type and direction based on retracement level
    if direction in ['uptrend', 'bullish']:
        if level <= 0.786:  # Continuation zone: 38.2%, 50%, 61.8%, 78.6%
            trade_direction = 'BUY'
            setup_type_override = 'Trend Continuation'
            trade_type = 'long'
        else:  # Reversal zone: 88.6% and beyond
            trade_direction = 'SELL'
            setup_type_override = 'Trend Reversal'
            trade_type = 'short'
    else:  # downtrend
        if level <= 0.786:  # Continuation zone
            trade_direction = 'SELL'
            setup_type_override = 'Trend Continuation'
            trade_type = 'short'
        else:  # Reversal zone: 88.6% and beyond
            trade_direction = 'BUY'
            setup_type_override = 'Trend Reversal'
            trade_type = 'long'
    
    # Calculate stop loss and targets based on trade type
    stop_loss = calculate_smart_stop_loss(entry_price, high_price, low_price, level, trade_type, pip_value, timeframe)
    targets = calculate_smart_targets(entry_price, high_price, low_price, trade_type, pip_value)
    
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
    
    # Calculate stop loss Fibonacci level and buffer details
    swing_range = high_price - low_price
    timeframe_settings = get_timeframe_settings(timeframe)
    expected_buffer_pips = timeframe_settings['stop_buffer_pips']
    
    # Determine what Fibonacci level the stop represents
    if trade_direction == 'BUY':
        if level < 0.618:
            # Stop should be around 78.6% level
            expected_stop_level = high_price - (swing_range * 0.786)
            stop_reference = "78.6% Retracement"
        else:
            # Stop should be below swing low
            expected_stop_level = low_price
            stop_reference = "0.0% (Swing Low)"
        buffer_pips = (expected_stop_level - stop_loss) / pip_value
    else:  # SELL
        if level > 0.382:
            # Stop should be around 23.6% level
            expected_stop_level = high_price - (swing_range * 0.236)
            stop_reference = "23.6% Retracement"
        else:
            # Stop should be above swing high
            expected_stop_level = high_price
            stop_reference = "100.0% (Swing High)"
        buffer_pips = (stop_loss - expected_stop_level) / pip_value
    
    # Calculate target Fibonacci levels
    target_fibonacci_levels = []
    for i, target in enumerate(targets):
        if trade_direction == 'BUY':
            if target <= high_price + (10 * pip_value):
                target_fib = "Break above swing high"
            elif abs(target - (high_price + (swing_range * 0.272))) < (5 * pip_value):
                target_fib = "127.2% Extension"
            elif abs(target - (high_price + (swing_range * 0.618))) < (5 * pip_value):
                target_fib = "161.8% Extension"
            else:
                extension_ratio = (target - high_price) / swing_range
                target_fib = f"{(1.0 + extension_ratio):.1%} Extension"
        else:  # SELL
            if target >= low_price - (10 * pip_value):
                target_fib = "Break below swing low"
            elif abs(target - (low_price - (swing_range * 0.272))) < (5 * pip_value):
                target_fib = "127.2% Extension"
            elif abs(target - (low_price - (swing_range * 0.618))) < (5 * pip_value):
                target_fib = "161.8% Extension"
            else:
                extension_ratio = (low_price - target) / swing_range
                target_fib = f"{(1.0 + extension_ratio):.1%} Extension"
        
        target_fibonacci_levels.append(target_fib)

    # Create setup
    setup = {
        'setup_id': f'fibonacci_{level:.1%}_{timeframe}',
        'strategy': strategy_name,
        'setup_type': setup_type,
        'direction': trade_direction,
        'fibonacci_level': f'{level:.1%} Retracement',
        'entry_price': round(entry_price, decimal_places),
        'stop_loss': round(stop_loss, decimal_places),
        'stop_fibonacci_level': f'{stop_reference} + {buffer_pips:.1f} pip buffer',
        'target_price': round(targets[0], decimal_places) if targets else 0,
        'targets': [round(t, decimal_places) for t in targets],
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
        'entry_reason': f'{level:.1%} Fibonacci retracement in {direction}',
        'invalidation': f'Close {"below" if trade_direction == "BUY" else "above"} {round(stop_loss, decimal_places)}',
        'analysis_timestamp': datetime.utcnow().isoformat() + 'Z'
    }
    
    return setup


def calculate_smart_stop_loss(entry_price: float, high_price: float, low_price: float,
                             level: float, trade_direction: str, pip_value: float, timeframe: str) -> float:
    """
    Calculate intelligent stop loss placement using deeper Fibonacci levels.
    """
    
    swing_range = high_price - low_price
    # Get timeframe-specific buffer
    timeframe_settings = get_timeframe_settings(timeframe)
    buffer_pips = timeframe_settings['stop_buffer_pips']
    buffer = buffer_pips * pip_value
    
    if trade_direction == 'long':
        # For long trades, stop below deeper retracement or swing low
        if level < 0.618:
            # Use 78.6% level as stop
            stop_level = high_price - (swing_range * 0.786)
        else:
            # Use swing low with buffer
            stop_level = low_price
        
        return stop_level - buffer
    
    else:  # short trades
        # For short trades, stop above shallower retracement or swing high
        if level > 0.382:
            # Use 23.6% level as stop
            stop_level = high_price - (swing_range * 0.236)
        else:
            # Use swing high with buffer
            stop_level = high_price
            
        return stop_level + buffer


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
        targets.append(high_price + (swing_range * 0.618))  # T3: 161.8% extension
    
    else:  # short targets
        # Short targets: break below swing low, then extensions  
        targets.append(low_price - (10 * pip_value))   # T1: Break swing low
        targets.append(low_price - (swing_range * 0.272))  # T2: 127.2% extension
        targets.append(low_price - (swing_range * 0.618))  # T3: 161.8% extension
    
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