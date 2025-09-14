# Penny Level Calculations - Efficient Mathematical Approach

def calculate_penny_level(price, is_jpy=False):
    """
    Calculate the nearest penny level for any price using mathematical approach.
    Penny levels are every 100 pips.
    
    Args:
        price: Current market price
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Nearest penny level
    """
    
    if is_jpy:
        # JPY pairs: pennies are every 1.00 (100 pips)
        penny_increment = 1.00
        decimal_places = 2
    else:
        # Non-JPY pairs: pennies are every 0.0100 (100 pips)
        penny_increment = 0.0100
        decimal_places = 4
    
    # Round to nearest penny level
    nearest_penny = round(price / penny_increment) * penny_increment
    
    return round(nearest_penny, decimal_places)

def calculate_all_penny_levels_in_range(min_price, max_price, is_jpy=False):
    """
    Calculate all penny levels within a price range.
    
    Args:
        min_price: Minimum price in range
        max_price: Maximum price in range
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of all penny levels in range
    """
    
    if is_jpy:
        penny_increment = 1.00
        decimal_places = 2
    else:
        penny_increment = 0.0100
        decimal_places = 4
    
    # Find first penny level at or above min_price
    first_penny = calculate_penny_level(min_price, is_jpy)
    if first_penny < min_price:
        first_penny += penny_increment
    
    # Generate all penny levels in range
    penny_levels = []
    current_level = first_penny
    
    while current_level <= max_price:
        penny_levels.append(round(current_level, decimal_places))
        current_level += penny_increment
    
    return penny_levels

def calculate_penny_levels_around_price(price, range_pips=300, is_jpy=False):
    """
    Calculate penny levels around a given price within specified pip range.
    
    Args:
        price: Current market price
        range_pips: Range in pips to search (default 300)
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of penny levels with distance information
    """
    
    if is_jpy:
        pip_value = 0.01
        penny_increment = 1.00
    else:
        pip_value = 0.0001
        penny_increment = 0.0100
    
    range_value = range_pips * pip_value
    min_price = price - range_value
    max_price = price + range_value
    
    # Get all penny levels in range
    penny_levels = calculate_all_penny_levels_in_range(min_price, max_price, is_jpy)
    
    # Calculate distance from current price
    levels_with_distance = []
    for level in penny_levels:
        distance = abs(price - level)
        distance_pips = int(distance / pip_value)
        
        levels_with_distance.append({
            'level': level,
            'distance_pips': distance_pips,
            'above_price': level > price
        })
    
    # Sort by distance from current price
    levels_with_distance.sort(key=lambda x: x['distance_pips'])
    
    return levels_with_distance

def is_valid_penny_level(level, is_jpy=False):
    """
    Validate if a level is a true penny level using mathematical check.
    
    Args:
        level: Price level to validate
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        True if valid penny level, False otherwise
    """
    
    if is_jpy:
        # JPY: Check if divisible by 1.00
        remainder = (level * 100) % 100
        return abs(remainder) < 0.01  # Allow for floating point precision
    else:
        # Non-JPY: Check if divisible by 0.0100
        remainder = (level * 10000) % 100
        return abs(remainder) < 0.01

def get_next_penny_levels(current_penny, direction='both', count=5, is_jpy=False):
    """
    Get the next penny levels in specified direction(s).
    
    Args:
        current_penny: Starting penny level
        direction: 'up', 'down', or 'both'
        count: Number of levels to return in each direction
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with next penny levels
    """
    
    if is_jpy:
        penny_increment = 1.00
        decimal_places = 2
    else:
        penny_increment = 0.0100
        decimal_places = 4
    
    result = {'current': current_penny}
    
    if direction in ['up', 'both']:
        up_levels = []
        for i in range(1, count + 1):
            next_level = round(current_penny + (i * penny_increment), decimal_places)
            up_levels.append(next_level)
        result['up'] = up_levels
    
    if direction in ['down', 'both']:
        down_levels = []
        for i in range(1, count + 1):
            next_level = round(current_penny - (i * penny_increment), decimal_places)
            down_levels.append(next_level)
        result['down'] = down_levels
    
    return result

def calculate_penny_bodyguards(penny_level, bodyguard_pips=25, is_jpy=False):
    """
    Calculate bodyguard levels for penny levels.
    Penny bodyguards are typically 20-30 pips.
    
    Args:
        penny_level: The penny level to calculate bodyguards for
        bodyguard_pips: Distance in pips for bodyguards (default 25)
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with penny level and bodyguard levels
    """
    
    if is_jpy:
        bodyguard_distance = bodyguard_pips * 0.01  # Convert pips to JPY price
        decimal_places = 2
    else:
        bodyguard_distance = bodyguard_pips * 0.0001  # Convert pips to non-JPY price
        decimal_places = 4
    
    upper_bodyguard = round(penny_level + bodyguard_distance, decimal_places)
    lower_bodyguard = round(penny_level - bodyguard_distance, decimal_places)
    
    return {
        'penny_level': penny_level,
        'upper_bodyguard': upper_bodyguard,
        'lower_bodyguard': lower_bodyguard,
        'bodyguards': [lower_bodyguard, upper_bodyguard],
        'bodyguard_pips': bodyguard_pips
    }

def find_relationship_to_other_levels(penny_level, is_jpy=False):
    """
    Find how this penny level relates to quarter levels and small quarter levels.
    
    Args:
        penny_level: Penny level to analyze
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with relationship information
    """
    
    if is_jpy:
        # JPY calculations
        regular_quarter_increment = 2.50
        small_quarter_increment = 0.25
        penny_increment = 1.00
        
        # Find nearest regular quarter
        nearest_regular_quarter = round(penny_level / regular_quarter_increment) * regular_quarter_increment
        
        # Find nearest small quarter
        nearest_small_quarter = round(penny_level / small_quarter_increment) * small_quarter_increment
        
        # Calculate positions
        regular_quarter_distance = abs(penny_level - nearest_regular_quarter)
        small_quarter_distance = abs(penny_level - nearest_small_quarter)
        
    else:
        # Non-JPY calculations
        regular_quarter_increment = 0.0250
        small_quarter_increment = 0.0025
        penny_increment = 0.0100
        
        # Find nearest regular quarter
        nearest_regular_quarter = round(penny_level / regular_quarter_increment) * regular_quarter_increment
        
        # Find nearest small quarter
        nearest_small_quarter = round(penny_level / small_quarter_increment) * small_quarter_increment
        
        # Calculate positions
        regular_quarter_distance = abs(penny_level - nearest_regular_quarter)
        small_quarter_distance = abs(penny_level - nearest_small_quarter)
    
    return {
        'penny_level': penny_level,
        'nearest_regular_quarter': round(nearest_regular_quarter, 4 if not is_jpy else 2),
        'nearest_small_quarter': round(nearest_small_quarter, 4 if not is_jpy else 2),
        'distance_to_regular_quarter_pips': int(regular_quarter_distance / (0.01 if is_jpy else 0.0001)),
        'distance_to_small_quarter_pips': int(small_quarter_distance / (0.01 if is_jpy else 0.0001)),
        'is_on_regular_quarter': regular_quarter_distance < 0.001,
        'is_on_small_quarter': small_quarter_distance < 0.001
    }

def get_penny_trading_levels_with_momentum(price, momentum_data, is_jpy=False):
    """
    Get comprehensive penny trading levels with multi-timeframe momentum analysis.
    This integrates with the Multi-Timeframe Momentum layer.
    
    Args:
        price: Current market price
        momentum_data: Dictionary with momentum percentages for different timeframes
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with penny levels and momentum analysis
    """
    
    # Find nearest penny level
    nearest_penny = calculate_penny_level(price, is_jpy)
    
    # Get surrounding penny levels
    surrounding_levels = get_next_penny_levels(nearest_penny, 'both', 3, is_jpy)
    
    # Get bodyguards for nearest penny
    bodyguards = calculate_penny_bodyguards(nearest_penny, 25, is_jpy)
    
    # Find relationships to other levels
    relationships = find_relationship_to_other_levels(nearest_penny, is_jpy)
    
    # Analyze momentum alignment (if momentum_data provided)
    momentum_analysis = None
    if momentum_data:
        momentum_analysis = analyze_momentum_for_penny_trading(momentum_data)
    
    return {
        'current_price': price,
        'nearest_penny': nearest_penny,
        'surrounding_levels': surrounding_levels,
        'bodyguards': bodyguards,
        'level_relationships': relationships,
        'momentum_analysis': momentum_analysis
    }

def analyze_momentum_for_penny_trading(momentum_data):
    """
    Analyze multi-timeframe momentum for penny level trading.
    
    Args:
        momentum_data: Dictionary with momentum percentages
                      e.g., {'48hr': -0.55, '24hr': -0.11, '4hr': -0.10, '60min': 0.00, '15min': 0.00}
    
    Returns:
        Dictionary with momentum analysis
    """
    
    # Define momentum thresholds
    strong_threshold = 0.15  # 0.15%
    weak_threshold = 0.05   # 0.05%
    
    # Analyze each timeframe
    timeframe_analysis = {}
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0
    
    for timeframe, momentum in momentum_data.items():
        if momentum > strong_threshold:
            sentiment = 'Strong Bullish'
            bullish_count += 1
        elif momentum > weak_threshold:
            sentiment = 'Bullish'
            bullish_count += 1
        elif momentum < -strong_threshold:
            sentiment = 'Strong Bearish'
            bearish_count += 1
        elif momentum < -weak_threshold:
            sentiment = 'Bearish'
            bearish_count += 1
        else:
            sentiment = 'Neutral'
            neutral_count += 1
        
        timeframe_analysis[timeframe] = {
            'momentum': momentum,
            'sentiment': sentiment
        }
    
    # Overall momentum bias
    total_timeframes = len(momentum_data)
    if bullish_count >= total_timeframes * 0.6:
        overall_bias = 'Bullish'
    elif bearish_count >= total_timeframes * 0.6:
        overall_bias = 'Bearish'
    else:
        overall_bias = 'Mixed'
    
    # Trading recommendation
    if bullish_count >= 3:
        recommendation = 'Look for penny level breakouts to upside'
    elif bearish_count >= 3:
        recommendation = 'Look for penny level breakouts to downside'
    else:
        recommendation = 'Wait for clearer momentum alignment'
    
    return {
        'timeframe_analysis': timeframe_analysis,
        'bullish_timeframes': bullish_count,
        'bearish_timeframes': bearish_count,
        'neutral_timeframes': neutral_count,
        'overall_bias': overall_bias,
        'recommendation': recommendation
    }

# Universal functions that auto-detect JPY vs non-JPY
def auto_calculate_penny_level(price, instrument):
    """Auto-detect JPY and calculate penny level."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_penny_level(price, is_jpy)

def auto_calculate_penny_bodyguards(penny_level, instrument, bodyguard_pips=25):
    """Auto-detect JPY and calculate penny bodyguards."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_penny_bodyguards(penny_level, bodyguard_pips, is_jpy)

def auto_get_penny_trading_levels(price, instrument, momentum_data=None):
    """Auto-detect JPY and get comprehensive penny levels."""
    is_jpy = 'JPY' in instrument.upper()
    return get_penny_trading_levels_with_momentum(price, momentum_data, is_jpy)

# Example usage and testing
if __name__ == "__main__":
    # Test non-JPY pair
    print("=== Non-JPY Penny Levels Example (EUR/USD) ===")
    price = 1.2187
    nearest_penny = calculate_penny_level(price, is_jpy=False)
    print(f"Price: {price}, Nearest Penny: {nearest_penny}")
    
    bodyguards = calculate_penny_bodyguards(nearest_penny, 25, is_jpy=False)
    print(f"Penny Bodyguards (25 pips): {bodyguards}")
    
    relationships = find_relationship_to_other_levels(nearest_penny, is_jpy=False)
    print(f"Level Relationships: {relationships}")
    
    # Test JPY pair
    print("\n=== JPY Penny Levels Example (USD/JPY) ===")
    jpy_price = 122.37
    jpy_penny = calculate_penny_level(jpy_price, is_jpy=True)
    print(f"Price: {jpy_price}, Nearest Penny: {jpy_penny}")
    
    jpy_bodyguards = calculate_penny_bodyguards(jpy_penny, 25, is_jpy=True)
    print(f"JPY Penny Bodyguards (25 pips): {jpy_bodyguards}")
    
    jpy_relationships = find_relationship_to_other_levels(jpy_penny, is_jpy=True)
    print(f"JPY Level Relationships: {jpy_relationships}")
    
    # Test validation
    print(f"\nValidation: 1.2200 is valid penny: {is_valid_penny_level(1.2200, False)}")
    print(f"Validation: 122.00 is valid JPY penny: {is_valid_penny_level(122.00, True)}")
    print(f"Validation: 1.2250 is valid penny: {is_valid_penny_level(1.2250, False)}")
    
    # Test with momentum data
    print(f"\n=== Penny Trading with Momentum Analysis ===")
    momentum_data = {
        '48hr': -0.55,
        '24hr': -0.11,
        '4hr': -0.10,
        '60min': 0.00,
        '15min': 0.00
    }
    
    comprehensive = get_penny_trading_levels_with_momentum(1.2187, momentum_data, is_jpy=False)
    print(f"Comprehensive Penny Analysis: {comprehensive['momentum_analysis']}")

