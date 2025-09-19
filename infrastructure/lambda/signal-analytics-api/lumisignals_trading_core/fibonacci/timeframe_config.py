"""
Timeframe-specific configurations for Fibonacci analysis
"""

def get_timeframe_parameters(timeframe: str) -> dict:
    """
    Get appropriate swing detection parameters based on timeframe.
    
    Args:
        timeframe: String like 'D1', 'H4', 'H1', 'M30', 'M15', 'M5'
    
    Returns:
        Dictionary with swing detection parameters
    """
    
    timeframe_configs = {
        'D1': {
            'min_pip_distance': 75,
            'window': 4,
            'min_strength': 3,
            'description': 'Daily - Major swings'
        },
        'H4': {
            'min_pip_distance': 35,
            'window': 3,
            'min_strength': 2,
            'description': '4-Hour - Significant intraday moves'
        },
        'H1': {
            'min_pip_distance': 15,
            'window': 6,
            'min_strength': 1,
            'description': '1-Hour - Hourly momentum shifts'
        },
        'M30': {
            'min_pip_distance': 12,
            'window': 2,
            'min_strength': 2,
            'description': '30-Minute - Short-term reversals'
        },
        'M15': {
            'min_pip_distance': 10,
            'window': 2,
            'min_strength': 1,
            'description': '15-Minute - Scalping swings'
        },
        'M5': {
            'min_pip_distance': 4,
            'window': 2,
            'min_strength': 1,
            'description': '5-Minute - Micro swings'
        }
    }
    
    return timeframe_configs.get(timeframe.upper(), timeframe_configs['H1'])  # Default to H1

def get_timeframe_fibonacci_ratios(timeframe: str) -> dict:
    """
    Get Fibonacci ratios optimized for each timeframe.
    
    Args:
        timeframe: Timeframe string
    
    Returns:
        Dictionary with retracement and extension ratios
    """
    
    timeframe_ratios = {
        'D1': {
            'retracement': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0],
            'extension': [0.0, 0.618, 1.0, 1.272, 1.414, 1.618, 2.0, 2.618]
        },
        'H4': {
            'retracement': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0],
            'extension': [0.0, 0.618, 1.0, 1.272, 1.618, 2.0]
        },
        'H1': {
            'retracement': [0.0, 0.236, 0.382, 0.5, 0.618, 1.0],
            'extension': [0.0, 0.618, 1.0, 1.272, 1.618]
        },
        'M30': {
            'retracement': [0.0, 0.382, 0.5, 0.618, 1.0],
            'extension': [0.0, 1.0, 1.272, 1.618]
        },
        'M15': {
            'retracement': [0.0, 0.382, 0.5, 0.618, 1.0],
            'extension': [0.0, 1.0, 1.272, 1.618]
        },
        'M5': {
            'retracement': [0.0, 0.5, 0.618, 1.0],
            'extension': [0.0, 1.0, 1.272]
        }
    }
    
    # Default to H1 if timeframe not found
    return timeframe_ratios.get(timeframe.upper(), timeframe_ratios['H1'])