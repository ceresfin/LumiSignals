# Redis Key Mismatch Fix Summary

## Root Cause of Rolling Gap

The rolling gap on pipstop.org was caused by **Redis key pattern mismatches** between:
- Data writer (Fargate): Uses `:historical` 
- Data readers (Lambda): Were using `:cold`

## Files Fixed

### 1. `/infrastructure/lambda/direct-candlestick-api/lambda_function.py`
- **Problem**: Looking for `:cold` key that doesn't exist
- **Fix**: Changed to `:historical` to match data orchestrator
- **Impact**: Fixes pipstop.org chart gaps immediately

### 2. `/infrastructure/lambda/signal-analytics-api/tiered_data_helper.py`
- **Problem**: Same mismatch in helper function
- **Fix**: Changed to `:historical` 
- **Impact**: Ensures consistency for future Lambda functions

## Other Systems Status

### ✅ Already Correct
- `/infrastructure/lambda/signal-analytics-api/lambda_function.py` - Line 157 already uses `:historical`
- Some dashboard APIs already use correct pattern

### ⚠️ Potential Issues Found
- Old backup files still have wrong pattern (harmless)
- Some strategy Lambda functions may have similar issues

## Expected Results

After deploying these fixes:
1. **Immediate**: pipstop.org should show complete data (no more gaps)
2. **Historical gaps**: Will remain (from the deployment period)
3. **Future**: No more rolling gaps from tier data mismatches

## Next Steps

1. Deploy the direct-candlestick-api fix (highest priority)
2. Monitor pipstop.org for gap resolution
3. Consider checking individual strategy Lambda functions if they use tiered data

## Key Lesson

This shows the importance of:
- Consistent naming conventions across the system
- Centralized configuration for Redis key patterns
- Documentation of data flow between components