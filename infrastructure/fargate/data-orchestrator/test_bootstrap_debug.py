#\!/usr/bin/env python3
"""
Debug script to test why bootstrap isn't collecting 500 candles
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Set environment variables
os.environ['ENABLE_BOOTSTRAP'] = 'true'
os.environ['BOOTSTRAP_CANDLES'] = '500'
os.environ['TIMEFRAMES'] = 'M5,H1'
os.environ['AGGREGATED_TIMEFRAMES'] = 'M15,M30'

from config import Settings

# Test configuration
settings = Settings()

print(f"Bootstrap enabled: {os.environ.get('ENABLE_BOOTSTRAP')}")
print(f"Bootstrap candles: {settings.bootstrap_candles}")
print(f"Timeframes: {settings.timeframes}")
print(f"All supported timeframes: {settings.get_all_supported_timeframes()}")
print(f"Aggregated timeframes: {settings.aggregated_timeframes}")

# Test candle count for bootstrap
for timeframe in settings.timeframes:
    bootstrap_count = settings.get_candle_count_for_collection(timeframe, is_bootstrap=True)
    regular_count = settings.get_candle_count_for_collection(timeframe, is_bootstrap=False)
    print(f"\n{timeframe}:")
    print(f"  Bootstrap candles: {bootstrap_count}")
    print(f"  Regular candles: {regular_count}")

# Check what timeframes bootstrap should process
print("\n\nTimeframes that bootstrap should process:")
for timeframe in settings.get_all_supported_timeframes():
    if timeframe in settings.aggregated_timeframes:
        print(f"  {timeframe}: SKIP (aggregated)")
    else:
        print(f"  {timeframe}: PROCESS")
EOF < /dev/null
