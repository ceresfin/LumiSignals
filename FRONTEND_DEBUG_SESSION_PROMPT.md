# LumiSignals Frontend Debug Session - Comprehensive Continuation Prompt

## 🎯 **Session Objective**
Debug and ensure data accuracy across the momentum dashboard frontend, specifically focusing on trade data consistency between RDS backend and frontend display components.

## 📊 **Current System Status (September 12, 2025)**

### ✅ **What's Working**
- **Data Orchestrator**: TD 207 deployed with 500-candle tiered storage system
- **Charts**: TradingView chart disposal race condition fixed - Momentum Grid loads properly
- **API Endpoints**: Direct Candlestick API serving 500 candles from Redis tiers
- **Backend**: RDS PostgreSQL has active trade data (3 trades confirmed)

### 🔍 **Areas Requiring Debug**

#### **1. Momentum Grid Trade Cards** 
**Location**: `Momentum Grid` tab → Individual currency pair trade cards
**Issues to Verify**:
- Trade card data accuracy vs. actual RDS data
- P&L calculations and pip movements
- Entry/exit prices and current positions
- Duration calculations
- Strategy name displays

**Current State**: 3 active trades showing:
1. USD/CAD Short 2050 units, Entry: 1.38311, P&L: -2.128, Pips: -10.4
2. EUR/GBP Short 2000 units, Entry: 0.86434, P&L: -2.5357, Pips: -12.7  
3. GBP/USD Short 2000 units, Entry: 1.35492, P&L: -3.32, Pips: -16.6

#### **2. Portfolio & Risk Tab**
**Location**: Main navigation → `Portfolio & Risk` tab
**Issues to Debug**:
- Overall portfolio metrics accuracy
- Risk calculations vs. actual open positions
- Account balance and equity displays
- Margin utilization calculations
- Aggregate P&L summaries

**Data Source**: Should pull from RDS PostgreSQL via active-trades API

#### **3. Live RDS Portfolio Tab**
**Location**: Main navigation → `Live RDS Portfolio` tab  
**Issues to Debug**:
- Direct RDS data display accuracy
- Real-time data updates
- Trade lifecycle status accuracy
- Database query performance
- Data freshness indicators

## 🔧 **Key Files & Components to Examine**

### **Frontend Components**
```
/mnt/c/Users/sonia/LumiSignals/infrastructure/terraform/momentum-dashboard/src/
├── components/
│   ├── charts/CurrencyPairGraphsWithTrades.tsx     # Momentum Grid trade cards
│   ├── portfolio/                                  # Portfolio & Risk components  
│   └── trades/                                     # Trade display components
├── hooks/
│   ├── useMomentumRanking.ts                      # Trade data processing logic
│   └── useActiveTradeData.ts                      # RDS data fetching
├── services/
│   └── api.ts                                     # API calls to RDS endpoints
└── App.tsx                                        # Main tab navigation
```

### **API Endpoints to Test**
```bash
# Active Trades API (Primary Data Source)
GET https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/active-trades

# Portfolio Summary API  
GET https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/portfolio-summary

# Account Info API
GET https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/account-info
```

### **Database Verification Commands**
```sql
-- Connect to RDS PostgreSQL to verify trade data
SELECT 
    trade_id,
    instrument,
    units,
    entry_price,
    current_price,
    unrealized_pnl,
    pips_moved,
    strategy_name,
    open_time,
    direction
FROM active_trades 
ORDER BY open_time DESC;

-- Portfolio summary verification
SELECT 
    account_balance,
    total_unrealized_pnl,
    margin_used,
    margin_available,
    equity
FROM account_summary 
ORDER BY timestamp DESC 
LIMIT 1;
```

## 🧪 **Debug Strategy & Testing Plan**

### **Phase 1: Data Source Verification**
1. **Test RDS API endpoints** directly via curl/Postman
2. **Compare API responses** to what frontend displays
3. **Verify database queries** return expected data
4. **Check data transformation** logic in frontend hooks

### **Phase 2: Frontend Component Analysis**
1. **Momentum Grid**: Inspect trade card data binding
2. **Portfolio & Risk**: Verify portfolio calculation logic  
3. **Live RDS Portfolio**: Check real-time data updates
4. **Cross-tab consistency**: Ensure same data displays identically

### **Phase 3: Data Flow Debugging**
1. **API → Hook → Component** data flow tracing
2. **Browser DevTools** network tab analysis
3. **Console logging** of data transformations
4. **State management** verification (if using React Context/Redux)

## 🔍 **Known Issues & Investigation Points**

### **Potential Data Accuracy Issues**
- **Currency Conversion**: Ensure pip calculations account for JPY pairs vs. non-JPY pairs
- **Time Zones**: Verify trade duration calculations use consistent timezone (UTC vs. local)
- **Precision**: Check decimal precision for prices and P&L (2 vs. 4 vs. 5 decimal places)
- **Real-time Updates**: Verify data refresh intervals and caching behavior

### **Frontend State Management Issues**
- **Stale Data**: Components showing cached/outdated information
- **Race Conditions**: Multiple API calls overwriting each other
- **Error Handling**: Failed API calls not properly handled
- **Loading States**: Incomplete data displayed during loading

### **RDS Integration Issues**
- **Database Connection**: PostgreSQL connection stability
- **Query Performance**: Slow queries affecting UX
- **Data Synchronization**: RDS vs. Redis data consistency
- **Transaction Isolation**: Concurrent read/write issues

## 🛠️ **Debug Tools & Commands**

### **Frontend Debugging**
```javascript
// Console debugging in browser DevTools
console.log('Trade data from API:', tradeData);
console.log('Processed trade cards:', processedTrades);
console.log('Portfolio calculations:', portfolioMetrics);

// Network tab filtering
// Filter by: 6oot32ybz4.execute-api.us-east-1.amazonaws.com
// Look for: active-trades, portfolio-summary, account-info requests
```

### **API Testing Commands**  
```bash
# Test active trades API
curl -s "https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/active-trades" | jq .

# Test portfolio summary
curl -s "https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/portfolio-summary" | jq .

# Test account info
curl -s "https://6oot32ybz4.execute-api.us-east-1.amazonaws.com/prod/account-info" | jq .
```

### **Database Direct Access**
```bash
# Connect to RDS PostgreSQL (requires AWS credentials)
aws rds describe-db-instances --query 'DBInstances[?DBName==`lumisignals`]'

# Use database connection details to connect via psql
# psql -h [RDS_ENDPOINT] -U [USERNAME] -d lumisignals
```

## 📋 **Debugging Checklist**

### **Momentum Grid Trade Cards**
- [ ] Verify trade count matches RDS query results
- [ ] Check individual trade P&L calculations  
- [ ] Validate pip movement calculations
- [ ] Confirm entry price accuracy
- [ ] Test current price updates
- [ ] Verify trade duration displays
- [ ] Check strategy name mappings

### **Portfolio & Risk Tab**
- [ ] Overall portfolio balance accuracy
- [ ] Total P&L calculation verification
- [ ] Margin utilization displays
- [ ] Risk metrics calculations
- [ ] Account equity calculations
- [ ] Performance indicators accuracy

### **Live RDS Portfolio Tab**
- [ ] Real-time data refresh functionality
- [ ] Database connection status
- [ ] Query execution time optimization  
- [ ] Error handling for failed queries
- [ ] Data freshness timestamps
- [ ] Raw vs. formatted data display

### **Cross-Component Consistency**
- [ ] Same trade shows identical data across tabs
- [ ] Portfolio totals consistent across components
- [ ] Time synchronization across all displays
- [ ] Currency formatting consistency
- [ ] Precision consistency (decimal places)

## 🚀 **Success Criteria**

### **Data Accuracy**
✅ Frontend trade cards exactly match RDS database entries  
✅ Portfolio calculations verified against actual account balances  
✅ Real-time updates working within acceptable latency (< 30 seconds)  
✅ All three tabs show consistent, accurate financial data

### **User Experience**  
✅ No console errors or failed API requests  
✅ Loading states handled gracefully  
✅ Error messages displayed for failed operations  
✅ Data refreshes without requiring manual page reload

### **Performance**
✅ API responses under 2 seconds  
✅ Database queries optimized for sub-second execution  
✅ Frontend rendering smooth without lag  
✅ Memory usage stable during extended use

## 📝 **Session Continuation Instructions**

**To resume this debug session:**

1. **Start with API verification**: Test all three RDS endpoints and document response structures
2. **Compare with database**: Run direct SQL queries to verify API data accuracy  
3. **Trace frontend data flow**: Follow data from API response → hooks → components → display
4. **Use browser DevTools**: Network tab, Console, and React DevTools for component inspection
5. **Document discrepancies**: Any differences between expected vs. actual data display
6. **Implement fixes**: Based on identified data accuracy issues

**Priority Order:**
1. Momentum Grid trade card accuracy (highest impact)
2. Portfolio & Risk tab calculations  
3. Live RDS Portfolio real-time updates
4. Cross-component data consistency

---

**Last Updated**: September 12, 2025  
**System Status**: Charts fixed, backend stable, ready for frontend data accuracy debugging  
**Next Session Focus**: RDS data accuracy verification and frontend component debugging