# Tier Rotation Fix Summary

## Issues Found and Fixed

### 1. **M5 Rolling Gap Issue (CRITICAL)**
- **Root Cause**: Double-trimming of hot tier causing data loss
- **Location**: `data_orchestrator.py` lines 1029-1039
- **Problem**: 
  - Hot tier was trimmed during rotation (line 1118 in `_rotate_hot_to_warm_tier`)
  - Then trimmed AGAIN after rotation (line 1039 in `_write_shard_timeframe_to_redis`)
  - This caused data loss and created rolling gaps
- **Fix Applied**: Removed redundant ltrim at line 1039

### 2. **Pipeline Execution Race Condition**
- **Root Cause**: Early pipeline execution causing timing issues
- **Location**: `data_orchestrator.py` lines 1029-1030
- **Problem**: Pipeline executed early to get count, then reset, causing potential race conditions
- **Fix Applied**: Updated pipeline execution flow

### 3. **H1 Collection Timing Issue**
- **Root Cause**: Strict `timestamp % 3600 == 0` check
- **Location**: `config.py` `should_collect_timeframe` method
- **Problem**: If collection was delayed by even 1 second, H1 would be skipped
- **Fix Applied**: Added 60-second window for H1 collection

## Files Modified

1. `/infrastructure/fargate/data-orchestrator/src/data_orchestrator.py`
   - Backup: `data_orchestrator.py.backup_20251002_105553`
   - Changes: Removed double ltrim, fixed pipeline execution

2. `/infrastructure/fargate/data-orchestrator/src/config.py`
   - Changes: Added time window for collection (60s for H1, proportional for others)

## Deployment

To deploy these fixes:

```bash
cd /mnt/c/Users/sonia/lumisignals/infrastructure/fargate/data-orchestrator

# Review changes
git diff src/data_orchestrator.py src/config.py

# Commit changes
git add src/data_orchestrator.py src/config.py
git commit -m "CRITICAL FIX: Resolve tier rotation double-trimming and H1 timing issues

- Fixed double-trimming bug causing rolling gaps in M5 data
- Added time window for H1 collection to prevent missed intervals
- Fixed pipeline execution flow to prevent race conditions"

# Push to repository
git push lumi main

# Deploy new container
bash deploy.sh

# Or use the prepared script
bash deploy_tier_rotation_fix.sh
```

## Expected Results

1. **M5 Rolling Gap**: Should stop progressing immediately after deployment
2. **H1 Collection**: Should resume at the next hour boundary
3. **Data Integrity**: No more data loss during tier rotation

## Monitoring

After deployment, monitor:
- M5 data gap should not increase beyond the current ~11 hour gap
- H1 should collect at 15:00 UTC (next scheduled time)
- Check CloudWatch logs for successful tier rotations
- Verify no "double ltrim" operations in logs

## Recovery

The current gaps will need to be addressed separately:
- M5 gap: 2025-10-01 19:30 to 2025-10-02 06:25
- H1 gap: After 2025-10-01 23:00

These are historical gaps from the deployment window and won't be filled automatically.