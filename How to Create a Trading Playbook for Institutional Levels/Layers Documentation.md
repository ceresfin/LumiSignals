# Layers Documentation

This document provides detailed information about the reusable layers used in the trading playbook. Each layer represents a specific market condition or analytical input that can be combined to create trading signals.




### Layer: Quarter Levels

**Purpose**: To identify key institutional and psychological price levels based on the Quarters Theory.

**Calculation**: The Quarter Levels are calculated by dividing a 1000-pip or 100-pip range into four equal quarters. The levels are then drawn on the chart as horizontal lines.

**Parameters**:

- `quarter_size`: The size of the quarter in pips (e.g., 250 for Large Quarters, 25 for Small Quarters).
- `range_size`: The total range to be divided into quarters (e.g., 1000 for Large Quarters, 100 for Small Quarters).

**Code Reference**: The Python code for calculating psychological levels is provided in the `get_psychological_levels` function in the `code_references.py` file.




### Layer: Trend Confirmation

**Purpose**: To confirm the direction of the long-term trend.

**Calculation**: A simple moving average (SMA) is used to determine the trend direction. If the price is above the SMA, the trend is considered bullish. If the price is below the SMA, the trend is considered bearish.

**Parameters**:

- `sma_period`: The period of the simple moving average (e.g., 200).

**Code Reference**: The implementation of the trend confirmation layer can be found in the `code_references.py` file.




### Layer: Price Action

**Purpose**: To identify specific price action patterns that trigger an entry signal.

**Calculation**: This layer checks if the price has touched a specific quarter level. The touch can be a wick or a close.

**Parameters**:

- `level`: The quarter level to be monitored.

**Code Reference**: The implementation of the price action layer can be found in the `code_references.py` file.



### Layer: Bodyguard Levels

**Purpose**: To create entry trigger levels positioned around quarter levels that act as early warning systems for institutional level challenges.

**Calculation**: Bodyguard levels are positioned exactly 75 pips above and below each quarter level. These levels serve as the actual entry triggers when breached with proper candlestick sentiment.

**Structure**:
- **Upper Bodyguard**: Quarter Level + 75 pips
- **Lower Bodyguard**: Quarter Level - 75 pips
- **Function**: Act as "trip wires" that detect when quarter levels are being challenged

**Examples**:
- Quarter Level 1.2250: Upper Bodyguard 1.2325, Lower Bodyguard 1.2175
- Quarter Level 1.2500: Upper Bodyguard 1.2575, Lower Bodyguard 1.2425

**Parameters**:

- `bodyguard_distance`: Fixed at 75 pips from the quarter level
- `quarter_level`: The base quarter level around which bodyguards are positioned
- `breach_direction`: 'up' or 'down' indicating direction of bodyguard breach

**Entry Logic**: When price pierces through a bodyguard level with strong candlestick sentiment (Bullish/Very Bullish for upward breaches, Bearish/Very Bearish for downward breaches), it signals that the institutional orders at the protected quarter level may be overwhelmed, triggering an entry in the direction of the breach.

**Usage**: Bodyguards are the primary entry mechanism for the Quarters Theory strategy. They provide early entry signals before price reaches the actual quarter levels, allowing traders to position ahead of major institutional order flow.

**Code Reference**: The implementation of bodyguard level calculation and breach detection can be found in the `code_references.py` file.


### Layer: Candlestick Sentiment

**Purpose**: To measure the strength and direction of price movement within a candlestick by analyzing where the closing price falls within the candlestick's range.

**Calculation**: The sentiment is determined by calculating the percentage of the candlestick range where the price closes:

- **Very Bullish**: Close is 80-100% of the range from low to high
- **Bullish**: Close is 60-80% of the range from low to high  
- **Neutral**: Close is 40-60% of the range from low to high
- **Bearish**: Close is 20-40% of the range from low to high
- **Very Bearish**: Close is 0-20% of the range from low to high

**Formula**: 
```
sentiment_percentage = (close - low) / (high - low) * 100
```

**Parameters**:

- `timeframe`: The timeframe of the candlestick being analyzed (typically 4-hour for this strategy)
- `sentiment_threshold`: Minimum sentiment level required for signal validation

**Usage**: This layer is used across multiple strategies and paradigms to filter entry signals. Only candlesticks with strong sentiment (Bullish/Very Bullish for longs, Bearish/Very Bearish for shorts) are considered valid signals.

**Code Reference**: The implementation of candlestick sentiment calculation can be found in the `code_references.py` file.


### Layer: Breakout Confirmation

**Purpose**: To confirm that price has genuinely broken through a level rather than just touching or wicking through it.

**Calculation**: This layer verifies that the candlestick close is beyond the target level, not just a temporary spike or wick. For bodyguard levels, the close must be beyond the bodyguard level in the direction of the intended trade.

**Parameters**:

- `target_level`: The level that must be broken (e.g., bodyguard level)
- `direction`: The direction of the breakout ('long' for upward breakouts, 'short' for downward breakouts)
- `confirmation_type`: Type of confirmation required ('close_beyond', 'body_beyond', etc.)

**Usage**: This layer prevents false signals from temporary price spikes and ensures that only genuine breakouts with follow-through are considered valid entry signals.

**Code Reference**: The implementation of breakout confirmation can be found in the `code_references.py` file.


### Layer: Static Round Number Levels

**Purpose**: To provide predefined institutional round number levels that remain constant and are consistently watched by large market participants.

**Calculation**: These levels are static and based on the institutional Forex Road Map structure:

**For Non-JPY Pairs:**
- Dimes: X.0000, X.1000, X.2000, X.3000, X.4000, X.5000, X.6000, X.7000, X.8000, X.9000
- Big Quarters: X.X000, X.X250, X.X500, X.X750  
- Pennies: X.XX00, X.XX50
- Small Quarters: X.XXX00, X.XXX25, X.XXX50, X.XXX75

**For JPY Pairs:**
- Dimes: XX0.00, XX5.00 (every 500 pips)
- Big Quarters: XX0.00, XX2.50, XX5.00, XX7.50
- Pennies: XX.00, XX.50
- Small Quarters: XX.00, XX.25, XX.50, XX.75

**Parameters**:

- `pair_type`: 'JPY' or 'non_JPY' to determine decimal structure
- `level_hierarchy`: 'dimes', 'big_quarters', 'pennies', 'small_quarters'
- `price_range`: Current price range to generate relevant levels

**Usage**: These levels act as permanent support and resistance zones where institutional order flow is expected to cluster.

**Code Reference**: The implementation of static round number level generation can be found in the `code_references.py` file.


### Layer: Level Hierarchy Classification

**Purpose**: To categorize round number levels by their institutional significance and expected market reaction strength.

**Classification System**:

1. **Dimes (Highest Priority)**: Major 1000-pip levels (X.0000, X.1000, etc.)
   - Strongest institutional interest
   - Highest probability of significant reactions
   - Often act as major support/resistance for extended periods

2. **Big Quarters (High Priority)**: 250-pip intervals (X.X000, X.X250, X.X500, X.X750)
   - Strong institutional interest
   - Reliable support/resistance levels
   - Common targets for institutional order placement

3. **Pennies (Medium Priority)**: 50-pip intervals (X.XX00, X.XX50)
   - Moderate institutional interest
   - Useful for intraday trading
   - Often provide temporary support/resistance

4. **Small Quarters (Lower Priority)**: 25-pip intervals (X.XXX00, X.XXX25, X.XXX50, X.XXX75)
   - Limited institutional interest
   - Primarily for scalping strategies
   - May provide brief pauses in price movement

**Parameters**:

- `level_value`: The specific price level to classify
- `pair_type`: 'JPY' or 'non_JPY' for appropriate classification rules

**Usage**: This layer helps prioritize which levels to focus on and determines the expected strength of reactions at different round number levels.

**Code Reference**: The implementation of level hierarchy classification can be found in the `code_references.py` file.


### Layer: Price Action Confluence

**Purpose**: To identify when multiple technical factors align at round number levels, increasing the probability of significant price reactions.

**Confluence Factors**:

1. **Previous Support/Resistance**: Level has acted as support or resistance in the past
2. **Trend Line Intersection**: Round number level coincides with trend line
3. **Fibonacci Levels**: Round number aligns with key Fibonacci retracement/extension levels
4. **Moving Average Confluence**: Price level near significant moving averages
5. **Volume Profile**: High volume traded at or near the round number level
6. **Time-based Levels**: Round numbers at key time intervals (daily/weekly opens, closes)

**Scoring System**:
- **High Confluence (3+ factors)**: Very high probability setup
- **Medium Confluence (2 factors)**: Good probability setup  
- **Low Confluence (1 factor)**: Basic round number reaction only

**Parameters**:

- `round_number_level`: The specific round number being analyzed
- `lookback_period`: Historical period to check for previous support/resistance
- `confluence_factors`: List of technical factors to check for alignment
- `minimum_confluence_score`: Minimum number of factors required for signal

**Usage**: This layer filters round number levels to focus only on those with multiple supporting technical factors, significantly improving trade success rates.

**Code Reference**: The implementation of price action confluence analysis can be found in the `code_references.py` file.


### Layer: Multi-Timeframe Momentum

**Purpose**: To analyze price momentum across multiple timeframes to identify short-term momentum shifts and confirm directional bias for entry signals.

**Calculation**: Calculates percentage price change over multiple lookback periods to create a momentum profile:

**Standard Timeframes (for Hourly Trading)**:
- **48hr**: Long-term momentum context
- **24hr**: Daily momentum trend  
- **4hr**: Medium-term momentum shift
- **60min**: Short-term momentum
- **15min**: Immediate momentum

**Adjusted Timeframes for Different Trading Styles**:

**For 4-Hour Candlestick Trading**:
- **7 days**: Long-term momentum context
- **3 days**: Medium-term momentum trend
- **24hr**: Daily momentum shift  
- **8hr**: Short-term momentum
- **4hr**: Immediate momentum

**For Daily Candlestick Trading**:
- **30 days**: Long-term momentum context
- **14 days**: Medium-term momentum trend
- **7 days**: Weekly momentum shift
- **3 days**: Short-term momentum  
- **1 day**: Immediate momentum

**Momentum Analysis**:
- **Aligned Momentum**: All timeframes showing same directional bias (high confidence)
- **Mixed Momentum**: Some timeframes conflicting (medium confidence)
- **Divergent Momentum**: Longer timeframes opposite to shorter ones (potential reversal)

**Parameters**:

- `timeframes`: List of lookback periods to analyze
- `price_data`: Historical price data for calculations
- `momentum_threshold`: Minimum percentage change to consider significant
- `alignment_requirement`: Number of timeframes that must align for signal confirmation

**Usage**: This layer is particularly valuable for penny level trading in the Round Numbers strategy, where short-term momentum shifts can indicate the best entry timing at smaller round number levels.

**Momentum Scoring**:
- **Strong Bullish**: 80%+ of timeframes showing positive momentum
- **Weak Bullish**: 60-80% of timeframes showing positive momentum
- **Neutral**: 40-60% mixed momentum
- **Weak Bearish**: 60-80% of timeframes showing negative momentum  
- **Strong Bearish**: 80%+ of timeframes showing negative momentum

**Code Reference**: The implementation of multi-timeframe momentum analysis can be found in the `code_references.py` file.


### Layer: Quarter Level Classification

**Purpose**: To categorize quarter levels as either Green (support-oriented) or Red (resistance-oriented) levels based on their ending digits and market behavior patterns.

**Classification Rules**:

**Green Levels (Support-Oriented)**:
- Typically quarter levels ending in .25 or .75 (e.g., 1.2425, 1.2575, 1.2325)
- Often act as support levels where price finds buying interest
- Generally associated with bounce/reversal setups
- Tend to have stronger support characteristics

**Red Levels (Resistance-Oriented)**:
- Typically quarter levels ending in .00 or .50 (e.g., 1.2500, 1.2250, 1.2000)
- Often act as resistance levels where price encounters selling pressure
- Generally associated with breakout/continuation setups
- Tend to have stronger resistance characteristics

**Parameters**:

- `quarter_level`: The specific quarter level price to classify
- `classification_method`: 'digit_based' (default) or 'historical_behavior'
- `lookback_period`: For historical behavior analysis (optional)

**Usage**: This classification determines which of the 5 setup types are available and helps predict the likely price behavior at each level.

**Code Reference**: The implementation of quarter level classification can be found in the `code_references.py` file.


### Layer: Setup Type Identification

**Purpose**: To automatically identify which of the 5 Quarters Theory setups applies based on the entry level classification and target level positioning.

**Setup Identification Logic**:

**Setup #1: Green to Green (Butter Middle)**
- Entry: Green level
- Target: Next green level with one red level in between
- Characteristics: 100 pip target, 25 pip stop, 4:1 R:R

**Setup #2: Green to Green (Red Middle)**
- Entry: Green level  
- Target: Next green level with red level in between (longer distance)
- Characteristics: 150 pip target, 50 pip stop, 3:1 R:R

**Setup #3: Green to Opposing Red**
- Entry: Green level
- Target: Nearest opposing red level
- Characteristics: 175 pip target, 75 pip stop, 2.33:1 R:R

**Setup #4: Red to Opposing Green**
- Entry: Red level
- Target: Nearest opposing green level
- Characteristics: 175 pip target, 75 pip stop, 2.33:1 R:R

**Setup #5: Red to Red**
- Entry: Red level
- Target: Next red level
- Characteristics: 250 pip target, 75 pip stop, 3.33:1 R:R

**Parameters**:

- `entry_level`: The quarter level where entry is planned
- `entry_classification`: 'green' or 'red' classification of entry level
- `available_targets`: List of potential target levels within range
- `max_target_distance`: Maximum distance to consider for target selection

**Output**: Returns setup type (1-5), target level, stop loss level, and risk/reward ratio.

**Usage**: This layer automates the setup selection process and ensures consistent application of the 5 setup types based on current market positioning.

**Code Reference**: The implementation of setup type identification can be found in the `code_references.py` file.


### Layer: Bodyguard Breach Confirmation

**Purpose**: To verify that price has genuinely breached through a bodyguard level with conviction, rather than just a temporary spike or false breakout.

**Confirmation Criteria**:

1. **Price Penetration**: Price must pierce through the bodyguard level (not just touch)
2. **Candlestick Close**: The 4-hour candlestick must close beyond the bodyguard level
3. **Sentiment Alignment**: Candlestick sentiment must align with breach direction:
   - Upward breaches require Bullish (60-80%) or Very Bullish (80-100%) sentiment
   - Downward breaches require Bearish (20-40%) or Very Bearish (0-20%) sentiment
4. **No Immediate Reversal**: Price should not immediately reverse back through the bodyguard

**Breach Types**:
- **Clean Breach**: Price breaks through with strong sentiment and continues
- **False Breach**: Price spikes through but immediately reverses (avoid these)
- **Weak Breach**: Price breaks through with neutral sentiment (avoid these)

**Parameters**:

- `bodyguard_level`: The specific bodyguard level being monitored
- `breach_direction`: 'up' or 'down' indicating expected breach direction
- `confirmation_timeframe`: Timeframe for confirmation (typically 4-hour)
- `minimum_sentiment`: Minimum required sentiment strength for validation

**Usage**: This layer prevents false signals from temporary price spikes and ensures that only genuine bodyguard breaches with institutional conviction are considered valid entry signals.

**Validation Process**:
1. Detect bodyguard level contact
2. Verify price penetration beyond level
3. Check candlestick sentiment alignment
4. Confirm close beyond bodyguard level
5. Generate entry signal if all criteria met

**Code Reference**: The implementation of bodyguard breach confirmation can be found in the `code_references.py` file.


### Layer: Entry Type Classification

**Purpose**: To distinguish between the two different entry mechanisms in the Quarters Theory strategy: Bodyguard Entries and Quarter Level Entries.

**Entry Type Categories**:

**Bodyguard Entries (Setups #1, #2)**:
- **Trigger**: Price pierces through bodyguard level with sentiment confirmation
- **Advantage**: Earlier entry before reaching institutional levels
- **Sentiment Requirement**: Bullish/Very Bullish for upward, Bearish/Very Bearish for downward
- **Logic**: Early warning system detecting quarter level challenges
- **Risk Profile**: Generally lower risk due to earlier entry

**Quarter Level Entries (Setups #4, #5)**:
- **Trigger**: Price breaks through actual quarter level with strong conviction
- **Advantage**: Higher conviction signals from institutional level breaks
- **Sentiment Requirement**: Very Bullish for upward, Very Bearish for downward (stronger requirement)
- **Logic**: Direct breakout from major institutional price zones
- **Risk Profile**: Higher conviction but may require larger stops

**Classification Logic**:
- If entry level is a bodyguard (75 pips from quarter) → Bodyguard Entry
- If entry level is a quarter level itself → Quarter Level Entry
- Different sentiment thresholds apply based on entry type
- Different risk management rules apply based on entry type

**Parameters**:

- `entry_level`: The specific price level where entry is planned
- `quarter_levels`: List of known quarter levels for comparison
- `bodyguard_distance`: Distance used to identify bodyguard levels (75 pips)
- `sentiment_requirements`: Different thresholds for each entry type

**Usage**: This classification determines the appropriate entry criteria, sentiment requirements, and risk management rules to apply for each signal.

**Code Reference**: The implementation of entry type classification can be found in the `code_references.py` file.

