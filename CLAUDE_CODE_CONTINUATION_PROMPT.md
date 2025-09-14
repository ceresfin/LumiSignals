# Claude Code Continuation Prompt - LumiSignals Trading Dashboard

## Project Overview

This is a comprehensive trading dashboard for LumiSignals that displays M5 (5-minute) candlestick charts with advanced analytics overlays. The frontend is a React/TypeScript application deployed on AWS S3/CloudFront, consuming candlestick data from Lambda functions via API Gateway.

**Key URLs:**
- **Frontend**: https://pipstop.org
- **Direct Candlestick API**: https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod
- **RDS API**: https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod (BROKEN - returns empty data)

## Current State & Issues

### ✅ SOLVED: CORS Issue (September 13, 2025)

**Problem**: M5 candlestick data was failing to load in the Analytics tab with CORS errors, while H1 data worked fine.

**Root Cause**: Lambda function was not returning proper CORS headers for the pipstop.org origin.

**Solution Applied**:
1. **Lambda Function Update** (`/infrastructure/lambda/direct-candlestick-api/lambda_function.py`):
   ```python
   # Dynamic CORS origin handling
   origin = event.get('headers', {}).get('origin', '') or event.get('headers', {}).get('Origin', '')
   allowed_origins = [
       'https://pipstop.org',
       'https://www.pipstop.org',
       'http://localhost:3000',
       'http://localhost:5173',
       'http://localhost:5174'
   ]
   cors_origin = origin if origin in allowed_origins else 'https://pipstop.org'
   
   return {
       'statusCode': 200,
       'headers': {
           'Content-Type': 'application/json',
           'Access-Control-Allow-Origin': cors_origin,  # Dynamic instead of '*'
           'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
           'Access-Control-Allow-Methods': 'OPTIONS,GET',
           'Access-Control-Allow-Credentials': 'true'
       },
       'body': json.dumps(candle_data)
   }
   ```

2. **Dependencies Fix** (`/infrastructure/lambda/direct-candlestick-api/requirements.txt`):
   ```
   redis==5.0.1
   async-timeout==4.0.3  # This was missing
   ```

3. **Deployment**:
   ```bash
   cd infrastructure/lambda/direct-candlestick-api
   pip install -r requirements.txt -t .
   zip -r lambda_function.zip .
   aws lambda update-function-code --function-name lumisignals-direct-candlestick-api --zip-file fileb://lambda_function.zip
   ```

**Result**: 100% CORS success rate, M5 data now loads properly.

### 🔄 ONGOING: React Component Remounting Issue

**Problem**: Analytics tab shows only 1 candlestick instead of 10, despite successful API calls and chart data setting.

**Root Cause**: React components are mounting multiple times (2-4 mounts per component), and the final mount wipes out the chart data.

**Debugging Journey**:

#### Phase 1: Initial Investigation
- **Symptom**: Charts show "Setting 10 candles" → "Chart data set successfully" but only 1 candle displays
- **Discovery**: Components were mounting 4-5 times each
- **Console Pattern**:
  ```
  🚀 TradingViewChartAnalytics mounted for EUR_USD
  🔍 CHART DEBUG: Setting 10 candles to chart for EUR_USD
  🔍 CHART DEBUG: Chart data set successfully for EUR_USD
  🚀 TradingViewChartAnalytics mounted for EUR_USD (again - wipes data)
  ```

#### Phase 2: Suspected Causes & Fixes Attempted

**1. Prop Stability Issues**
- **Suspected**: `sortRank` prop changing from undefined → 4 → 1 (due to sorting)
- **Fix Attempted**: Removed `sortRank` prop entirely
- **Result**: Still 4 mounts

**2. Callback Recreation**
- **Suspected**: `onUserInteraction` callback being recreated in map loop
- **Fix Attempted**: Moved callback outside map, used stable reference
- **Result**: Still multiple mounts

**3. Analytics Array Recreation**
- **Suspected**: `selectedAnalytics` array being recreated each render
- **Fix Attempted**: Memoized with `React.useMemo(() => ['fibonacci', 'momentum', 'sentiment', 'levels'], [])`
- **Result**: Still multiple mounts

**4. Sorting Logic Causing DOM Reordering**
- **Suspected**: When prices load, components get re-sorted, causing React to remount
- **Fix Attempted**: Completely disabled sorting logic
- **Result**: Still multiple mounts (not the cause)

**5. React.StrictMode Double Mounting**
- **Suspected**: StrictMode causes components to mount twice in development
- **Fix Attempted**: Removed `<React.StrictMode>` wrapper from `main.tsx`
- **Result**: Reduced mounts but still multiple

**6. Price Fetching State Updates**
- **Suspected**: Failed price API calls causing parent state updates → child remounts
- **Fix Attempted**: Disabled price fetching completely
- **Discovery**: This eliminated some mounts but not all

**7. Component State Updates Propagating**
- **Suspected**: `setLoading()`, `setError()`, `setAnalyticsData()` causing parent re-renders
- **Fix Attempted**: Disabled these state setters
- **Result**: TBD (most recent attempt)

#### Phase 3: Current Understanding

**Mount Pattern Discovered**:
- Mount #1: Initial render
- Mount #2: Usually caused by async operations completing
- Mount #3: Chart data gets set successfully here
- Mount #4: Wipes out the chart data (6 seconds later, suggesting another async operation)

**Key Insights**:
- 4 mounts might correspond to 4 analytics: fibonacci, momentum, sentiment, levels
- State updates in child components cause parent to re-render all children
- Chart data survives in refs but gets cleared when chart DOM element is recreated

## Architecture & API Documentation

### API Endpoints

#### 1. Direct Candlestick API (✅ WORKING)
- **Endpoint**: `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/{currency_pair}/{timeframe}`
- **Lambda**: `lumisignals-direct-candlestick-api`
- **Purpose**: Serves candlestick data directly from Redis (500 candles per pair)
- **Data Source**: Redis tiered storage system
- **Parameters**:
  - `currency_pair`: EUR_USD, GBP_JPY, etc. (28 forex pairs)
  - `timeframe`: H1, M5, H4, D1
  - `count` (query param): Number of candles (default: 500)
- **Response Format**:
  ```json
  [
    {
      "datetime": "2025-09-12T20:55:00Z",
      "open": 1.10456,
      "high": 1.10478,
      "low": 1.10445,
      "close": 1.10469,
      "volume": 0
    }
  ]
  ```

#### 2. RDS API (❌ BROKEN)
- **Endpoint**: `https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/market-data`
- **Issue**: Returns empty data - RDS has no candlestick data stored
- **Status**: DO NOT USE
- **Used By**: `getCandlestickDataFromRDS()` method (causes Graphs tab to fail)

### Frontend API Service

**File**: `/infrastructure/terraform/momentum-dashboard/src/services/api.ts`

**Working Method**:
```typescript
async getCandlestickData(currencyPair: string, timeframe: string = 'H1', count: number = 50): Promise<ApiResponse<any>> {
  const directUrl = `https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/${currencyPair}/${timeframe}?count=${count}`;
  const response = await fetch(directUrl);
  const data = await response.json();
  return { success: true, data: data };
}
```

**Broken Method (DO NOT USE)**:
```typescript
async getCandlestickDataFromRDS(currencyPair: string, timeframe: string = 'H1'): Promise<ApiResponse<any>> {
  return this.request(`/market-data?type=candlestick&currency_pair=${currencyPair}&timeframe=${timeframe}`);
}
```

### Key Components

#### 1. Analytics Tab - CurrencyPairGraphsAnalytics.tsx
- **Purpose**: Display M5 charts with analytics overlays
- **Features**: Fibonacci, momentum, sentiment, institutional levels
- **Issue**: Components remounting, showing 1 candle instead of 10
- **API**: Uses `getCandlestickData()` for chart data
- **Status**: Currently being debugged

#### 2. Graphs Tab - CurrencyPairGraphsWithTrades.tsx
- **Purpose**: Display H1 charts with trade overlays
- **Issue**: Uses broken `getCandlestickDataFromRDS()` method
- **Status**: Disabled due to CORS issues

#### 3. Chart Component - LightweightTradingViewChartAnalytics.tsx
- **Library**: TradingView Lightweight Charts
- **Data Processing**: Takes 50 candles, displays first 10
- **Analytics**: Institutional levels, fibonacci, momentum, sentiment
- **Issue**: Gets remounted multiple times, losing chart data

### Infrastructure Access

#### AWS Resources
```bash
# Lambda Functions
aws lambda list-functions --query "Functions[?contains(FunctionName, 'candlestick')].FunctionName"

# API Gateway
aws apigateway get-rest-apis --query "items[*].[name,id,description]"

# S3 Bucket (Frontend)
aws s3 ls s3://pipstop.org-website

# CloudFront Distribution
aws cloudfront list-distributions --query "DistributionList.Items[*].[Id,DomainName,Comment]"
```

#### Deployment Commands
```bash
# Frontend Build & Deploy
npm run build
aws s3 sync dist/ s3://pipstop.org-website --delete --cache-control max-age=0
aws cloudfront create-invalidation --distribution-id EKCW6AHXVBAW0 --paths "/*"

# Lambda Update
cd infrastructure/lambda/direct-candlestick-api
zip -r lambda_function.zip .
aws lambda update-function-code --function-name lumisignals-direct-candlestick-api --zip-file fileb://lambda_function.zip
```

## Current Code State

### Working Features
- ✅ CORS is fixed - all M5 API calls work from browser
- ✅ Lambda function returns proper data
- ✅ Chart library can display candlesticks
- ✅ Analytics calculations work
- ✅ Institutional level overlays work

### Broken Features
- ❌ Charts show 1 candle instead of 10 (remounting issue)
- ❌ Graphs tab disabled (uses broken RDS API)
- ❌ Price fetching disabled (was causing remounts)
- ❌ Sorting disabled (was suspected to cause remounts)

### Debugging Tools in Place
- Mount counter with timestamps
- Comprehensive console logging
- Chart lifecycle tracking
- API call success/failure logging

### Files Modified (Most Recent Session)
1. **main.tsx**: Removed React.StrictMode
2. **CurrencyPairGraphsAnalytics.tsx**: Disabled price fetching and sorting
3. **LightweightTradingViewChartAnalytics.tsx**: Disabled state setters, added mount debugging
4. **lambda_function.py**: Fixed CORS headers (previously)

## Next Steps & Recommendations

### Immediate Priority: Fix Remounting Issue
1. **Test Current State**: Check if disabling state setters reduced mounts to 1
2. **If Still Remounting**: 
   - Add React DevTools Profiler to see what's triggering re-renders
   - Consider moving chart components outside the Analytics parent
   - Try React.memo() with custom comparison function
   - Check if useEffect dependencies are causing issues

### Future Enhancements (After Remounting Fixed)
1. **Re-enable Price Fetching**: With proper error handling to prevent state updates
2. **Fix Graphs Tab**: Either fix RDS API or migrate to Direct API
3. **Re-enable Sorting**: With stable references to prevent remounts
4. **Add Error Boundaries**: To prevent single chart failures from affecting others
5. **Performance Optimization**: Virtualization for 28 charts, lazy loading

### Testing Commands
```bash
# CORS Test
curl -H "Origin: https://pipstop.org" https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod/candlestick/EUR_USD/M5?count=10

# Lambda Logs
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/lumisignals"
aws logs tail /aws/lambda/lumisignals-direct-candlestick-api --follow
```

## Historical Context

This issue emerged when adding the Analytics tab to an existing system that had working H1 charts. The debugging process has been extensive, involving:
- 6+ deployment cycles
- Multiple architectural changes
- Systematic elimination of suspected causes
- Deep React lifecycle analysis

The system was working perfectly at 10pm EST on 9/12/25 before the Analytics tab was added. The current approach is to isolate and fix the remounting issue, then incrementally re-enable features.

## Key Learnings

1. **CORS must be configured at Lambda level** - API Gateway settings alone are insufficient
2. **React remounting can be caused by**: StrictMode, prop changes, parent re-renders, state updates
3. **State updates propagate upward** - Child component setState() can cause parent re-renders
4. **API failures cause cascading issues** - Failed price fetches → state updates → remounts
5. **Debugging React lifecycle requires systematic elimination** of suspected causes

---

*Last Updated: September 14, 2025, 03:58 UTC*
*Status: Debugging component remounting issue*
*Priority: Fix 1-candle display issue in Analytics tab*