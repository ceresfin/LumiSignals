#!/usr/bin/env python3
"""
LumiSignals Trading Core - Fibonacci Analysis Implementation

Automatic Fibonacci level detection and confluence analysis.

Supports two modes:
- 'fixed': Timeframe-aware fixed pip thresholds
- 'atr': Dynamic ATR-based thresholds
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from .atr_calculator import calculate_atr, get_atr_multipliers_by_strategy
from .timeframe_config import get_timeframe_parameters, get_timeframe_fibonacci_ratios

def detect_swing_points(price_data: List[Dict], window: int = 5, min_strength: int = 3) -> Dict[str, List]:
    """
    Automatically detect swing highs and lows in price data.
    
    Args:
        price_data: List of price dictionaries with 'high', 'low', 'close', 'timestamp'
        window: Number of periods on each side to confirm swing
        min_strength: Minimum number of periods that must be lower/higher
    
    Returns:
        Dictionary with swing highs and lows
    """
    
    if len(price_data) < window * 2 + 1:
        return {'swing_highs': [], 'swing_lows': []}
    
    swing_highs = []
    swing_lows = []
    
    for i in range(window, len(price_data) - window):
        current_high = price_data[i]['high']
        current_low = price_data[i]['low']
        
        # Check for swing high
        is_swing_high = True
        for j in range(i - window, i + window + 1):
            if j != i and price_data[j]['high'] >= current_high:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_highs.append({
                'price': current_high,
                'index': i,
                'timestamp': price_data[i]['timestamp'],
                'strength': window
            })
        
        # Check for swing low
        is_swing_low = True
        for j in range(i - window, i + window + 1):
            if j != i and price_data[j]['low'] <= current_low:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_lows.append({
                'price': current_low,
                'index': i,
                'timestamp': price_data[i]['timestamp'],
                'strength': window
            })
    
    return {'swing_highs': swing_highs, 'swing_lows': swing_lows}

def find_significant_swings(swing_points: Dict, min_pip_distance: int = 100, is_jpy: bool = False) -> List[Dict]:
    """
    Filter swing points to find only significant moves.
    
    Args:
        swing_points: Output from detect_swing_points
        min_pip_distance: Minimum distance in pips between swings
        is_jpy: True for JPY pairs
    
    Returns:
        Filtered significant swings
    """
    
    pip_value = 0.01 if is_jpy else 0.0001
    min_price_distance = min_pip_distance * pip_value
    
    # Combine and sort all swings by timestamp
    all_swings = []
    
    for swing in swing_points['swing_highs']:
        all_swings.append({**swing, 'type': 'high'})
    
    for swing in swing_points['swing_lows']:
        all_swings.append({**swing, 'type': 'low'})
    
    all_swings.sort(key=lambda x: x['index'])
    
    # Filter for significant moves
    significant_swings = []
    last_swing = None
    
    for swing in all_swings:
        if last_swing is None:
            significant_swings.append(swing)
            last_swing = swing
        else:
            # Check if this swing is significant enough
            price_distance = abs(swing['price'] - last_swing['price'])
            
            if price_distance >= min_price_distance:
                # Also check if it's alternating (high after low, low after high)
                if swing['type'] != last_swing['type']:
                    significant_swings.append(swing)
                    last_swing = swing
                elif price_distance > min_price_distance * 1.5:  # Allow same type if much larger move
                    significant_swings.append(swing)
                    last_swing = swing
    
    return significant_swings

def find_significant_swings_timeframe(swing_points: Dict, timeframe: str = 'H1', is_jpy: bool = False) -> List[Dict]:
    """
    Find significant swings using timeframe-specific thresholds.
    """
    params = get_timeframe_parameters(timeframe)
    min_pip_distance = params['min_pip_distance']
    return find_significant_swings(swing_points, min_pip_distance, is_jpy)

def find_significant_swings_atr(swing_points: Dict, price_data: List[Dict], atr_multiplier: float = 2.0, is_jpy: bool = False) -> Dict[str, Any]:
    """
    Find significant swings using ATR-based thresholds.
    """
    # Calculate ATR
    atr_analysis = calculate_atr(price_data, period=14)
    current_atr = atr_analysis['current_atr']
    
    if current_atr == 0:
        return {
            'significant_swings': [],
            'total_swings': 0,
            'atr_analysis': atr_analysis,
            'message': 'Unable to calculate ATR'
        }
    
    # Calculate swing threshold in pips
    pip_value = 0.01 if is_jpy else 0.0001
    swing_threshold_price = current_atr * atr_multiplier
    min_pip_distance = int(swing_threshold_price / pip_value)
    
    # Use existing function with ATR-based threshold
    significant_swings = find_significant_swings(swing_points, min_pip_distance, is_jpy)
    
    # Add ATR metrics
    for i, swing in enumerate(significant_swings):
        if i > 0:
            prev_swing = significant_swings[i-1]
            swing_size = abs(swing['price'] - prev_swing['price'])
            swing['atr_multiple'] = swing_size / current_atr if current_atr > 0 else 0
        else:
            swing['atr_multiple'] = 0
    
    return {
        'significant_swings': significant_swings,
        'total_swings': len(significant_swings),
        'swing_threshold': swing_threshold_price,
        'current_atr': current_atr,
        'atr_multiplier': atr_multiplier,
        'min_pip_distance': min_pip_distance
    }

def generate_fibonacci_levels(high_price: float, low_price: float, direction: str = 'retracement') -> Dict[str, Dict]:
    """
    Generate Fibonacci levels between high and low prices.
    
    Args:
        high_price: Higher price point
        low_price: Lower price point
        direction: 'retracement' or 'extension'
    
    Returns:
        Dictionary with Fibonacci levels
    """
    
    # Standard Fibonacci ratios
    retracement_ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    extension_ratios = [0.0, 0.618, 1.0, 1.272, 1.414, 1.618, 2.0, 2.618]
    
    price_range = high_price - low_price
    
    if direction == 'retracement':
        ratios = retracement_ratios
        levels = {}
        
        for ratio in ratios:
            level_price = high_price - (price_range * ratio)
            levels[f'{ratio:.3f}'] = {
                'price': round(level_price, 5),
                'ratio': ratio,
                'type': 'retracement',
                'description': f'{ratio:.1%} Retracement'
            }
    
    else:  # extension
        ratios = extension_ratios
        levels = {}
        
        for ratio in ratios:
            level_price = low_price - (price_range * (ratio - 1.0))
            levels[f'{ratio:.3f}'] = {
                'price': round(level_price, 5),
                'ratio': ratio,
                'type': 'extension',
                'description': f'{ratio:.1%} Extension'
            }
    
    return levels

def auto_generate_fibonacci_from_swings(significant_swings: List[Dict], current_price: float) -> Dict[str, Any]:
    """
    Automatically generate Fibonacci levels from detected swings.
    
    Args:
        significant_swings: List of significant swing points
        current_price: Current market price
    
    Returns:
        Dictionary with multiple Fibonacci level sets
    """
    
    if len(significant_swings) < 2:
        return {'fibonacci_sets': [], 'message': 'Insufficient swing data'}
    
    fibonacci_sets = []
    
    # Generate Fibonacci levels for recent swing patterns
    for i in range(len(significant_swings) - 1):
        swing1 = significant_swings[i]
        swing2 = significant_swings[i + 1]
        
        # Determine high and low
        if swing1['price'] > swing2['price']:
            high_swing = swing1
            low_swing = swing2
            trend_direction = 'downtrend'
        else:
            high_swing = swing2
            low_swing = swing1
            trend_direction = 'uptrend'
        
        # Generate retracement levels
        retracement_levels = generate_fibonacci_levels(
            high_swing['price'], 
            low_swing['price'], 
            'retracement'
        )
        
        # Generate extension levels
        extension_levels = generate_fibonacci_levels(
            high_swing['price'], 
            low_swing['price'], 
            'extension'
        )
        
        # Calculate relevance score based on recency and proximity to current price
        time_weight = 1.0 / (len(significant_swings) - i)  # More recent = higher weight
        
        # Find closest Fibonacci level to current price
        all_fib_prices = [level['price'] for level in retracement_levels.values()]
        all_fib_prices.extend([level['price'] for level in extension_levels.values()])
        
        closest_fib_distance = min([abs(current_price - price) for price in all_fib_prices])
        proximity_weight = 1.0 / (1.0 + closest_fib_distance * 10000)  # Closer = higher weight
        
        relevance_score = time_weight * proximity_weight
        
        fibonacci_sets.append({
            'id': f'fib_set_{i}',
            'high_swing': high_swing,
            'low_swing': low_swing,
            'trend_direction': trend_direction,
            'retracement_levels': retracement_levels,
            'extension_levels': extension_levels,
            'relevance_score': relevance_score,
            'swing_range_pips': int(abs(high_swing['price'] - low_swing['price']) * 10000)
        })
    
    # Sort by relevance score (most relevant first)
    fibonacci_sets.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    return {
        'fibonacci_sets': fibonacci_sets,
        'total_sets': len(fibonacci_sets),
        'most_relevant': fibonacci_sets[0] if fibonacci_sets else None
    }

def integrate_fibonacci_with_institutional_levels(fibonacci_sets: Dict, institutional_levels: Dict, tolerance_pips: int = 10, is_jpy: bool = False) -> Dict[str, Any]:
    """
    Find confluences between Fibonacci levels and institutional levels.
    
    Args:
        fibonacci_sets: Output from auto_generate_fibonacci_from_swings
        institutional_levels: Dictionary with dimes, quarters, small_quarters, pennies
        tolerance_pips: Pip tolerance for confluence detection
        is_jpy: True for JPY pairs
    
    Returns:
        Dictionary with confluence analysis
    """
    
    pip_value = 0.01 if is_jpy else 0.0001
    tolerance_price = tolerance_pips * pip_value
    
    confluences = []
    
    # Flatten all institutional levels
    all_institutional = []
    for level_type, levels in institutional_levels.items():
        for level in levels:
            all_institutional.append({
                'price': level,
                'type': level_type,
                'level': level
            })
    
    # Check each Fibonacci set for confluences
    for fib_set in fibonacci_sets['fibonacci_sets']:
        set_confluences = []
        
        # Check retracement levels
        for ratio, fib_level in fib_set['retracement_levels'].items():
            fib_price = fib_level['price']
            
            for inst_level in all_institutional:
                if abs(fib_price - inst_level['price']) <= tolerance_price:
                    confluence_strength = 1.0 / (1.0 + abs(fib_price - inst_level['price']) * 10000)
                    
                    set_confluences.append({
                        'fibonacci_ratio': ratio,
                        'fibonacci_price': fib_price,
                        'fibonacci_type': 'retracement',
                        'institutional_type': inst_level['type'],
                        'institutional_price': inst_level['price'],
                        'confluence_strength': confluence_strength,
                        'price_difference_pips': int(abs(fib_price - inst_level['price']) / pip_value)
                    })
        
        # Check extension levels
        for ratio, fib_level in fib_set['extension_levels'].items():
            fib_price = fib_level['price']
            
            for inst_level in all_institutional:
                if abs(fib_price - inst_level['price']) <= tolerance_price:
                    confluence_strength = 1.0 / (1.0 + abs(fib_price - inst_level['price']) * 10000)
                    
                    set_confluences.append({
                        'fibonacci_ratio': ratio,
                        'fibonacci_price': fib_price,
                        'fibonacci_type': 'extension',
                        'institutional_type': inst_level['type'],
                        'institutional_price': inst_level['price'],
                        'confluence_strength': confluence_strength,
                        'price_difference_pips': int(abs(fib_price - inst_level['price']) / pip_value)
                    })
        
        if set_confluences:
            confluences.append({
                'fibonacci_set_id': fib_set['id'],
                'confluences': set_confluences,
                'confluence_count': len(set_confluences),
                'total_strength': sum([c['confluence_strength'] for c in set_confluences])
            })
    
    # Sort confluences by total strength
    confluences.sort(key=lambda x: x['total_strength'], reverse=True)
    
    return {
        'confluences': confluences,
        'total_confluence_sets': len(confluences),
        'strongest_confluence': confluences[0] if confluences else None
    }

def create_sample_price_data(current_price: float = 1.2187, periods: int = 50, is_jpy: bool = False) -> List[Dict]:
    """Create sample price data for testing."""
    
    np.random.seed(42)  # For reproducible results
    
    price_data = []
    base_price = current_price
    
    for i in range(periods):
        # Simulate price movement
        change = np.random.normal(0, 0.01 if not is_jpy else 1.0)  # Random walk
        base_price += change
        
        # Create OHLC data
        high = base_price + abs(np.random.normal(0, 0.005 if not is_jpy else 0.5))
        low = base_price - abs(np.random.normal(0, 0.005 if not is_jpy else 0.5))
        close = base_price + np.random.normal(0, 0.002 if not is_jpy else 0.2)
        
        price_data.append({
            'high': round(high, 4 if not is_jpy else 2),
            'low': round(low, 4 if not is_jpy else 2),
            'close': round(close, 4 if not is_jpy else 2),
            'timestamp': datetime.now() - timedelta(hours=periods-i)
        })
    
    return price_data

def analyze_fibonacci_levels(instrument: str, current_price: float = None, price_data: List[Dict] = None, mode: str = 'fixed', timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Main function to analyze Fibonacci levels for an instrument.
    
    Args:
        instrument: Currency pair (e.g., 'EUR_USD')
        current_price: Current market price
        price_data: Historical price data, if None will generate sample data
    
    Returns:
        Complete Fibonacci analysis
    """
    
    # Determine if JPY pair
    is_jpy = 'JPY' in instrument
    
    # Use provided data or create sample data
    if price_data is None:
        if current_price is None:
            current_price = 150.0 if is_jpy else 1.1000
        price_data = create_sample_price_data(current_price, 50, is_jpy)
    
    if current_price is None and price_data:
        current_price = price_data[-1]['close']
    
    # Get mode-specific parameters
    if mode == 'atr':
        # ATR-based analysis
        strategy = 'balanced'  # Can be made configurable later
        strategy_params = get_atr_multipliers_by_strategy(strategy)
        window = strategy_params['window']
        atr_multiplier = strategy_params['swing_multiplier']
        
        # Detect swing points with ATR-appropriate window
        swing_points = detect_swing_points(price_data, window=window)
        
        # Find significant swings using ATR
        atr_result = find_significant_swings_atr(swing_points, price_data, atr_multiplier, is_jpy)
        significant_swings = atr_result.get('significant_swings', [])
        
        # Add ATR info to result
        atr_info = {
            'mode': 'atr',
            'strategy': strategy,
            'current_atr': atr_result.get('current_atr', 0),
            'swing_threshold': atr_result.get('swing_threshold', 0),
            'atr_multiplier': atr_multiplier,
            'min_pip_distance': atr_result.get('min_pip_distance', 0)
        }
    else:  # mode == 'fixed'
        # Timeframe-based analysis
        params = get_timeframe_parameters(timeframe)
        window = params['window']
        
        # Detect swing points with timeframe-appropriate window
        swing_points = detect_swing_points(price_data, window=window)
        
        # Find significant swings using timeframe thresholds
        significant_swings = find_significant_swings_timeframe(swing_points, timeframe, is_jpy)
        
        # Add timeframe info to result
        atr_info = {
            'mode': 'fixed',
            'timeframe': timeframe,
            'min_pip_distance': params['min_pip_distance'],
            'description': params['description']
        }
    
    # Generate Fibonacci analysis
    fibonacci_analysis = auto_generate_fibonacci_from_swings(significant_swings, current_price)
    
    # Prepare simplified output for frontend
    if fibonacci_analysis['most_relevant']:
        most_relevant = fibonacci_analysis['most_relevant']
        
        # Extract key levels for chart overlay
        key_levels = []
        for ratio, level_data in most_relevant['retracement_levels'].items():
            if float(ratio) in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]:
                key_levels.append({
                    'ratio': float(ratio),
                    'price': level_data['price'],
                    'description': level_data['description']
                })
        
        return {
            'levels': [level['ratio'] for level in key_levels],
            'high': most_relevant['high_swing']['price'],
            'low': most_relevant['low_swing']['price'],
            'direction': most_relevant['trend_direction'],
            'current_retracement': 0.382,  # Could be calculated based on current price
            'key_level': 0.618,
            'detailed_levels': key_levels,
            'swing_range_pips': most_relevant['swing_range_pips'],
            'relevance_score': most_relevant['relevance_score'],
            'mode': mode,
            'mode_info': atr_info
        }
    else:
        # Fallback basic levels - differentiate by mode
        if mode == 'fixed':
            # H1 timeframe specific levels (fewer levels, more conservative range)
            return {
                'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 1.0],  # No 0.786 for H1
                'high': current_price * 1.015,  # 1.5% range (conservative)
                'low': current_price * 0.985,
                'direction': 'neutral',
                'current_retracement': 0.382,
                'key_level': 0.618,
                'message': 'Using fallback Fixed Fibonacci levels (H1) - insufficient swing data',
                'mode': mode,
                'mode_info': atr_info if 'atr_info' in locals() else {'mode': mode}
            }
        else:  # mode == 'atr'
            # ATR mode with full levels and wider range
            return {
                'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0],  # All levels
                'high': current_price * 1.025,  # 2.5% range (more aggressive)
                'low': current_price * 0.975,
                'direction': 'neutral',
                'current_retracement': 0.5,
                'key_level': 0.618,
                'message': 'Using fallback ATR Fibonacci levels - insufficient swing data',
                'mode': mode,
                'mode_info': atr_info if 'atr_info' in locals() else {'mode': mode}
            }