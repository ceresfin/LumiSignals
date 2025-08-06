# OANDA-Airtable Trade Sync Lambda

## Overview
This Lambda function provides automated synchronization between OANDA trading platform and Airtable database. It syncs:
- Active Trades
- Closed Trades (with comprehensive filtering)
- Pending Orders
- Currency Exposures
- Currency Pair Positions

## Structure

```
trade-sync/
├── main.py              # Lambda handler entry point
├── sync/                # Sync modules for each table
│   ├── active_trades.py
│   ├── closed_trades.py
│   ├── pending_orders.py
│   ├── positions.py
│   └── exposures.py
├── utils/               # Utility modules
│   ├── oanda_api.py     # OANDA API client
│   ├── airtable_api.py  # Airtable utilities
│   └── calculations.py  # Forex calculations
└── config/              # Configuration
    └── field_mappings.py # Field mapping definitions
```

## Key Features

### Closed Trades Sync
- Syncs ALL trades from June 2025 to current date
- Filters trades by close reason: Stop Loss Hit, Take Profit, Sell Market
- Calculates comprehensive metrics:
  - Pips gained/lost (with JPY pair handling)
  - Risk/reward ratios
  - Actual exit prices from transactions
  - Stop loss and take profit levels

### Enhanced Field Mapping
All required fields are populated:
- Trade ID, Instrument, Direction, Units
- Entry/Exit Price, Open/Close Time
- Gross/Net P&L, Close Reason, Gain/Loss
- Pips, Strategy, Status
- Return:Risk Ratio, Stop Loss, Take Profit
- Max Favorable/Adverse (placeholders for future enhancement)

### Intelligent Updates
- Updates existing records instead of delete/recreate
- Preserves manually added Airtable fields
- Handles pagination for large datasets
- Efficient batch processing

## Deployment

### Local Testing
```bash
python main.py
```

### Lambda Deployment
1. Package the entire `trade-sync` directory
2. Include dependencies (requests, python-dateutil)
3. Set handler to `main.lambda_handler`
4. Configure environment variables if needed

### Required AWS Secrets
- `lumisignals/oanda/api/credentials`
  - api_key
  - account_id
  - environment (practice/live)
  
- `lumisignals/airtable/api/credentials`
  - api_token
  - base_id

## Configuration

### Close Reason Filtering
Edit `ALLOWED_CLOSE_REASONS` in `config/field_mappings.py` to change which trades are synced.

### Date Range
To modify the sync date range for closed trades, edit the `start_date` in `sync/closed_trades.py`.

## Monitoring

The Lambda logs detailed information:
- Number of records synced per table
- Any errors or warnings
- Total sync duration
- Individual operation counts (created/updated/deleted)

## Error Handling

- Graceful handling of API errors
- Detailed error logging
- Continues sync even if individual records fail
- Returns comprehensive error information