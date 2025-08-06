"""
Simple momentum calculator for trading strategies
"""

from typing import List, Dict, Any


def calculate_momentum(candles: List[Dict[str, Any]], periods: int = 2) -> float:
    """
    Calculate price momentum over specified periods
    
    Args:
        candles: List of candle data
        periods: Number of periods to calculate momentum over
        
    Returns:
        Momentum as percentage change
    """
    if not candles or len(candles) < periods:
        return 0.0
    
    try:
        # Get closing prices
        current_close = float(candles[-1]['mid']['c'])
        previous_close = float(candles[-periods]['mid']['c'])
        
        if previous_close == 0:
            return 0.0
        
        # Calculate percentage change
        momentum = (current_close - previous_close) / previous_close
        
        return momentum
        
    except (KeyError, ValueError, IndexError):
        return 0.0


def calculate_multi_timeframe_momentum(candles_dict: Dict[str, List[Dict]]) -> Dict[str, float]:
    """
    Calculate momentum across multiple timeframes
    
    Args:
        candles_dict: Dictionary of timeframe -> candle data
        
    Returns:
        Dictionary of timeframe -> momentum value
    """
    momentum_values = {}
    
    for timeframe, candles in candles_dict.items():
        momentum = calculate_momentum(candles)
        momentum_values[timeframe] = momentum
    
    return momentum_values


def determine_momentum_direction(momentum_60m: float, momentum_4h: float, 
                               threshold: float = 0.05) -> str:
    """
    Determine overall momentum direction
    
    Args:
        momentum_60m: 60-minute momentum
        momentum_4h: 4-hour momentum
        threshold: Minimum momentum threshold
        
    Returns:
        'POSITIVE', 'NEGATIVE', or 'NEUTRAL'
    """
    # Both timeframes must agree
    if momentum_60m > threshold and momentum_4h > threshold:
        return 'POSITIVE'
    elif momentum_60m < -threshold and momentum_4h < -threshold:
        return 'NEGATIVE'
    else:
        return 'NEUTRAL'