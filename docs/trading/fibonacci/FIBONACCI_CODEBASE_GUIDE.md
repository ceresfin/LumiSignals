# LumiSignals Fibonacci Analysis Codebase Guide

## Overview
This guide provides a comprehensive overview of the Fibonacci analysis system within LumiSignals, including function locations, deployment procedures, and development best practices.

## 🏗️ Architecture Overview

```
📁 LumiSignals/
├── 🧪 test_detailed_setups.py                    # Main testing interface
├── 📁 infrastructure/lambda/signal-analytics-api/
│   ├── 📄 lambda_function.py                     # Main Lambda handler
│   ├── 📁 lumisignals_trading_core/fibonacci/    # Development source
│   └── 📁 complete_package/                      # Deployment package
│       ├── 📄 lambda_function.py                 # Deployed Lambda
│       └── 📁 lumisignals_trading_core/fibonacci/ # Deployed fibonacci code
```

## 📊 Core Fibonacci System Components

### 1. **Main Test Interface** 
**File:** `/test_detailed_setups.py`
- **Purpose:** Primary interface for testing and analyzing fibonacci setups
- **Usage:** `python3 test_detailed_setups.py [PAIR] [TIMEFRAME]`
- **Key Functions:**
  - `convert_timestamp_to_est()` - Converts API timestamps to EST timezone
  - `get_fibonacci_analysis_from_api()` - Calls Lambda API endpoints
  - `print_detailed_analysis()` - Formats and displays complete analysis
  - `calculate_fibonacci_levels()` - Calculates retracement levels for display

### 2. **Lambda Function Handler**
**File:** `/infrastructure/lambda/signal-analytics-api/complete_package/lambda_function.py`
- **Purpose:** Main AWS Lambda entry point for all analytics
- **Key Functions:**
  - `get_tiered_price_data()` - Retrieves candle data from Redis (hot/warm/cold tiers)
  - `get_redis_candles()` - Connects to Redis shards and retrieves raw candle data
  - `perform_swing_analysis()` - Calls swing detection with proper timestamp handling
  - `perform_fibonacci_analysis()` - Orchestrates fibonacci analysis workflow
  - `lambda_handler()` - Main entry point handling API routes

### 3. **Core Fibonacci Analysis Engine**
**File:** `/infrastructure/lambda/signal-analytics-api/complete_package/lumisignals_trading_core/fibonacci/improved_fibonacci_analysis.py`
- **Purpose:** Advanced fibonacci analysis with extremes-first swing selection
- **Key Functions:**
  - `detect_major_swing_points()` - Finds significant swing highs/lows using prominence + extremes
  - `find_best_fibonacci_swing_pair()` - Selects optimal swing pair using extremes-first approach
  - `generate_improved_fibonacci_levels()` - Creates fibonacci retracement levels
  - `analyze_fibonacci_levels_improved()` - Main analysis orchestrator
  - `generate_enhanced_trade_setups()` - Creates actionable trade setups with R:R ratios
  - `calculate_smart_stop_loss()` - Calculates intelligent stop placement
  - `calculate_smart_targets()` - Generates multiple profit targets using extensions

### 4. **Fibonacci Module Initialization**
**File:** `/infrastructure/lambda/signal-analytics-api/complete_package/lumisignals_trading_core/fibonacci/__init__.py`
- **Purpose:** Exports main fibonacci functions for import
- **Exports:**
  - `detect_major_swing_points`
  - `find_best_fibonacci_swing_pair` 
  - `generate_improved_fibonacci_levels`
  - `analyze_fibonacci_levels_improved`
  - `generate_enhanced_trade_setups`

### 5. **Configuration Modules**
**Files:**
- `timeframe_config.py` - Timeframe-specific parameters and fibonacci ratios
- `atr_calculator.py` - ATR-based dynamic thresholds

## 🔄 Data Flow Architecture

```
1. Redis Shards (4 shards with tiered storage)
   ↓ get_redis_candles()
2. Lambda Function (candle formatting + timestamp extraction)
   ↓ perform_swing_analysis() / perform_fibonacci_analysis()
3. Swing Detection (identify major swing points with timestamps)
   ↓ find_best_fibonacci_swing_pair()
4. Fibonacci Analysis (calculate levels and generate trade setups)
   ↓ API Response
5. test_detailed_setups.py (display formatted results)
```

## 🚀 Deployment Procedures

### Standard Deployment Process
```bash
# 1. Navigate to Lambda directory
cd infrastructure/lambda/signal-analytics-api/

# 2. Use existing deployment scripts (DO NOT create new ones)
python3 deploy_complete_package.py

# 3. Test deployment
python3 test_detailed_setups.py EUR_USD
```

### Deployment Package Structure
- **Source:** `/lumisignals_trading_core/fibonacci/` (development)
- **Target:** `/complete_package/lumisignals_trading_core/fibonacci/` (deployment)
- **Process:** Automated copy via Python deployment scripts using S3

### Critical Deployment Notes
- ✅ Always deploy the complete package (all dependencies included)
- ✅ Use existing Python S3 deployment scripts
- ✅ Test immediately after deployment with `test_detailed_setups.py`
- ❌ DO NOT create separate deployment methods
- ❌ DO NOT deploy individual files

## 🧬 Key Function Responsibilities

### Swing Detection Functions
| Function | File | Purpose |
|----------|------|---------|
| `detect_major_swing_points()` | improved_fibonacci_analysis.py | Find significant swing highs/lows using prominence scoring |
| `find_best_fibonacci_swing_pair()` | improved_fibonacci_analysis.py | Select optimal swing pair using extremes-first approach |

### Fibonacci Level Functions  
| Function | File | Purpose |
|----------|------|---------|
| `generate_improved_fibonacci_levels()` | improved_fibonacci_analysis.py | Calculate retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%) |
| `calculate_fibonacci_levels()` | test_detailed_setups.py | Display-only fibonacci calculations |

### Trade Setup Functions
| Function | File | Purpose |
|----------|------|---------|
| `generate_enhanced_trade_setups()` | improved_fibonacci_analysis.py | Create actionable trades with entries/stops/targets |
| `calculate_smart_stop_loss()` | improved_fibonacci_analysis.py | Intelligent stop placement using deeper fibonacci levels |
| `calculate_smart_targets()` | improved_fibonacci_analysis.py | Multiple targets using fibonacci extensions |

### Utility Functions
| Function | File | Purpose |
|----------|------|---------|
| `convert_timestamp_to_est()` | test_detailed_setups.py | Convert API timestamps to EST for display |
| `get_timeframe_settings()` | improved_fibonacci_analysis.py | Get timeframe-specific parameters |

## 🚫 Anti-Patterns to Avoid

### ❌ DON'T: Create Duplicate Functions
- Each function should have ONE authoritative location
- Use existing functions rather than creating similar ones
- If modifications needed, update the existing function

### ❌ DON'T: Create New Files
- Work within existing file structure
- Extend existing modules rather than creating new ones
- Use git stash/commit workflow for experimentation

### ❌ DON'T: Create Custom Deployment Scripts
- Use existing Python S3 deployment scripts
- Follow established deployment patterns
- Test with `test_detailed_setups.py` after every deployment

## ✅ Best Practices

### 🔧 Development Workflow
```bash
# 1. Make changes in development files
vim infrastructure/lambda/signal-analytics-api/lumisignals_trading_core/fibonacci/improved_fibonacci_analysis.py

# 2. Stash experimental changes
git stash push -m "experimental fibonacci changes"

# 3. Deploy and test
python3 deploy_complete_package.py
python3 test_detailed_setups.py EUR_USD

# 4. If successful, commit; if not, pop stash
git commit -m "Update fibonacci analysis"
# OR
git stash pop
```

### 🧪 Testing Protocol
1. **Always test with `test_detailed_setups.py`** after any changes
2. **Verify timestamps are showing properly** (not "Unknown")
3. **Check both M5 and H1 timeframes** for consistency
4. **Validate fibonacci levels and trade setups** have proper R:R ratios

### 📝 Function Updates
- **Modify existing functions** rather than creating new ones
- **Maintain backward compatibility** when possible  
- **Update imports** in `__init__.py` if function signatures change
- **Document changes** in git commit messages

## 🔍 Current Function Status

### ✅ Working Functions (DO NOT DUPLICATE)
- `detect_major_swing_points()` - Swing detection with extremes-first approach ✓
- `find_best_fibonacci_swing_pair()` - Optimal swing pair selection ✓
- `generate_improved_fibonacci_levels()` - Fibonacci level calculation ✓
- `convert_timestamp_to_est()` - Timestamp conversion ✓
- All trade setup generation functions ✓

### 🎯 Integration Points
- **Lambda API:** `/analytics/trade-setups` and `/analytics/all-signals`
- **Redis Data:** Tiered storage (hot/warm/cold) across 4 shards
- **Test Interface:** `python3 test_detailed_setups.py [PAIR] [TIMEFRAME]`

## 📚 Quick Reference

### Test EUR_USD Analysis
```bash
python3 test_detailed_setups.py EUR_USD     # M5 timeframe (default)
python3 test_detailed_setups.py EUR_USD H1  # H1 timeframe  
```

### Deploy Changes
```bash
cd infrastructure/lambda/signal-analytics-api/
python3 deploy_complete_package.py
```

### Check API Endpoints
```bash
# Trade setups
curl "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws/analytics/trade-setups?timeframe=M5"

# All signals  
curl "https://hqsiypravhxr5lhhkajvstmnpi0mxckg.lambda-url.us-east-1.on.aws/analytics/all-signals?timeframe=M5"
```

---

**Remember:** This codebase follows a principle of **single responsibility** and **no duplication**. Always work within the existing structure, use git for version control, and test thoroughly with the provided interfaces.