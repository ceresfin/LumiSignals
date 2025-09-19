"""
ATR (Average True Range) calculator for dynamic Fibonacci analysis
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def calculate_atr(price_data: List[Dict[str, float]], period: int = 14) -> Dict[str, Any]:
    """
    Calculate Average True Range (ATR) for given price data.
    
    Args:
        price_data: List of price dictionaries with 'high', 'low', 'close'
        period: Number of periods for ATR calculation (default 14)
    
    Returns:
        Dictionary with ATR values and current ATR
    """
    
    if len(price_data) < period + 1:
        return {'atr_values': [], 'current_atr': 0, 'message': 'Insufficient data for ATR calculation'}
    
    true_ranges = []
    
    for i in range(1, len(price_data)):
        current = price_data[i]
        previous = price_data[i-1]
        
        # Calculate True Range components
        high_low = current['high'] - current['low']
        high_close_prev = abs(current['high'] - previous['close'])
        low_close_prev = abs(current['low'] - previous['close'])
        
        # True Range is the maximum of the three
        true_range = max(high_low, high_close_prev, low_close_prev)
        true_ranges.append(true_range)
    
    # Calculate ATR using Simple Moving Average of True Ranges
    atr_values = []
    
    for i in range(period - 1, len(true_ranges)):
        atr_period_data = true_ranges[i - period + 1:i + 1]
        atr = sum(atr_period_data) / len(atr_period_data)
        atr_values.append(atr)
    
    current_atr = atr_values[-1] if atr_values else 0
    
    return {
        'atr_values': atr_values,
        'current_atr': current_atr,
        'true_ranges': true_ranges,
        'period': period
    }

def get_atr_multipliers_by_strategy(strategy: str = 'balanced') -> Dict[str, Any]:
    """
    Get ATR multipliers for different trading strategies.
    
    Args:
        strategy: Trading strategy type
    
    Returns:
        Dictionary with ATR multipliers and parameters
    """
    
    strategies = {
        'conservative': {
            'swing_multiplier': 3.0,
            'window': 5,
            'description': 'Conservative - Major structural swings only',
            'use_case': 'Daily/H4 position trading',
            'noise_level': 'Very Low'
        },
        'balanced': {
            'swing_multiplier': 1.0,
            'window': 2,
            'description': 'Balanced - Good sensitivity vs noise ratio',
            'use_case': 'H1-H4 swing trading',
            'noise_level': 'Low'
        },
        'sensitive': {
            'swing_multiplier': 1.5,
            'window': 3,
            'description': 'Sensitive - More responsive to smaller moves',
            'use_case': 'M30-H1 day trading',
            'noise_level': 'Medium'
        },
        'aggressive': {
            'swing_multiplier': 1.0,
            'window': 2,
            'description': 'Aggressive - Maximum sensitivity',
            'use_case': 'M5-M15 scalping',
            'noise_level': 'High'
        }
    }
    
    return strategies.get(strategy, strategies['balanced'])