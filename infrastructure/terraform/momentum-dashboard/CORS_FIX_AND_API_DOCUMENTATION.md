# CORS Fix and Candlestick API Documentation

## CORS Issue and Resolution

### The Problem
- **When**: September 13, 2025, around 9:30 AM EST
- **Issue**: M5 candlestick data was failing to load in the Analytics tab with CORS errors
- **Browser Error**: `Access to fetch at 'https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/M5' from origin 'https://pipstop.org' has been blocked by CORS policy`
- **Important**: H1 data was working fine, only M5 had CORS issues

### Root Cause Analysis
1. Ran `test-h1-behavior.js` which showed both H1 and M5 worked perfectly from Node.js (100% success rate)
2. This proved the issue was browser-specific CORS enforcement, not a backend problem
3. The Lambda function was not returning proper CORS headers for the pipstop.org origin

### The Fix Applied

#### 1. Lambda Function Update
**File**: `/infrastructure/lambda/direct-candlestick-api/lambda_function.py`

**Original Code** (problematic):
```python
return {
    'statusCode': 200,
    'headers': {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',  # Too permissive
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'OPTIONS,GET'
    },
    'body': json.dumps(candle_data)
}
```

**Fixed Code**:
```python
# Get the origin from the request headers
origin = event.get('headers', {}).get('origin', '') or event.get('headers', {}).get('Origin', '')

# Define allowed origins
allowed_origins = [
    'https://pipstop.org',
    'https://www.pipstop.org',
    'http://localhost:3000',
    'http://localhost:5173',
    'http://localhost:5174'
]

# Set CORS origin based on request
if origin in allowed_origins:
    cors_origin = origin
else:
    cors_origin = 'https://pipstop.org'  # Default to production

return {
    'statusCode': 200,
    'headers': {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': cors_origin,  # Dynamic based on request
        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
        'Access-Control-Allow-Methods': 'OPTIONS,GET',
        'Access-Control-Allow-Credentials': 'true'
    },
    'body': json.dumps(candle_data)
}
```

#### 2. Dependencies Fix
**File**: `/infrastructure/lambda/direct-candlestick-api/requirements.txt`

Added missing dependency:
```
redis==5.0.1
async-timeout==4.0.3  # This was missing and causing Lambda errors
```

#### 3. Deployment Steps
```bash
# 1. Package the Lambda
cd infrastructure/lambda/direct-candlestick-api
pip install -r requirements.txt -t .
zip -r lambda_function.zip .

# 2. Update Lambda function
aws lambda update-function-code \
  --function-name lumisignals-direct-candlestick-api \
  --zip-file fileb://lambda_function.zip

# 3. Test CORS
node test-cors.js
# Result: ✅ CORS Test Results: 100% success rate
```

## Working Candlestick APIs

### 1. Direct Candlestick API (WORKING ✅)
**Endpoint**: `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/{currency_pair}/{timeframe}`
- **Lambda Function**: `lumisignals-direct-candlestick-api`
- **Purpose**: Serves candlestick data directly from Redis without session filtering
- **Data Source**: Redis tiered storage (500 candles per pair)

**Parameters**:
- `currency_pair`: Any of the 28 forex pairs (e.g., "EUR_USD", "GBP_JPY")
- `timeframe`: "H1" or "M5" (H4 and D also available but not used in frontend)
- `count` (optional): Number of candles to return (default: 500)

**Example Request**:
```javascript
// Fetch 50 M5 candles for EUR_USD
const response = await fetch(
  'https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/M5?count=50'
);
```

**Response Format**:
```json
[
  {
    "datetime": "2025-09-12T20:55:00Z",
    "open": 1.10456,
    "high": 1.10478,
    "low": 1.10445,
    "close": 1.10469,
    "volume": 0
  },
  // ... more candles
]
```

### 2. RDS-Based API (BROKEN ❌)
**Endpoint**: `https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/market-data`
- **Issue**: Returns empty data - RDS has no candlestick data stored
- **Used By**: `getCandlestickDataFromRDS()` in api.ts
- **Status**: DO NOT USE

### 3. Frontend API Service Methods

**File**: `/infrastructure/terraform/momentum-dashboard/src/services/api.ts`

#### Working Method:
```typescript
async getCandlestickData(currencyPair: string, timeframe: string = 'H1', count: number = 50): Promise<ApiResponse<any>> {
  const directUrl = `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/${currencyPair}/${timeframe}?count=${count}`;
  const response = await fetch(directUrl);
  const data = await response.json();
  return {
    success: true,
    data: data
  };
}
```

#### Broken Method (DO NOT USE):
```typescript
async getCandlestickDataFromRDS(currencyPair: string, timeframe: string = 'H1'): Promise<ApiResponse<any>> {
  // This queries RDS which has NO candlestick data
  return this.request(`/market-data?type=candlestick&currency_pair=${currencyPair}&timeframe=${timeframe}`);
}
```

## Current Issues and Workarounds

### 1. Component Remounting Issue
**Problem**: Charts are remounting multiple times, causing only 1 candle to display
**Cause**: React component lifecycle issues with changing props (sortRank changes)
**Attempted Fixes**:
- Stabilized selectedAnalytics array
- Removed recreating callbacks
- Removed sortRank prop entirely

### 2. Timestamp Field Issue (FIXED)
**Problem**: Charts showed "Invalid Date" on x-axis
**Cause**: API returns `datetime` field but code was looking for `candle.time`
**Fix**: Changed from `candle.time` to `candle.datetime` in chart component

## Testing Commands

### Test CORS:
```bash
# Create test-cors.js
cat > test-cors.js << 'EOF'
const fetch = require('node-fetch');

async function testCORS() {
  const url = 'https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/M5?count=10';
  
  try {
    const response = await fetch(url, {
      headers: {
        'Origin': 'https://pipstop.org'
      }
    });
    
    console.log('Status:', response.status);
    console.log('CORS Headers:', response.headers.get('access-control-allow-origin'));
    
    if (response.ok) {
      const data = await response.json();
      console.log('Data received:', data.length, 'candles');
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

testCORS();
EOF

node test-cors.js
```

### Clear CloudFront Cache:
```bash
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*"
```

## Key Learnings

1. **CORS must be configured at Lambda level** - API Gateway CORS settings alone are not sufficient
2. **Dynamic CORS origins** are better than wildcard (*) for security
3. **Always test from browser context** - Node.js tests don't enforce CORS
4. **RDS API is not functional** - Always use Direct Candlestick API
5. **Component remounting** can overwrite chart data - need proper React lifecycle management