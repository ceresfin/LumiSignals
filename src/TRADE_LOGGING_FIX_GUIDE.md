# Trade Logging Fix Guide

## Overview

This guide explains the fixes implemented to ensure all trades are properly logged and synchronized with Airtable for comprehensive trade journaling.

## Issues Fixed

### 1. **Incomplete Metadata Storage**
- **Problem**: Trade metadata was not being consistently stored with all required fields
- **Fix**: Created `ComprehensiveTradeLog` class that captures ALL trade data including:
  - Order details (ID, type, direction, units)
  - Price levels (entry, stop loss, take profit, current)
  - Strategy metadata (setup name, momentum analysis, zone position)
  - Session context (trading session, liquidity level)
  - Risk metrics (R:R ratio, risk amount)

### 2. **Metadata Classification Issues**
- **Problem**: Momentum direction and strategy bias were not mapping correctly to Airtable select options
- **Fix**: Implemented proper mapping functions:
  ```python
  momentum_direction_mapping = {
      'strong_bullish': 'Strong Bullish',
      'bullish': 'Weak Bullish',
      'neutral': 'Neutral',
      'bearish': 'Weak Bearish',
      'strong_bearish': 'Strong Bearish'
  }
  ```

### 3. **Missing Trade Logs**
- **Problem**: Some trades were not being logged if placed through certain code paths
- **Fix**: Created `TradeLoggerWrapper` that intercepts ALL order placements

### 4. **Sync Issues**
- **Problem**: sync_all.py was not properly accessing enhanced metadata
- **Fix**: Created `EnhancedTradeSync` that:
  - Reads from comprehensive trade logs
  - Properly maps all fields for Airtable
  - Handles both pending and filled orders
  - Updates current prices for open trades

## New Components

### 1. **enhanced_trade_logger.py**
Comprehensive trade logging system that:
- Stores complete trade information in JSON files
- Tracks order lifecycle (pending → filled/cancelled)
- Maintains sync status with Airtable
- Provides statistics and reporting

### 2. **enhanced_sync_all.py**
Enhanced synchronization that:
- Syncs comprehensive logs to Airtable
- Matches OANDA transactions with local logs
- Updates current prices for open trades
- Generates sync reports

### 3. **trade_logger_integration.py**
Integration wrapper that:
- Intercepts order placements
- Ensures all trades are logged
- Maintains backward compatibility
- Calculates risk metrics

## Usage Instructions

### 1. **For New Trading Strategies**

```python
from trade_logger_integration import create_logged_oanda_api
from config.oanda_config import API_KEY, ACCOUNT_ID

# Create API with logging
api = create_logged_oanda_api(API_KEY, ACCOUNT_ID)

# Prepare order request
order_request = {
    'instrument': 'EUR_USD',
    'units': 1000,
    'type': 'MARKET',
    'stopLossOnFill': {'price': 1.0950},
    'takeProfitOnFill': {'price': 1.1050}
}

# Prepare metadata
metadata = {
    'setup_name': 'PCM_EUR/USD_MARKET_BUY_Strong',
    'strategy_tag': 'PCM',
    'momentum_strength': 0.75,
    'momentum_strength_str': 'Strong',
    'momentum_direction': 'bullish',
    'momentum_direction_str': 'Weak Bullish',
    'strategy_bias': 'BUY',
    'zone_position': 'In_Buy_Zone',
    'signal_confidence': 85
}

# Prepare context
strategy_context = {
    'trading_session': 'London',
    'session_overlap': 'London-NY',
    'liquidity_level': 'High',
    'market_time_et': '2025-06-29 10:30:00 ET'
}

# Execute order with logging
result = api.wrapper.log_and_execute_order(
    order_request, 
    metadata, 
    strategy_context
)
```

### 2. **For Existing Strategies**

Modify the order placement code:

```python
# OLD CODE:
result = self.api.place_order(order_request)

# NEW CODE:
result = self.api.wrapper.log_and_execute_order(
    order_request,
    metadata,
    strategy_context
)
```

### 3. **Running Synchronization**

```bash
# Run enhanced sync
python src/enhanced_sync_all.py

# This will:
# 1. Sync all unsynced logs to Airtable
# 2. Match OANDA transactions with logs
# 3. Update prices for open trades
# 4. Generate a sync report
```

### 4. **Checking Trade Logs**

```python
from enhanced_trade_logger import get_trade_logger

# Get logger instance
logger = get_trade_logger()

# Get statistics
stats = logger.get_trade_statistics()
print(f"Total logs: {stats['total_logs']}")
print(f"Unsynced: {stats['unsynced_logs']}")
print(f"Strategy breakdown: {stats['strategy_breakdown']}")

# Get unsynced logs
unsynced = logger.get_unsyced_logs()
for log in unsynced:
    print(f"{log.setup_name} - {log.order_status}")
```

## File Locations

Trade logs are stored in:
- `src/trading_logs/comprehensive_trade_log.json` - All trades
- `src/trading_logs/pending_orders.json` - Pending orders only
- `src/trading_logs/filled_trades.json` - Filled trades only
- `src/trading_logs/cancelled_orders.json` - Cancelled orders only

## Airtable Field Mapping

The system maps to these Airtable fields:

### Order Information
- OANDA Order ID
- Fill ID
- Instrument
- Order Type
- Direction
- Units

### Price Levels
- Entry Price
- Stop Loss
- Target Price
- Current Price
- Filled Price

### Strategy Metadata
- Setup Name
- Strategy Tag
- Strategy Variant
- Momentum Strength (numeric)
- Momentum Strength (Text)
- Momentum Direction (select)
- Strategy Bias (select)
- Zone Position (select)
- Signal Confidence
- Distance to Entry (Pips)

### Session Context
- Trading Session
- Session Overlap
- Liquidity Level
- Market Time ET

### Risk Metrics
- Risk Amount (USD)
- Risk Percentage
- R:R Ratio Calculated

## Troubleshooting

### Missing Trades
1. Check `comprehensive_trade_log.json` for the order
2. Look for sync errors in `enhanced_sync.log`
3. Verify order ID matches between OANDA and logs

### Sync Errors
1. Check Airtable field names match exactly
2. Verify select options are configured in Airtable
3. Check for None/null values in numeric fields

### Metadata Issues
1. Ensure all strategies provide complete metadata
2. Check mapping functions for your values
3. Verify strategy_tag is consistent

## Migration from Old System

To migrate existing trades:

```python
from enhanced_sync_all import EnhancedTradeSync

# Initialize sync
sync = EnhancedTradeSync()

# Sync historical transactions
sync.sync_oanda_transactions(from_id="1")

# Sync all logs
sync.sync_comprehensive_logs()
```

## Best Practices

1. **Always provide complete metadata** when placing orders
2. **Run sync regularly** (every 15-30 minutes)
3. **Check logs** for any sync errors
4. **Backup trade logs** regularly
5. **Test with small positions** first

## Support

For issues or questions:
1. Check the log files in `src/trading_logs/`
2. Review `enhanced_sync.log` for sync errors
3. Verify Airtable permissions and field configuration