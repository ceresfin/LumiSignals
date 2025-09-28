#!/usr/bin/env python3
"""
LumiSignals Trading Core - Fibonacci Analysis Module

This module provides Fibonacci retracement and extension analysis for trading.
"""

# Updated to use the improved Fibonacci analysis
from .improved_fibonacci_analysis import (
    detect_major_swing_points,
    find_best_fibonacci_swing_pair,
    generate_improved_fibonacci_levels,
    analyze_fibonacci_levels_improved,
    generate_enhanced_trade_setups
)

# Legacy function mapping for backward compatibility
def analyze_fibonacci_levels(*args, **kwargs):
    """Legacy wrapper - redirects to improved analysis"""
    return analyze_fibonacci_levels_improved(*args, **kwargs)

__all__ = [
    'detect_major_swing_points',
    'find_best_fibonacci_swing_pair',
    'generate_improved_fibonacci_levels', 
    'analyze_fibonacci_levels_improved',
    'generate_enhanced_trade_setups',
    'analyze_fibonacci_levels'  # Legacy compatibility
]