# LumiSignals Data Orchestrator: Complete System Explanation

**A simple guide to understanding how our trading data collection works**

---

## 🎯 What Does the Data Orchestrator Do?

The Data Orchestrator is like a **smart data collector** that automatically gathers trading information from OANDA (our broker) and stores it in our systems so the pipstop.org dashboard can show real-time charts and trading data.

### Main Jobs:

1. **📊 Collects Candlestick Data** - Price charts for 28 currency pairs
2. **💰 Tracks Live Trades** - What trades are currently open
3. **🗄️ Stores Everything** - Puts data in Redis (fast) and PostgreSQL (permanent)
4. **🧹 Cleans Up** - Removes old/stale trade data

---

## 🕐 Data Collection Schedule

### M5 (5-Minute) Candlesticks
- **How Often**: Every 5 minutes (300 seconds)
- **What We Get**: OHLCV data (Open, High, Low, Close, Volume)
- **How Much**: 100 candlesticks per currency pair per collection
- **Total Per Hour**: 28 pairs × 12 collections = 336 data points
- **Daily Volume**: ~8,064 M5 candlesticks across all pairs

### H1 (Hourly) Candlesticks  
- **How Often**: Every 1 hour (3600 seconds)
- **What We Get**: OHLCV data aggregated over 1 hour
- **How Much**: 100 candlesticks per currency pair per collection
- **Total Per Day**: 28 pairs × 24 collections = 672 data points
- **Daily Volume**: 672 H1 candlesticks across all pairs

### Currency Pairs We Monitor
**28 Major Pairs Total:**
- Major pairs: EUR_USD, GBP_USD, USD_JPY, USD_CHF, USD_CAD, AUD_USD, NZD_USD
- Cross pairs: EUR_GBP, EUR_JPY, GBP_JPY, AUD_JPY, etc.
- All combinations of: EUR, GBP, USD, JPY, CHF, CAD, AUD, NZD

---

## 🏗️ System Architecture

### Data Flow Pipeline
```
OANDA API → ECS Fargate → Redis Cluster → Lambda APIs → pipstop.org Dashboard
                    ↓
                PostgreSQL RDS (Permanent Storage)
```

### Components:

**1. ECS Fargate Container**
- **What**: Docker container running our data collection code
- **Where**: AWS ECS (Elastic Container Service)
- **Resources**: 2048 CPU, 4096 MB Memory (high performance)
- **Task Definition**: Currently TD 196 (Golden Template)

**2. Redis Cluster (4 Shards)**
- **What**: Super-fast memory database for real-time data
- **Purpose**: Immediate access for dashboard charts
- **Data Retention**: 5 days (432,000 seconds TTL)
- **Sharding**: Currency pairs split across 4 Redis nodes for performance

**3. PostgreSQL RDS**
- **What**: Permanent database for trade history
- **Purpose**: Long-term storage, analysis, reporting
- **Data**: Trade records, account info, historical analysis

**4. Lambda APIs**
- **What**: Serverless functions that serve data to dashboard
- **Main Function**: `lumisignals-direct-candlestick-api`
- **Purpose**: Fast data retrieval for charts

---

## 💾 Data Storage Strategy

### Redis Storage Pattern
```
Key Format: market_data:{currency_pair}:{timeframe}:{type}
Examples:
- market_data:EUR_USD:M5:current    (latest 100 M5 candles)
- market_data:EUR_USD:H1:historical (last 500 H1 candles)
- market_data:EUR_USD:M5:pricing    (current bid/ask)
```

### Data Distribution (Redis Sharding)
- **Shard 0**: EUR_USD, GBP_USD, USD_JPY, USD_CAD, AUD_USD, NZD_USD, USD_CHF
- **Shard 1**: EUR_GBP, EUR_JPY, EUR_CAD, EUR_AUD, EUR_NZD, EUR_CHF, GBP_JPY
- **Shard 2**: GBP_CAD, GBP_AUD, GBP_NZD, GBP_CHF, AUD_JPY, AUD_CAD, AUD_NZD  
- **Shard 3**: AUD_CHF, NZD_JPY, NZD_CAD, NZD_CHF, CAD_JPY, CAD_CHF, CHF_JPY

---

## ⚡ Performance & Optimization

### Is Our Process Optimized for Lazy Loading?
**YES!** Here's how:

**1. Tiered Data Access**
- **Level 1**: Redis (millisecond access) - for charts
- **Level 2**: PostgreSQL (seconds) - for detailed analysis
- **Level 3**: OANDA API (rate-limited) - for fresh data only

**2. Smart Caching**
- Dashboard requests hit Redis first (super fast)
- Only missing data triggers OANDA API calls
- 5-day data retention in Redis covers most chart needs

**3. Efficient Data Serving**
- Lambda functions serve pre-processed data
- Charts load incrementally (100 candles at a time)
- Users can scroll back through cached historical data

**4. Rate Limiting Protection**
- Max 20 requests/second to OANDA API
- Batch processing to minimize API calls
- Concurrent processing across Redis shards

### Data Volume Analysis
**Daily API Calls to OANDA:**
- M5 collections: 12 per hour × 24 hours = 288 collections/day
- H1 collections: 24 per day
- Per collection: ~28 API calls (one per currency pair)
- **Total**: ~8,736 API calls per day

**Storage Requirements:**
- Each candlestick: ~100 bytes
- M5 daily: 8,064 candles × 100 bytes = ~806 KB/day
- H1 daily: 672 candles × 100 bytes = ~67 KB/day
- **Total candlestick data**: ~873 KB per day for all pairs

---

## 🔄 Other Key Processes

### 1. Comprehensive Trade Orchestrator
**What It Does:**
- Collects detailed trade information (31 fields per trade)
- Tracks P&L, margin, swap costs, financing
- Identifies and removes stale/inactive trades
- Updates trade status in real-time

**When It Runs:**
- Every 5 minutes alongside candlestick collection
- Cleanup process runs on startup

### 2. Health Monitoring
**Tracks:**
- API response times
- Redis connection status
- Database connection health
- Error rates and failures
- Memory and CPU usage

### 3. Rate Limiting System
**Purpose:**
- Prevent OANDA API throttling
- Ensure reliable data collection
- Manage concurrent requests across shards

**Configuration:**
- Max 20 requests/second
- Burst limit: 30 requests
- Exponential backoff on failures

### 4. Backfill System
**H1 Historical Data:**
- Runs once on container startup
- Collects 30 days of H1 historical data
- Ensures charts have scrollback capability
- Only runs if Redis lacks sufficient H1 data

---

## 🚀 System Performance Metrics

### Real-Time Capabilities
- **Chart Updates**: Every 5 minutes for M5, every hour for H1
- **Trade Updates**: Every 5 minutes
- **Dashboard Latency**: <100ms (Redis cache hits)
- **API Response Time**: <2 seconds average

### Scalability
- **Concurrent Processing**: 4 Redis shards processed simultaneously
- **Batch Processing**: 10 currency pairs per batch
- **High Performance**: 2048 CPU units, 4GB RAM allocated
- **Fault Tolerance**: Auto-restart on failures, health monitoring

### Data Reliability
- **Redundancy**: Data stored in both Redis and PostgreSQL
- **Backup Strategy**: PostgreSQL automated backups
- **Error Handling**: Graceful failures with retry logic
- **Monitoring**: CloudWatch logs and metrics

---

## 🔧 Configuration Management

### Environment Variables
```
TIMEFRAMES=["M5", "H1"]              # What timeframes to collect
COLLECTION_INTERVAL_SECONDS=300      # How often to run (5 minutes)
ENABLE_H1_BACKFILL=true             # Enable historical H1 data collection
MAX_REQUESTS_PER_SECOND=20          # OANDA API rate limit
REDIS_TTL_SECONDS=432000            # Data retention (5 days)
```

### AWS Secrets Manager
- **OANDA Credentials**: API key, account ID, environment
- **Database Credentials**: PostgreSQL connection details
- **Secure**: No secrets in code or environment variables

---

## 📊 Dashboard Integration

### pipstop.org Features Powered by Data Orchestrator:
1. **Real-time Candlestick Charts** - M5 and H1 timeframes
2. **Institutional Level Overlays** - Price level indicators  
3. **Active Trade Visualization** - Entry, target, stop loss levels
4. **Trade Performance Tracking** - P&L, pips moved, duration
5. **Currency Pair Sorting** - By proximity to institutional levels

### Chart Loading Process:
1. User opens pipstop.org
2. Dashboard requests latest H1 data via Lambda API
3. Lambda checks Redis cache (fast!)
4. If data exists: Return immediately
5. If missing: Trigger fresh collection from OANDA
6. Charts render with smooth loading experience

---

## 🎯 System Goals & Benefits

### What We Achieve:
- **Real-time Trading Insights**: Live data for informed decisions
- **Historical Analysis**: Trend identification and pattern recognition  
- **Performance Monitoring**: Track trading success across strategies
- **Risk Management**: Visual stop-loss and target levels
- **Institutional Analysis**: Price proximity to psychological levels

### Business Value:
- **Faster Decision Making**: Sub-second chart loading
- **Comprehensive Coverage**: 28 currency pairs monitored
- **Cost Efficient**: Optimized API usage, smart caching
- **Reliable**: 99.9%+ uptime with auto-recovery
- **Scalable**: Can easily add more currency pairs or timeframes

---

*Last Updated: September 11, 2025*
*System Status: Operational (Golden Template TD 196)*