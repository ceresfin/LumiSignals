#!/usr/bin/env python3
"""
Momentum calculation module for lumisignals-trading-core

This module provides sophisticated market-aware momentum calculations for forex trading,
including multi-timeframe analysis, forex market hour awareness, and consensus signal generation.

Classes:
    ForexMarketSchedule: Handles forex market hours and trading day logic
    MarketAwareMomentumCalculator: Main momentum calculator with 5-timeframe analysis

Utility Functions:
    calculate_instrument_momentum: Quick momentum calculation for single instrument
    get_trading_consensus: Get consensus signal with confidence scoring
    is_momentum_aligned: Check if momentum meets alignment requirements
    get_momentum_strength_score: Calculate momentum strength score (0-100)
    get_current_market_time: Get current market time (EST/EDT)
    is_market_currently_open: Check if forex market is currently open
    get_trading_hours_ago: Get market time from specified trading hours ago
"""

# Core classes
from .forex_market_schedule import ForexMarketSchedule
from .market_aware_momentum import MarketAwareMomentumCalculator

# Utility functions from forex_market_schedule
from .forex_market_schedule import (
    get_current_market_time,
    is_market_currently_open,
    get_trading_hours_ago
)

# Utility functions from market_aware_momentum
from .market_aware_momentum import (
    calculate_instrument_momentum,
    get_trading_consensus,
    is_momentum_aligned,
    get_momentum_strength_score
)

# Module metadata
__version__ = "1.0.0"
__author__ = "LumiSignals Trading Team"
__description__ = "Market-aware momentum calculations for forex trading strategies"

# Define what gets imported with "from lumisignals_trading_core.momentum import *"
__all__ = [
    # Core classes
    'ForexMarketSchedule',
    'MarketAwareMomentumCalculator',
    
    # Market schedule utilities
    'get_current_market_time',
    'is_market_currently_open', 
    'get_trading_hours_ago',
    
    # Momentum calculation utilities
    'calculate_instrument_momentum',
    'get_trading_consensus',
    'is_momentum_aligned',
    'get_momentum_strength_score',
]

# Available strategy types for momentum calculations
SUPPORTED_STRATEGIES = ['pennies', 'quarters', 'dimes', 'small_quarters']

# Default momentum significance threshold (5 basis points)
DEFAULT_MOMENTUM_THRESHOLD = 0.05

# Quick module validation
def validate_module():
    """Validate that all core components are available"""
    try:
        # Test core class instantiation
        schedule = ForexMarketSchedule()
        current_time = schedule.get_market_time()
        
        return {
            'status': 'success',
            'current_market_time': current_time.isoformat(),
            'market_open': schedule.is_market_open(current_time),
            'supported_strategies': SUPPORTED_STRATEGIES,
            'version': __version__
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'version': __version__
        }

# Module initialization message
def get_module_info():
    """Get module information and status"""
    return {
        'module': 'lumisignals_trading_core.momentum',
        'version': __version__,
        'description': __description__,
        'author': __author__,
        'supported_strategies': SUPPORTED_STRATEGIES,
        'default_threshold': DEFAULT_MOMENTUM_THRESHOLD,
        'available_classes': ['ForexMarketSchedule', 'MarketAwareMomentumCalculator'],
        'available_utilities': [
            'calculate_instrument_momentum',
            'get_trading_consensus', 
            'is_momentum_aligned',
            'get_momentum_strength_score',
            'get_current_market_time',
            'is_market_currently_open',
            'get_trading_hours_ago'
        ]
    }