# Debugging Chart Remounting and Re-rendering Issue

## Problem Statement
The charts in the 'graphs' tab of pipstop.org were mounting 4 times instead of once, causing performance issues and visual flickering. This led to discovering a much larger infinite re-rendering problem.

## Timeline of Debugging Attempts

### 1. Initial Issue: Charts Mounting 4 Times
**Problem**: Each chart component was mounting 4 times instead of once.
**Initial Hypothesis**: Unnecessary re-renders in parent component.

### 2. First Attempt: React.memo Enhancement
**Action**: Enhanced React.memo comparison to prevent re-renders
```javascript
// Added array comparison helper
const areArraysEqual = (a: any[], b: any[]): boolean => {
  if (a.length !== b.length) return false;
  return a.every((item, index) => item === b[index]);
};
```
**Result**: No improvement - still 4 mounts

### 3. Second Attempt: Reduce Active Trades API Calls
**Action**: Changed active trades refresh from 30 seconds to 15 minutes
```javascript
// Before: const interval = setInterval(fetchActiveTrades, 30000);
// After: const interval = setInterval(fetchActiveTrades, 900000);
```
**Result**: Reduced network traffic but still 4 mounts

### 4. Third Attempt: Memoize Graphs Component
**Action**: Memoized the graphs component in App.tsx
```javascript
const graphsComponent = useMemo(() => (
  <CurrencyPairGraphsWithTrades timeframe="H1" chartHeight={400} />
), []); // Empty deps - component never changes
```
**Result**: Still 4 mounts

### 5. Discovery #1: Missing useRef Import
**Action**: Added comprehensive logging to track mount/unmount patterns
**Result**: App crashed with black screen - forgot to import useRef
**Learning**: Simple logging without hooks is safer for debugging

### 6. Major Discovery: Not 4 Mounts, but 49+ Renders!
**Action**: Added simple console logging
**Finding**: 
- Not just 4 mounts, but 49+ parent component renders
- Infinite re-rendering loop discovered
- Each render was causing child components to remount

### 7. Fourth Attempt: State Batching with startTransition
**Action**: Batched state updates using React's startTransition
```javascript
startTransition(() => {
  setAllActiveTrades(response.data);
  setAvailableStrategies(strategies);
  setLoading(false);
});
```
**Result**: Improved from 4 mounts to 3 mounts, but still had issues

### 8. Discovery #2: OANDA API Calls During Debug
**Finding**: Debug code was making OANDA API calls on every chart mount
```javascript
// This was running for each chart mount:
const response = await api.getCandlestickData(currencyPair, timeframe, 500);
```
**Action**: Disabled auto-refresh interval but kept initial data fetch
**Result**: Charts stopped loading entirely

### 9. Fifth Attempt: Re-enable Data Fetch with Staggering
**Action**: Kept staggered initial fetch but disabled 5-minute refresh interval
```javascript
// Kept: const randomDelay = Math.random() * 2000;
// Disabled: const interval = setInterval(() => fetchCandlestickData(), refreshInterval);
```
**Result**: Charts loading but still multiple parent renders

### 10. Discovery #3: 29 Parent Renders = 1 Initial + 28 Currency Pairs
**Finding**: Parent component was re-rendering once for each currency pair
**Hypothesis**: Each chart's data load was triggering parent re-render

### 11. Sixth Attempt: Fix userInteractedCharts Set Recreation
**Action**: Only create new Set if currency pair isn't already tracked
```javascript
setUserInteractedCharts(prev => {
  if (prev.has(currencyPair)) {
    return prev; // Return same Set if currency pair already exists
  }
  return new Set(prev).add(currencyPair); // Only create new Set if needed
});
```
**Result**: No improvement - still ~29 parent renders

### 12. Seventh Attempt: Memoize Filtered Trades
**Action**: Memoized filtered trades to prevent new arrays on every render
```javascript
const filteredTradesByPair = useMemo(() => {
  const tradesByPair: Record<string, any[]> = {};
  sortedPairs.forEach(pair => {
    tradesByPair[pair] = allActiveTrades.filter((trade: any) => trade.instrument === pair);
  });
  return tradesByPair;
}, [sortedPairs, allActiveTrades]);
```
**Result**: Still no improvement

### 13. Enhanced Debugging: Track Object Reference Changes
**Action**: Added detailed logging to track which objects were changing
```javascript
Object.keys(currentRefs).forEach(key => {
  if (prevRefs.current[key] !== currentRefs[key as keyof typeof currentRefs]) {
    console.log(`🔄 REFERENCE CHANGED: ${key} (render #${renderCount.current})`);
  }
});
```
**Finding**: `userInteractedCharts` was changing on EVERY render after #3

### 14. Discovery #4: Chart Event Handlers Triggering False Interactions
**Finding**: Chart library's `subscribeVisibleTimeRangeChange` was firing during data load
**Root Cause**: When candlestick data loaded, chart view updates triggered "user interaction" callbacks

### 15. Final Fix: Debounce and Filter Real User Interactions
**Action**: Only track actual user interactions, not programmatic updates
```javascript
// Only trigger if chart has been rendered for more than 2 seconds
// This prevents false triggers during initial data load
if (Date.now() - chartCreatedTime > 2000) {
  handleInteraction();
}
```

### 16. Bonus Discovery: OANDA Nanosecond Timestamps
**Finding**: OANDA timestamps with nanosecond precision were causing React to see data as "different"
**Action**: Implemented timeframe-aware timestamp normalization
```javascript
switch(timeframe) {
  case 'H1':
    date.setMinutes(0, 0, 0); // Force to :00:00.000
    break;
  // ... other timeframes
}
```

## Final Results
- Parent renders reduced from **29+ to 2**
- Chart mounts reduced from **4 to 1**
- Active trades API calls reduced from **every 30 seconds to every 15 minutes**
- Eliminated infinite re-rendering loop
- Charts now stable without flickering

## Key Learnings
1. **What looks like a mounting issue might be a re-rendering issue** - Initial "4 mounts" was actually a symptom of 49+ parent re-renders
2. **Debug code can cause production issues** - OANDA API calls left in for debugging were causing cascading re-renders
3. **React's object reference equality is strict** - Creating new arrays/Sets on every render causes re-renders
4. **Chart libraries can trigger false events** - TradingView's event handlers fired during programmatic updates
5. **Timestamp precision matters** - Nanosecond differences can cause React to re-render
6. **State batching is important** - Multiple setState calls should be batched to prevent cascading renders

## Technical Debt Identified
1. Large bundle sizes (charts bundle is 585KB)
2. Need to implement lazy loading for charts
3. Need to add timeframe dropdown for different intervals
4. 175 duplicate timestamps in EUR_USD data need investigation