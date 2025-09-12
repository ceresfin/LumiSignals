# Redis Tiered Storage Verification Guide

This guide provides comprehensive tools to verify that your Redis tiered storage system has successfully collected 500 candles for major currency pairs.

## Overview

The verification system consists of multiple scripts designed to test Redis connectivity, validate data distribution across tiers, and ensure the bootstrap collection process has worked correctly.

## Scripts and Tools

### 1. Redis Cluster Diagnostics (`redis_diagnostics.sh`)

**Purpose**: Check Redis cluster status from outside the VPC using AWS CLI.

```bash
./redis_diagnostics.sh
```

**What it checks:**
- ElastiCache cluster status
- Node health and endpoints
- Security group configuration
- VPC and subnet information
- AWS Secrets Manager credentials

### 2. Fargate Redis Test (`test_redis_from_fargate.py`)

**Purpose**: Comprehensive Redis verification from within the VPC (Fargate/EC2).

```bash
# Test basic connectivity
python3 test_redis_from_fargate.py --test-connection

# Full verification suite
python3 test_redis_from_fargate.py --full-verification --save-results

# Check specific currency pair
python3 test_redis_from_fargate.py --pair EUR_USD --timeframe M5

# Scan for keys
python3 test_redis_from_fargate.py --scan-keys "market_data:*"
```

**What it verifies:**
- Connection to all 4 Redis shards
- Hot tier data (50 candles per pair)
- Warm tier data (450 candles per pair) 
- Cold tier data (historical/bootstrap)
- Data structure integrity
- TTL settings
- Total candle counts (target: 500+ per pair)

### 3. Redis Storage Monitor (`redis_monitor.py`)

**Purpose**: Continuous monitoring of Redis storage health.

```bash
# One-time check
python3 redis_monitor.py --once

# Continuous monitoring (for sidecar container)
python3 redis_monitor.py
```

**Features:**
- Real-time metrics collection
- CloudWatch metrics integration
- Data freshness monitoring
- Storage efficiency tracking
- Anomaly detection

### 4. Simplified Verification (`verify_redis_simple.py`)

**Purpose**: Basic verification without pydantic_settings dependency.

```bash
python3 verify_redis_simple.py
```

**Use case**: Testing from local environment or when dependencies are limited.

### 5. Quick Redis Check (`run_redis_check.sh`)

**Purpose**: One-time verification task runner in AWS.

```bash
# Run verification
./run_redis_check.sh

# Run with live log following
./run_redis_check.sh --follow-logs
```

**What it does:**
- Creates and runs ECS Fargate verification task
- Uses same VPC as your data orchestrator
- Provides immediate results and logs

### 6. Deployment with Verification (`deploy_with_redis_verification.sh`)

**Purpose**: Complete deployment pipeline with automated verification.

```bash
./deploy_with_redis_verification.sh
```

**Process:**
1. Builds and pushes Docker image
2. Updates ECS service
3. Waits for deployment completion
4. Runs Redis verification task
5. Reports success/failure

## Redis Configuration

### Cluster Setup
- **Manual Sharding**: 4 Redis nodes
- **Endpoints**: 
  - `lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379`
  - `lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379`
  - `lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379`
  - `lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379`

### Authentication
- **Secret**: `lumisignals/redis/market-data/auth-token`
- **Format**: `{"auth_token":"...", "endpoint":"...", "port":6379}`

### Currency Pair Sharding
```
shard_0: EUR_USD, GBP_USD, USD_JPY, USD_CAD, AUD_USD, NZD_USD, USD_CHF
shard_1: EUR_GBP, EUR_JPY, EUR_CAD, EUR_AUD, EUR_NZD, EUR_CHF, GBP_JPY
shard_2: GBP_CAD, GBP_AUD, GBP_NZD, GBP_CHF, AUD_JPY, AUD_CAD, AUD_NZD
shard_3: AUD_CHF, NZD_JPY, NZD_CAD, NZD_CHF, CAD_JPY, CAD_CHF, CHF_JPY
```

## Tiered Storage System

### Key Patterns
```
market_data:{currency_pair}:{timeframe}:hot        # 50 most recent candles
market_data:{currency_pair}:{timeframe}:warm       # 450 older candles  
market_data:{currency_pair}:{timeframe}:historical # Bootstrap/cold data
market_data:{currency_pair}:{timeframe}:current    # Latest candle
```

### Expected Data Distribution
- **Hot Tier**: 50 candles (TTL: 1 day)
- **Warm Tier**: 450 candles (TTL: 5 days)
- **Cold Tier**: 500 candles (TTL: 7 days)
- **Total Target**: 500+ candles per major pair

### Major Currency Pairs to Verify
- EUR_USD
- GBP_USD  
- USD_JPY
- USD_CAD

## Verification Process

### Step 1: Check Infrastructure
```bash
./redis_diagnostics.sh
```
Verify that Redis clusters are running and accessible.

### Step 2: Run Quick Check
```bash
./run_redis_check.sh --follow-logs
```
Execute verification from within the VPC and follow results.

### Step 3: Interpret Results

**Success Indicators:**
- ✅ 4/4 Redis shards connected
- ✅ Major pairs have 500+ candles
- ✅ Data structure is valid JSON
- ✅ TTL settings are correct
- ✅ Overall status: PASS

**Failure Indicators:**
- ❌ Connection timeouts
- ❌ Missing auth token
- ❌ No data in tiers
- ❌ < 500 candles per pair
- ❌ Overall status: NEEDS ATTENTION

### Step 4: Troubleshooting

#### Connection Issues
```bash
# Check VPC connectivity
aws ecs describe-services --cluster lumisignals-trading-cluster --services lumisignals-data-orchestrator

# Verify auth token
aws secretsmanager get-secret-value --secret-id "lumisignals/redis/market-data/auth-token"

# Check security groups allow Redis traffic (port 6379)
```

#### Data Issues
```bash
# Check if data orchestrator is running
aws ecs describe-services --cluster lumisignals-trading-cluster --services lumisignals-data-orchestrator

# View orchestrator logs
aws logs tail /ecs/lumisignals-data-orchestrator --follow

# Manual key inspection
python3 test_redis_from_fargate.py --scan-keys "market_data:EUR_USD:*"
```

## Integration with CI/CD

### Pre-deployment Check
```bash
# Add to deployment pipeline
./run_redis_check.sh
if [ $? -eq 0 ]; then
    echo "✅ Redis verification passed - proceeding with deployment"
else
    echo "❌ Redis verification failed - stopping deployment"
    exit 1
fi
```

### Post-deployment Verification
```bash
# Include in deployment script
./deploy_with_redis_verification.sh
```

### Monitoring Integration
```bash
# Add as sidecar container
python3 redis_monitor.py
```

## CloudWatch Metrics

The monitoring system publishes these metrics to `LumiSignals/Redis` namespace:

- `Redis_PairsWithData`: Number of pairs with data
- `Redis_TotalCandles`: Total candles across all pairs
- `Redis_PairsMeetingTarget`: Pairs with 500+ candles
- `Redis_PairTotalCandles`: Per-pair candle counts

## Expected Verification Output

```
🎯 REDIS TIERED STORAGE VERIFICATION REPORT
================================================================================

📅 Verification Time: 2024-01-15T10:30:00Z

🔗 REDIS CLUSTER STATUS
   Connected Shards: 4/4
   Connection Rate: 100.0%
     ✓ shard_0: lumisignals-main-vpc-trading-shard-1-001... - connected
     ✓ shard_1: lumisignals-main-vpc-trading-shard-2-001... - connected
     ✓ shard_2: lumisignals-main-vpc-trading-shard-3-001... - connected
     ✓ shard_3: lumisignals-main-vpc-trading-shard-4-001... - connected

📊 DATA DISTRIBUTION SUMMARY
   Pairs Tested: 4
   Pairs with Data: 4
   Total Candles: 2,000
   Pairs Meeting 500+ Target: 4
   Average Candles per Pair: 500.0

📈 DETAILED PAIR ANALYSIS
   ✓ EUR_USD_M5:
      Shard: shard_0
      Total Candles: 500
        HOT: 50 candles (TTL: 86400s)
        WARM: 450 candles (TTL: 432000s)
        COLD: 500 candles (TTL: 604800s)

✅ COMPLIANCE STATUS
   ✓ Cluster Connectivity: True
   ✓ Data Availability: True
   ✓ Target Collection: True

✅ OVERALL STATUS: PASS
```

## Support and Troubleshooting

### Common Issues

1. **Connection Timeouts**: Ensure scripts run from within VPC
2. **Auth Failures**: Verify Secrets Manager permissions
3. **Missing Data**: Check data orchestrator logs and OANDA connection
4. **Partial Data**: Bootstrap process may still be running

### Getting Help

1. Check logs: `aws logs tail /ecs/lumisignals-data-orchestrator --follow`
2. Verify service: `aws ecs describe-services --cluster lumisignals-trading-cluster --services lumisignals-data-orchestrator`
3. Manual verification: `./run_redis_check.sh --follow-logs`

This verification system ensures your Redis tiered storage is working correctly and maintaining the required 500 candles for optimal trading strategy performance.