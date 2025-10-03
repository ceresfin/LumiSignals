# LumiSignals Analytics Development Methodology

## Table of Contents
1. [Core Development Principles](#core-development-principles)
2. [Function Architecture & Anti-Patterns](#function-architecture--anti-patterns)
3. [Redis Infrastructure & Data Management](#redis-infrastructure--data-management)
4. [Dependencies & Environment Management](#dependencies--environment-management)
5. [Git Workflow & Version Control](#git-workflow--version-control)
6. [Deployment & Testing Strategy](#deployment--testing-strategy)
7. [Error Handling & Debugging Framework](#error-handling--debugging-framework)
8. [Trade Setup Generation Standards](#trade-setup-generation-standards)
9. [Data Format Standards](#data-format-standards)
10. [Documentation & Knowledge Transfer](#documentation--knowledge-transfer)

---

## Core Development Principles

### 1. Single Responsibility Functions
- **ONE main analytics function per analysis type** (e.g., `generate_pair_analytics()`)
- **ALWAYS enhance existing functions** rather than creating duplicates
- Use parameters to extend functionality, not new function names

### 2. No Function Proliferation
**❌ NEVER DO THIS:**
```python
def analyze_fibonacci_basic()
def analyze_fibonacci_enhanced()  
def analyze_fibonacci_with_confluence()
def analyze_fibonacci_tiered()  # Creates broken fallback chains
```

**✅ ALWAYS DO THIS:**
```python
def analyze_fibonacci_levels(instrument: str, timeframe: str = 'H1', 
                           include_confluence: bool = False,
                           institutional_levels: Dict = None,
                           mode: str = 'adaptive') -> Dict[str, Any]:
    # Single function with configurable parameters
```

### 3. Git-Based Versioning
- Use Git commits for version control, **not function name versioning**
- Create meaningful commit messages describing functional changes
- Use branches for experimental features, merge when stable

---

## Function Architecture & Anti-Patterns

### Main Analytics Function Pattern
```python
def generate_pair_analytics(instrument: str, timeframe: str = 'H1', 
                          include_confluence: bool = False,
                          institutional_levels: Dict = None,
                          include_trade_setups: bool = True) -> Dict[str, Any]:
    """
    Single centralized analytics function for all pair analysis
    
    Args:
        instrument: Currency pair (e.g., 'EUR_USD')
        timeframe: Analysis timeframe ('M5', 'H1', 'H4', 'D1')
        include_confluence: Add confluence analysis from multiple sources
        institutional_levels: Supply/demand institutional level data
        include_trade_setups: Generate actionable trade setups
    
    Returns:
        Complete analytics package with standardized structure
    """
```

### Anti-Pattern: Fallback Chains
**Problem Experienced:**
```python
try:
    return analyze_fibonacci_enhanced(...)
except:
    return analyze_fibonacci_tiered(...)  # Falls back to broken function!
```

**Solution:**
- Validate inputs and handle errors within the main function
- Use feature flags, not fallback functions
- If a feature isn't ready, return structured error messages

### Enhancement Strategy
When adding new features:
1. **Extend existing function parameters**
2. **Add feature flags for optional functionality**
3. **Maintain backward compatibility**
4. **Update tests for new parameters**

---

## Redis Infrastructure & Data Management

### Connection Architecture
```python
# Sharded Redis cluster configuration
REDIS_NODES = [
    "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
    "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
]

# Instrument-based sharding (matches Fargate data collection)
SHARD_MAPPING = {
    # Shard 0: Major USD pairs
    "EUR_USD": 0, "GBP_USD": 0, "USD_JPY": 0, "USD_CAD": 0,
    # Shard 1: EUR cross pairs + GBP_JPY  
    "EUR_GBP": 1, "EUR_JPY": 1, "EUR_CAD": 1, "GBP_JPY": 1,
    # Shard 2: GBP and AUD cross pairs
    "GBP_CAD": 2, "GBP_AUD": 2, "AUD_JPY": 2, "AUD_CAD": 2,
    # Shard 3: Remaining cross pairs
    "AUD_CHF": 3, "NZD_JPY": 3, "CAD_JPY": 3, "CHF_JPY": 3
}
```

### Data Key Patterns
```python
# Tiered storage pattern (hot/warm/cold)
hot_key = f"market_data:{instrument}:{timeframe}:hot"      # Latest ~200 candles
warm_key = f"market_data:{instrument}:{timeframe}:warm"    # Previous ~300 candles  
cold_key = f"market_data:{instrument}:{timeframe}:historical"  # Archive data
pricing_key = f"market_data:{instrument}:pricing:current"  # Real-time price

# Working timeframes (confirmed data availability)
AVAILABLE_TIMEFRAMES = ['M5', 'H1']  # Redis contains 500 candles each
MISSING_TIMEFRAMES = ['M1', 'M15', 'H4', 'D1']  # Not collected by data pipeline
```

### Redis Connection Best Practices
```python
def get_redis_client_for_instrument(instrument: str):
    """Get correct Redis client based on instrument sharding"""
    if not redis_connections:
        init_redis_connections()
    
    shard_id = SHARD_MAPPING.get(instrument, 0)
    return redis_connections.get(shard_id)

# Connection settings for stability
redis.Redis(
    host=host, port=int(port),
    decode_responses=False,  # Keep as bytes for JSON parsing
    socket_connect_timeout=30,
    socket_timeout=30,
    retry_on_timeout=True,
    health_check_interval=30
)
```

### Security Group Requirements
**Lambda Security Group:**
- Outbound TCP 6379 (Redis) ✅
- Deployed in same VPC as Redis cluster ✅

**Redis Security Group:**  
- Inbound TCP 6379 from Lambda Security Group ✅
- Same VPC/subnet configuration ✅

### Data Format Standards
```python
# Redis candle data format (LIST storage)
{
    'h': float,     # high price
    'l': float,     # low price  
    'c': float,     # close price
    'o': float,     # open price
    'time': str     # timestamp
}

# Lambda analysis format (converted)
{
    'high': float,
    'low': float,
    'close': float, 
    'open': float,
    'timestamp': str
}
```

---

## Dependencies & Environment Management

### Critical Dependencies
```python
# Core Lambda dependencies (verified working)
import redis==6.4.0          # Redis cluster connectivity
import numpy                 # From complete_package/ (22.3MB)
import pytz                  # Timezone handling for timeframes
import boto3                 # AWS services
import json                  # Data parsing
import logging               # Error tracking

# Trading Core Module
from lumisignals_trading_core.fibonacci.improved_fibonacci_analysis import analyze_fibonacci_levels
from lumisignals_trading_core.fibonacci.timeframe_config import get_timeframe_config
```

### Deployment Package Structure
```
lambda_deployment.zip
├── lambda_function.py                 # Main Lambda handler
├── fibonacci_strategy_naming.py       # Trade setup naming
├── redis/                            # Redis client module
├── pytz/                             # Timezone data
├── numpy/                            # From complete_package/
├── numpy.libs/                       # NumPy binary dependencies
└── lumisignals_trading_core/         # Custom trading analysis
    ├── fibonacci/
    ├── swing/
    └── timeframe/
```

### Import Error Prevention
```python
# Validate all imports with specific error handling
try:
    from lumisignals_trading_core.fibonacci.improved_fibonacci_analysis import analyze_fibonacci_levels
except ImportError as e:
    logger.error(f"Trading core import failed: {e}")
    raise Exception(f"Fibonacci analysis unavailable - import error: {str(e)}")
```

---

## Git Workflow & Version Control

### Commit Strategy
- **Feature commits:** `feat: Add confluence analysis to Fibonacci setups`
- **Bug fixes:** `fix: Resolve institutional_levels undefined variable`  
- **Integration:** `FEAT: Integrate Fixed-mode Fibonacci analysis into pipstop.org graphs`
- **Major changes:** `MAJOR: Fixed-mode-only Fibonacci analysis with accurate structural levels`

### Before Major Changes
```bash
# Always save current state before significant modifications
git add .
git commit -m "SAVE: Preserve working state before function consolidation

- analyze_fibonacci_levels_improved() working correctly
- Dependencies: numpy, pytz, redis all functional  
- 28 pairs generating trade setups with 500 candles each
- M5/H1 timeframes confirmed working"
```

### Function Preservation Strategy
When replacing or consolidating functions, **NEVER delete old working functions immediately**. Instead:

#### 1. Archive Working Functions in Git
```bash
# Create archive branch before removing functions
git checkout -b archive/analyze-fibonacci-tiered
git add .
git commit -m "ARCHIVE: Preserve analyze_fibonacci_tiered() before removal

Function details:
- Last working version of analyze_fibonacci_tiered()
- Working parameters and configuration
- Dependencies: numpy 1.26.4, trading core v1.2
- Performance: 500 candles, 0.85s response time
- Known issues: None in M5/H1 timeframes

Reason for archival: Consolidating into analyze_fibonacci_levels()
Replacement commit: [will update when merged]"

# Return to main development
git checkout main
```

#### 2. Comment Out (Don't Delete) Before Testing
```python
# Keep old function commented for quick revert
def generate_pair_analytics_with_setups(instrument: str, timeframe: str) -> Dict:
    """
    ARCHIVED 2025-09-23: Consolidated into generate_pair_analytics()
    Archive branch: archive/pair-analytics-with-setups
    Commit: abc123def456
    
    Kept for reference - had good confluence logic that was merged
    """
    pass  # Implementation moved to generate_pair_analytics()

# New consolidated function
def generate_pair_analytics(instrument: str, timeframe: str = 'H1', 
                          include_confluence: bool = False) -> Dict:
    # Enhanced version with all functionality
    pass
```

#### 3. Archive Branch Naming Convention
```bash
archive/function-name-date          # For individual functions
archive/fibonacci-analysis-sept2025 # For entire modules  
archive/working-state-before-refactor  # For major changes
fallback/last-known-good-fibonacci  # For emergency rollback
```

### Branch Strategy
- `main`: Production-ready code only
- `feature/fibonacci-enhancements`: New features
- `fix/dependency-issues`: Bug fixes  
- `experimental/new-indicators`: Untested features
- `archive/function-name`: Preserved old implementations
- `fallback/emergency-*`: Emergency rollback points

---

## Code Update & Deployment Process ⭐ MANDATORY WORKFLOW

### REQUIRED: Development → Deploy → Test → Commit Pipeline

**❌ NEVER deploy code without following this exact sequence:**

#### 1. Development Phase
```bash
# Modify code in local files
vim lambda_function.py
vim fibonacci_trade_setups.py

# CRITICAL: Copy updated files to complete_package/ directory
cp lambda_function.py complete_package/lambda_function.py
cp fibonacci_trade_setups.py complete_package/fibonacci_trade_setups.py
```

#### 2. Package Creation & S3 Deployment
```bash
# CRITICAL: Use Python deployment scripts, NOT AWS CLI or manual uploads
python3 deploy_complete_package.py

# This Python script:
# - Creates complete_package_deployment.zip (~81MB) with all dependencies
# - Uploads to s3://lumisignals-backups-e5558a85/lambda/
# - Deploys to Lambda from S3 (bypasses 70MB direct upload limit)
# - Handles boto3 client configuration properly

# ❌ DO NOT use manual AWS CLI commands like:
# aws lambda update-function-code --zip-file fileb://package.zip
# ❌ Manual uploads often fail due to SSL/size/timeout issues
```

#### 3. MANDATORY: Immediate Testing
```bash
# REQUIRED: Test immediately after deployment
cd /mnt/c/Users/sonia/LumiSignals
python3 test_deployed_fibonacci_lambda.py

# Verify all endpoints return Status Code 200
# Check trade setup generation (M5 and H1 timeframes)
# Validate Fibonacci levels are correct
```

#### 4. Git Commit ONLY After Successful Deployment
```bash
# DEPLOY FIRST, THEN COMMIT (not the reverse)
git add infrastructure/lambda/signal-analytics-api/lambda_function.py
git add infrastructure/lambda/signal-analytics-api/fibonacci_trade_setups.py

git commit -m "FEAT: Add [description of changes]

- Working Lambda deployment confirmed
- [Specific test results, e.g., "8 H1 setups, 3 M5 setups generated"]
- [Technical details of changes]

🤖 Generated with [Claude Code](https://claude.ai/code)
Co-Authored-By: Claude <noreply@anthropic.com>"
```

### Deployment Size Guidelines

**When to use S3 deployment:**
- ✅ **Always when pandas/numpy/pytz dependencies are included**
- ✅ Package size >70MB (Lambda direct upload limit)
- ✅ Complete dependency packages (recommended approach)

**When NOT to use direct deployment:**
- ❌ Never deploy only lambda_function.py without dependencies
- ❌ This breaks the function by losing numpy, redis, pytz modules
- ❌ "Minimal fixes" are a myth - Lambda needs ALL dependencies

### Rollback Procedures

**Immediate rollback from S3:**
```bash
# Deploy previous working package from S3
aws lambda update-function-code \
  --function-name lumisignals-signal-analytics-api \
  --s3-bucket lumisignals-backups-e5558a85 \
  --s3-key lambda/[previous-working-package].zip \
  --region us-east-1

# Test immediately
python3 test_deployed_fibonacci_lambda.py
```

**When to prompt for Git commit:**
- ✅ After successful deployment and testing
- ✅ When trade setup generation is working
- ✅ When all endpoints return 200 status codes
- ✅ Document specific test results in commit message

---

## Deployment & Testing Strategy

### Single Source of Truth Principle
**CRITICAL**: Always regenerate deployment packages from source files during deployment. Never commit deployment artifacts to git.

#### Source Directory Structure
```
lumisignals_trading_core/        # ✅ ONLY SOURCE OF TRUTH (tracked in git)
├── fibonacci/
│   ├── improved_fibonacci_analysis.py
│   └── timeframe_config.py
└── swing/
    └── swing_detection.py

complete_package/                # ❌ DEPLOYMENT ARTIFACT (should NOT be in git)
└── lumisignals_trading_core/    # Generated fresh during each deployment
```

#### Deployment Best Practices
1. **Source files** (`lumisignals_trading_core/`) are the ONLY source of truth
2. **Deployment directories** (`complete_package/`, `deploy_package/`) should be:
   - Generated fresh during deployment
   - Never committed to git
   - Added to `.gitignore`
   
3. **Deployment scripts** should ALWAYS:
   ```python
   # Copy from source of truth to deployment directory
   os.system('cp -r lumisignals_trading_core/* complete_package/lumisignals_trading_core/')
   ```

4. **NEVER manually edit** files in deployment directories
5. **ALWAYS verify** source files match deployment after copy

#### Common Anti-Pattern (What NOT to do)
```bash
# ❌ WRONG: Editing files in complete_package directly
vim complete_package/lumisignals_trading_core/fibonacci/improved_fibonacci_analysis.py

# ❌ WRONG: Committing deployment artifacts to git  
git add complete_package/
git commit -m "Updated fibonacci analysis"

# Result: Git version differs from actual source, causing deployment mismatches
```

#### Correct Pattern
```bash
# ✅ CORRECT: Edit source files only
vim lumisignals_trading_core/fibonacci/improved_fibonacci_analysis.py

# ✅ CORRECT: Deploy using script that copies from source
python3 deploy_complete_s3.py  # This copies from source to complete_package

# ✅ CORRECT: Only commit source files
git add lumisignals_trading_core/
git commit -m "Updated fibonacci analysis"
```

### Pre-Deployment Checklist
```python
# 1. Dependency verification
def verify_dependencies():
    try:
        import numpy
        import pytz  
        import redis
        from lumisignals_trading_core.fibonacci import improved_fibonacci_analysis
        return True
    except ImportError as e:
        return f"Missing dependency: {e}"

# 2. Redis connectivity test
def test_redis_connectivity():
    for instrument in ['EUR_USD', 'GBP_USD']:
        candles = get_redis_candles(f"market_data:{instrument}:H1:hot", instrument)
        if len(candles) == 0:
            return f"No data for {instrument}"
    return "Redis OK"

# 3. Function integration test  
def test_analytics_pipeline():
    result = generate_pair_analytics('EUR_USD', 'H1', include_trade_setups=True)
    if 'error' in result:
        return f"Analytics error: {result['error']}"
    return "Analytics OK"
```

### Deployment Scripts
Use dedicated deployment scripts with proper error handling:
- `deploy_full_numpy.py`: Complete package with S3 fallback
- `deploy_minimal_fix.py`: Quick updates with essential dependencies
- Never deploy without testing dependencies first

### Testing Framework
```python
# Always test working timeframes after deployment
WORKING_TIMEFRAMES = ['M5', 'H1']
TEST_PAIRS = ['EUR_USD', 'GBP_USD', 'USD_JPY']

def validate_deployment():
    for tf in WORKING_TIMEFRAMES:
        for pair in TEST_PAIRS:
            result = generate_pair_analytics(pair, tf)
            assert 'error' not in result
            assert result['total_candles'] == 500
            assert 'fibonacci' in result
```

---

## Error Handling & Debugging Framework

### Structured Error Response
```python
def handle_analysis_error(error: Exception, context: str) -> Dict:
    """Return structured error with debugging context"""
    return {
        'error': str(error),
        'context': context,
        'timestamp': datetime.utcnow().isoformat(),
        'debug_info': {
            'function': context,
            'error_type': type(error).__name__
        }
    }
```

### Debugging Script Pattern
```python
# Create focused debugging scripts for specific issues
def debug_specific_issue():
    """Template for debugging scripts"""
    print("🔍 Issue Investigation")
    print("=" * 60)
    
    # Test specific functionality
    # Report results with clear success/failure indicators
    # Provide actionable recommendations
```

### Common Error Patterns
- **ImportError**: Missing dependencies → Check deployment package
- **No price data**: Redis key mismatch → Verify timeframe availability  
- **Connection timeout**: Security group → Check VPC/subnet configuration
- **Function proliferation**: Broken fallbacks → Consolidate to main function

---

## Trade Setup Generation Standards

### Fibonacci Trade Setup Structure
```python
{
    "setup_id": "fibonacci_50.0%_H1",
    "strategy": "Fibonacci Standard Retracement 50.0% H1 Uptrend", 
    "direction": "BUY",
    "fibonacci_level": "50.0% Retracement",
    "entry_price": 1.1770,
    "stop_loss": 1.1692,
    "targets": [1.1888, 1.1938, 1.2013],
    "risk_pips": 77.3,
    "reward_pips": [118.9, 168.1, 243.5],
    "risk_reward_ratios": [1.54, 2.18, 3.15],
    "primary_rr": 1.54,
    "best_rr": 3.15,
    "setup_quality": 35,
    "quality_breakdown": {
        "risk_reward_score": 25,
        "confluence_score": 0, 
        "distance_score": 10,
        "risk_reward_rating": "Acceptable",
        "distance_rating": "Distant"
    }
}
```

### Quality Scoring System
- **Risk/Reward Score**: 0-50 points (25+ = Acceptable)
- **Confluence Score**: 0-30 points (Multiple indicator alignment)
- **Distance Score**: 0-20 points (Entry proximity to current price)
- **Total Quality**: 0-100 points (70+ = High Quality)

### Trade Setup Validation
- Minimum risk/reward ratio: 1.5:1
- Maximum risk: 100 pips per setup
- Stop loss below previous structural low (uptrend)
- Multiple profit targets for scaled exits

---

## Data Format Standards

### Candle Data Pipeline
```python
# Redis Storage Format (from data collection)
redis_candle = {
    'h': 1.18784,  # high
    'l': 1.16606,  # low
    'c': 1.18032,  # close  
    'o': 1.17890,  # open
    'time': '2025-09-23T05:00:00Z'
}

# Lambda Analysis Format (converted for trading core)
analysis_candle = {
    'high': 1.18784,
    'low': 1.16606, 
    'close': 1.18032,
    'open': 1.17890,
    'timestamp': '2025-09-23T05:00:00Z'
}
```

### Response Structure Standards
```python
{
    'instrument': 'EUR_USD',
    'timeframe': 'H1', 
    'current_price': 1.18032,
    'total_candles': 500,
    'data_source': 'redis_tiered',
    'fibonacci': { /* Fibonacci analysis */ },
    'trade_setups': [ /* Generated setups */ ],
    'analysis_timestamp': '2025-09-23T05:32:30.245642Z'
}
```

---

## Documentation & Knowledge Transfer

### Function Documentation Standards
```python
def generate_pair_analytics(instrument: str, timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Generate comprehensive analytics for currency pair
    
    Args:
        instrument: Currency pair in OANDA format (e.g., 'EUR_USD')
        timeframe: Analysis timeframe ('M5', 'H1' - others not available)
        
    Returns:
        Dict containing:
        - fibonacci: Fibonacci analysis with trade setups
        - current_price: Real-time price from Redis
        - total_candles: Number of candles analyzed (expected: 500)
        - trade_setups: List of actionable trade recommendations
        
    Raises:
        Exception: If Redis data unavailable or dependencies missing
        
    Dependencies:
        - Redis cluster connectivity (VPC security groups)
        - numpy (from complete_package/)
        - pytz (timezone handling)
        - lumisignals_trading_core (Fibonacci analysis)
        
    Data Sources:
        - Redis keys: market_data:{instrument}:{timeframe}:hot/warm
        - Available timeframes: M5, H1 (500 candles each)
        - 28 currency pairs across 4 Redis shards
    """
```

### Architecture Decision Records
Document major decisions:
- Why tiered Redis storage (hot/warm/cold)
- Why sharded architecture (instrument-based distribution) 
- Why single analytics function (prevent proliferation)
- Why Git-based versioning (avoid function name versioning)

---

## Lessons Learned & Anti-Patterns to Avoid

### Function Proliferation Crisis
**What Happened:**
- Created `analyze_fibonacci_tiered()` as "enhanced" version
- Original function became fallback when new one failed
- Fallback chain led to broken implementations being called
- System became unreliable with multiple versions of similar functions
- Lost access to working implementations when debugging failed

**Prevention:**
- **One function per analysis type**
- **Parameters for configuration, not new functions**
- **No fallback chains to old implementations**
- **Test thoroughly before deployment**
- **Archive old functions in Git before removal**

### Git Archive Strategy Success
**What We Learned:**
- Git branches preserve exact working states including dependencies
- Archive branches enable quick rollbacks without system downtime
- Detailed commit messages help identify why functions were changed
- Comment-out strategy allows gradual migration with safety net

**Emergency Rollback Process:**
```bash
# Quick revert to last known working state
git checkout fallback/last-known-good-fibonacci
git checkout -b hotfix/revert-fibonacci-changes
# Copy working function back to main
# Deploy immediately
# Debug the broken version separately
```

### Dependency Management Crisis  
**What Happened:**
- Missing pytz caused all Fibonacci analysis to fail
- Numpy import conflicts from incorrect package structure
- Lambda deployment timed out due to package size

**Prevention:**
- **Maintain working deployment scripts**
- **Test dependencies before deploying**
- **Use complete_package/ for known working dependencies**
- **Document exact dependency versions that work**

### Redis Data Access Mystery
**What Happened:**
- Fast responses but "No price data available" errors
- Security group configuration suspected but incorrect
- Root cause: Only M5/H1 timeframes have data, others empty

**Prevention:**
- **Document available timeframes clearly**
- **Test data availability before analysis**
- **Distinguish between connection and data issues**
- **Create debugging scripts for common problems**

---

## Quick Reference Commands

### Testing Analytics
```bash
# Test working timeframes
python3 debug_redis_keys.py

# Test specific trade setup values  
python3 test_fibonacci_trade_setup_values.py

# Test dependencies
python3 -c "import numpy, pytz, redis; print('Dependencies OK')"
```

### Deployment
```bash
# Full deployment with all dependencies
python3 deploy_full_numpy.py

# Quick updates (small changes only)
python3 deploy_minimal_fix.py
```

### Git Workflow
```bash
# Save state before major changes
git add . && git commit -m "SAVE: Working state before modifications"

# Create feature branch
git checkout -b feature/new-indicator

# Merge when ready
git checkout main && git merge feature/new-indicator
```

### Function Archive & Rollback
```bash
# Archive function before modification
git checkout -b archive/function-name-$(date +%Y%m%d)
git add . && git commit -m "ARCHIVE: Preserve working function before changes"
git checkout main

# Emergency rollback
git checkout archive/function-name-20250923
git checkout -b hotfix/emergency-revert
# Copy function back to main branch

# List all archive branches
git branch | grep archive

# Find specific archived function
git log --oneline --grep="ARCHIVE.*fibonacci"
```

---

**Last Updated**: September 23, 2025  
**Version**: 1.0  
**Status**: Production methodology based on successful Fibonacci implementation