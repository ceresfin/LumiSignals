"""
LumiSignals Trading Core - Swing Detection Module

Enhanced swing point detection and market structure analysis.
"""

from .swing_detection import (
    SwingPoint,
    MarketStructure, 
    EnhancedSwingDetector,
    analyze_swing_structure
)

__all__ = [
    'SwingPoint',
    'MarketStructure',
    'EnhancedSwingDetector', 
    'analyze_swing_structure'
]