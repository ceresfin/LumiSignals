#!/usr/bin/env python3
"""
LumiSignals Trading Core - Shared trading infrastructure for AWS Lambda

This package provides core trading infrastructure components that can be shared
across multiple Lambda functions for psychological level trading strategies.

Modules:
    momentum: Market-aware momentum calculations with forex trading hour logic
    
Future modules (planned):
    sentiment: Scotia Bank and news sentiment analysis
    signals: Unified signal generation and validation
    utils: Common trading utilities and helpers
"""

# Core module imports
from . import momentum

# Package metadata
__version__ = "1.0.0"
__author__ = "LumiSignals Trading Team"
__title__ = "lumisignals-trading-core"
__description__ = "Shared trading infrastructure for LumiSignals Lambda functions"

# Define what gets imported with "from lumisignals_trading_core import *"
__all__ = [
    'momentum',
]

# Quick access to most commonly used classes
from .momentum import (
    MarketAwareMomentumCalculator,
    ForexMarketSchedule,
    get_current_market_time,
    is_market_currently_open
)

# Layer information
LAYER_INFO = {
    'name': 'lumisignals-trading-core',
    'version': __version__,
    'description': __description__,
    'author': __author__,
    'modules': ['momentum'],
    'primary_classes': [
        'MarketAwareMomentumCalculator',
        'ForexMarketSchedule'
    ],
    'supported_strategies': ['pennies', 'quarters', 'dimes', 'small_quarters'],
    'aws_lambda_compatible': True,
    'python_version': '3.9+'
}

def get_layer_info():
    """Get information about this Lambda layer"""
    return LAYER_INFO

def validate_layer():
    """Validate that all core components are working"""
    try:
        # Validate momentum module
        momentum_status = momentum.validate_module()
        
        return {
            'layer_status': 'healthy',
            'version': __version__,
            'momentum_module': momentum_status,
            'total_modules': len(__all__)
        }
    except Exception as e:
        return {
            'layer_status': 'error',
            'error': str(e),
            'version': __version__
        }

# Usage examples for documentation
USAGE_EXAMPLES = {
    'basic_momentum': """
# Basic momentum calculation
from lumisignals_trading_core import MarketAwareMomentumCalculator

calc = MarketAwareMomentumCalculator(oanda_api)
momentum_data = calc.get_momentum_summary('EUR_USD', 'pennies')
print(f"EUR/USD momentum: {momentum_data['momentum_summary']['overall_bias']}")
""",
    
    'consensus_signal': """
# Get trading consensus with confidence
from lumisignals_trading_core.momentum import get_trading_consensus

consensus = get_trading_consensus(oanda_api, 'GBP_USD', 'pennies')
if consensus['trading_ready']:
    print(f"Signal: {consensus['signal']} with {consensus['confidence']:.1%} confidence")
""",
    
    'market_schedule': """
# Check market hours
from lumisignals_trading_core import get_current_market_time, is_market_currently_open

if is_market_currently_open():
    current_time = get_current_market_time()
    print(f"Market is open. Current time: {current_time}")
else:
    print("Market is closed")
"""
}