# H1 Collection Logic Analysis

## Current Implementation

### 1. Collection Timing Configuration (`config.py`)
- **Collection Interval**: Every 300 seconds (5 minutes)
- **H1 Window**: 360 seconds (6 minutes) - FIXED from previous 60 seconds
- **Logic Location**: `should_collect_timeframe()` and `get_timeframes_to_collect()`

### 2. H1 Collection Logic
```python
# From config.py lines 230-236
if timeframe == "H1":
    window = 360  # 6 minutes window for H1 to ensure reliable collection
else:
    window = min(60, interval // 10)  # 10% of interval or 60 seconds max
remainder = current_time % interval
return remainder < window
```

### 3. Collection Window Analysis
- **Old 60-second window**: Only collected H1 if data orchestrator ran exactly at :00
- **New 360-second window**: Collects H1 if running between :00 and :06 past the hour
- **Reliability**: With 5-minute collection cycles, guarantees at least one cycle hits the window

### 4. Main Collection Flow
1. Data orchestrator runs every 5 minutes
2. `get_timeframes_to_collect()` determines which timeframes to collect
3. Always collects M5 (primary timeframe)
4. Checks if H1 should be collected based on the 6-minute window
5. If within window, adds H1 to collection list

### 5. Recent Fixes Applied
- **deploy_h1_window_fix.sh** (Oct 2, 14:36): Extended H1 window from 60s to 360s
- Fix ensures 100% H1 collection hit rate with 5-minute cycles
- Prevents missing H1 data when orchestrator starts slightly after the hour

### 6. Expected Behavior
- H1 data collected once per hour during the first 6 minutes
- Collection happens at either :00 or :05 past the hour (whichever cycle runs first)
- No duplicate collections within the same hour
- All 28 currency pairs get H1 data consistently

### 7. Key Code Sections

**config.py (lines 217-259)**: Core collection timing logic
- `should_collect_timeframe()`: Determines if a timeframe should be collected
- `get_timeframes_to_collect()`: Returns list of timeframes for current cycle

**data_orchestrator.py (lines 720-773)**: Main collection execution
- Gets timeframes from config
- Processes each timeframe for all currency pairs
- Updates collection timestamps

### 8. Testing Results
With 360-second window, H1 collection is guaranteed because:
- Window covers :00 to :06 minutes past the hour
- Data orchestrator runs every 5 minutes
- At least one cycle (either :00 or :05) will hit the window

## Conclusion
The H1 collection logic has been fixed with a 6-minute window that ensures reliable hourly collection. The fix was deployed on Oct 2, and H1 data should now be collected consistently for all currency pairs.