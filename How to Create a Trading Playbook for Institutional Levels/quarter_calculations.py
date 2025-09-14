# Quarter Level Calculations - Efficient Mathematical Approach

def calculate_quarter_level(price, is_jpy=False):
    """
    Calculate the nearest quarter level for any price using mathematical approach.
    
    Args:
        price: Current market price
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Nearest quarter level
    """
    
    if is_jpy:
        # JPY pairs: quarters are every 2.50 (250 pips)
        quarter_increment = 2.50
        decimal_places = 2
    else:
        # Non-JPY pairs: quarters are every 0.0250 (250 pips)
        quarter_increment = 0.0250
        decimal_places = 4
    
    # Round to nearest quarter level
    nearest_quarter = round(price / quarter_increment) * quarter_increment
    
    return round(nearest_quarter, decimal_places)

def calculate_all_quarter_levels_in_range(min_price, max_price, is_jpy=False):
    """
    Calculate all quarter levels within a price range.
    
    Args:
        min_price: Minimum price in range
        max_price: Maximum price in range
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of all quarter levels in range
    """
    
    if is_jpy:
        quarter_increment = 2.50
        decimal_places = 2
    else:
        quarter_increment = 0.0250
        decimal_places = 4
    
    # Find first quarter level at or above min_price
    first_quarter = calculate_quarter_level(min_price, is_jpy)
    if first_quarter < min_price:
        first_quarter += quarter_increment
    
    # Generate all quarter levels in range
    quarter_levels = []
    current_level = first_quarter
    
    while current_level <= max_price:
        quarter_levels.append(round(current_level, decimal_places))
        current_level += quarter_increment
    
    return quarter_levels

def calculate_quarter_levels_around_price(price, range_pips=500, is_jpy=False):
    """
    Calculate quarter levels around a given price within specified pip range.
    
    Args:
        price: Current market price
        range_pips: Range in pips to search (default 500)
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        List of quarter levels with distance information
    """
    
    if is_jpy:
        pip_value = 0.01
        quarter_increment = 2.50
    else:
        pip_value = 0.0001
        quarter_increment = 0.0250
    
    range_value = range_pips * pip_value
    min_price = price - range_value
    max_price = price + range_value
    
    # Get all quarter levels in range
    quarter_levels = calculate_all_quarter_levels_in_range(min_price, max_price, is_jpy)
    
    # Calculate distance from current price
    levels_with_distance = []
    for level in quarter_levels:
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

def calculate_bodyguards_for_quarter(quarter_level, is_jpy=False):
    """
    Calculate bodyguard levels for a given quarter level.
    Bodyguards are always 75 pips above and below the quarter.
    
    Args:
        quarter_level: The quarter level to calculate bodyguards for
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with quarter level and bodyguard levels
    """
    
    if is_jpy:
        bodyguard_distance = 0.75  # 75 pips for JPY
        decimal_places = 2
    else:
        bodyguard_distance = 0.0075  # 75 pips for non-JPY
        decimal_places = 4
    
    upper_bodyguard = round(quarter_level + bodyguard_distance, decimal_places)
    lower_bodyguard = round(quarter_level - bodyguard_distance, decimal_places)
    
    return {
        'quarter_level': quarter_level,
        'upper_bodyguard': upper_bodyguard,
        'lower_bodyguard': lower_bodyguard,
        'bodyguards': [lower_bodyguard, upper_bodyguard]
    }

def is_valid_quarter_level(level, is_jpy=False):
    """
    Validate if a level is a true quarter level using mathematical check.
    
    Args:
        level: Price level to validate
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        True if valid quarter level, False otherwise
    """
    
    if is_jpy:
        # JPY: Check if divisible by 2.50
        remainder = (level * 100) % 250
        return abs(remainder) < 0.01  # Allow for floating point precision
    else:
        # Non-JPY: Check if divisible by 0.0250
        remainder = (level * 10000) % 250
        return abs(remainder) < 0.01

def get_next_quarter_levels(current_quarter, direction='both', count=3, is_jpy=False):
    """
    Get the next quarter levels in specified direction(s).
    
    Args:
        current_quarter: Starting quarter level
        direction: 'up', 'down', or 'both'
        count: Number of levels to return in each direction
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with next quarter levels
    """
    
    if is_jpy:
        quarter_increment = 2.50
        decimal_places = 2
    else:
        quarter_increment = 0.0250
        decimal_places = 4
    
    result = {'current': current_quarter}
    
    if direction in ['up', 'both']:
        up_levels = []
        for i in range(1, count + 1):
            next_level = round(current_quarter + (i * quarter_increment), decimal_places)
            up_levels.append(next_level)
        result['up'] = up_levels
    
    if direction in ['down', 'both']:
        down_levels = []
        for i in range(1, count + 1):
            next_level = round(current_quarter - (i * quarter_increment), decimal_places)
            down_levels.append(next_level)
        result['down'] = down_levels
    
    return result

def calculate_setup_targets(entry_level, entry_type='bodyguard', direction='up', is_jpy=False):
    """
    Calculate all possible setup targets for quarter theory trading.
    
    Args:
        entry_level: Entry price level
        entry_type: 'bodyguard' or 'quarter'
        direction: 'up' or 'down'
        is_jpy: True for JPY pairs, False for non-JPY pairs
    
    Returns:
        Dictionary with all 5 setup types and their targets
    """
    
    if is_jpy:
        quarter_increment = 2.50
        bodyguard_distance = 0.75
        pip_value = 0.01
        decimal_places = 2
    else:
        quarter_increment = 0.0250
        bodyguard_distance = 0.0075
        pip_value = 0.0001
        decimal_places = 4
    
    setups = {}
    
    if entry_type == 'bodyguard':
        # Find the protected quarter level
        if direction == 'up':
            protected_quarter = round(entry_level - bodyguard_distance, decimal_places)
        else:
            protected_quarter = round(entry_level + bodyguard_distance, decimal_places)
        
        # Calculate targets based on direction
        if direction == 'up':
            # Setup #1: Next bodyguard (100 pips)
            next_quarter = round(protected_quarter + quarter_increment, decimal_places)
            setup1_target = round(next_quarter - bodyguard_distance, decimal_places)
            
            # Setup #3: Next quarter (175 pips) - Traditional
            setup3_target = next_quarter
            
            # Setup #5: Second quarter (250 pips)
            setup5_target = round(protected_quarter + (2 * quarter_increment), decimal_places)
            
            setups = {
                'setup_1': {
                    'name': 'Butter (Bodyguard to Bodyguard)',
                    'target': setup1_target,
                    'stop': protected_quarter,
                    'pips_reward': 100,
                    'pips_risk': 75,
                    'risk_reward': 1.33
                },
                'setup_3': {
                    'name': 'Traditional (Bodyguard to Quarter)',
                    'target': setup3_target,
                    'stop': protected_quarter,
                    'pips_reward': 175,
                    'pips_risk': 75,
                    'risk_reward': 2.33
                },
                'setup_5': {
                    'name': 'Extended (Bodyguard to Second Quarter)',
                    'target': setup5_target,
                    'stop': protected_quarter,
                    'pips_reward': 250,
                    'pips_risk': 75,
                    'risk_reward': 3.33
                }
            }
        
        else:  # direction == 'down'
            # Similar logic for downward moves
            next_quarter = round(protected_quarter - quarter_increment, decimal_places)
            setup1_target = round(next_quarter + bodyguard_distance, decimal_places)
            setup3_target = next_quarter
            setup5_target = round(protected_quarter - (2 * quarter_increment), decimal_places)
            
            setups = {
                'setup_1': {
                    'name': 'Butter (Bodyguard to Bodyguard)',
                    'target': setup1_target,
                    'stop': protected_quarter,
                    'pips_reward': 100,
                    'pips_risk': 75,
                    'risk_reward': 1.33
                },
                'setup_3': {
                    'name': 'Traditional (Bodyguard to Quarter)',
                    'target': setup3_target,
                    'stop': protected_quarter,
                    'pips_reward': 175,
                    'pips_risk': 75,
                    'risk_reward': 2.33
                },
                'setup_5': {
                    'name': 'Extended (Bodyguard to Second Quarter)',
                    'target': setup5_target,
                    'stop': protected_quarter,
                    'pips_reward': 250,
                    'pips_risk': 75,
                    'risk_reward': 3.33
                }
            }
    
    return setups

# Universal functions that auto-detect JPY vs non-JPY
def auto_calculate_quarter_level(price, instrument):
    """Auto-detect JPY and calculate quarter level."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_quarter_level(price, is_jpy)

def auto_calculate_bodyguards(quarter_level, instrument):
    """Auto-detect JPY and calculate bodyguards."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_bodyguards_for_quarter(quarter_level, is_jpy)

def auto_calculate_quarter_levels_around_price(price, instrument, range_pips=500):
    """Auto-detect JPY and get quarter levels around price."""
    is_jpy = 'JPY' in instrument.upper()
    return calculate_quarter_levels_around_price(price, range_pips, is_jpy)

# Example usage and testing
if __name__ == "__main__":
    # Test non-JPY pair
    print("=== Non-JPY Example (EUR/USD) ===")
    price = 1.2180
    nearest_quarter = calculate_quarter_level(price, is_jpy=False)
    print(f"Price: {price}, Nearest Quarter: {nearest_quarter}")
    
    bodyguards = calculate_bodyguards_for_quarter(nearest_quarter, is_jpy=False)
    print(f"Bodyguards: {bodyguards}")
    
    # Test JPY pair
    print("\n=== JPY Example (USD/JPY) ===")
    jpy_price = 122.30
    jpy_quarter = calculate_quarter_level(jpy_price, is_jpy=True)
    print(f"Price: {jpy_price}, Nearest Quarter: {jpy_quarter}")
    
    jpy_bodyguards = calculate_bodyguards_for_quarter(jpy_quarter, is_jpy=True)
    print(f"Bodyguards: {jpy_bodyguards}")
    
    # Test validation
    print(f"\nValidation: 1.2250 is valid quarter: {is_valid_quarter_level(1.2250, False)}")
    print(f"Validation: 122.50 is valid JPY quarter: {is_valid_quarter_level(122.50, True)}")
    print(f"Validation: 1.2260 is valid quarter: {is_valid_quarter_level(1.2260, False)}")

