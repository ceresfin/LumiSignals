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
                                    timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Improved Fibonacci analysis with major swing detection.
    
    Args:
        instrument: Currency pair (e.g., 'EUR_USD')
        current_price: Current market price
        price_data: Historical price data
        mode: 'fixed' or 'atr'
        timeframe: Timeframe for analysis
        
    Returns:
        Improved Fibonacci analysis with major swing levels
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
    
    return fibonacci_result