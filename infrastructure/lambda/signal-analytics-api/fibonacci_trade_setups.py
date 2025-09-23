import numpy as np
from datetime import datetime

def generate_fibonacci_trade_setups(fibonacci_analysis, current_price, trend_direction, institutional_levels=None, is_jpy=False):
    """
    Generate complete trade setups from Fibonacci analysis.
    
    Args:
        fibonacci_analysis: Output from robust swing detection with Fibonacci levels
        current_price: Current market price
        trend_direction: 'uptrend' or 'downtrend'
        institutional_levels: Optional institutional levels for confluence
        is_jpy: True for JPY pairs
    
    Returns:
        Dictionary with complete trade setups
    """
    
    if not fibonacci_analysis or not fibonacci_analysis.get('fibonacci_sets'):
        return {'trade_setups': [], 'message': 'No Fibonacci analysis available'}
    
    pip_value = 0.01 if is_jpy else 0.0001
    decimal_places = 2 if is_jpy else 4
    
    trade_setups = []
    
    # Get the most relevant Fibonacci set
    most_relevant = fibonacci_analysis['most_relevant']
    if not most_relevant:
        return {'trade_setups': [], 'message': 'No relevant Fibonacci levels found'}
    
    retracement_levels = most_relevant['retracement_levels']
    extension_levels = most_relevant['extension_levels']
    high_swing = most_relevant['high_swing']
    low_swing = most_relevant['low_swing']
    
    # Generate trade setups based on trend direction
    if trend_direction.lower() == 'uptrend':
        setups = generate_uptrend_setups(
            retracement_levels, extension_levels, high_swing, low_swing, 
            current_price, institutional_levels, pip_value, decimal_places
        )
    else:  # downtrend
        setups = generate_downtrend_setups(
            retracement_levels, extension_levels, high_swing, low_swing, 
            current_price, institutional_levels, pip_value, decimal_places
        )
    
    return {
        'trade_setups': setups,
        'trend_direction': trend_direction,
        'fibonacci_range_pips': most_relevant['swing_range_pips'],
        'high_swing': high_swing,
        'low_swing': low_swing,
        'current_price': current_price,
        'total_setups': len(setups)
    }

def generate_uptrend_setups(retracement_levels, extension_levels, high_swing, low_swing, current_price, institutional_levels, pip_value, decimal_places):
    """Generate trade setups for uptrend scenarios."""
    
    setups = []
    
    # Key Fibonacci retracement levels for uptrend entries
    key_retracement_ratios = ['0.382', '0.500', '0.618', '0.786']
    
    # Strategy 1: Fibonacci Retracement Entries (Buy the Dip)
    for ratio in key_retracement_ratios:
        if ratio in retracement_levels:
            fib_level = retracement_levels[ratio]
            entry_price = fib_level['price']
            
            # Only consider if price is near or above this level
            distance_to_entry = abs(current_price - entry_price)
            max_distance = 50 * pip_value  # Within 50 pips
            
            if distance_to_entry <= max_distance:
                # Determine stop loss (below next deeper retracement or swing low)
                stop_loss = determine_uptrend_stop_loss(ratio, retracement_levels, low_swing, pip_value)
                
                # Determine targets (previous high and extensions)
                targets = determine_uptrend_targets(high_swing, extension_levels, entry_price)
                
                # Calculate risk/reward
                risk_pips = int(abs(entry_price - stop_loss) / pip_value)
                reward_pips = int(abs(targets[0] - entry_price) / pip_value) if targets else 0
                risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
                
                # Check for institutional confluence
                confluence = check_institutional_confluence(entry_price, institutional_levels, pip_value) if institutional_levels else None
                
                setup = {
                    'setup_id': f'uptrend_retracement_{ratio}',
                    'strategy': 'Fibonacci Retracement Entry',
                    'direction': 'long',
                    'entry_price': round(entry_price, decimal_places),
                    'stop_loss': round(stop_loss, decimal_places),
                    'targets': [round(target, decimal_places) for target in targets],
                    'fibonacci_level': f'{float(ratio):.1%} Retracement',
                    'risk_pips': risk_pips,
                    'reward_pips': reward_pips,
                    'risk_reward_ratio': round(risk_reward_ratio, 2),
                    'distance_to_entry_pips': int(distance_to_entry / pip_value),
                    'confluence': confluence,
                    'setup_quality': calculate_setup_quality(risk_reward_ratio, confluence, distance_to_entry, pip_value),
                    'entry_condition': f'Buy at {float(ratio):.1%} Fibonacci retracement in uptrend',
                    'invalidation': f'Close below {round(stop_loss, decimal_places)}'
                }
                
                setups.append(setup)
    
    # Strategy 2: Fibonacci Extension Breakout (Trend Continuation)
    previous_high = high_swing['price']
    
    # Only if current price is near the previous high
    if abs(current_price - previous_high) <= 30 * pip_value:
        
        # Extension targets
        extension_ratios = ['1.272', '1.382', '1.618', '2.000']
        extension_targets = []
        
        for ratio in extension_ratios:
            if ratio in extension_levels:
                extension_targets.append(extension_levels[ratio]['price'])
        
        if extension_targets:
            entry_price = previous_high + (5 * pip_value)  # Breakout entry above high
            stop_loss = determine_breakout_stop_loss(retracement_levels, previous_high, pip_value)
            
            risk_pips = int(abs(entry_price - stop_loss) / pip_value)
            reward_pips = int(abs(extension_targets[0] - entry_price) / pip_value)
            risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
            
            # Check confluence at breakout level
            confluence = check_institutional_confluence(entry_price, institutional_levels, pip_value) if institutional_levels else None
            
            setup = {
                'setup_id': 'uptrend_extension_breakout',
                'strategy': 'Fibonacci Extension Breakout',
                'direction': 'long',
                'entry_price': round(entry_price, decimal_places),
                'stop_loss': round(stop_loss, decimal_places),
                'targets': [round(target, decimal_places) for target in extension_targets],
                'fibonacci_level': 'Extension Breakout',
                'risk_pips': risk_pips,
                'reward_pips': reward_pips,
                'risk_reward_ratio': round(risk_reward_ratio, 2),
                'distance_to_entry_pips': int(abs(current_price - entry_price) / pip_value),
                'confluence': confluence,
                'setup_quality': calculate_setup_quality(risk_reward_ratio, confluence, abs(current_price - entry_price), pip_value),
                'entry_condition': f'Buy breakout above {round(previous_high, decimal_places)}',
                'invalidation': f'Close below {round(stop_loss, decimal_places)}'
            }
            
            setups.append(setup)
    
    # Sort setups by quality
    setups.sort(key=lambda x: x['setup_quality'], reverse=True)
    
    return setups

def generate_downtrend_setups(retracement_levels, extension_levels, high_swing, low_swing, current_price, institutional_levels, pip_value, decimal_places):
    """Generate trade setups for downtrend scenarios."""
    
    setups = []
    
    # Key Fibonacci retracement levels for downtrend entries (sell the rally)
    key_retracement_ratios = ['0.382', '0.500', '0.618', '0.786']
    
    # Strategy 1: Fibonacci Retracement Entries (Sell the Rally)
    for ratio in key_retracement_ratios:
        if ratio in retracement_levels:
            fib_level = retracement_levels[ratio]
            entry_price = fib_level['price']
            
            # Only consider if price is near or below this level
            distance_to_entry = abs(current_price - entry_price)
            max_distance = 50 * pip_value
            
            if distance_to_entry <= max_distance:
                # Stop loss above next higher retracement or swing high
                stop_loss = determine_downtrend_stop_loss(ratio, retracement_levels, high_swing, pip_value)
                
                # Targets (previous low and extensions)
                targets = determine_downtrend_targets(low_swing, extension_levels, entry_price)
                
                risk_pips = int(abs(stop_loss - entry_price) / pip_value)
                reward_pips = int(abs(entry_price - targets[0]) / pip_value) if targets else 0
                risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
                
                confluence = check_institutional_confluence(entry_price, institutional_levels, pip_value) if institutional_levels else None
                
                setup = {
                    'setup_id': f'downtrend_retracement_{ratio}',
                    'strategy': 'Fibonacci Retracement Entry',
                    'direction': 'short',
                    'entry_price': round(entry_price, decimal_places),
                    'stop_loss': round(stop_loss, decimal_places),
                    'targets': [round(target, decimal_places) for target in targets],
                    'fibonacci_level': f'{float(ratio):.1%} Retracement',
                    'risk_pips': risk_pips,
                    'reward_pips': reward_pips,
                    'risk_reward_ratio': round(risk_reward_ratio, 2),
                    'distance_to_entry_pips': int(distance_to_entry / pip_value),
                    'confluence': confluence,
                    'setup_quality': calculate_setup_quality(risk_reward_ratio, confluence, distance_to_entry, pip_value),
                    'entry_condition': f'Sell at {float(ratio):.1%} Fibonacci retracement in downtrend',
                    'invalidation': f'Close above {round(stop_loss, decimal_places)}'
                }
                
                setups.append(setup)
    
    # Strategy 2: Fibonacci Extension Breakdown (Trend Continuation)
    previous_low = low_swing['price']
    
    if abs(current_price - previous_low) <= 30 * pip_value:
        
        extension_ratios = ['1.272', '1.382', '1.618', '2.000']
        extension_targets = []
        
        for ratio in extension_ratios:
            if ratio in extension_levels:
                extension_targets.append(extension_levels[ratio]['price'])
        
        if extension_targets:
            entry_price = previous_low - (5 * pip_value)  # Breakdown entry below low
            stop_loss = determine_breakdown_stop_loss(retracement_levels, previous_low, pip_value)
            
            risk_pips = int(abs(stop_loss - entry_price) / pip_value)
            reward_pips = int(abs(entry_price - extension_targets[0]) / pip_value)
            risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
            
            confluence = check_institutional_confluence(entry_price, institutional_levels, pip_value) if institutional_levels else None
            
            setup = {
                'setup_id': 'downtrend_extension_breakdown',
                'strategy': 'Fibonacci Extension Breakdown',
                'direction': 'short',
                'entry_price': round(entry_price, decimal_places),
                'stop_loss': round(stop_loss, decimal_places),
                'targets': [round(target, decimal_places) for target in extension_targets],
                'fibonacci_level': 'Extension Breakdown',
                'risk_pips': risk_pips,
                'reward_pips': reward_pips,
                'risk_reward_ratio': round(risk_reward_ratio, 2),
                'distance_to_entry_pips': int(abs(current_price - entry_price) / pip_value),
                'confluence': confluence,
                'setup_quality': calculate_setup_quality(risk_reward_ratio, confluence, abs(current_price - entry_price), pip_value),
                'entry_condition': f'Sell breakdown below {round(previous_low, decimal_places)}',
                'invalidation': f'Close above {round(stop_loss, decimal_places)}'
            }
            
            setups.append(setup)
    
    setups.sort(key=lambda x: x['setup_quality'], reverse=True)
    return setups

def determine_uptrend_stop_loss(current_ratio, retracement_levels, low_swing, pip_value):
    """Determine appropriate stop loss for uptrend setups."""
    
    # Get deeper retracement levels
    ratio_values = {'0.382': 0.382, '0.500': 0.500, '0.618': 0.618, '0.786': 0.786, '1.000': 1.000}
    current_value = ratio_values.get(current_ratio, 0.5)
    
    # Find next deeper level
    deeper_levels = [ratio for ratio, value in ratio_values.items() 
                    if value > current_value and ratio in retracement_levels]
    
    if deeper_levels:
        # Use next deeper Fibonacci level minus buffer
        next_deeper = min(deeper_levels, key=lambda x: ratio_values[x])
        stop_price = retracement_levels[next_deeper]['price'] - (10 * pip_value)
    else:
        # Use swing low minus buffer
        stop_price = low_swing['price'] - (15 * pip_value)
    
    return stop_price

def determine_downtrend_stop_loss(current_ratio, retracement_levels, high_swing, pip_value):
    """Determine appropriate stop loss for downtrend setups."""
    
    ratio_values = {'0.382': 0.382, '0.500': 0.500, '0.618': 0.618, '0.786': 0.786, '1.000': 1.000}
    current_value = ratio_values.get(current_ratio, 0.5)
    
    # Find next shallower level
    shallower_levels = [ratio for ratio, value in ratio_values.items() 
                       if value < current_value and ratio in retracement_levels]
    
    if shallower_levels:
        next_shallower = max(shallower_levels, key=lambda x: ratio_values[x])
        stop_price = retracement_levels[next_shallower]['price'] + (10 * pip_value)
    else:
        # Use swing high plus buffer
        stop_price = high_swing['price'] + (15 * pip_value)
    
    return stop_price

def determine_uptrend_targets(high_swing, extension_levels, entry_price):
    """Determine target levels for uptrend setups."""
    
    targets = []
    
    # Primary target: Previous high
    targets.append(high_swing['price'])
    
    # Extension targets
    extension_ratios = ['1.272', '1.618', '2.000']
    for ratio in extension_ratios:
        if ratio in extension_levels:
            targets.append(extension_levels[ratio]['price'])
    
    # Filter targets above entry price
    targets = [target for target in targets if target > entry_price]
    targets.sort()  # Ascending order
    
    return targets[:3]  # Maximum 3 targets

def determine_downtrend_targets(low_swing, extension_levels, entry_price):
    """Determine target levels for downtrend setups."""
    
    targets = []
    
    # Primary target: Previous low
    targets.append(low_swing['price'])
    
    # Extension targets
    extension_ratios = ['1.272', '1.618', '2.000']
    for ratio in extension_ratios:
        if ratio in extension_levels:
            targets.append(extension_levels[ratio]['price'])
    
    # Filter targets below entry price
    targets = [target for target in targets if target < entry_price]
    targets.sort(reverse=True)  # Descending order
    
    return targets[:3]  # Maximum 3 targets

def determine_breakout_stop_loss(retracement_levels, previous_high, pip_value):
    """Determine stop loss for breakout setups."""
    
    # Use 50% retracement or previous high minus buffer
    if '0.500' in retracement_levels:
        return retracement_levels['0.500']['price']
    else:
        return previous_high - (20 * pip_value)

def determine_breakdown_stop_loss(retracement_levels, previous_low, pip_value):
    """Determine stop loss for breakdown setups."""
    
    # Use 50% retracement or previous low plus buffer
    if '0.500' in retracement_levels:
        return retracement_levels['0.500']['price']
    else:
        return previous_low + (20 * pip_value)

def check_institutional_confluence(price, institutional_levels, pip_value, tolerance_pips=10):
    """Check if Fibonacci level aligns with institutional levels."""
    
    if not institutional_levels:
        return None
    
    tolerance = tolerance_pips * pip_value
    confluences = []
    
    # Check all institutional level types
    for level_type, levels in institutional_levels.items():
        for level in levels:
            if abs(price - level) <= tolerance:
                distance_pips = int(abs(price - level) / pip_value)
                confluences.append({
                    'level_type': level_type,
                    'level_price': level,
                    'distance_pips': distance_pips
                })
    
    return confluences if confluences else None

def calculate_setup_quality(risk_reward_ratio, confluence, distance_to_entry, pip_value):
    """Calculate overall setup quality score."""
    
    score = 0
    
    # Risk/reward component (0-50 points)
    if risk_reward_ratio >= 3.0:
        score += 50
    elif risk_reward_ratio >= 2.0:
        score += 35
    elif risk_reward_ratio >= 1.5:
        score += 25
    elif risk_reward_ratio >= 1.0:
        score += 15
    
    # Confluence component (0-30 points)
    if confluence:
        confluence_count = len(confluence)
        score += min(confluence_count * 10, 30)
    
    # Distance to entry component (0-20 points)
    distance_pips = distance_to_entry / pip_value
    if distance_pips <= 10:
        score += 20
    elif distance_pips <= 25:
        score += 15
    elif distance_pips <= 50:
        score += 10
    
    return score

# Example usage based on the chart you showed
if __name__ == "__main__":
    print("=== Fibonacci Trade Setup Generation ===")
    
    # Simulate the EUR/USD scenario from your chart
    current_price = 1.1748  # Near 61.8% retracement
    trend_direction = 'uptrend'
    
    # Mock Fibonacci analysis (based on your chart levels)
    mock_fibonacci_analysis = {
        'most_relevant': {
            'swing_range_pips': 400,
            'high_swing': {'price': 1.1850},
            'low_swing': {'price': 1.1650},
            'retracement_levels': {
                '0.236': {'price': 1.1803, 'ratio': 0.236},
                '0.382': {'price': 1.1774, 'ratio': 0.382},
                '0.500': {'price': 1.1750, 'ratio': 0.500},
                '0.618': {'price': 1.1726, 'ratio': 0.618},
                '0.786': {'price': 1.1693, 'ratio': 0.786}
            },
            'extension_levels': {
                '1.272': {'price': 1.1904, 'ratio': 1.272},
                '1.618': {'price': 1.1973, 'ratio': 1.618},
                '2.000': {'price': 1.2050, 'ratio': 2.000}
            }
        },
        'fibonacci_sets': [{}]  # Non-empty to pass validation
    }
    
    # Mock institutional levels (from your chart)
    institutional_levels = {
        'quarters': [1.1750, 1.2000],
        'pennies': [1.1700, 1.1800],
        'dimes': [1.1000, 1.2000]
    }
    
    # Generate trade setups
    trade_analysis = generate_fibonacci_trade_setups(
        mock_fibonacci_analysis,
        current_price,
        trend_direction,
        institutional_levels,
        is_jpy=False
    )
    
    print(f"Current Price: {current_price}")
    print(f"Trend Direction: {trend_direction}")
    print(f"Total Setups Generated: {trade_analysis['total_setups']}")
    
    # Display trade setups
    for i, setup in enumerate(trade_analysis['trade_setups']):
        print(f"\n=== Setup {i+1}: {setup['strategy']} ===")
        print(f"Direction: {setup['direction'].upper()}")
        print(f"Entry: {setup['entry_price']}")
        print(f"Stop Loss: {setup['stop_loss']}")
        print(f"Targets: {setup['targets']}")
        print(f"Fibonacci Level: {setup['fibonacci_level']}")
        print(f"Risk: {setup['risk_pips']} pips")
        print(f"Reward: {setup['reward_pips']} pips")
        print(f"R:R Ratio: {setup['risk_reward_ratio']}:1")
        print(f"Setup Quality: {setup['setup_quality']}/100")
        
        if setup['confluence']:
            print(f"Institutional Confluence: {len(setup['confluence'])} levels")
            for conf in setup['confluence']:
                print(f"  - {conf['level_type']}: {conf['level_price']} ({conf['distance_pips']} pips away)")
        
        print(f"Entry Condition: {setup['entry_condition']}")
        print(f"Invalidation: {setup['invalidation']}")
    
    print(f"\n=== Trading Recommendations ===")
    if trade_analysis['trade_setups']:
        best_setup = trade_analysis['trade_setups'][0]
        print(f"Best Setup: {best_setup['strategy']}")
        print(f"Quality Score: {best_setup['setup_quality']}/100")
        print(f"Recommended Action: {best_setup['entry_condition']}")
    else:
        print("No high-quality setups available at current price level")

