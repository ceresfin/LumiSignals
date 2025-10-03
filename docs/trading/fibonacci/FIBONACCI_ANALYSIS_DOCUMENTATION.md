# Fibonacci Analysis System Documentation

## Overview

The `improved_fibonacci_analysis.py` module provides a comprehensive Fibonacci retracement and extension trading system. It combines swing point detection, Fibonacci level calculation, and intelligent trade setup generation with risk management and quality scoring.

## Core System Flow

### 1. Main Analysis Function (`analyze_fibonacci_levels_improved`)

This is the primary entry point that orchestrates the entire analysis:

```python
analyze_fibonacci_levels_improved(instrument, current_price, price_data, mode, timeframe, 
                                 include_trade_setups, include_confluence, institutional_levels)
```

**Flow:**
1. Determines if JPY pair (affects pip calculations)
2. Extracts current price from latest candle if not provided
3. Sets up parameters based on mode ('atr' or 'fixed')
4. Calls swing detection
5. Finds best swing pair
6. Generates Fibonacci levels
7. Optionally generates trade setups

**Mode Selection:**
- **ATR Mode**: Uses Average True Range to dynamically determine swing sizes and lookback periods
- **Fixed Mode**: Uses predefined timeframe-specific parameters

---

## 2. Swing Detection System (`detect_major_swing_points`)

### Purpose
Identifies significant swing highs and lows within a specified lookback period using prominence-based detection.

### Key Features

#### Lookback-Based Analysis
```python
recent_data = price_data[-lookback_periods:] if len(price_data) >= lookback_periods else price_data
```
- Analyzes only the most recent `lookback_periods` candles
- Prevents analysis from being skewed by ancient price data
- Default lookback: 50 periods (adjustable by timeframe)

#### Prominence Detection Algorithm
1. **Adaptive Window Sizing**: Uses `min(10, len(highs) // 4)` for proximity checking
2. **Local Maxima/Minima**: Finds points that are highest/lowest within their proximity window
3. **Significance Filtering**: Points must be within 15% of the recent absolute high/low
4. **Minimum Move Filtering**: Ensures swings are at least `min_swing_size_pips` apart

#### Swing High Detection Logic
```python
is_major_high = (current_high >= max(left_range) and 
                current_high >= max(right_range) and
                current_high >= local_max_high * 0.85)
```

#### Swing Low Detection Logic
```python
is_major_low = (current_low <= min(left_range) and 
               current_low <= min(right_range) and
               current_low <= local_min_low * 1.15)
```

### Output Structure
Returns dictionary with:
- `swing_highs`: Array of swing high objects with price, index, timestamp, method, prominence_score
- `swing_lows`: Array of swing low objects with price, index, timestamp, method, prominence_score
- Metadata: total counts, dataset range, parameters used

---

## 3. Swing Pair Selection (`find_best_fibonacci_swing_pair`)

### Purpose
Selects the most relevant swing high/low pair for Fibonacci analysis from detected swings.

### Trend Direction Logic
Uses chronological comparison to determine trend:

#### Timestamp-Based Comparison
```python
if high_timestamp and low_timestamp:
    # Handle Oanda nanosecond timestamps
    if str(high_timestamp).isdigit():
        trend_direction = 'uptrend' if high_ns > low_ns else 'downtrend'
    else:
        # ISO format timestamps
        trend_direction = 'uptrend' if high_dt > low_dt else 'downtrend'
```

**Logic**: 
- If swing high occurred after swing low → **uptrend**
- If swing low occurred after swing high → **downtrend**

### Current Retracement Calculation

#### Downtrend Retracement
```python
# DOWNTREND: FROM swing high (100%) TO swing low (0%)
current_retracement = (current_price - best_low['price']) / (best_high['price'] - best_low['price'])
```

#### Uptrend Retracement  
```python
# UPTREND: FROM swing low (100%) TO swing high (0%)
current_retracement = (best_high['price'] - current_price) / (best_high['price'] - best_low['price'])
```

### Relevance Scoring
Combines three factors:
1. **Size Score**: Larger swings (up to 100 pips) get higher scores
2. **Prominence Score**: Average of both swing prominence values
3. **Proximity Score**: Price within swing range = 1.0, outside gets distance penalty

---

## 4. Fibonacci Level Generation (`generate_improved_fibonacci_levels`)

### Core Calculation Logic

#### Downtrend Fibonacci Levels
```python
# Downtrend: FROM high (1.0) TO low (0.0)
# 0.618 retracement = 61.8% back UP from low toward high
level_price = low_price + (price_range * ratio)
```

#### Uptrend Fibonacci Levels
```python
# Uptrend: FROM low (1.0) TO high (0.0)  
# 0.618 retracement = 61.8% back DOWN from high toward low
level_price = high_price - (price_range * ratio)
```

### Timeframe-Specific Ratios
Uses `get_timeframe_fibonacci_ratios()` to get appropriate ratios:
- Default: `[0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]`
- Customizable per timeframe for optimal results

### Key Level Determination
Selects next significant level based on current retracement:
```python
if current_ret < 0.382:
    key_level = 0.382
elif current_ret < 0.5:
    key_level = 0.5
elif current_ret < 0.618:
    key_level = 0.618
else:
    key_level = 0.786
```

---

## 5. Trade Setup Generation (`generate_enhanced_trade_setups`)

### Three Trade Types

#### 1. TREND_EXTENSION (0-23.6% retracement)
- **Entry**: At 0% (swing point)
- **Logic**: Momentum continuation with minimal retracement
- **Targets**: Start at 138.2% extension

#### 2. TREND_CONTINUATION (23.6-78.6% retracement)  
- **Entry**: At 38.2%, 50%, or 61.8% based on current position
- **Logic**: Classic Fibonacci retracement trading
- **Targets**: Swing break + 127.2% extension

#### 3. TREND_REVERSAL (78.6%+ retracement)
- **Entry**: At 100% (full retracement)
- **Logic**: Deep retracement suggests potential reversal
- **Targets**: Major Fibonacci levels in opposite direction

### Entry Price Calculation

#### For Downtrend
```python
if entry_level == 0.0:
    entry_price = low_price  # 0% = swing low
elif entry_level == 1.0:
    entry_price = high_price  # 100% = swing high
else:
    entry_price = low_price + (swing_range * entry_level)
```

#### For Uptrend
```python
if entry_level == 0.0:
    entry_price = high_price  # 0% = swing high
elif entry_level == 1.0:
    entry_price = low_price  # 100% = swing low
else:
    entry_price = high_price - (swing_range * entry_level)
```

---

## 6. Trade Setup Creation (`create_proper_fibonacci_setup`)

### Trade Direction Logic

#### Trend Continuation (0-78.6%)
```python
if direction in ['uptrend', 'bullish']:
    trade_direction = 'BUY'  # Buy the retracement in uptrend
else:
    trade_direction = 'SELL'  # Sell the retracement bounce in downtrend
```

#### Trend Reversal (78.6%+)
```python
if direction in ['uptrend', 'bullish']:
    trade_direction = 'SELL'  # Reversal - sell the high
else:
    trade_direction = 'BUY'  # Reversal - buy the low
```

### Target Calculation

#### Extension Targets (138.2%, 161.8%, 200%)
```python
def calculate_extension_targets(base_price, swing_range, direction, decimal_places):
    extension_levels = [1.382, 1.618, 2.0]
    for level in extension_levels:
        if direction == 'down':
            target = base_price - (swing_range * level)
        else:
            target = base_price + (swing_range * level)
```

#### Continuation Targets (Swing Break + 127.2%)
```python
def calculate_continuation_targets(high_price, low_price, direction, decimal_places):
    if direction == 'up':
        swing_break = high_price
        extension_127 = high_price + (swing_range * 0.272)
    else:
        swing_break = low_price
        extension_127 = low_price - (swing_range * 0.272)
```

---

## 7. Stop Loss Calculation (`calculate_smart_stop_loss_with_level`)

### Intelligent Stop Placement

#### For Long Trades
```python
# Stop at the next Fibonacci level BELOW entry + buffer
next_level_down = get_next_fib_level_down(level)
if next_level_down == 0.0:
    stop_level = low_price - buffer  # Use swing low
else:
    stop_level = low_price + (swing_range * next_level_down) - buffer
```

#### For Short Trades
```python
# Stop at the next Fibonacci level ABOVE entry + buffer
next_level_up = get_next_fib_level_up(level)
if next_level_up == 1.0:
    stop_level = high_price + buffer  # Use swing high
else:
    stop_level = high_price - (swing_range * next_level_up) + buffer
```

### Timeframe-Specific Buffers
```python
timeframe_settings = get_timeframe_settings(timeframe)
buffer_pips = timeframe_settings['stop_buffer_pips']
```

**Buffer Sizes by Timeframe**:
- M5: 3 pips
- M15: 5 pips  
- M30: 8 pips
- H1: 15 pips
- H4: 25 pips
- D1: 50 pips

---

## 8. Risk/Reward Calculations

### Basic Metrics
```python
risk_pips = abs(entry_price - stop_loss) / pip_value
reward_pips = [abs(target - entry_price) / pip_value for target in targets]
risk_reward_ratio = reward_pips[0] / risk_pips if risk_pips > 0 else 0
```

### Multiple R:R Ratios
- **Primary R:R**: Most conservative (first target)
- **Best R:R**: Highest ratio available
- **Risk/Reward Array**: R:R for each target

### Minimum Requirements
```python
if primary_rr < 1.5:
    return None  # Skip setups that don't meet minimum R:R requirement
```

---

## 9. Quality Scoring System (`calculate_enhanced_setup_quality`)

### Scoring Components (Total: 100 points)

#### 1. Risk/Reward Score (0-40 points)
- R:R ≥ 3.0: 40 points
- R:R ≥ 2.5: 35 points  
- R:R ≥ 2.0: 30 points
- R:R ≥ 1.5: 20 points
- R:R ≥ 1.0: 10 points

#### 2. Confluence Score (0-25 points)
- High strength confluences: 10 points each
- Medium strength confluences: 5 points each
- Maximum: 25 points

#### 3. Distance Score (0-20 points)
Based on distance to entry relative to timeframe settings:
- ≤ 20% of max distance: 20 points
- ≤ 50% of max distance: 15 points
- ≤ 80% of max distance: 10 points
- ≤ 100% of max distance: 5 points

#### 4. Fibonacci Level Score (0-10 points)
- 61.8% (Golden ratio): 10 points
- 38.2% (Golden ratio): 9 points
- 78.6% (Deep retracement): 8 points
- 50% (Psychological): 7 points
- Other levels: 5 points

#### 5. Timeframe Bonus (0-5 points)
- M5: 1 point
- M15: 2 points
- M30: 3 points
- H1: 4 points  
- H4/D1: 5 points

### Quality Ratings
- **85-100**: Excellent
- **70-84**: Good
- **55-69**: Fair
- **40-54**: Poor
- **<40**: Very Poor

---

## 10. Confluence Analysis

### Institutional Level Generation (`generate_institutional_levels`)

#### For JPY Pairs
```python
levels = {
    'quarters': [],  # Not applicable for JPY
    'pennies': [base_level + i for i in range(-level_range, level_range + 1)],  # Whole numbers
    'dimes': [base_level + (i * 10) for i in range(-3, 4)]  # Every 10 yen
}
```

#### For Non-JPY Pairs
```python
levels = {
    'quarters': [quarter_base + (i * 0.0025) for i in range(-20, 21)],  # Every 0.0025
    'pennies': [penny_base + (i * 0.01) for i in range(-10, 11)],      # Every 0.01
    'dimes': [dime_base + (i * 0.10) for i in range(-5, 6)]           # Every 0.10
}
```

### Confluence Strength Calculation
```python
strength = 1.0 / (1.0 + distance * 10000)  # Closer = stronger
```

---

## 11. Timeframe Configuration

### Entry Distance Settings
```python
TIMEFRAME_SETTINGS = {
    'M5': {'entry_distance_pips': 10, 'stop_buffer_pips': 3, 'trade_type': 'scalp'},
    'M15': {'entry_distance_pips': 20, 'stop_buffer_pips': 5, 'trade_type': 'short_term'},
    'M30': {'entry_distance_pips': 35, 'stop_buffer_pips': 8, 'trade_type': 'intraday'},
    'H1': {'entry_distance_pips': 50, 'stop_buffer_pips': 15, 'trade_type': 'intraday'},
    'H4': {'entry_distance_pips': 100, 'stop_buffer_pips': 25, 'trade_type': 'swing'},
    'D1': {'entry_distance_pips': 200, 'stop_buffer_pips': 50, 'trade_type': 'position'}
}
```

---

## 12. Key Mathematical Formulas

### Pip Value Calculation
```python
pip_value = 0.01 if is_jpy else 0.0001  # JPY pairs use 0.01, others use 0.0001
```

### Price Distance to Pips
```python
distance_pips = abs(price1 - price2) / pip_value
```

### Fibonacci Retracement Formula
```python
# For any retracement level (0.0 to 1.0)
retracement_price = swing_start + (swing_range * retracement_level)
```

### Fibonacci Extension Formula
```python
# For extension levels (>1.0)
extension_price = swing_end + (swing_range * (extension_level - 1.0))
```

---

## 13. Error Handling and Validation

### Data Validation
- Minimum data requirements (20+ candles)
- Valid swing detection (at least 1 high and 1 low)
- Non-zero risk calculations
- Minimum R:R requirements (1.5+)

### Distance Filtering
```python
distance_to_entry = abs(current_price - entry_price)
if distance_to_entry > max_distance:
    return []  # Too far from entry
```

### Fallback Mechanisms
- Timestamp comparison fallbacks to index comparison
- Multiple swing detection methods
- Default parameter values for edge cases

---

## Usage Examples

### Basic Analysis
```python
result = analyze_fibonacci_levels_improved(
    instrument='EUR_USD',
    current_price=1.1050,
    price_data=candle_data,
    mode='fixed',
    timeframe='H1',
    include_trade_setups=True
)
```

### With Confluence Analysis
```python
institutional_levels = generate_institutional_levels(1.1050, 'EUR_USD')
result = analyze_fibonacci_levels_improved(
    instrument='EUR_USD',
    current_price=1.1050,
    price_data=candle_data,
    mode='atr',
    timeframe='H1',
    include_trade_setups=True,
    include_confluence=True,
    institutional_levels=institutional_levels
)
```

This comprehensive system provides professional-grade Fibonacci analysis with intelligent trade setup generation, risk management, and quality assessment suitable for algorithmic trading applications.