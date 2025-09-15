# Direct Candlestick API Lambda Documentation

## Overview
This Lambda function provides direct access to candlestick data from Redis, bypassing the main Lambda strategies. It was created as a workaround to access pure candlestick data without trading logic or session filtering.

## API Endpoint
**Base URL**: `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod`

## API Routes

### Get Candlestick Data
```
GET /candlestick/{currency_pair}/{timeframe}?count={count}
```

**Path Parameters**:
- `currency_pair` (required): Currency pair like EUR_USD, GBP_USD, etc.
- `timeframe` (optional): Timeframe like M5, H1, etc. Default: H1

**Query Parameters**:
- `count` (optional): Number of candles to retrieve. Default: 50

**Example Request**:
```
GET https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/USD_CAD/H1?count=500
```

**Example Response**:
```json
{
  "success": true,
  "data": [
    {
      "time": "2025-09-15T00:00:00Z",
      "timestamp": "2025-09-15T00:00:00Z",
      "open": 1.3625,
      "high": 1.3635,
      "low": 1.3620,
      "close": 1.3630,
      "volume": 1250
    }
  ],
  "metadata": {
    "currency_pair": "USD_CAD",
    "timeframe": "H1",
    "count": 500,
    "requested_count": 500,
    "timestamp": "2025-09-15T00:30:00Z",
    "data_source": "REDIS_FARGATE_TIERED_H1",
    "sources_used": ["hot(50)", "warm(450)"]
  }
}
```

## Data Architecture

### Data Flow
```
OANDA → Fargate → Redis (4 shards) → Lambda → API Gateway → Dashboard
```

### Redis Tiered Storage
The Lambda accesses 3 tiers of Redis storage:
- **Hot Tier**: 50 most recent candles (1 day TTL)
- **Warm Tier**: 450 older candles (5 days TTL)
- **Cold Tier**: 500 bootstrap candles (7 days TTL)

### Currency Pair to Shard Mapping
- **Shard 0**: EUR_USD, GBP_USD, USD_JPY, USD_CAD, AUD_USD, NZD_USD, USD_CHF
- **Shard 1**: EUR_GBP, EUR_JPY, EUR_CAD, EUR_AUD, EUR_NZD, EUR_CHF, GBP_JPY
- **Shard 2**: GBP_CAD, GBP_AUD, GBP_NZD, GBP_CHF, AUD_JPY, AUD_CAD, AUD_NZD
- **Shard 3**: AUD_CHF, NZD_JPY, NZD_CAD, NZD_CHF, CAD_JPY, CAD_CHF, CHF_JPY

## CORS Configuration

### Current CORS Headers (as of 2025-09-15)
```python
cors_headers = {
    'Access-Control-Allow-Origin': cors_origin,  # Specific origin from allowed list
    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,x-api-key',
    'Access-Control-Allow-Methods': 'GET,OPTIONS,POST',
    'Access-Control-Allow-Credentials': 'false',
    'Access-Control-Max-Age': '86400'
}
```

### Allowed Origins
- https://pipstop.org
- https://www.pipstop.org
- http://pipstop.org
- http://www.pipstop.org

## Current Issues (2025-09-15)

### CORS Conflict
- API Gateway CORS configuration is overriding Lambda CORS headers
- OPTIONS preflight returns `Access-Control-Allow-Origin: *` instead of specific origin
- This causes browser CORS errors when accessing from pipstop.org

### Solutions Being Considered
1. Update API Gateway CORS configuration to pass through Lambda headers
2. Remove API Gateway CORS and let Lambda handle all CORS
3. Return to original system without API Gateway

## Lambda Function Details

### Runtime
- Python 3.x
- Handler: `lambda_function.lambda_handler`

### Environment Variables
None required - all configuration is hardcoded

### IAM Permissions Required
- VPC access (to reach Redis in private subnets)
- CloudWatch Logs write permissions

### Redis Connection Details
```python
redis_nodes = [
    "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
]
```

## Testing

### Test with curl
```bash
# Test OPTIONS preflight
curl -X OPTIONS -H "Origin: https://pipstop.org" \
  "https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/USD_CAD/H1?count=1"

# Test actual GET request
curl -H "Origin: https://pipstop.org" \
  "https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/USD_CAD/H1?count=500"
```

## Backup and Recovery

### Backup Created
- File: `lambda_function_backup_2025_09_15.py`
- Contains exact copy of current Lambda function
- Can be used to revert any changes

### To Revert
1. Copy backup file contents back to `lambda_function.py`
2. Deploy Lambda function
3. Test API functionality

## Related Documentation
- `/mnt/c/Users/sonia/LumiSignals/LUMISIGNALS-DATA-ORCHESTRATOR-EXPLAINED.md`
- `/mnt/c/Users/sonia/LumiSignals/infrastructure/terraform/momentum-dashboard/CORS_FIX_AND_API_DOCUMENTATION.md`