# Fibonacci Analysis Logic Documentation

## Overview

This document explains the comprehensive logic behind the LumiSignals Fibonacci analysis system, which generates algorithmic trade setups based on Fibonacci retracement and extension levels.

## Core Architecture

### Main Function Flow
```
Price Data → Swing Detection → Fibonacci Calculation → Trade Setup Generation → Quality Scoring
```

The system processes market data through a pipeline that identifies significant price swings, calculates Fibonacci levels, and generates actionable trade setups with risk management parameters.

---

## 1. Swing Detection Logic (`detect_major_swing_points`)

### Purpose
Identifies significant price turning points (swing highs and lows) from recent market data.

### Algorithm
```python
def detect_major_swing_points(price_data, lookback_periods=50, min_swing_size_pips=15, is_jpy=False)
```

### Key Components

#### Lookback-Based Analysis
- **Recent Focus**: Analyzes only the most recent `lookback_periods` candles
- **Prevents Stale Data**: Avoids using outdated swings from distant history
- **Default**: 50 periods for balanced recency vs. significance

#### Prominence Detection
```python
# Method 1: Find swing highs using prominence within recent data
for i in range(prominence_window, len(highs) - prominence_window):
    is_local_max = all(highs[i] >= highs[j] for j in range(i - prominence_window, i + prominence_window + 1))
```

- **Local Maximum/Minimum**: Point must be highest/lowest within its prominence window
- **Adaptive Window**: Window size adjusts based on data length (minimum 3, typical 10)
- **Significance Filter**: Only swings within 15% of absolute high/low are considered major

#### Swing Validation
- **Minimum Size**: Swings must exceed `min_swing_size_pips` to be considered
- **Pip Value Adjustment**: 0.01 for JPY pairs, 0.0001 for others
- **Prominence Scoring**: Higher prominence = more significant swing

### Output
```python
{
    'swing_highs': [{'price': 1.2050, 'index': 25, 'prominence': 0.85}],
    'swing_lows': [{'price': 1.1950, 'index': 45, 'prominence': 0.92}]
}
```

---

## 2. Fibonacci Level Calculation

### Core Principle: FROM/TO Logic

#### Correct Fibonacci Convention
- **Downtrend**: FROM swing high (100%) TO swing low (0%)
- **Uptrend**: FROM swing low (100%) TO swing high (0%)

```python
# Downtrend example: High 1.2000 → Low 1.1900 (100 pips range)
fibonacci_levels = {
    100.0: 1.2000,  # Swing high (FROM)
    78.6:  1.1979,  # 78.6% retracement
    61.8:  1.1938,  # Golden ratio
    50.0:  1.1950,  # Half retracement
    38.2:  1.1962,  # 38.2% retracement
    23.6:  1.1976,  # 23.6% retracement
    0.0:   1.1900   # Swing low (TO)
}
```

#### Current Retracement Calculation
```python
if direction == 'downtrend':
    current_retracement = (high_price - current_price) / (high_price - low_price)
else:  # uptrend
    current_retracement = (current_price - low_price) / (high_price - low_price)
```

### Timeframe-Adaptive Ratios
```python
TIMEFRAME_FIBONACCI_RATIOS = {
    'M5': [0.236, 0.382, 0.5, 0.618, 0.786],      # Core levels for scalping
    'H1': [0.236, 0.382, 0.5, 0.618, 0.786],      # Standard levels
    'H4': [0.236, 0.382, 0.5, 0.618, 0.786, 0.886] # Extended for swing trades
}
```

---

## 3. Trade Setup Generation (`create_proper_fibonacci_setup`)

### Three Trade Types Based on Retracement Level

#### A. TREND_EXTENSION (0% - 23.6% retracement)
```python
# Price at or near swing extreme - momentum continuation
entry_reason = "Price at swing extreme - extending momentum"
targets = calculate_extension_targets()  # 127.2%, 138.2%, 161.8%
```

**Logic**: Price has barely pulled back, likely to continue in trend direction
- **Entry**: At or near swing point
- **Targets**: Fibonacci extensions beyond previous swing
- **Risk**: Moderate (trend is strong)

#### B. TREND_CONTINUATION (23.6% - 78.6% retracement)
```python
# Classic Fibonacci trading zone
if direction == 'uptrend':
    trade_direction = 'BUY'   # Buy the dip in uptrend
else:
    trade_direction = 'SELL'  # Sell the bounce in downtrend
```

**Logic**: Normal retracement in trending market - expect trend resumption
- **Entry**: At key Fibonacci levels (38.2%, 50%, 61.8%)
- **Targets**: Previous swing break + extensions
- **Risk**: Lower (high probability zone)

#### C. TREND_REVERSAL (78.6%+ retracement)
```python
# Deep retracement suggesting potential trend change
setup_type_override = 'Trend Reversal'
# Reverse trade direction
trade_direction = 'BUY' if direction == 'downtrend' else 'SELL'
```

**Logic**: Deep retracement suggests trend weakness - potential reversal
- **Entry**: At extreme Fibonacci levels
- **Targets**: Reversal back to previous structure
- **Risk**: Higher (counter-trend trading)

---

## 4. Entry, Stop, and Target Logic

### Entry Price Determination
```python
# Find closest Fibonacci level to current price
valid_entries = [level for level in fib_levels if meets_distance_criteria(level)]
entry_level = min(valid_entries, key=lambda x: abs(x - current_retracement))
entry_price = calculate_price_from_level(entry_level)
```

### Stop Loss Placement: Next Fibonacci Level + Buffer
```python
def calculate_smart_stop_loss_with_level():
    if trade_direction == 'long':
        # Stop at next Fibonacci level BELOW entry + buffer
        next_level_down = get_next_fib_level_down(entry_level)
        stop_loss = low_price + (swing_range * next_level_down) - buffer
    else:  # short
        # Stop at next Fibonacci level ABOVE entry + buffer
        next_level_up = get_next_fib_level_up(entry_level)
        stop_loss = high_price - (swing_range * next_level_up) + buffer
```

**Key Innovation**: Uses logical Fibonacci levels instead of arbitrary fixed distances

### Target Calculation
```python
# Extension targets based on trade type
def calculate_extension_targets(base_price, swing_range, direction):
    extensions = [1.272, 1.382, 1.618]  # Common Fibonacci extensions
    if direction == 'up':
        return [base_price + (swing_range * ext) for ext in extensions]
    else:
        return [base_price - (swing_range * ext) for ext in extensions]
```

---

## 5. Timeframe-Adaptive Settings

### Buffer and Distance Settings
```python
TIMEFRAME_SETTINGS = {
    'M5': {
        'entry_distance_pips': 10,     # Very close entries for scalping
        'stop_buffer_pips': 3,         # Minimal buffer for low noise
        'trade_type': 'scalp'
    },
    'H1': {
        'entry_distance_pips': 50,     # Current working setting
        'stop_buffer_pips': 15,        # Current working setting
        'trade_type': 'intraday'
    },
    'D1': {
        'entry_distance_pips': 200,    # Very wide for position trades
        'stop_buffer_pips': 50,        # Large buffer for daily noise
        'trade_type': 'position'
    }
}
```

### Purpose
- **Noise Filtering**: Higher timeframes need larger buffers
- **Entry Precision**: Scalping requires tighter entries
- **Risk Management**: Position trades allow wider stops

---

## 6. Trend Direction Determination

### Chronological Analysis
```python
def determine_trend_direction_with_timestamps():
    try:
        if high_timestamp and low_timestamp:
            high_dt = parse_timestamp(high_timestamp)
            low_dt = parse_timestamp(low_timestamp)
            
            if high_dt > low_dt:
                return 'downtrend'  # High came after low
            else:
                return 'uptrend'    # Low came after high
    except:
        # Fallback to index comparison
        return 'downtrend' if high_index > low_index else 'uptrend'
```

### Multi-Format Support
- **Nanosecond timestamps**: `'2025-09-26T20:00:00.000000000Z'`
- **ISO format**: `'2025-09-26T20:00:00Z'`
- **Index fallback**: When timestamps unavailable

---

## 7. Risk/Reward Calculations

### Multiple R:R Ratios
```python
risk_pips = abs(entry_price - stop_loss) / pip_value
reward_pips = [abs(target - entry_price) / pip_value for target in targets]
risk_reward_ratios = [reward / risk_pips for reward in reward_pips]

# Primary (conservative) and best (optimistic) ratios
primary_rr = risk_reward_ratios[0]  # First target
best_rr = max(risk_reward_ratios)   # Best possible outcome
```

### Minimum R:R Enforcement
```python
# Filter setups with insufficient risk/reward
if primary_rr < 1.5:
    continue  # Skip low-quality setups
```

---

## 8. Quality Scoring System (100-point scale)

### Scoring Components
```python
def calculate_quality_score():
    # Risk/Reward Component (40 points max)
    rr_score = min(40, (risk_reward_ratio - 1.0) * 20)
    
    # Confluence Component (25 points max)
    confluence_score = calculate_confluence_alignment()
    
    # Distance Component (20 points max)
    distance_score = max(0, 20 - (distance_to_entry_pips / 2))
    
    # Fibonacci Level Component (10 points max)
    level_score = get_fibonacci_level_score(entry_level)
    
    # Timeframe Bonus (5 points max)
    timeframe_score = get_timeframe_bonus(timeframe)
    
    return {
        'risk_reward': rr_score,
        'confluence': confluence_score,
        'distance': distance_score,
        'fibonacci_level': level_score,
        'timeframe': timeframe_score,
        'total': sum(all_scores)
    }
```

### Quality Thresholds
- **70+**: High quality setup
- **50-69**: Medium quality setup
- **<50**: Low quality setup (may be filtered)

---

## 9. Mathematical Precision

### Pip Value Handling
```python
pip_value = 0.01 if is_jpy_pair(instrument) else 0.0001
decimal_places = 3 if is_jpy_pair(instrument) else 5
```

### Retracement Formula
```python
# Accurate retracement calculation
if direction == 'downtrend':
    retracement = (high_price - current_price) / swing_range
else:
    retracement = (current_price - low_price) / swing_range
```

### Extension Calculations
```python
# Extension beyond swing range
extension_price = base_price + (swing_range * extension_ratio)
```

---

## 10. Output Structure

### Complete Trade Setup
```python
{
    'instrument': 'EUR_USD',
    'direction': 'BUY',
    'trade_type': 'TREND_CONTINUATION',
    'setup_type': 'TREND_CONTINUATION',
    'strategy': 'TREND_CONTINUATION',
    'entry_price': 1.1695,
    'stop_loss': 1.1680,
    'targets': [1.1710, 1.1720, 1.1735],
    'current_price': 1.1698,
    'fibonacci_level': '38.2% Entry',
    'stop_fibonacci_level': '50.0% Level + Buffer',
    'target_fibonacci_levels': ['Swing Break', '127.2% Extension', '138.2% Extension'],
    'risk_pips': 15.0,
    'reward_pips': [15.0, 25.0, 40.0],
    'risk_reward_ratio': 1.0,
    'risk_reward_ratios': [1.0, 1.67, 2.67],
    'primary_rr': 1.0,
    'best_rr': 2.67,
    'distance_to_entry_pips': 3.0,
    'setup_quality': 72,
    'quality_breakdown': {
        'risk_reward': 32,
        'confluence': 20,
        'distance': 14,
        'fibonacci_level': 4,
        'timeframe': 2,
        'total': 72
    },
    'timeframe': 'H1',
    'swing_high': 1.1750,
    'swing_low': 1.1650,
    'current_retracement_pct': 38.2,
    'entry_reason': 'Fibonacci 38.2% retracement in uptrend - continuation entry',
    'invalidation': 'Break beyond 50.0% Level + Buffer',
    'confluence': None,
    'confluence_summary': None,
    'analysis_timestamp': '2025-09-26T20:54:34.123456Z'
}
```

---

## Key Trading Logic Principles

### 1. Trend-Following Bias
- Uptrends: Buy retracements, target higher highs
- Downtrends: Sell bounces, target lower lows

### 2. Risk Management
- Stops at logical Fibonacci levels (not arbitrary)
- Minimum 1.5 R:R requirement
- Timeframe-appropriate position sizing

### 3. Multi-Target Approach
- Conservative first target (break even quickly)
- Progressive targets at extension levels
- Partial profit-taking strategy

### 4. Quality Filtering
- Comprehensive scoring system
- Multiple confirmation factors
- Adaptable quality thresholds

This system represents institutional-grade Fibonacci analysis with sophisticated risk management and quality control mechanisms suitable for algorithmic trading applications.