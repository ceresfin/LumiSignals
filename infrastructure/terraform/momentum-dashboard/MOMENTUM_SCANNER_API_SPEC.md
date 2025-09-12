# Momentum Scanner API Specification

**Endpoint**: `GET /api/momentum/scanner`  
**Purpose**: Provide 5-timeframe momentum analysis for all 28 currency pairs with caching  
**Integration**: Uses `lumisignals-trading-core` Lambda layer for calculations

## Request Format

```http
GET /api/momentum/scanner
Content-Type: application/json
```

### Query Parameters (Optional)
- `currency` (string): Filter by currency (USD, EUR, GBP, JPY, CAD, AUD, CHF, NZD) or 'ALL'
- `refresh` (boolean): Force cache refresh if true

## Response Format

### Success Response (200 OK)
```json
{
  "success": true,
  "data": {
    "EUR_USD": {
      "pair": "EUR_USD",
      "bid": 1.0745,
      "changes": {
        "48h": 0.35,
        "24h": 0.24,
        "4h": 0.08,
        "60m": -0.02,
        "15m": 0.01
      },
      "momentum_summary": {
        "overall_bias": "BULLISH",
        "strength": "MODERATE", 
        "confidence": 0.8,
        "aligned_timeframes": 4,
        "total_timeframes": 5
      },
      "market_session": "London",
      "last_updated": "2025-09-12T19:30:00.000Z"
    },
    "GBP_USD": {
      "pair": "GBP_USD", 
      "bid": 1.3124,
      "changes": {
        "48h": 0.16,
        "24h": 0.08,
        "4h": -0.04,
        "60m": -0.08,
        "15m": -0.05
      },
      "momentum_summary": {
        "overall_bias": "NEUTRAL",
        "strength": "WEAK",
        "confidence": 0.4,
        "aligned_timeframes": 2,
        "total_timeframes": 5
      },
      "market_session": "London",
      "last_updated": "2025-09-12T19:30:00.000Z"
    }
    // ... all 28 pairs
  },
  "metadata": {
    "total_pairs": 28,
    "market_session": "London",
    "server_time": "2025-09-12T19:30:00.000Z",
    "cache_expires": "2025-09-12T19:35:00.000Z",
    "calculation_time_ms": 234
  },
  "timestamp": "2025-09-12T19:30:00.000Z"
}
```

### Error Response (500 Internal Server Error)
```json
{
  "success": false,
  "error": "Failed to calculate momentum data",
  "details": "OANDA API timeout",
  "timestamp": "2025-09-12T19:30:00.000Z"
}
```

## Backend Implementation Guide

### 1. Lambda Function Structure
```python
# momentum_scanner_lambda.py

import json
import redis
from lumisignals_trading_core import MarketAwareMomentumCalculator
from oanda_api import OandaAPI

# Redis client for caching (5-minute TTL)
redis_client = redis.Redis(host='your-redis-cluster', decode_responses=True)
CACHE_TTL = 300  # 5 minutes

def lambda_handler(event, context):
    """
    Momentum Scanner API Lambda Handler
    """
    try:
        # Check cache first
        cache_key = "momentum_scanner:all_pairs"
        cached_data = redis_client.get(cache_key)
        
        if cached_data and not event.get('queryStringParameters', {}).get('refresh'):
            print("📦 Serving momentum data from cache")
            return {
                'statusCode': 200,
                'headers': {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                },
                'body': cached_data
            }
        
        # Calculate fresh momentum data
        print("🔄 Calculating fresh momentum data for all 28 pairs")
        
        # Initialize APIs
        oanda_api = OandaAPI()
        momentum_calc = MarketAwareMomentumCalculator(oanda_api)
        
        # All 28 currency pairs
        all_pairs = [
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD', 'USD_CHF',
            'EUR_JPY', 'GBP_JPY', 'CAD_JPY', 'AUD_JPY', 'NZD_JPY', 'CHF_JPY',
            'EUR_GBP', 'EUR_CAD', 'EUR_AUD', 'EUR_NZD', 'EUR_CHF',
            'GBP_CAD', 'GBP_AUD', 'GBP_NZD', 'GBP_CHF',
            'AUD_CAD', 'AUD_NZD', 'AUD_CHF', 'NZD_CAD', 'NZD_CHF'
        ]
        
        momentum_data = {}
        start_time = time.time()
        
        # Calculate momentum for each pair (parallel processing recommended)
        for pair in all_pairs:
            try:
                # Use the sophisticated momentum calculator from trading core layer
                momentum_summary = momentum_calc.get_momentum_summary(pair, 'pennies')
                
                if 'error' not in momentum_summary:
                    momentum_data[pair] = {
                        'pair': pair,
                        'bid': momentum_summary['current_price'],
                        'changes': {
                            '48h': momentum_summary['detailed_momentum']['48h']['percent_change'],
                            '24h': momentum_summary['detailed_momentum']['24h']['percent_change'],
                            '4h': momentum_summary['detailed_momentum']['4h']['percent_change'],
                            '60m': momentum_summary['detailed_momentum']['60m']['percent_change'],
                            '15m': momentum_summary['detailed_momentum']['15m']['percent_change']
                        },
                        'momentum_summary': momentum_summary['momentum_summary'],
                        'market_session': momentum_summary['market_session_info']['session_name'],
                        'last_updated': momentum_summary['timestamp']
                    }
                else:
                    print(f"❌ Failed to calculate momentum for {pair}: {momentum_summary['error']}")
                    
            except Exception as e:
                print(f"❌ Error calculating {pair} momentum: {e}")
        
        calculation_time_ms = int((time.time() - start_time) * 1000)
        
        # Build response
        response_data = {
            'success': True,
            'data': momentum_data,
            'metadata': {
                'total_pairs': len(momentum_data),
                'market_session': momentum_calc.market_schedule.get_session_info()['session_name'],
                'server_time': datetime.now().isoformat(),
                'cache_expires': (datetime.now() + timedelta(seconds=CACHE_TTL)).isoformat(),
                'calculation_time_ms': calculation_time_ms
            },
            'timestamp': datetime.now().isoformat()
        }
        
        # Cache the response
        response_json = json.dumps(response_data)
        redis_client.setex(cache_key, CACHE_TTL, response_json)
        
        print(f"✅ Momentum calculation complete: {len(momentum_data)} pairs in {calculation_time_ms}ms")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': response_json
        }
        
    except Exception as e:
        print(f"❌ Momentum scanner API error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }
```

### 2. Required Dependencies
- `lumisignals-trading-core` Lambda layer (with MarketAwareMomentumCalculator)
- `redis` for caching
- `oanda-api` for price data
- Standard Python libraries (json, time, datetime)

### 3. Caching Strategy

**Cache Key Structure:**
- `momentum_scanner:all_pairs` - Full dataset
- `momentum_scanner:currency:{CURRENCY}` - Filtered by currency
- TTL: 5 minutes (300 seconds)

**Cache Benefits:**
- Reduces OANDA API calls (28 pairs × 5 timeframes = 140+ API calls)
- Improves response time (< 100ms from cache vs 2-5 seconds calculation)
- Reduces Lambda execution costs

### 4. Performance Optimizations

**Parallel Processing:**
```python
import concurrent.futures

def calculate_pair_momentum(pair, momentum_calc):
    return momentum_calc.get_momentum_summary(pair, 'pennies')

# Parallel execution for all 28 pairs
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(calculate_pair_momentum, pair, momentum_calc): pair 
              for pair in all_pairs}
    
    for future in concurrent.futures.as_completed(futures):
        pair = futures[future]
        try:
            momentum_summary = future.result()
            # Process result...
        except Exception as e:
            print(f"Error calculating {pair}: {e}")
```

**API Batch Optimization:**
- Use OANDA batch pricing API when possible
- Implement circuit breaker for API failures
- Add retry logic with exponential backoff

### 5. Monitoring & Alerting

**CloudWatch Metrics:**
- `momentum_scanner.calculation_time` (milliseconds)
- `momentum_scanner.api_calls_count` (per 5 minutes)
- `momentum_scanner.cache_hit_rate` (percentage)
- `momentum_scanner.error_rate` (percentage)

**Alarms:**
- Calculation time > 10 seconds
- Error rate > 5%
- Cache hit rate < 80%

## Frontend Integration

The frontend `MomentumScanner` component is already configured to:

1. **Call the API** via `api.getMomentumScannerData()`
2. **Handle caching** with 5-minute refresh intervals
3. **Graceful fallback** to demo data if API unavailable
4. **Display all data fields** from the API response
5. **Currency filtering** using radio buttons

## Testing the Implementation

### 1. Local Testing
```bash
# Test with curl
curl -X GET "https://your-api.execute-api.us-east-1.amazonaws.com/prod/api/momentum/scanner" \
  -H "Content-Type: application/json"

# Test with cache refresh
curl -X GET "https://your-api.execute-api.us-east-1.amazonaws.com/prod/api/momentum/scanner?refresh=true" \
  -H "Content-Type: application/json"
```

### 2. Frontend Integration Test
1. Navigate to "Momentum Scanner" tab
2. Verify 5-minute auto-refresh working
3. Test currency filter radio buttons
4. Check console for API calls and caching behavior

### 3. Performance Validation
- Response time < 5 seconds (fresh calculation)
- Response time < 100ms (cached)
- All 28 pairs returned
- Valid momentum data for each timeframe

## Security Considerations

1. **API Gateway** throttling (100 requests/minute per IP)
2. **CORS** headers configured correctly
3. **Input validation** for query parameters
4. **Redis security** with authentication
5. **OANDA API keys** stored in AWS Secrets Manager

## Deployment Steps

1. **Package** `lumisignals-trading-core` layer
2. **Deploy** momentum scanner Lambda function
3. **Configure** API Gateway route: `/api/momentum/scanner`
4. **Set up** Redis cluster for caching
5. **Configure** CloudWatch monitoring
6. **Test** end-to-end functionality

---

This API specification provides everything needed to implement the backend for the Momentum Scanner feature using the sophisticated momentum calculation capabilities of the `lumisignals-trading-core` layer.