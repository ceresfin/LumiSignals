# Small Quarter Level Calculations - Efficient Mathematical Approach

def calculate_small_quarter_level(price, is_jpy=False):
    """
    Calculate the nearest small quarter level for any price using mathematical approach.
    Small quarters are every 25 pips instead of 250 pips.
    
    Args:
        price: Current market price
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Nearest small quarter level
    """
    
    if is_jpy:
        # JPY pairs: small quarters are every 0.25 (25 pips)
        small_quarter_increment = 0.25
        decimal_places = 2
    else:
        # Non-JPY pairs: small quarters are every 0.0025 (25 pips)
        small_quarter_increment = 0.0025
        decimal_places = 4
    
    # Round to nearest small quarter level
    nearest_small_quarter = round(price / small_quarter_increment) * small_quarter_increment
    
    return round(nearest_small_quarter, decimal_places)

def calculate_all_small_quarter_levels_in_range(min_price, max_price, is_jpy=False):
    """
    Calculate all small quarter levels within a price range.
    
    Args:
        min_price: Minimum price in range
        max_price: Maximum price in range
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of all small quarter levels in range
    """
    
    if is_jpy:
        small_quarter_increment = 0.25
        decimal_places = 2
    else:
        small_quarter_increment = 0.0025
        decimal_places = 4
    
    # Find first small quarter level at or above min_price
    first_small_quarter = calculate_small_quarter_level(min_price, is_jpy)
    if first_small_quarter < min_price:
        first_small_quarter += small_quarter_increment
    
    # Generate all small quarter levels in range
    small_quarter_levels = []
    current_level = first_small_quarter
    
    while current_level <= max_price:
        small_quarter_levels.append(round(current_level, decimal_places))
        current_level += small_quarter_increment
    
    return small_quarter_levels

def calculate_small_quarter_levels_around_price(price, range_pips=200, is_jpy=False):
    """
    Calculate small quarter levels around a given price within specified pip range.
    
    Args:
        price: Current market price
        range_pips: Range in pips to search (default 200)
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of small quarter levels with distance information
    """
    
    if is_jpy:
        pip_value = 0.01
        small_quarter_increment = 0.25
    else:
        pip_value = 0.0001
        small_quarter_increment = 0.0025
    
    range_value = range_pips * pip_value
    min_price = price - range_value
    max_price = price + range_value
    
    # Get all small quarter levels in range
    small_quarter_levels = calculate_all_small_quarter_levels_in_range(min_price, max_price, is_jpy)
    
    # Calculate distance from current price
    levels_with_distance = []
    for level in small_quarter_levels:
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

def is_valid_small_quarter_level(level, is_jpy=False):
    """
    Validate if a level is a true small quarter level using mathematical check.
    
    Args:
        level: Price level to validate
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        True if valid small quarter level, False otherwise
    """
    
    if is_jpy:
        # JPY: Check if divisible by 0.25
        remainder = (level * 100) % 25
        return abs(remainder) < 0.01  # Allow for floating point precision
    else:
        # Non-JPY: Check if divisible by 0.0025
        remainder = (level * 10000) % 25
        return abs(remainder) < 0.01

def get_next_small_quarter_levels(current_small_quarter, direction='both', count=5, is_jpy=False):
    """
    Get the next small quarter levels in specified direction(s).
    
    Args:
        current_small_quarter: Starting small quarter level
        direction: 'up', 'down', or 'both'
        count: Number of levels to return in each direction
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with next small quarter levels
    """
    
    if is_jpy:
        small_quarter_increment = 0.25
        decimal_places = 2
    else:
        small_quarter_increment = 0.0025
        decimal_places = 4
    
    result = {'current': current_small_quarter}
    
    if direction in ['up', 'both']:
        up_levels = []
        for i in range(1, count + 1):
            next_level = round(current_small_quarter + (i * small_quarter_increment), decimal_places)
            up_levels.append(next_level)
        result['up'] = up_levels
    
    if direction in ['down', 'both']:
        down_levels = []
        for i in range(1, count + 1):
            next_level = round(current_small_quarter - (i * small_quarter_increment), decimal_places)
            down_levels.append(next_level)
        result['down'] = down_levels
    
    return result

def calculate_small_quarter_bodyguards(small_quarter_level, bodyguard_pips=15, is_jpy=False):
    """
    Calculate bodyguard levels for small quarters.
    Since small quarters are closer together, bodyguards are typically smaller (15-20 pips).
    
    Args:
        small_quarter_level: The small quarter level to calculate bodyguards for
        bodyguard_pips: Distance in pips for bodyguards (default 15)
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with small quarter level and bodyguard levels
    """
    
    if is_jpy:
        bodyguard_distance = bodyguard_pips * 0.01  # Convert pips to JPY price
        decimal_places = 2
    else:
        bodyguard_distance = bodyguard_pips * 0.0001  # Convert pips to non-JPY price
        decimal_places = 4
    
    upper_bodyguard = round(small_quarter_level + bodyguard_distance, decimal_places)
    lower_bodyguard = round(small_quarter_level - bodyguard_distance, decimal_places)
    
    return {
        'small_quarter_level': small_quarter_level,
        'upper_bodyguard': upper_bodyguard,
        'lower_bodyguard': lower_bodyguard,
        'bodyguards': [lower_bodyguard, upper_bodyguard],
        'bodyguard_pips': bodyguard_pips
    }

def find_relationship_to_regular_quarter(small_quarter_level, is_jpy=False):
    """
    Find which regular quarter level this small quarter relates to.
    
    Args:
        small_quarter_level: Small quarter level
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with relationship information
    """
    
    if is_jpy:
        # JPY regular quarters are every 2.50
        regular_quarter = round(small_quarter_level / 2.50) * 2.50
        position_in_cycle = round((small_quarter_level % 2.50) / 0.25)
    else:
        # Non-JPY regular quarters are every 0.0250
        regular_quarter = round(small_quarter_level / 0.0250) * 0.0250
        position_in_cycle = round((small_quarter_level % 0.0250) / 0.0025)
    
    cycle_names = ['Quarter', 'Quarter+25', 'Quarter+50', 'Quarter+75', 
                   'Quarter+100', 'Quarter+125', 'Quarter+150', 'Quarter+175',
                   'Quarter+200', 'Quarter+225']
    
    return {
        'small_quarter': small_quarter_level,
        'nearest_regular_quarter': regular_quarter,
        'position_in_cycle': int(position_in_cycle),
        'cycle_name': cycle_names[int(position_in_cycle)] if position_in_cycle < len(cycle_names) else f'Quarter+{int(position_in_cycle)*25}',
        'distance_from_quarter_pips': int(position_in_cycle * 25)
    }

def get_small_quarter_trading_levels(price, is_jpy=False):
    """
    Get comprehensive small quarter trading levels around current price.
    
    Args:
        price: Current market price
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with all relevant small quarter levels and relationships
    """
    
    # Find nearest small quarter
    nearest_small_quarter = calculate_small_quarter_level(price, is_jpy)
    
    # Get surrounding small quarters
    surrounding_levels = get_next_small_quarter_levels(nearest_small_quarter, 'both', 5, is_jpy)
    
    # Get bodyguards for nearest small quarter
    bodyguards = calculate_small_quarter_bodyguards(nearest_small_quarter, 15, is_jpy)
    
    # Find relationship to regular quarter
    relationship = find_relationship_to_regular_quarter(nearest_small_quarter, is_jpy)
    
    return {
        'current_price': price,
        'nearest_small_quarter': nearest_small_quarter,
        'surrounding_levels': surrounding_levels,
        'bodyguards': bodyguards,
        'regular_quarter_relationship': relationship
    }

# Universal functions that auto-detect JPY vs non-JPY
def auto_calculate_small_quarter_level(price, instrument):
    """Auto-detect JPY and calculate small quarter level."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_small_quarter_level(price, is_jpy)

def auto_calculate_small_quarter_bodyguards(small_quarter_level, instrument, bodyguard_pips=15):
    """Auto-detect JPY and calculate small quarter bodyguards."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_small_quarter_bodyguards(small_quarter_level, bodyguard_pips, is_jpy)

def auto_get_small_quarter_trading_levels(price, instrument):
    """Auto-detect JPY and get comprehensive small quarter levels."""
    is_jpy = 'JPY' in instrument.upper()
    return get_small_quarter_trading_levels(price, is_jpy)

# Example usage and testing
if __name__ == "__main__":
    # Test non-JPY pair
    print("=== Non-JPY Small Quarters Example (EUR/USD) ===")
    price = 1.2187
    nearest_small_quarter = calculate_small_quarter_level(price, is_jpy=False)
    print(f"Price: {price}, Nearest Small Quarter: {nearest_small_quarter}")
    
    bodyguards = calculate_small_quarter_bodyguards(nearest_small_quarter, 15, is_jpy=False)
    print(f"Small Quarter Bodyguards (15 pips): {bodyguards}")
    
    relationship = find_relationship_to_regular_quarter(nearest_small_quarter, is_jpy=False)
    print(f"Relationship to Regular Quarter: {relationship}")
    
    # Test JPY pair
    print("\n=== JPY Small Quarters Example (USD/JPY) ===")
    jpy_price = 122.37
    jpy_small_quarter = calculate_small_quarter_level(jpy_price, is_jpy=True)
    print(f"Price: {jpy_price}, Nearest Small Quarter: {jpy_small_quarter}")
    
    jpy_bodyguards = calculate_small_quarter_bodyguards(jpy_small_quarter, 15, is_jpy=True)
    print(f"JPY Small Quarter Bodyguards (15 pips): {jpy_bodyguards}")
    
    jpy_relationship = find_relationship_to_regular_quarter(jpy_small_quarter, is_jpy=True)
    print(f"JPY Relationship to Regular Quarter: {jpy_relationship}")
    
    # Test validation
    print(f"\nValidation: 1.2175 is valid small quarter: {is_valid_small_quarter_level(1.2175, False)}")
    print(f"Validation: 122.25 is valid JPY small quarter: {is_valid_small_quarter_level(122.25, True)}")
    print(f"Validation: 1.2177 is valid small quarter: {is_valid_small_quarter_level(1.2177, False)}")
    
    # Test comprehensive levels
    print(f"\n=== Comprehensive Small Quarter Analysis ===")
    comprehensive = get_small_quarter_trading_levels(1.2187, is_jpy=False)
    print(f"Comprehensive Analysis: {comprehensive}")

