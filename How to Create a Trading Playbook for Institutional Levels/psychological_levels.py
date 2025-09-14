def get_psychological_levels(price, instrument):
    """
    Calculates psychological levels for a given price and instrument.
    Includes dimes, quarters, small quarters, and pennies.
    """
    is_jpy = 'JPY' in instrument.upper()

    if is_jpy:
        # JPY pairs (2 decimal places)
        dimes = [round(price, -1) + i * 10 for i in range(-5, 6)]  # XX0.00 levels (every 1000 pips)
        quarters = [round(price / 2.5) * 2.5 + i * 2.5 for i in range(-10, 11)]  # XX2.50 levels (every 250 pips)
        small_quarters = [round(price / 0.25) * 0.25 + i * 0.25 for i in range(-20, 21)]  # XX.25 levels (every 25 pips)
        pennies = [round(price) + i * 1 for i in range(-20, 21)]  # XX.00 levels (every 100 pips)
        
        # Clean up and round to proper decimal places
        dimes = [round(level, 2) for level in dimes]
        quarters = [round(level, 2) for level in quarters]
        small_quarters = [round(level, 2) for level in small_quarters]
        pennies = [round(level, 2) for level in pennies]
        
    else:
        # Non-JPY pairs (4 decimal places)
        dimes = [round(price, 1) + i * 0.1 for i in range(-5, 6)]  # X.1000 levels (every 1000 pips)
        quarters = [round(price / 0.025) * 0.025 + i * 0.025 for i in range(-10, 11)]  # X.X250 levels (every 250 pips)
        small_quarters = [round(price / 0.0025) * 0.0025 + i * 0.0025 for i in range(-20, 21)]  # X.XX25 levels (every 25 pips)
        pennies = [round(price / 0.01) * 0.01 + i * 0.01 for i in range(-20, 21)]  # X.XX00 levels (every 100 pips)
        
        # Clean up and round to proper decimal places
        dimes = [round(level, 4) for level in dimes]
        quarters = [round(level, 4) for level in quarters]
        small_quarters = [round(level, 4) for level in small_quarters]
        pennies = [round(level, 4) for level in pennies]

    # Remove duplicates and sort
    dimes = sorted(list(set(dimes)))
    quarters = sorted(list(set(quarters)))
    small_quarters = sorted(list(set(small_quarters)))
    pennies = sorted(list(set(pennies)))

    return {
        'dimes': dimes, 
        'quarters': quarters, 
        'small_quarters': small_quarters,
        'pennies': pennies
    }

def get_bodyguards_for_levels(levels, instrument, level_type='quarters'):
    """
    Calculate bodyguard levels for given institutional levels.
    Different level types have different bodyguard distances.
    
    Args:
        levels: List of institutional levels
        instrument: Currency pair symbol
        level_type: Type of level ('dimes', 'quarters', 'small_quarters', 'pennies')
    
    Returns:
        Dictionary with levels and their bodyguards
    """
    is_jpy = 'JPY' in instrument.upper()
    
    # Define bodyguard distances for each level type
    bodyguard_distances = {
        'dimes': 100,        # 100 pips for dimes
        'quarters': 75,      # 75 pips for quarters
        'pennies': 20,       # 20 pips for pennies
        'small_quarters': 7.5  # 7.5 pips for small quarters
    }
    
    bodyguard_pips = bodyguard_distances.get(level_type, 75)  # Default to 75 if unknown
    
    if is_jpy:
        bodyguard_distance = bodyguard_pips * 0.01  # Convert pips to JPY price
        decimal_places = 2
    else:
        bodyguard_distance = bodyguard_pips * 0.0001  # Convert pips to non-JPY price
        decimal_places = 4
    
    bodyguards = {}
    
    for level in levels:
        upper_bodyguard = round(level + bodyguard_distance, decimal_places)
        lower_bodyguard = round(level - bodyguard_distance, decimal_places)
        
        bodyguards[level] = {
            'upper': upper_bodyguard,
            'lower': lower_bodyguard,
            'bodyguards': [lower_bodyguard, upper_bodyguard],
            'bodyguard_pips': bodyguard_pips,
            'level_type': level_type
        }
    
    return bodyguards

def identify_butter_zones(price, instrument, range_levels=3):
    """
    Identify butter zones around current price where trades can happen
    between institutional levels without crossing quarters or dimes.
    
    Args:
        price: Current market price
        instrument: Currency pair symbol
        range_levels: Number of levels to look around current price
    
    Returns:
        Dictionary with butter zone opportunities
    """
    is_jpy = 'JPY' in instrument.upper()
    
    # Get all psychological levels
    levels = get_psychological_levels(price, instrument)
    
    # Get bodyguards for quarters (main institutional levels)
    quarter_bodyguards = get_bodyguards_for_levels(levels['quarters'], instrument, 'quarters')
    
    # Find current position relative to quarters
    quarters = levels['quarters']
    current_quarter_index = None
    
    for i, quarter in enumerate(quarters):
        if abs(price - quarter) < (0.125 if is_jpy else 0.0125):  # Within 125 pips of quarter
            current_quarter_index = i
            break
    
    if current_quarter_index is None:
        return {'butter_zones': [], 'message': 'No clear quarter level proximity'}
    
    # Identify butter zones between quarters
    butter_zones = []
    
    # Look for zones between current quarter and adjacent quarters
    for offset in [-1, 1]:  # Previous and next quarter
        target_index = current_quarter_index + offset
        
        if 0 <= target_index < len(quarters):
            current_quarter = quarters[current_quarter_index]
            target_quarter = quarters[target_index]
            
            # Get bodyguards for both quarters
            current_bodyguards = quarter_bodyguards[current_quarter]
            target_bodyguards = quarter_bodyguards[target_quarter]
            
            # Determine butter zone boundaries
            if target_quarter > current_quarter:
                # Upward butter zone
                zone_start = current_bodyguards['upper']
                zone_end = target_bodyguards['lower']
                direction = 'up'
            else:
                # Downward butter zone
                zone_start = current_bodyguards['lower']
                zone_end = target_bodyguards['upper']
                direction = 'down'
            
            # Calculate zone metrics
            zone_distance = abs(zone_end - zone_start)
            zone_pips = int(zone_distance / (0.01 if is_jpy else 0.0001))
            
            butter_zones.append({
                'zone_id': f'Zone_{direction}_{current_quarter_index}',
                'direction': direction,
                'entry_level': zone_start,
                'target_level': zone_end,
                'stop_loss': current_quarter,
                'zone_pips': zone_pips,
                'risk_pips': int(abs(zone_start - current_quarter) / (0.01 if is_jpy else 0.0001)),
                'reward_pips': zone_pips,
                'risk_reward_ratio': round(zone_pips / abs(zone_start - current_quarter), 2),
                'current_quarter': current_quarter,
                'target_quarter': target_quarter
            })
    
    return {
        'current_price': price,
        'current_quarter': quarters[current_quarter_index] if current_quarter_index is not None else None,
        'butter_zones': butter_zones,
        'total_zones': len(butter_zones)
    }

def get_comprehensive_levels_analysis(price, instrument):
    """
    Get comprehensive analysis of all institutional levels and trading opportunities.
    
    Args:
        price: Current market price
        instrument: Currency pair symbol
    
    Returns:
        Complete analysis with all levels and opportunities
    """
    
    # Get all psychological levels
    levels = get_psychological_levels(price, instrument)
    
    # Get butter zones
    butter_analysis = identify_butter_zones(price, instrument)
    
    # Get bodyguards for all level types with correct distances
    dime_bodyguards = get_bodyguards_for_levels(levels['dimes'], instrument, 'dimes')
    quarter_bodyguards = get_bodyguards_for_levels(levels['quarters'], instrument, 'quarters')
    small_quarter_bodyguards = get_bodyguards_for_levels(levels['small_quarters'], instrument, 'small_quarters')
    penny_bodyguards = get_bodyguards_for_levels(levels['pennies'], instrument, 'pennies')
    
    # Find nearest levels of each type
    is_jpy = 'JPY' in instrument.upper()
    pip_value = 0.01 if is_jpy else 0.0001
    
    def find_nearest_level(price, level_list):
        if not level_list:
            return None
        return min(level_list, key=lambda x: abs(x - price))
    
    nearest_levels = {
        'dime': find_nearest_level(price, levels['dimes']),
        'quarter': find_nearest_level(price, levels['quarters']),
        'small_quarter': find_nearest_level(price, levels['small_quarters']),
        'penny': find_nearest_level(price, levels['pennies'])
    }
    
    # Calculate distances
    distances = {}
    for level_type, level in nearest_levels.items():
        if level is not None:
            distance_pips = int(abs(price - level) / pip_value)
            distances[level_type] = {
                'level': level,
                'distance_pips': distance_pips,
                'above_price': level > price
            }
    
    return {
        'instrument': instrument,
        'current_price': price,
        'is_jpy': is_jpy,
        'all_levels': levels,
        'nearest_levels': distances,
        'butter_zones': butter_analysis,
        'bodyguards': {
            'dimes': dime_bodyguards,
            'quarters': quarter_bodyguards,
            'small_quarters': small_quarter_bodyguards,
            'pennies': penny_bodyguards
        }
    }

# Example usage and testing
if __name__ == "__main__":
    # Test non-JPY pair
    print("=== Non-JPY Example (EUR/USD) ===")
    price = 1.2187
    instrument = 'EURUSD'
    
    levels = get_psychological_levels(price, instrument)
    print(f"Price: {price}")
    print(f"Dimes: {levels['dimes'][:5]}...")  # Show first 5
    print(f"Quarters: {levels['quarters'][:5]}...")
    print(f"Small Quarters: {levels['small_quarters'][:5]}...")
    print(f"Pennies: {levels['pennies'][:5]}...")
    
    # Test butter zones
    butter_zones = identify_butter_zones(price, instrument)
    print(f"Butter Zones: {len(butter_zones['butter_zones'])} found")
    for zone in butter_zones['butter_zones']:
        print(f"  {zone['zone_id']}: {zone['entry_level']} → {zone['target_level']} ({zone['zone_pips']} pips)")
    
    # Test JPY pair
    print("\n=== JPY Example (USD/JPY) ===")
    jpy_price = 122.37
    jpy_instrument = 'USDJPY'
    
    jpy_levels = get_psychological_levels(jpy_price, jpy_instrument)
    print(f"Price: {jpy_price}")
    print(f"Dimes: {jpy_levels['dimes'][:5]}...")
    print(f"Quarters: {jpy_levels['quarters'][:5]}...")
    print(f"Small Quarters: {jpy_levels['small_quarters'][:5]}...")
    print(f"Pennies: {jpy_levels['pennies'][:5]}...")
    
    # Test comprehensive analysis
    print("\n=== Comprehensive Analysis ===")
    comprehensive = get_comprehensive_levels_analysis(price, instrument)
    print(f"Nearest Quarter: {comprehensive['nearest_levels']['quarter']}")
    print(f"Nearest Small Quarter: {comprehensive['nearest_levels']['small_quarter']}")
    print(f"Butter Zones Available: {comprehensive['butter_zones']['total_zones']}")


    
    # Test different bodyguard distances
    print("\n=== Bodyguard Distance Testing ===")
    test_level = 1.2250
    
    for level_type in ['dimes', 'quarters', 'small_quarters', 'pennies']:
        bodyguards = get_bodyguards_for_levels([test_level], instrument, level_type)
        bg_info = bodyguards[test_level]
        print(f"{level_type.title()}: {test_level} → Bodyguards: {bg_info['lower']} / {bg_info['upper']} ({bg_info['bodyguard_pips']} pips)")
    
    # Test JPY bodyguards
    print("\n=== JPY Bodyguard Distance Testing ===")
    jpy_test_level = 122.50
    
    for level_type in ['dimes', 'quarters', 'small_quarters', 'pennies']:
        jpy_bodyguards = get_bodyguards_for_levels([jpy_test_level], jpy_instrument, level_type)
        jpy_bg_info = jpy_bodyguards[jpy_test_level]
        print(f"{level_type.title()}: {jpy_test_level} → Bodyguards: {jpy_bg_info['lower']} / {jpy_bg_info['upper']} ({jpy_bg_info['bodyguard_pips']} pips)")

