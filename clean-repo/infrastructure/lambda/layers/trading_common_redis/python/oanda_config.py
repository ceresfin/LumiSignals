# oanda_config.py
# Configuration settings for Oanda trading integration
# This file keeps all our settings in one place, making them easy to modify

import os

# Oanda API credentials
# We use environment variables for security - never hardcode real credentials!
API_KEY = os.getenv('OANDA_API_KEY', '45f57a060fa720b79da0fcd8656bd832-1b71616af845f432ba0cfbe183a121ef')
ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID', '101-001-21245555-001')
ENVIRONMENT = os.getenv('OANDA_ENV', 'practice')  # 'practice' for demo, 'live' for real money

# Trading risk management parameters
# These settings help control how much risk you take with each trade
DEFAULT_RISK_PERCENT = 1.0  # Risk 2% of account balance per trade
MAX_POSITIONS = 40           # Maximum number of open positions at once
MAX_DAILY_TRADES = 40       # Limit trades per day to avoid overtrading

# Instrument preferences
# List of currency pairs you want to focus on
PREFERRED_INSTRUMENTS = [
    'EUR_USD',  # Euro/US Dollar
    'GBP_USD',  # British Pound/US Dollar
    'USD_JPY',  # US Dollar/Japanese Yen
    'AUD_USD',  # Australian Dollar/US Dollar
]

# Default order parameters
DEFAULT_STOP_LOSS_PIPS = 20    # Default stop loss in pips
DEFAULT_TAKE_PROFIT_PIPS = 40  # Default take profit in pips (2:1 risk/reward ratio)