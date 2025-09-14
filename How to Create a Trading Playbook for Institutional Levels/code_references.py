import pandas as pd

def get_psychological_levels(price, instrument):
    """Calculates psychological levels for a given price and instrument."""
    is_jpy = 'JPY' in instrument

    if is_jpy:
        # JPY pairs (2 decimal places)
        dimes = [round(price, -2) + i * 10 for i in range(-5, 6)]  # X00.00 levels
        quarters = [round(price, 1) + i * 2.5 for i in range(-10, 11)]  # XX2.50 levels
        pennies = [round(price, 0) + i * 1 for i in range(-20, 21)]  # XX.00 levels
    else:
        # Non-JPY pairs (4 decimal places)
        dimes = [round(price, 1) + i * 0.1 for i in range(-5, 6)]  # X.1000 levels
        quarters = [round(price, 3) + i * 0.025 for i in range(-10, 11)]  # X.X250 levels
        pennies = [round(price, 2) + i * 0.01 for i in range(-20, 21)]  # X.XX10 levels

    return {'dimes': dimes, 'quarters': quarters, 'pennies': pennies}

def trend_confirmation(price_data, sma_period=200):
    """Confirms the trend direction using a simple moving average."""
    sma = price_data['close'].rolling(window=sma_period).mean().iloc[-1]
    current_price = price_data['close'].iloc[-1]

    if current_price > sma:
        return 'bullish'
    elif current_price < sma:
        return 'bearish'
    else:
        return 'sideways'

def price_action_touch(price_data, level):
    """Checks if the price has touched a specific level."""
    if price_data['low'].iloc[-1] <= level <= price_data['high'].iloc[-1]:
        return True
    else:
        return False



def calculate_bodyguard_levels(quarter_levels, bodyguard_distance=75):
    """
    Calculates bodyguard levels positioned above and below quarter levels.
    Bodyguards act as entry triggers, not the quarter levels themselves.
    """
    bodyguard_levels = {}
    
    for level_type, levels in quarter_levels.items():
        bodyguard_levels[level_type] = []
        for quarter_level in levels:
            # Convert pips to price units (assuming 4-decimal pairs, adjust for JPY)
            pip_value = 0.0001  # For most pairs
            if 'JPY' in str(quarter_level):  # Simple check, should be improved
                pip_value = 0.01
            
            distance = bodyguard_distance * pip_value
            
            # Create bodyguard entries with their protected quarter level
            upper_bodyguard = {
                'level': quarter_level + distance,
                'type': 'upper_bodyguard',
                'protected_quarter': quarter_level,
                'direction': 'up'
            }
            
            lower_bodyguard = {
                'level': quarter_level - distance,
                'type': 'lower_bodyguard', 
                'protected_quarter': quarter_level,
                'direction': 'down'
            }
            
            bodyguard_levels[level_type].extend([lower_bodyguard, upper_bodyguard])
    
    return bodyguard_levels

def confirm_bodyguard_breach(price_data, bodyguard_info, required_sentiment=['bullish', 'very_bullish']):
    """
    Confirms that price has breached through a bodyguard level with proper conviction.
    
    Args:
        price_data: DataFrame with OHLC data
        bodyguard_info: Dict containing bodyguard level info
        required_sentiment: List of acceptable sentiment types for confirmation
    """
    current_candle = price_data.iloc[-1]
    bodyguard_level = bodyguard_info['level']
    breach_direction = bodyguard_info['direction']
    
    # Get candlestick sentiment
    sentiment, sentiment_pct = calculate_candlestick_sentiment(
        current_candle['open'],
        current_candle['high'],
        current_candle['low'],
        current_candle['close']
    )
    
    # Check if price has breached the bodyguard level
    if breach_direction == 'up':
        # For upward breach, price must close above bodyguard
        price_breached = current_candle['close'] > bodyguard_level
        # Also check that price actually penetrated (not just gapped)
        penetration_confirmed = current_candle['low'] <= bodyguard_level
    else:  # breach_direction == 'down'
        # For downward breach, price must close below bodyguard
        price_breached = current_candle['close'] < bodyguard_level
        # Also check that price actually penetrated (not just gapped)
        penetration_confirmed = current_candle['high'] >= bodyguard_level
    
    # Check sentiment alignment
    sentiment_aligned = sentiment in required_sentiment
    
    # Confirm breach
    breach_confirmed = price_breached and penetration_confirmed and sentiment_aligned
    
    return {
        'breach_confirmed': breach_confirmed,
        'price_breached': price_breached,
        'penetration_confirmed': penetration_confirmed,
        'sentiment_aligned': sentiment_aligned,
        'sentiment': sentiment,
        'sentiment_pct': sentiment_pct,
        'breach_direction': breach_direction
    }

def quarters_theory_bodyguard_signal(price_data, instrument, timeframe='4H'):
    """
    Complete signal generation for Quarters Theory using bodyguard entry system.
    Returns entry signals when bodyguards are breached with proper confirmation.
    """
    current_price = price_data['close'].iloc[-1]
    
    # Get quarter levels
    quarter_levels = get_psychological_levels(current_price, instrument)
    
    # Calculate bodyguard levels
    bodyguard_levels = calculate_bodyguard_levels(quarter_levels)
    
    signals = []
    
    # Check each bodyguard level for potential breach
    for level_type, bodyguards in bodyguard_levels.items():
        for bodyguard_info in bodyguards:
            bodyguard_level = bodyguard_info['level']
            
            # Skip bodyguards too far from current price
            distance = abs(current_price - bodyguard_level)
            pip_value = 0.0001 if 'JPY' not in instrument else 0.01
            max_distance = 50 * pip_value  # Within 50 pips
            
            if distance > max_distance:
                continue
            
            # Determine required sentiment based on breach direction
            if bodyguard_info['direction'] == 'up':
                required_sentiment = ['bullish', 'very_bullish']
                signal_direction = 'long'
            else:
                required_sentiment = ['bearish', 'very_bearish']
                signal_direction = 'short'
            
            # Check for bodyguard breach
            breach_result = confirm_bodyguard_breach(price_data, bodyguard_info, required_sentiment)
            
            if breach_result['breach_confirmed']:
                # Generate signals for different setup types
                setups = identify_bodyguard_setups(bodyguard_info, quarter_levels, instrument)
                
                for setup in setups:
                    signal = {
                        'direction': signal_direction,
                        'setup_type': setup['setup_type'],
                        'setup_name': setup['setup_name'],
                        'entry_level': bodyguard_level,
                        'target_level': setup['target_level'],
                        'stop_loss': setup['stop_loss'],
                        'take_profit_pips': setup['take_profit_pips'],
                        'stop_loss_pips': setup['stop_loss_pips'],
                        'risk_reward_ratio': setup['risk_reward_ratio'],
                        'protected_quarter': bodyguard_info['protected_quarter'],
                        'bodyguard_type': bodyguard_info['type'],
                        'breach_direction': bodyguard_info['direction'],
                        'sentiment': breach_result['sentiment'],
                        'sentiment_pct': breach_result['sentiment_pct']
                    }
                    
                    signals.append(signal)
    
    # Sort signals by setup type priority (Setup #1 highest priority)
    signals.sort(key=lambda x: x['setup_type'])
    
    return signals

def identify_bodyguard_setups(bodyguard_info, quarter_levels, instrument):
    """
    Identifies available setup types when a bodyguard is breached.
    """
    pip_value = 0.0001 if 'JPY' not in instrument else 0.01
    bodyguard_level = bodyguard_info['level']
    protected_quarter = bodyguard_info['protected_quarter']
    breach_direction = bodyguard_info['direction']
    
    setups = []
    
    # Get all quarter levels in a flat list for easier processing
    all_quarters = []
    for level_type, levels in quarter_levels.items():
        all_quarters.extend(levels)
    all_quarters = sorted(set(all_quarters))
    
    # Find the index of the protected quarter
    try:
        quarter_index = all_quarters.index(protected_quarter)
    except ValueError:
        return setups  # Protected quarter not found
    
    if breach_direction == 'up':
        # For upward breaches, look for targets above
        
        # Setup #1: Next bodyguard (100 pips)
        if quarter_index + 1 < len(all_quarters):
            next_quarter = all_quarters[quarter_index + 1]
            target_bodyguard = next_quarter - (75 * pip_value)  # Lower bodyguard of next quarter
            
            setups.append({
                'setup_type': 1,
                'setup_name': 'Bodyguard to Next Bodyguard',
                'target_level': target_bodyguard,
                'stop_loss': protected_quarter,  # Back to protected quarter
                'take_profit_pips': 100,
                'stop_loss_pips': 25,
                'risk_reward_ratio': 4.0
            })
        
        # Setup #4: Next quarter level (175 pips)
        if quarter_index + 1 < len(all_quarters):
            next_quarter = all_quarters[quarter_index + 1]
            
            setups.append({
                'setup_type': 4,
                'setup_name': 'Bodyguard to Next Quarter Level',
                'target_level': next_quarter,
                'stop_loss': protected_quarter,
                'take_profit_pips': 175,
                'stop_loss_pips': 75,
                'risk_reward_ratio': 2.33
            })
        
        # Setup #5: Second quarter level (250+ pips)
        if quarter_index + 2 < len(all_quarters):
            second_quarter = all_quarters[quarter_index + 2]
            
            setups.append({
                'setup_type': 5,
                'setup_name': 'Bodyguard to Second Quarter Level',
                'target_level': second_quarter,
                'stop_loss': protected_quarter,
                'take_profit_pips': 250,
                'stop_loss_pips': 75,
                'risk_reward_ratio': 3.33
            })
    
    else:  # breach_direction == 'down'
        # For downward breaches, look for targets below
        
        # Setup #1: Next bodyguard (100 pips)
        if quarter_index - 1 >= 0:
            prev_quarter = all_quarters[quarter_index - 1]
            target_bodyguard = prev_quarter + (75 * pip_value)  # Upper bodyguard of previous quarter
            
            setups.append({
                'setup_type': 1,
                'setup_name': 'Bodyguard to Next Bodyguard',
                'target_level': target_bodyguard,
                'stop_loss': protected_quarter,
                'take_profit_pips': 100,
                'stop_loss_pips': 25,
                'risk_reward_ratio': 4.0
            })
        
        # Setup #4: Previous quarter level (175 pips)
        if quarter_index - 1 >= 0:
            prev_quarter = all_quarters[quarter_index - 1]
            
            setups.append({
                'setup_type': 4,
                'setup_name': 'Bodyguard to Next Quarter Level',
                'target_level': prev_quarter,
                'stop_loss': protected_quarter,
                'take_profit_pips': 175,
                'stop_loss_pips': 75,
                'risk_reward_ratio': 2.33
            })
        
        # Setup #5: Second quarter level (250+ pips)
        if quarter_index - 2 >= 0:
            second_quarter = all_quarters[quarter_index - 2]
            
            setups.append({
                'setup_type': 5,
                'setup_name': 'Bodyguard to Second Quarter Level',
                'target_level': second_quarter,
                'stop_loss': protected_quarter,
                'take_profit_pips': 250,
                'stop_loss_pips': 75,
                'risk_reward_ratio': 3.33
            })
    
    return setups

def calculate_candlestick_sentiment(open_price, high_price, low_price, close_price):
    """Calculates candlestick sentiment based on where the close falls within the range."""
    if high_price == low_price:  # Avoid division by zero
        return 'neutral', 50.0
    
    range_size = high_price - low_price
    close_position = close_price - low_price
    sentiment_percentage = (close_position / range_size) * 100
    
    if sentiment_percentage >= 80:
        return 'very_bullish', sentiment_percentage
    elif sentiment_percentage >= 60:
        return 'bullish', sentiment_percentage
    elif sentiment_percentage >= 40:
        return 'neutral', sentiment_percentage
    elif sentiment_percentage >= 20:
        return 'bearish', sentiment_percentage
    else:
        return 'very_bearish', sentiment_percentage

def confirm_breakout(price_data, target_level, direction):
    """Confirms that price has broken through a level with a proper close."""
    current_candle = price_data.iloc[-1]
    close_price = current_candle['close']
    
    if direction == 'long':
        return close_price > target_level
    elif direction == 'short':
        return close_price < target_level
    else:
        return False

def quarters_theory_signal(price_data, instrument, timeframe='4H'):
    """
    Complete signal generation for Quarters Theory with Bodyguard Levels strategy.
    Returns entry signals with all required confirmations.
    """
    current_price = price_data['close'].iloc[-1]
    current_candle = price_data.iloc[-1]
    
    # Get psychological levels
    psych_levels = get_psychological_levels(current_price, instrument)
    
    # Calculate bodyguard levels
    bodyguard_levels = calculate_bodyguard_levels(psych_levels)
    
    # Calculate candlestick sentiment
    sentiment, sentiment_pct = calculate_candlestick_sentiment(
        current_candle['open'],
        current_candle['high'], 
        current_candle['low'],
        current_candle['close']
    )
    
    signals = []
    
    # Check for long signals (bullish sentiment + break above bodyguard)
    if sentiment in ['bullish', 'very_bullish']:
        for level_type, levels in bodyguard_levels.items():
            for level in levels:
                if confirm_breakout(price_data, level, 'long'):
                    # Find the corresponding quarter level (75 pips below this bodyguard)
                    pip_value = 0.0001 if 'JPY' not in instrument else 0.01
                    quarter_level = level - (75 * pip_value)
                    stop_loss = quarter_level
                    take_profit = level + (350 * pip_value)
                    
                    signals.append({
                        'direction': 'long',
                        'entry_level': level,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_pips': 75,
                        'reward_pips': 350,
                        'rr_ratio': 4.67,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
    
    # Check for short signals (bearish sentiment + break below bodyguard)
    elif sentiment in ['bearish', 'very_bearish']:
        for level_type, levels in bodyguard_levels.items():
            for level in levels:
                if confirm_breakout(price_data, level, 'short'):
                    # Find the corresponding quarter level (75 pips above this bodyguard)
                    pip_value = 0.0001 if 'JPY' not in instrument else 0.01
                    quarter_level = level + (75 * pip_value)
                    stop_loss = quarter_level
                    take_profit = level - (350 * pip_value)
                    
                    signals.append({
                        'direction': 'short',
                        'entry_level': level,
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_pips': 75,
                        'reward_pips': 350,
                        'rr_ratio': 4.67,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
    
    return signals


def generate_static_round_levels(current_price, instrument, level_type='all', range_pips=500):
    """Generates static round number levels based on institutional Forex Road Map."""
    is_jpy = 'JPY' in instrument
    pip_value = 0.01 if is_jpy else 0.0001
    
    levels = {
        'dimes': [],
        'big_quarters': [],
        'pennies': [],
        'small_quarters': []
    }
    
    if is_jpy:
        # JPY pairs (2 decimal places)
        base_price = int(current_price)
        price_range = range(base_price - range_pips//100, base_price + range_pips//100 + 1)
        
        for price in price_range:
            # Dimes: XX0.00, XX5.00
            if price % 5 == 0:
                levels['dimes'].append(float(price))
            
            # Big Quarters: XX0.00, XX2.50, XX5.00, XX7.50
            for quarter in [0, 2.5, 5, 7.5]:
                level = price + quarter
                levels['big_quarters'].append(level)
            
            # Pennies: XX.00, XX.50
            for penny in [0, 0.5]:
                level = price + penny
                levels['pennies'].append(level)
            
            # Small Quarters: XX.00, XX.25, XX.50, XX.75
            for small_q in [0, 0.25, 0.5, 0.75]:
                level = price + small_q
                levels['small_quarters'].append(level)
    
    else:
        # Non-JPY pairs (4 decimal places)
        base_price = round(current_price, 1)
        price_range_start = base_price - (range_pips * pip_value)
        price_range_end = base_price + (range_pips * pip_value)
        
        # Generate levels in the range
        current = price_range_start
        while current <= price_range_end:
            # Dimes: X.0000, X.1000, X.2000, etc.
            if current % 0.1 == 0:
                levels['dimes'].append(round(current, 4))
            
            # Big Quarters: X.X000, X.X250, X.X500, X.X750
            decimal_part = current % 0.1
            if decimal_part in [0, 0.025, 0.05, 0.075]:
                levels['big_quarters'].append(round(current, 4))
            
            # Pennies: X.XX00, X.XX50
            if current % 0.01 in [0, 0.005]:
                levels['pennies'].append(round(current, 4))
            
            # Small Quarters: X.XXX00, X.XXX25, X.XXX50, X.XXX75
            if current % 0.001 in [0, 0.00025, 0.0005, 0.00075]:
                levels['small_quarters'].append(round(current, 4))
            
            current += 0.00025  # Increment by smallest unit
    
    # Remove duplicates and sort
    for level_category in levels:
        levels[level_category] = sorted(list(set(levels[level_category])))
    
    if level_type == 'all':
        return levels
    else:
        return levels.get(level_type, [])

def classify_level_hierarchy(level, instrument):
    """Classifies a round number level by its institutional hierarchy."""
    is_jpy = 'JPY' in instrument
    
    if is_jpy:
        # JPY classification
        if level % 5 == 0:
            return 'dimes', 4  # Highest priority
        elif level % 2.5 == 0:
            return 'big_quarters', 3
        elif level % 0.5 == 0:
            return 'pennies', 2
        elif level % 0.25 == 0:
            return 'small_quarters', 1
        else:
            return 'none', 0
    else:
        # Non-JPY classification
        if level % 0.1 == 0:
            return 'dimes', 4  # Highest priority
        elif level % 0.025 == 0:
            return 'big_quarters', 3
        elif level % 0.005 == 0:
            return 'pennies', 2
        elif level % 0.00025 == 0:
            return 'small_quarters', 1
        else:
            return 'none', 0

def analyze_price_action_confluence(price_data, round_level, lookback_periods=100):
    """Analyzes confluence factors at a round number level."""
    confluence_score = 0
    confluence_factors = []
    
    # Check for previous support/resistance
    touches = 0
    for i in range(min(lookback_periods, len(price_data))):
        candle = price_data.iloc[-(i+1)]
        if candle['low'] <= round_level <= candle['high']:
            touches += 1
    
    if touches >= 3:
        confluence_score += 1
        confluence_factors.append('previous_support_resistance')
    
    # Check for moving average confluence (example with 200 SMA)
    if len(price_data) >= 200:
        sma_200 = price_data['close'].rolling(200).mean().iloc[-1]
        if abs(sma_200 - round_level) < (0.001 if 'JPY' not in str(round_level) else 0.1):
            confluence_score += 1
            confluence_factors.append('moving_average_confluence')
    
    # Check for recent high/low confluence
    recent_high = price_data['high'].tail(20).max()
    recent_low = price_data['low'].tail(20).min()
    
    if abs(recent_high - round_level) < (0.001 if 'JPY' not in str(round_level) else 0.1):
        confluence_score += 1
        confluence_factors.append('recent_high_confluence')
    elif abs(recent_low - round_level) < (0.001 if 'JPY' not in str(round_level) else 0.1):
        confluence_score += 1
        confluence_factors.append('recent_low_confluence')
    
    # Classify confluence strength
    if confluence_score >= 3:
        confluence_strength = 'high'
    elif confluence_score >= 2:
        confluence_strength = 'medium'
    elif confluence_score >= 1:
        confluence_strength = 'low'
    else:
        confluence_strength = 'none'
    
    return {
        'confluence_score': confluence_score,
        'confluence_strength': confluence_strength,
        'confluence_factors': confluence_factors
    }

def round_numbers_signal_generator(price_data, instrument, signal_type='both'):
    """
    Generates trading signals for Static Round Numbers strategy.
    signal_type: 'reversal', 'breakout', or 'both'
    """
    current_price = price_data['close'].iloc[-1]
    current_candle = price_data.iloc[-1]
    
    # Generate relevant round number levels
    round_levels = generate_static_round_levels(current_price, instrument)
    
    # Get candlestick sentiment
    sentiment, sentiment_pct = calculate_candlestick_sentiment(
        current_candle['open'],
        current_candle['high'],
        current_candle['low'],
        current_candle['close']
    )
    
    signals = []
    
    # Check each level type (prioritize higher hierarchy levels)
    for level_type in ['dimes', 'big_quarters', 'pennies', 'small_quarters']:
        for level in round_levels[level_type]:
            # Skip levels too far from current price
            distance = abs(current_price - level)
            max_distance = 0.01 if 'JPY' not in instrument else 1.0
            if distance > max_distance:
                continue
            
            # Classify level hierarchy
            hierarchy, priority = classify_level_hierarchy(level, instrument)
            
            # Analyze confluence
            confluence = analyze_price_action_confluence(price_data, level)
            
            # Only consider levels with at least medium confluence for higher hierarchy
            if hierarchy in ['dimes', 'big_quarters'] and confluence['confluence_strength'] == 'none':
                continue
            
            # Check for reversal signals
            if signal_type in ['reversal', 'both']:
                # Price approaching from below, bearish rejection
                if (current_price <= level and 
                    current_candle['high'] >= level and
                    sentiment in ['bearish', 'very_bearish']):
                    
                    signals.append({
                        'type': 'reversal',
                        'direction': 'short',
                        'entry_level': level,
                        'stop_loss': level + (50 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'take_profit': level - (100 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'level_hierarchy': hierarchy,
                        'priority': priority,
                        'confluence': confluence,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
                
                # Price approaching from above, bullish rejection
                elif (current_price >= level and 
                      current_candle['low'] <= level and
                      sentiment in ['bullish', 'very_bullish']):
                    
                    signals.append({
                        'type': 'reversal',
                        'direction': 'long',
                        'entry_level': level,
                        'stop_loss': level - (50 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'take_profit': level + (100 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'level_hierarchy': hierarchy,
                        'priority': priority,
                        'confluence': confluence,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
            
            # Check for breakout signals
            if signal_type in ['breakout', 'both']:
                # Bullish breakout above level
                if (current_candle['close'] > level and
                    current_candle['open'] <= level and
                    sentiment in ['bullish', 'very_bullish']):
                    
                    signals.append({
                        'type': 'breakout',
                        'direction': 'long',
                        'entry_level': level,
                        'stop_loss': level - (25 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'take_profit': level + (75 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'level_hierarchy': hierarchy,
                        'priority': priority,
                        'confluence': confluence,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
                
                # Bearish breakout below level
                elif (current_candle['close'] < level and
                      current_candle['open'] >= level and
                      sentiment in ['bearish', 'very_bearish']):
                    
                    signals.append({
                        'type': 'breakout',
                        'direction': 'short',
                        'entry_level': level,
                        'stop_loss': level + (25 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'take_profit': level - (75 * (0.01 if 'JPY' in instrument else 0.0001)),
                        'level_hierarchy': hierarchy,
                        'priority': priority,
                        'confluence': confluence,
                        'sentiment': sentiment,
                        'sentiment_pct': sentiment_pct
                    })
    
    # Sort signals by priority (higher hierarchy levels first)
    signals.sort(key=lambda x: x['priority'], reverse=True)
    
    return signals


def calculate_multi_timeframe_momentum(price_data, timeframes=None, trading_style='hourly'):
    """
    Calculates momentum across multiple timeframes.
    
    Args:
        price_data: DataFrame with OHLC data
        timeframes: Custom timeframes dict, or None for default
        trading_style: 'hourly', '4hour', or 'daily' for appropriate timeframe scaling
    """
    
    if timeframes is None:
        if trading_style == 'hourly':
            timeframes = {
                '48hr': 48,
                '24hr': 24, 
                '4hr': 4,
                '60min': 1,
                '15min': 0.25
            }
        elif trading_style == '4hour':
            timeframes = {
                '7days': 42,  # 7 days * 6 4hr candles per day
                '3days': 18,  # 3 days * 6 4hr candles per day
                '24hr': 6,    # 6 4hr candles in 24hr
                '8hr': 2,     # 2 4hr candles in 8hr
                '4hr': 1      # 1 4hr candle
            }
        elif trading_style == 'daily':
            timeframes = {
                '30days': 30,
                '14days': 14,
                '7days': 7,
                '3days': 3,
                '1day': 1
            }
    
    current_price = price_data['close'].iloc[-1]
    momentum_data = {}
    
    for period_name, periods in timeframes.items():
        if trading_style == 'hourly' and period_name == '15min':
            # For 15min, we need to look at sub-hourly data
            # This is a simplified approach - in practice you'd need 15min data
            if len(price_data) >= 1:
                past_price = price_data['close'].iloc[-1]  # Simplified
            else:
                past_price = current_price
        else:
            periods_int = int(periods)
            if len(price_data) > periods_int:
                past_price = price_data['close'].iloc[-(periods_int + 1)]
            else:
                past_price = price_data['close'].iloc[0]
        
        if past_price != 0:
            momentum_pct = ((current_price - past_price) / past_price) * 100
        else:
            momentum_pct = 0
            
        momentum_data[period_name] = round(momentum_pct, 3)
    
    return momentum_data

def analyze_momentum_alignment(momentum_data, threshold=0.05):
    """
    Analyzes momentum alignment across timeframes.
    
    Args:
        momentum_data: Dict of timeframe momentum percentages
        threshold: Minimum percentage to consider significant
    """
    
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    total_timeframes = len(momentum_data)
    
    for period, momentum in momentum_data.items():
        if momentum > threshold:
            positive_count += 1
        elif momentum < -threshold:
            negative_count += 1
        else:
            neutral_count += 1
    
    positive_ratio = positive_count / total_timeframes
    negative_ratio = negative_count / total_timeframes
    
    # Determine overall momentum bias
    if positive_ratio >= 0.8:
        momentum_bias = 'strong_bullish'
    elif positive_ratio >= 0.6:
        momentum_bias = 'weak_bullish'
    elif negative_ratio >= 0.8:
        momentum_bias = 'strong_bearish'
    elif negative_ratio >= 0.6:
        momentum_bias = 'weak_bearish'
    else:
        momentum_bias = 'neutral'
    
    # Check for divergence (shorter vs longer timeframes)
    timeframe_keys = list(momentum_data.keys())
    if len(timeframe_keys) >= 3:
        # Compare shortest 2 timeframes vs longest 2 timeframes
        short_term_avg = sum([momentum_data[timeframe_keys[-2]], momentum_data[timeframe_keys[-1]]]) / 2
        long_term_avg = sum([momentum_data[timeframe_keys[0]], momentum_data[timeframe_keys[1]]]) / 2
        
        divergence = False
        if (short_term_avg > threshold and long_term_avg < -threshold) or \
           (short_term_avg < -threshold and long_term_avg > threshold):
            divergence = True
    else:
        divergence = False
    
    return {
        'momentum_bias': momentum_bias,
        'positive_count': positive_count,
        'negative_count': negative_count,
        'neutral_count': neutral_count,
        'positive_ratio': positive_ratio,
        'negative_ratio': negative_ratio,
        'divergence_detected': divergence,
        'alignment_strength': max(positive_ratio, negative_ratio)
    }

def enhanced_round_numbers_signal_with_momentum(price_data, instrument, trading_style='hourly', signal_type='both'):
    """
    Enhanced round numbers signal generator that includes multi-timeframe momentum analysis.
    """
    
    # Get basic round numbers signals
    basic_signals = round_numbers_signal_generator(price_data, instrument, signal_type)
    
    # Calculate multi-timeframe momentum
    momentum_data = calculate_multi_timeframe_momentum(price_data, trading_style=trading_style)
    momentum_analysis = analyze_momentum_alignment(momentum_data)
    
    enhanced_signals = []
    
    for signal in basic_signals:
        # Add momentum data to signal
        signal['momentum_data'] = momentum_data
        signal['momentum_analysis'] = momentum_analysis
        
        # Filter signals based on momentum for penny levels
        if signal['level_hierarchy'] == 'pennies':
            # For penny levels, require stronger momentum alignment
            if momentum_analysis['alignment_strength'] < 0.6:
                continue  # Skip signals with weak momentum alignment
            
            # For penny level reversals, look for momentum divergence
            if signal['type'] == 'reversal' and not momentum_analysis['divergence_detected']:
                continue  # Skip reversal signals without momentum divergence
            
            # For penny level breakouts, require aligned momentum
            if signal['type'] == 'breakout':
                if signal['direction'] == 'long' and momentum_analysis['momentum_bias'] not in ['weak_bullish', 'strong_bullish']:
                    continue
                elif signal['direction'] == 'short' and momentum_analysis['momentum_bias'] not in ['weak_bearish', 'strong_bearish']:
                    continue
        
        # For higher hierarchy levels, momentum is confirmatory but not filtering
        elif signal['level_hierarchy'] in ['dimes', 'big_quarters']:
            # Add momentum confidence score
            if signal['direction'] == 'long':
                momentum_confidence = momentum_analysis['positive_ratio']
            else:
                momentum_confidence = momentum_analysis['negative_ratio']
            
            signal['momentum_confidence'] = momentum_confidence
        
        enhanced_signals.append(signal)
    
    return enhanced_signals

def format_momentum_scanner_output(momentum_data):
    """
    Formats momentum data in a scanner-like output for display.
    """
    scanner_output = []
    
    for timeframe, momentum_pct in momentum_data.items():
        color = 'green' if momentum_pct > 0 else 'red' if momentum_pct < 0 else 'neutral'
        scanner_output.append({
            'timeframe': timeframe,
            'momentum_pct': f"{momentum_pct:+.2f}%",
            'color': color
        })
    
    return scanner_output


def classify_quarter_level(quarter_level, method='digit_based'):
    """
    Classifies a quarter level as Green (support) or Red (resistance).
    
    Args:
        quarter_level: The quarter level price to classify
        method: 'digit_based' or 'historical_behavior'
    """
    
    if method == 'digit_based':
        # Extract the decimal portion to determine classification
        decimal_part = quarter_level % 1
        
        # Round to avoid floating point precision issues
        decimal_part = round(decimal_part, 4)
        
        # Green levels typically end in .25 or .75
        if decimal_part in [0.0025, 0.0075, 0.0225, 0.0275, 0.0425, 0.0475, 0.0625, 0.0675, 0.0825, 0.0875]:
            return 'green'
        # Red levels typically end in .00 or .50  
        elif decimal_part in [0.0000, 0.0050, 0.0200, 0.0250, 0.0400, 0.0450, 0.0600, 0.0650, 0.0800, 0.0850]:
            return 'red'
        else:
            # For levels ending in .25, .75 (quarter points)
            if str(decimal_part).endswith('25') or str(decimal_part).endswith('75'):
                return 'green'
            # For levels ending in .00, .50 (half and whole points)
            elif str(decimal_part).endswith('00') or str(decimal_part).endswith('50'):
                return 'red'
            else:
                return 'neutral'
    
    return 'neutral'

def identify_setup_type(entry_level, quarter_levels, max_distance=300):
    """
    Identifies which of the 5 setup types applies based on entry level and available targets.
    
    Args:
        entry_level: The quarter level where entry is planned
        quarter_levels: List of all available quarter levels
        max_distance: Maximum pips to consider for target selection
    """
    
    entry_classification = classify_quarter_level(entry_level)
    pip_value = 0.0001  # Assuming non-JPY pair
    
    # Find potential target levels within range
    potential_targets = []
    for level in quarter_levels:
        distance = abs(level - entry_level)
        if 0 < distance <= (max_distance * pip_value):
            target_classification = classify_quarter_level(level)
            potential_targets.append({
                'level': level,
                'classification': target_classification,
                'distance_pips': int(distance / pip_value)
            })
    
    # Sort by distance
    potential_targets.sort(key=lambda x: x['distance_pips'])
    
    setups = []
    
    if entry_classification == 'green':
        # Look for green targets (Setup #1 and #2)
        green_targets = [t for t in potential_targets if t['classification'] == 'green']
        
        for target in green_targets:
            distance = target['distance_pips']
            
            # Setup #1: Green to Green (Butter Middle) - ~100 pips
            if 75 <= distance <= 125:
                setups.append({
                    'setup_type': 1,
                    'setup_name': 'Green to Green (Butter Middle)',
                    'entry_level': entry_level,
                    'target_level': target['level'],
                    'stop_loss': entry_level - (25 * pip_value),
                    'take_profit_pips': 100,
                    'stop_loss_pips': 25,
                    'risk_reward_ratio': 4.0
                })
            
            # Setup #2: Green to Green (Red Middle) - ~150 pips
            elif 125 < distance <= 175:
                setups.append({
                    'setup_type': 2,
                    'setup_name': 'Green to Green (Red Middle)',
                    'entry_level': entry_level,
                    'target_level': target['level'],
                    'stop_loss': entry_level - (50 * pip_value),
                    'take_profit_pips': 150,
                    'stop_loss_pips': 50,
                    'risk_reward_ratio': 3.0
                })
        
        # Look for red targets (Setup #3)
        red_targets = [t for t in potential_targets if t['classification'] == 'red']
        
        for target in red_targets:
            distance = target['distance_pips']
            
            # Setup #3: Green to Opposing Red - ~175 pips
            if 150 <= distance <= 200:
                setups.append({
                    'setup_type': 3,
                    'setup_name': 'Green to Opposing Red',
                    'entry_level': entry_level,
                    'target_level': target['level'],
                    'stop_loss': entry_level - (75 * pip_value),
                    'take_profit_pips': 175,
                    'stop_loss_pips': 75,
                    'risk_reward_ratio': 2.33
                })
    
    elif entry_classification == 'red':
        # Look for green targets (Setup #4)
        green_targets = [t for t in potential_targets if t['classification'] == 'green']
        
        for target in green_targets:
            distance = target['distance_pips']
            
            # Setup #4: Red to Opposing Green - ~175 pips
            if 150 <= distance <= 200:
                setups.append({
                    'setup_type': 4,
                    'setup_name': 'Red to Opposing Green',
                    'entry_level': entry_level,
                    'target_level': target['level'],
                    'stop_loss': entry_level - (75 * pip_value),
                    'take_profit_pips': 175,
                    'stop_loss_pips': 75,
                    'risk_reward_ratio': 2.33
                })
        
        # Look for red targets (Setup #5)
        red_targets = [t for t in potential_targets if t['classification'] == 'red']
        
        for target in red_targets:
            distance = target['distance_pips']
            
            # Setup #5: Red to Red - ~250 pips
            if 225 <= distance <= 275:
                setups.append({
                    'setup_type': 5,
                    'setup_name': 'Red to Red',
                    'entry_level': entry_level,
                    'target_level': target['level'],
                    'stop_loss': entry_level - (75 * pip_value),
                    'take_profit_pips': 250,
                    'stop_loss_pips': 75,
                    'risk_reward_ratio': 3.33
                })
    
    return setups

def enhanced_quarters_theory_signal(price_data, instrument, timeframe='4H'):
    """
    Enhanced Quarters Theory signal generator with 5 setup types.
    """
    current_price = price_data['close'].iloc[-1]
    current_candle = price_data.iloc[-1]
    
    # Generate quarter levels around current price
    quarter_levels = []
    pip_value = 0.0001 if 'JPY' not in instrument else 0.01
    
    # Generate levels in a range around current price
    base_level = round(current_price / (0.0025 if 'JPY' not in instrument else 0.25)) * (0.0025 if 'JPY' not in instrument else 0.25)
    
    for i in range(-10, 11):
        level = base_level + (i * 0.0025 if 'JPY' not in instrument else i * 0.25)
        quarter_levels.append(round(level, 4 if 'JPY' not in instrument else 2))
    
    # Get candlestick sentiment
    sentiment, sentiment_pct = calculate_candlestick_sentiment(
        current_candle['open'],
        current_candle['high'],
        current_candle['low'],
        current_candle['close']
    )
    
    signals = []
    
    # Check each quarter level for potential entry
    for entry_level in quarter_levels:
        # Skip levels too far from current price
        distance = abs(current_price - entry_level)
        if distance > (50 * pip_value):  # Within 50 pips
            continue
        
        # Check if price has broken through this level
        if not confirm_breakout(price_data, entry_level, 'long' if current_price > entry_level else 'short'):
            continue
        
        # Identify available setups for this entry level
        available_setups = identify_setup_type(entry_level, quarter_levels)
        
        for setup in available_setups:
            # Check sentiment requirements
            if setup['setup_type'] in [1, 2]:  # Conservative setups
                required_sentiment = ['bullish', 'very_bullish'] if current_price > entry_level else ['bearish', 'very_bearish']
            else:  # More aggressive setups
                required_sentiment = ['very_bullish'] if current_price > entry_level else ['very_bearish']
            
            if sentiment in required_sentiment:
                signal = {
                    'direction': 'long' if current_price > entry_level else 'short',
                    'setup_type': setup['setup_type'],
                    'setup_name': setup['setup_name'],
                    'entry_level': setup['entry_level'],
                    'target_level': setup['target_level'],
                    'stop_loss': setup['stop_loss'],
                    'take_profit_pips': setup['take_profit_pips'],
                    'stop_loss_pips': setup['stop_loss_pips'],
                    'risk_reward_ratio': setup['risk_reward_ratio'],
                    'sentiment': sentiment,
                    'sentiment_pct': sentiment_pct,
                    'entry_classification': classify_quarter_level(setup['entry_level']),
                    'target_classification': classify_quarter_level(setup['target_level'])
                }
                
                signals.append(signal)
    
    # Sort by setup type priority (Setup #1 highest priority)
    signals.sort(key=lambda x: x['setup_type'])
    
    return signals


def get_static_quarter_levels(min_level=0.0, max_level=3.0):
    """
    Returns static quarter levels from the predefined list to avoid calculation errors.
    Quarter levels always end in .000, .250, .500, .750
    
    Args:
        min_level: Minimum level to include (default 0.0)
        max_level: Maximum level to include (default 3.0)
    """
    
    # Static list of all quarter levels from 0 to 3
    quarter_levels = [
        # 0.0000 - 0.9750 Range
        0.0000, 0.0250, 0.0500, 0.0750, 0.1000, 0.1250, 0.1500, 0.1750,
        0.2000, 0.2250, 0.2500, 0.2750, 0.3000, 0.3250, 0.3500, 0.3750,
        0.4000, 0.4250, 0.4500, 0.4750, 0.5000, 0.5250, 0.5500, 0.5750,
        0.6000, 0.6250, 0.6500, 0.6750, 0.7000, 0.7250, 0.7500, 0.7750,
        0.8000, 0.8250, 0.8500, 0.8750, 0.9000, 0.9250, 0.9500, 0.9750,
        
        # 1.0000 - 1.9750 Range
        1.0000, 1.0250, 1.0500, 1.0750, 1.1000, 1.1250, 1.1500, 1.1750,
        1.2000, 1.2250, 1.2500, 1.2750, 1.3000, 1.3250, 1.3500, 1.3750,
        1.4000, 1.4250, 1.4500, 1.4750, 1.5000, 1.5250, 1.5500, 1.5750,
        1.6000, 1.6250, 1.6500, 1.6750, 1.7000, 1.7250, 1.7500, 1.7750,
        1.8000, 1.8250, 1.8500, 1.8750, 1.9000, 1.9250, 1.9500, 1.9750,
        
        # 2.0000 - 2.9750 Range
        2.0000, 2.0250, 2.0500, 2.0750, 2.1000, 2.1250, 2.1500, 2.1750,
        2.2000, 2.2250, 2.2500, 2.2750, 2.3000, 2.3250, 2.3500, 2.3750,
        2.4000, 2.4250, 2.4500, 2.4750, 2.5000, 2.5250, 2.5500, 2.5750,
        2.6000, 2.6250, 2.6500, 2.6750, 2.7000, 2.7250, 2.7500, 2.7750,
        2.8000, 2.8250, 2.8500, 2.8750, 2.9000, 2.9250, 2.9500, 2.9750,
        
        # 3.0000
        3.0000
    ]
    
    # Filter levels within the specified range
    filtered_levels = [level for level in quarter_levels if min_level <= level <= max_level]
    
    return filtered_levels

def get_quarter_levels_around_price(current_price, range_pips=500):
    """
    Gets quarter levels around the current price within a specified pip range.
    Uses static quarter levels list to avoid calculation errors.
    
    Args:
        current_price: Current market price
        range_pips: Range in pips to look for quarter levels (default 500)
    """
    
    pip_value = 0.0001  # For non-JPY pairs
    range_value = range_pips * pip_value
    
    min_level = max(0.0, current_price - range_value)
    max_level = min(3.0, current_price + range_value)
    
    # Get all quarter levels in range
    all_quarters = get_static_quarter_levels(min_level, max_level)
    
    # Find levels closest to current price
    relevant_quarters = []
    for level in all_quarters:
        distance = abs(current_price - level)
        if distance <= range_value:
            relevant_quarters.append({
                'level': level,
                'distance_pips': int(distance / pip_value),
                'above_price': level > current_price
            })
    
    # Sort by distance from current price
    relevant_quarters.sort(key=lambda x: x['distance_pips'])
    
    return relevant_quarters

def get_bodyguards_for_quarter(quarter_level):
    """
    Gets the bodyguard levels for a specific quarter level.
    Bodyguards are always 75 pips (0.0075) above and below the quarter.
    
    Args:
        quarter_level: The quarter level to get bodyguards for
    """
    
    bodyguard_distance = 0.0075  # 75 pips
    
    upper_bodyguard = round(quarter_level + bodyguard_distance, 4)
    lower_bodyguard = round(quarter_level - bodyguard_distance, 4)
    
    return {
        'quarter_level': quarter_level,
        'upper_bodyguard': upper_bodyguard,
        'lower_bodyguard': lower_bodyguard,
        'bodyguards': [lower_bodyguard, upper_bodyguard]
    }

def validate_quarter_level(level):
    """
    Validates if a given level is a true quarter level.
    Quarter levels always end in .000, .250, .500, .750
    
    Args:
        level: Price level to validate
    """
    
    # Get the decimal part
    decimal_part = level % 1
    decimal_part = round(decimal_part, 4)
    
    # Valid quarter endings
    valid_endings = [0.0000, 0.0250, 0.0500, 0.0750]
    
    # Check if the decimal part matches any valid ending
    for ending in valid_endings:
        if abs(decimal_part - ending) < 0.0001:
            return True
    
    return False

def find_nearest_quarter_level(price):
    """
    Finds the nearest quarter level to a given price.
    Uses static list to ensure accuracy.
    
    Args:
        price: Current price to find nearest quarter for
    """
    
    # Get quarter levels around the price
    quarters = get_quarter_levels_around_price(price, range_pips=200)
    
    if not quarters:
        return None
    
    # Return the closest quarter level
    return quarters[0]['level']



# JPY Quarter Levels Functions

def get_static_jpy_quarter_levels(min_level=50.0, max_level=300.0):
    """
    Returns static JPY quarter levels from the predefined list to avoid calculation errors.
    JPY quarter levels always end in .00, 2.50, 5.00, 7.50
    
    Args:
        min_level: Minimum level to include (default 50.0)
        max_level: Maximum level to include (default 300.0)
    """
    
    # Static list of all JPY quarter levels from 50 to 300
    jpy_quarter_levels = [
        # 50.00 - 99.50 Range
        50.00, 52.50, 55.00, 57.50, 60.00, 62.50, 65.00, 67.50,
        70.00, 72.50, 75.00, 77.50, 80.00, 82.50, 85.00, 87.50,
        90.00, 92.50, 95.00, 97.50,
        
        # 100.00 - 149.50 Range
        100.00, 102.50, 105.00, 107.50, 110.00, 112.50, 115.00, 117.50,
        120.00, 122.50, 125.00, 127.50, 130.00, 132.50, 135.00, 137.50,
        140.00, 142.50, 145.00, 147.50,
        
        # 150.00 - 199.50 Range
        150.00, 152.50, 155.00, 157.50, 160.00, 162.50, 165.00, 167.50,
        170.00, 172.50, 175.00, 177.50, 180.00, 182.50, 185.00, 187.50,
        190.00, 192.50, 195.00, 197.50,
        
        # 200.00 - 249.50 Range
        200.00, 202.50, 205.00, 207.50, 210.00, 212.50, 215.00, 217.50,
        220.00, 222.50, 225.00, 227.50, 230.00, 232.50, 235.00, 237.50,
        240.00, 242.50, 245.00, 247.50,
        
        # 250.00 - 300.00 Range
        250.00, 252.50, 255.00, 257.50, 260.00, 262.50, 265.00, 267.50,
        270.00, 272.50, 275.00, 277.50, 280.00, 282.50, 285.00, 287.50,
        290.00, 292.50, 295.00, 297.50, 300.00
    ]
    
    # Filter levels within the specified range
    filtered_levels = [level for level in jpy_quarter_levels if min_level <= level <= max_level]
    
    return filtered_levels

def get_jpy_quarter_levels_around_price(current_price, range_pips=500):
    """
    Gets JPY quarter levels around the current price within a specified pip range.
    Uses static JPY quarter levels list to avoid calculation errors.
    
    Args:
        current_price: Current market price for JPY pair
        range_pips: Range in pips to look for quarter levels (default 500)
    """
    
    pip_value = 0.01  # For JPY pairs
    range_value = range_pips * pip_value
    
    min_level = max(50.0, current_price - range_value)
    max_level = min(300.0, current_price + range_value)
    
    # Get all quarter levels in range
    all_quarters = get_static_jpy_quarter_levels(min_level, max_level)
    
    # Find levels closest to current price
    relevant_quarters = []
    for level in all_quarters:
        distance = abs(current_price - level)
        if distance <= range_value:
            relevant_quarters.append({
                'level': level,
                'distance_pips': int(distance / pip_value),
                'above_price': level > current_price
            })
    
    # Sort by distance from current price
    relevant_quarters.sort(key=lambda x: x['distance_pips'])
    
    return relevant_quarters

def get_jpy_bodyguards_for_quarter(quarter_level):
    """
    Gets the bodyguard levels for a specific JPY quarter level.
    Bodyguards are always 75 pips (0.75) above and below the quarter.
    
    Args:
        quarter_level: The JPY quarter level to get bodyguards for
    """
    
    bodyguard_distance = 0.75  # 75 pips for JPY
    
    upper_bodyguard = round(quarter_level + bodyguard_distance, 2)
    lower_bodyguard = round(quarter_level - bodyguard_distance, 2)
    
    return {
        'quarter_level': quarter_level,
        'upper_bodyguard': upper_bodyguard,
        'lower_bodyguard': lower_bodyguard,
        'bodyguards': [lower_bodyguard, upper_bodyguard]
    }

def validate_jpy_quarter_level(level):
    """
    Validates if a given level is a true JPY quarter level.
    JPY quarter levels always end in .00, 2.50, 5.00, 7.50
    
    Args:
        level: Price level to validate
    """
    
    # Get the decimal part
    decimal_part = (level * 100) % 1000
    decimal_part = round(decimal_part, 0)
    
    # Valid JPY quarter endings (in hundredths)
    valid_endings = [0, 250, 500, 750]  # .00, 2.50, 5.00, 7.50
    
    # Check if the decimal part matches any valid ending
    return decimal_part in valid_endings

def find_nearest_jpy_quarter_level(price):
    """
    Finds the nearest JPY quarter level to a given price.
    Uses static list to ensure accuracy.
    
    Args:
        price: Current JPY pair price to find nearest quarter for
    """
    
    # Get quarter levels around the price
    quarters = get_jpy_quarter_levels_around_price(price, range_pips=200)
    
    if not quarters:
        return None
    
    # Return the closest quarter level
    return quarters[0]['level']

def is_jpy_pair(instrument):
    """
    Determines if a currency pair is a JPY pair.
    
    Args:
        instrument: Currency pair symbol (e.g., 'USDJPY', 'EURJPY')
    """
    
    return 'JPY' in instrument.upper()

def get_quarter_levels_for_instrument(instrument, current_price, range_pips=500):
    """
    Gets appropriate quarter levels based on instrument type (JPY or non-JPY).
    
    Args:
        instrument: Currency pair symbol
        current_price: Current market price
        range_pips: Range in pips to search
    """
    
    if is_jpy_pair(instrument):
        return get_jpy_quarter_levels_around_price(current_price, range_pips)
    else:
        return get_quarter_levels_around_price(current_price, range_pips)

def get_bodyguards_for_instrument(instrument, quarter_level):
    """
    Gets appropriate bodyguard levels based on instrument type (JPY or non-JPY).
    
    Args:
        instrument: Currency pair symbol
        quarter_level: The quarter level to get bodyguards for
    """
    
    if is_jpy_pair(instrument):
        return get_jpy_bodyguards_for_quarter(quarter_level)
    else:
        return get_bodyguards_for_quarter(quarter_level)

