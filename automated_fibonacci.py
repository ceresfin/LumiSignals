import numpy as np
from datetime import datetime, timedelta

def detect_swing_points(price_data, window=5, min_strength=3):
    """
    Automatically detect swing highs and lows in price data.
    
    Args:
        price_data: List of price dictionaries with 'high', 'low', 'close', 'timestamp'
        window: Number of periods on each side to confirm swing
        min_strength: Minimum number of periods that must be lower/higher
    
    Returns:
        Dictionary with swing highs and lows
    """
    
    if len(price_data) < window * 2 + 1:
        return {'swing_highs': [], 'swing_lows': []}
    
    swing_highs = []
    swing_lows = []
    
    for i in range(window, len(price_data) - window):
        current_high = price_data[i]['high']
        current_low = price_data[i]['low']
        
        # Check for swing high
        is_swing_high = True
        for j in range(i - window, i + window + 1):
            if j != i and price_data[j]['high'] >= current_high:
                is_swing_high = False
                break
        
        if is_swing_high:
            swing_highs.append({
                'price': current_high,
                'index': i,
                'timestamp': price_data[i]['timestamp'],
                'strength': window
            })
        
        # Check for swing low
        is_swing_low = True
        for j in range(i - window, i + window + 1):
            if j != i and price_data[j]['low'] <= current_low:
                is_swing_low = False
                break
        
        if is_swing_low:
            swing_lows.append({
                'price': current_low,
                'index': i,
                'timestamp': price_data[i]['timestamp'],
                'strength': window
            })
    
    return {'swing_highs': swing_highs, 'swing_lows': swing_lows}

def find_significant_swings(swing_points, min_pip_distance=100, is_jpy=False):
    """
    Filter swing points to find only significant moves.
    
    Args:
        swing_points: Output from detect_swing_points
        min_pip_distance: Minimum distance in pips between swings
        is_jpy: True for JPY pairs
    
    Returns:
        Filtered significant swings
    """
    
    pip_value = 0.01 if is_jpy else 0.0001
    min_price_distance = min_pip_distance * pip_value
    
    # Combine and sort all swings by timestamp
    all_swings = []
    
    for swing in swing_points['swing_highs']:
        all_swings.append({**swing, 'type': 'high'})
    
    for swing in swing_points['swing_lows']:
        all_swings.append({**swing, 'type': 'low'})
    
    all_swings.sort(key=lambda x: x['index'])
    
    # Filter for significant moves
    significant_swings = []
    last_swing = None
    
    for swing in all_swings:
        if last_swing is None:
            significant_swings.append(swing)
            last_swing = swing
        else:
            # Check if this swing is significant enough
            price_distance = abs(swing['price'] - last_swing['price'])
            
            if price_distance >= min_price_distance:
                # Also check if it's alternating (high after low, low after high)
                if swing['type'] != last_swing['type']:
                    significant_swings.append(swing)
                    last_swing = swing
                elif price_distance > min_price_distance * 1.5:  # Allow same type if much larger move
                    significant_swings.append(swing)
                    last_swing = swing
    
    return significant_swings

def generate_fibonacci_levels(high_price, low_price, direction='retracement'):
    """
    Generate Fibonacci levels between high and low prices.
    
    Args:
        high_price: Higher price point
        low_price: Lower price point
        direction: 'retracement' or 'extension'
    
    Returns:
        Dictionary with Fibonacci levels
    """
    
    # Standard Fibonacci ratios
    retracement_ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    extension_ratios = [0.0, 0.618, 1.0, 1.272, 1.414, 1.618, 2.0, 2.618]
    
    price_range = high_price - low_price
    
    if direction == 'retracement':
        ratios = retracement_ratios
        levels = {}
        
        for ratio in ratios:
            level_price = high_price - (price_range * ratio)
            levels[f'{ratio:.3f}'] = {
                'price': round(level_price, 5),
                'ratio': ratio,
                'type': 'retracement',
                'description': f'{ratio:.1%} Retracement'
            }
    
    else:  # extension
        ratios = extension_ratios
        levels = {}
        
        for ratio in ratios:
            level_price = low_price - (price_range * (ratio - 1.0))
            levels[f'{ratio:.3f}'] = {
                'price': round(level_price, 5),
                'ratio': ratio,
                'type': 'extension',
                'description': f'{ratio:.1%} Extension'
            }
    
    return levels

def auto_generate_fibonacci_from_swings(significant_swings, current_price):
    """
    Automatically generate Fibonacci levels from detected swings.
    
    Args:
        significant_swings: List of significant swing points
        current_price: Current market price
    
    Returns:
        Dictionary with multiple Fibonacci level sets
    """
    
    if len(significant_swings) < 2:
        return {'fibonacci_sets': [], 'message': 'Insufficient swing data'}
    
    fibonacci_sets = []
    
    # Generate Fibonacci levels for recent swing patterns
    for i in range(len(significant_swings) - 1):
        swing1 = significant_swings[i]
        swing2 = significant_swings[i + 1]
        
        # Determine high and low
        if swing1['price'] > swing2['price']:
            high_swing = swing1
            low_swing = swing2
            trend_direction = 'downtrend'
        else:
            high_swing = swing2
            low_swing = swing1
            trend_direction = 'uptrend'
        
        # Generate retracement levels
        retracement_levels = generate_fibonacci_levels(
            high_swing['price'], 
            low_swing['price'], 
            'retracement'
        )
        
        # Generate extension levels
        extension_levels = generate_fibonacci_levels(
            high_swing['price'], 
            low_swing['price'], 
            'extension'
        )
        
        # Calculate relevance score based on recency and proximity to current price
        time_weight = 1.0 / (len(significant_swings) - i)  # More recent = higher weight
        
        # Find closest Fibonacci level to current price
        all_fib_prices = [level['price'] for level in retracement_levels.values()]
        all_fib_prices.extend([level['price'] for level in extension_levels.values()])
        
        closest_fib_distance = min([abs(current_price - price) for price in all_fib_prices])
        proximity_weight = 1.0 / (1.0 + closest_fib_distance * 10000)  # Closer = higher weight
        
        relevance_score = time_weight * proximity_weight
        
        fibonacci_sets.append({
            'id': f'fib_set_{i}',
            'high_swing': high_swing,
            'low_swing': low_swing,
            'trend_direction': trend_direction,
            'retracement_levels': retracement_levels,
            'extension_levels': extension_levels,
            'relevance_score': relevance_score,
            'swing_range_pips': int(abs(high_swing['price'] - low_swing['price']) * 10000)
        })
    
    # Sort by relevance score (most relevant first)
    fibonacci_sets.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    return {
        'fibonacci_sets': fibonacci_sets,
        'total_sets': len(fibonacci_sets),
        'most_relevant': fibonacci_sets[0] if fibonacci_sets else None
    }

def integrate_fibonacci_with_institutional_levels(fibonacci_sets, institutional_levels, tolerance_pips=10, is_jpy=False):
    """
    Find confluences between Fibonacci levels and institutional levels.
    
    Args:
        fibonacci_sets: Output from auto_generate_fibonacci_from_swings
        institutional_levels: Dictionary with dimes, quarters, small_quarters, pennies
        tolerance_pips: Pip tolerance for confluence detection
        is_jpy: True for JPY pairs
    
    Returns:
        Dictionary with confluence analysis
    """
    
    pip_value = 0.01 if is_jpy else 0.0001
    tolerance_price = tolerance_pips * pip_value
    
    confluences = []
    
    # Flatten all institutional levels
    all_institutional = []
    for level_type, levels in institutional_levels.items():
        for level in levels:
            all_institutional.append({
                'price': level,
                'type': level_type,
                'level': level
            })
    
    # Check each Fibonacci set for confluences
    for fib_set in fibonacci_sets['fibonacci_sets']:
        set_confluences = []
        
        # Check retracement levels
        for ratio, fib_level in fib_set['retracement_levels'].items():
            fib_price = fib_level['price']
            
            for inst_level in all_institutional:
                if abs(fib_price - inst_level['price']) <= tolerance_price:
                    confluence_strength = 1.0 / (1.0 + abs(fib_price - inst_level['price']) * 10000)
                    
                    set_confluences.append({
                        'fibonacci_ratio': ratio,
                        'fibonacci_price': fib_price,
                        'fibonacci_type': 'retracement',
                        'institutional_type': inst_level['type'],
                        'institutional_price': inst_level['price'],
                        'confluence_strength': confluence_strength,
                        'price_difference_pips': int(abs(fib_price - inst_level['price']) / pip_value)
                    })
        
        # Check extension levels
        for ratio, fib_level in fib_set['extension_levels'].items():
            fib_price = fib_level['price']
            
            for inst_level in all_institutional:
                if abs(fib_price - inst_level['price']) <= tolerance_price:
                    confluence_strength = 1.0 / (1.0 + abs(fib_price - inst_level['price']) * 10000)
                    
                    set_confluences.append({
                        'fibonacci_ratio': ratio,
                        'fibonacci_price': fib_price,
                        'fibonacci_type': 'extension',
                        'institutional_type': inst_level['type'],
                        'institutional_price': inst_level['price'],
                        'confluence_strength': confluence_strength,
                        'price_difference_pips': int(abs(fib_price - inst_level['price']) / pip_value)
                    })
        
        if set_confluences:
            confluences.append({
                'fibonacci_set_id': fib_set['id'],
                'confluences': set_confluences,
                'confluence_count': len(set_confluences),
                'total_strength': sum([c['confluence_strength'] for c in set_confluences])
            })
    
    # Sort confluences by total strength
    confluences.sort(key=lambda x: x['total_strength'], reverse=True)
    
    return {
        'confluences': confluences,
        'total_confluence_sets': len(confluences),
        'strongest_confluence': confluences[0] if confluences else None
    }

def create_sample_price_data(current_price=1.2187, periods=50, is_jpy=False):
    """Create sample price data for testing."""
    
    np.random.seed(42)  # For reproducible results
    
    price_data = []
    base_price = current_price
    
    for i in range(periods):
        # Simulate price movement
        change = np.random.normal(0, 0.01 if not is_jpy else 1.0)  # Random walk
        base_price += change
        
        # Create OHLC data
        high = base_price + abs(np.random.normal(0, 0.005 if not is_jpy else 0.5))
        low = base_price - abs(np.random.normal(0, 0.005 if not is_jpy else 0.5))
        close = base_price + np.random.normal(0, 0.002 if not is_jpy else 0.2)
        
        price_data.append({
            'high': round(high, 4 if not is_jpy else 2),
            'low': round(low, 4 if not is_jpy else 2),
            'close': round(close, 4 if not is_jpy else 2),
            'timestamp': datetime.now() - timedelta(hours=periods-i)
        })
    
    return price_data

# Example usage and testing
if __name__ == "__main__":
    from updated_psychological_levels import get_psychological_levels
    
    print("=== Automated Fibonacci Level Generation ===")
    
    # Test with EUR/USD
    current_price = 1.2187
    instrument = 'EURUSD'
    is_jpy = False
    
    # Create sample price data
    price_data = create_sample_price_data(current_price, 50, is_jpy)
    print(f"Generated {len(price_data)} price periods")
    
    # Detect swing points
    swing_points = detect_swing_points(price_data, window=3)
    print(f"Detected {len(swing_points['swing_highs'])} swing highs, {len(swing_points['swing_lows'])} swing lows")
    
    # Find significant swings
    significant_swings = find_significant_swings(swing_points, min_pip_distance=50, is_jpy=is_jpy)
    print(f"Found {len(significant_swings)} significant swings")
    
    if significant_swings:
        for i, swing in enumerate(significant_swings[-3:]):  # Show last 3
            print(f"  Swing {i+1}: {swing['type'].title()} at {swing['price']} (index {swing['index']})")
    
    # Generate Fibonacci levels
    fibonacci_analysis = auto_generate_fibonacci_from_swings(significant_swings, current_price)
    print(f"\nGenerated {fibonacci_analysis['total_sets']} Fibonacci sets")
    
    if fibonacci_analysis['most_relevant']:
        most_relevant = fibonacci_analysis['most_relevant']
        print(f"\nMost Relevant Fibonacci Set:")
        print(f"  High: {most_relevant['high_swing']['price']} Low: {most_relevant['low_swing']['price']}")
        print(f"  Trend: {most_relevant['trend_direction']}")
        print(f"  Range: {most_relevant['swing_range_pips']} pips")
        print(f"  Relevance Score: {most_relevant['relevance_score']:.4f}")
        
        print(f"\n  Key Retracement Levels:")
        for ratio, level in most_relevant['retracement_levels'].items():
            if float(ratio) in [0.382, 0.5, 0.618]:  # Show key levels
                print(f"    {level['description']}: {level['price']}")
    
    # Test confluence with institutional levels
    institutional_levels = get_psychological_levels(current_price, instrument)
    confluence_analysis = integrate_fibonacci_with_institutional_levels(
        fibonacci_analysis, 
        institutional_levels, 
        tolerance_pips=15, 
        is_jpy=is_jpy
    )
    
    print(f"\nConfluence Analysis:")
    print(f"  Found {confluence_analysis['total_confluence_sets']} Fibonacci sets with institutional confluences")
    
    if confluence_analysis['strongest_confluence']:
        strongest = confluence_analysis['strongest_confluence']
        print(f"  Strongest confluence set has {strongest['confluence_count']} confluences:")
        
        for confluence in strongest['confluences'][:3]:  # Show top 3
            print(f"    Fib {confluence['fibonacci_ratio']} ({confluence['fibonacci_price']}) ≈ {confluence['institutional_type']} ({confluence['institutional_price']}) - {confluence['price_difference_pips']} pips apart")

