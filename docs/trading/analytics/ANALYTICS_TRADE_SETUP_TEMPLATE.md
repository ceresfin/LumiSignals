# Analytics & Trade Setup Development Template

## Overview
This template guides the development of new analytics and their corresponding trade setup logic for the LumiSignals trading system. The system is designed for high-volume trading (40+ trades/day) across 28 currency pairs.

## Architecture Context
- **Lambda Function**: `signal-analytics-api` (centralized approach)
- **Data Source**: Redis cluster with tiered data (hot/warm/cold)
- **Deployment**: AWS Lambda with `deploy_with_trading_core.py`
- **Risk Requirements**: Minimum 1.6667 (5:3) risk/reward ratio
- **Frontend**: React/TypeScript dashboard at pipstop.org

## Step 1: Create New Analytic Function

### 1.1 Analytic Function Template
```python
def analyze_[analytic_name]_tiered(price_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze [analytic name] using tiered price data
    
    Args:
        price_data: Dictionary containing:
            - combined: List of candles (hot + warm data)
            - current_price: Current market price
            - instrument: Currency pair (e.g., 'EUR_USD')
            - timeframe: Timeframe (e.g., 'H1')
            - total_candles: Number of candles available
    
    Returns:
        Dictionary with analytic results
    """
    try:
        from lumisignals_trading_core.[module] import [analysis_function]
        
        instrument = price_data['instrument']
        current_price = price_data['current_price']
        combined_candles = price_data['combined']
        
        # Convert Redis candle format to analysis format
        formatted_candles = []
        for candle in combined_candles:
            formatted_candles.append({
                'high': float(candle.get('h', candle.get('high', 0))),
                'low': float(candle.get('l', candle.get('low', 0))),
                'close': float(candle.get('c', candle.get('close', 0))),
                'open': float(candle.get('o', candle.get('open', 0))),
                'timestamp': candle.get('time', candle.get('timestamp', ''))
            })
        
        # Perform analysis
        if current_price and len(formatted_candles) > 10:
            result = [analysis_function](instrument, current_price, formatted_candles, timeframe=price_data['timeframe'])
            
            logger.info(f"[Analytic] analysis for {instrument}: {result}")
            
            return {
                # Core analytic data
                'signal': result.get('signal', 'neutral'),
                'strength': result.get('strength', 0),
                'levels': result.get('levels', []),
                'direction': result.get('direction', 'neutral'),
                
                # Additional metadata
                'confidence': result.get('confidence', 0),
                'key_level': result.get('key_level', 0),
                'timeframe': price_data['timeframe'],
                'candles_analyzed': len(formatted_candles),
                
                # Any analytic-specific data
                'custom_field': result.get('custom_field', None)
            }
        else:
            raise Exception("Insufficient data for analysis")
            
    except Exception as e:
        logger.error(f"[Analytic] analysis error for {price_data['instrument']}: {str(e)}")
        # Return fallback result
        return create_fallback_[analytic](price_data)

def create_fallback_[analytic](price_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create fallback [analytic] analysis when primary analysis fails"""
    instrument = price_data['instrument']
    current_price = price_data['current_price'] or 1.1000
    
    return {
        'signal': 'neutral',
        'strength': 0,
        'levels': [],
        'direction': 'neutral',
        'confidence': 0.1,
        'fallback': True,
        'message': f'Using fallback [analytic] analysis for {instrument}'
    }
```

### 1.2 Integration in generate_pair_analytics()
```python
# In generate_pair_analytics function, add:
[analytic]_data = analyze_[analytic]_tiered(price_data)

# Add to return dictionary:
return {
    # ... existing fields ...
    '[analytic]': [analytic]_data,
    # ... rest of fields ...
}
```

## Step 2: Create Trade Setup Functions

### 2.1 Individual Signal Trade Setup Template
```python
def generate_[analytic]_trade_setups(analytic_data: Dict[str, Any], instrument: str, 
                                     current_price: float) -> List[Dict[str, Any]]:
    """
    Generate trade setups from [analytic] analysis
    Minimum risk/reward ratio: 1.6667 (5:3)
    
    Args:
        analytic_data: Results from analyze_[analytic]_tiered()
        instrument: Currency pair (e.g., 'EUR_USD')
        current_price: Current market price
    
    Returns:
        List of trade setup dictionaries
    """
    try:
        if not analytic_data or analytic_data.get('fallback', False):
            return []
        
        signal = analytic_data.get('signal', 'neutral')
        strength = analytic_data.get('strength', 0)
        levels = analytic_data.get('levels', [])
        
        # Skip if no clear signal
        if signal == 'neutral' or strength < 0.6:
            return []
        
        is_jpy_pair = 'JPY' in instrument
        pip_factor = 100 if is_jpy_pair else 10000
        min_risk_reward = 1.6667
        
        trade_setups = []
        
        # Generate setups based on signal type
        if signal == 'bullish':
            setup = generate_[analytic]_bullish_setup(
                instrument, analytic_data, current_price, 
                pip_factor, min_risk_reward
            )
            if setup:
                trade_setups.append(setup)
                
        elif signal == 'bearish':
            setup = generate_[analytic]_bearish_setup(
                instrument, analytic_data, current_price,
                pip_factor, min_risk_reward
            )
            if setup:
                trade_setups.append(setup)
        
        return trade_setups
        
    except Exception as e:
        logger.error(f"Error generating [analytic] trade setups for {instrument}: {e}")
        return []

def generate_[analytic]_bullish_setup(instrument: str, analytic_data: Dict[str, Any],
                                     current_price: float, pip_factor: int, 
                                     min_risk_reward: float) -> Dict[str, Any]:
    """Generate bullish trade setup from [analytic] signal"""
    try:
        # Extract key levels/data from analytic
        entry_level = analytic_data.get('entry_level', current_price)
        support_level = analytic_data.get('support_level', current_price * 0.995)
        resistance_level = analytic_data.get('resistance_level', current_price * 1.01)
        
        # Entry logic (customize based on analytic)
        entry = entry_level
        
        # Stop loss logic (customize based on analytic)
        stop_buffer_pips = get_[analytic]_stop_buffer(analytic_data)
        stop_loss = support_level - (stop_buffer_pips / pip_factor)
        
        # Calculate risk in pips
        risk_pips = abs(entry - stop_loss) * pip_factor
        
        # Target logic (customize based on analytic)
        min_target_pips = risk_pips * min_risk_reward
        target_price = entry + (min_target_pips / pip_factor)
        
        # Use resistance or calculated target, whichever is better
        if resistance_level > target_price:
            target_price = resistance_level
        
        # Calculate actual risk/reward ratio
        reward_pips = abs(target_price - entry) * pip_factor
        risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
        
        # Only return setup if it meets minimum risk/reward
        if risk_reward_ratio < min_risk_reward:
            return None
        
        # Calculate position sizing
        position_size = calculate_position_size(instrument, risk_pips, target_risk_percent=1.0)
        
        return {
            'type': 'bullish',
            'source': '[analytic]',
            'instrument': instrument,
            'entry_price': round(entry, 5),
            'stop_loss': round(stop_loss, 5),
            'target_price': round(target_price, 5),
            'signal_strength': analytic_data.get('strength', 0),
            'risk_pips': round(risk_pips, 1),
            'reward_pips': round(reward_pips, 1),
            'risk_reward_ratio': round(risk_reward_ratio, 2),
            'position_size': position_size,
            'setup_quality': get_setup_quality(risk_reward_ratio, analytic_data.get('confidence', 0)),
            'current_distance_pips': round(abs(current_price - entry) * pip_factor, 1),
            'analytic_details': {
                # Include relevant analytic-specific data
                'key_level': analytic_data.get('key_level'),
                'confidence': analytic_data.get('confidence')
            }
        }
        
    except Exception as e:
        logger.error(f"Error generating bullish [analytic] setup: {e}")
        return None
```

### 2.2 Confluence Trade Setup Template
```python
def generate_confluence_trade_setups(all_analytics: Dict[str, Any], instrument: str,
                                   current_price: float) -> List[Dict[str, Any]]:
    """
    Generate trade setups using confluence of multiple analytics
    
    Args:
        all_analytics: Dictionary containing all analytic results
        instrument: Currency pair
        current_price: Current market price
    
    Returns:
        List of confluence-based trade setups
    """
    try:
        # Extract individual analytics
        fibonacci_data = all_analytics.get('fibonacci', {})
        [analytic]_data = all_analytics.get('[analytic]', {})
        momentum_data = all_analytics.get('momentum', {})
        
        # Define confluence criteria
        signals = []
        
        # Check Fibonacci signal
        if fibonacci_data.get('direction') == 'bullish':
            signals.append(('fibonacci', 'bullish', fibonacci_data.get('relevance_score', 0)))
        elif fibonacci_data.get('direction') == 'bearish':
            signals.append(('fibonacci', 'bearish', fibonacci_data.get('relevance_score', 0)))
        
        # Check [analytic] signal
        if [analytic]_data.get('signal') == 'bullish':
            signals.append(('[analytic]', 'bullish', [analytic]_data.get('strength', 0)))
        elif [analytic]_data.get('signal') == 'bearish':
            signals.append(('[analytic]', 'bearish', [analytic]_data.get('strength', 0)))
        
        # Check momentum signal
        if momentum_data.get('overall_bias') == 'BULLISH':
            signals.append(('momentum', 'bullish', momentum_data.get('confidence', 0)))
        elif momentum_data.get('overall_bias') == 'BEARISH':
            signals.append(('momentum', 'bearish', momentum_data.get('confidence', 0)))
        
        # Require at least 2 signals in agreement
        bullish_signals = [(s, score) for s, direction, score in signals if direction == 'bullish']
        bearish_signals = [(s, score) for s, direction, score in signals if direction == 'bearish']
        
        trade_setups = []
        
        if len(bullish_signals) >= 2:
            # Generate bullish confluence setup
            setup = generate_confluence_bullish_setup(
                instrument, all_analytics, bullish_signals, current_price
            )
            if setup:
                trade_setups.append(setup)
                
        if len(bearish_signals) >= 2:
            # Generate bearish confluence setup
            setup = generate_confluence_bearish_setup(
                instrument, all_analytics, bearish_signals, current_price
            )
            if setup:
                trade_setups.append(setup)
        
        return trade_setups
        
    except Exception as e:
        logger.error(f"Error generating confluence trade setups: {e}")
        return []

def generate_confluence_bullish_setup(instrument: str, all_analytics: Dict[str, Any],
                                     confirming_signals: List[tuple], current_price: float) -> Dict[str, Any]:
    """Generate bullish setup from multiple confirming signals"""
    try:
        is_jpy_pair = 'JPY' in instrument
        pip_factor = 100 if is_jpy_pair else 10000
        min_risk_reward = 1.6667
        
        # Combine levels from different analytics for optimal entry/stop/target
        fibonacci_data = all_analytics.get('fibonacci', {})
        [analytic]_data = all_analytics.get('[analytic]', {})
        
        # Entry: Use most conservative entry from confirming signals
        entries = []
        if 'fibonacci' in [s[0] for s in confirming_signals]:
            fib_levels = fibonacci_data.get('detailed_levels', [])
            for level in fib_levels:
                if level['ratio'] >= 0.5:  # 50% or deeper retracement
                    entries.append(level['price'])
        
        if '[analytic]' in [s[0] for s in confirming_signals]:
            entries.append([analytic]_data.get('entry_level', current_price))
        
        entry = min(entries) if entries else current_price  # Most conservative for bullish
        
        # Stop loss: Use tightest stop that maintains good R:R
        stops = []
        if fibonacci_data.get('low'):
            stops.append(fibonacci_data['low'] - (5 / pip_factor))
        if [analytic]_data.get('support_level'):
            stops.append([analytic]_data['support_level'] - (5 / pip_factor))
        
        stop_loss = max(stops) if stops else entry - (20 / pip_factor)  # Tightest stop
        
        # Target: Use confluence of resistance levels
        targets = []
        if fibonacci_data.get('high'):
            # Fibonacci extension
            swing_range = fibonacci_data['high'] - fibonacci_data['low']
            targets.append(fibonacci_data['high'] + (swing_range * 0.618))  # 161.8% extension
        if [analytic]_data.get('resistance_level'):
            targets.append([analytic]_data['resistance_level'])
        
        # Calculate required target for minimum R:R
        risk_pips = abs(entry - stop_loss) * pip_factor
        min_target = entry + (risk_pips * min_risk_reward / pip_factor)
        
        # Use best available target
        target_price = max(targets) if targets and max(targets) > min_target else min_target
        
        # Calculate final risk/reward
        reward_pips = abs(target_price - entry) * pip_factor
        risk_reward_ratio = reward_pips / risk_pips if risk_pips > 0 else 0
        
        if risk_reward_ratio < min_risk_reward:
            return None
        
        # Calculate confluence strength
        avg_strength = sum(score for _, score in confirming_signals) / len(confirming_signals)
        
        return {
            'type': 'bullish',
            'source': 'confluence',
            'instrument': instrument,
            'entry_price': round(entry, 5),
            'stop_loss': round(stop_loss, 5),
            'target_price': round(target_price, 5),
            'confirming_signals': [s[0] for s in confirming_signals],
            'confluence_strength': round(avg_strength, 2),
            'risk_pips': round(risk_pips, 1),
            'reward_pips': round(reward_pips, 1),
            'risk_reward_ratio': round(risk_reward_ratio, 2),
            'position_size': calculate_position_size(instrument, risk_pips, target_risk_percent=1.5),  # Higher risk for confluence
            'setup_quality': 'excellent' if avg_strength > 0.8 else 'good',
            'current_distance_pips': round(abs(current_price - entry) * pip_factor, 1)
        }
        
    except Exception as e:
        logger.error(f"Error generating confluence bullish setup: {e}")
        return None
```

## Step 3: Integration Checklist

### 3.1 Add to generate_pair_analytics()
- [ ] Add analytic function call: `[analytic]_data = analyze_[analytic]_tiered(price_data)`
- [ ] Add to return dictionary: `'[analytic]': [analytic]_data,`

### 3.2 Add Individual Trade Setups
- [ ] Call trade setup function after analytic generation
- [ ] Add setups to consolidated list

### 3.3 Update Confluence Logic
- [ ] Add new analytic to confluence checks
- [ ] Define signal extraction logic
- [ ] Set appropriate weight/importance

### 3.4 Frontend Integration
- [ ] Add to signal list in `CurrencyPairGraphsWithTrades.tsx`
- [ ] Create visualization logic if needed
- [ ] Add to toggle controls

## Step 4: Testing Template

### 4.1 Create Test File: test_[analytic]_analysis.py
```python
#!/usr/bin/env python3
"""Test script for [analytic] analysis and trade setups"""

import json
from lambda_function import analyze_[analytic]_tiered, generate_[analytic]_trade_setups

def test_[analytic]_analysis():
    """Test [analytic] analysis with sample data"""
    
    # Create sample price data
    sample_price_data = {
        'instrument': 'EUR_USD',
        'current_price': 1.1050,
        'timeframe': 'H1',
        'total_candles': 100,
        'combined': [
            {'o': 1.1000, 'h': 1.1020, 'l': 1.0980, 'c': 1.1010, 'time': '2024-01-01T00:00:00Z'},
            # Add more sample candles as needed
        ]
    }
    
    # Test analysis
    result = analyze_[analytic]_tiered(sample_price_data)
    print(f"Analysis Result: {json.dumps(result, indent=2)}")
    
    # Test trade setups
    setups = generate_[analytic]_trade_setups(result, 'EUR_USD', 1.1050)
    print(f"Trade Setups: {json.dumps(setups, indent=2)}")

if __name__ == "__main__":
    test_[analytic]_analysis()
```

### 4.2 Deployment Steps
1. Update `lambda_function.py` with new analytic code
2. Run local tests: `python3 test_[analytic]_analysis.py`
3. Deploy: `python3 deploy_with_trading_core.py`
4. Test via API: `curl -X GET "https://[lambda-url]/analytics/all-signals?timeframe=H1"`

## Step 5: Common Patterns & Best Practices

### 5.1 Risk Management
- Always enforce minimum 1.6667 risk/reward ratio
- Use dynamic stop buffers based on market conditions
- Scale position size with confidence level

### 5.2 Signal Quality
- Individual signals: Require minimum 0.6 strength/confidence
- Confluence signals: Require 2+ confirming signals
- Weight signals by their historical accuracy

### 5.3 Error Handling
- Always provide fallback values
- Log errors with context
- Never crash on bad data

### 5.4 Performance
- Use the shared price_data object
- Avoid redundant calculations
- Cache expensive computations

## Example Analytics to Implement

1. **RSI Divergence**
   - Signal: Bullish/bearish divergence
   - Entry: After divergence confirmation
   - Stop: Recent swing high/low
   - Target: Previous resistance/support

2. **Moving Average Crossover**
   - Signal: MA cross direction
   - Entry: On pullback to fast MA
   - Stop: Below slow MA
   - Target: 1.618 * risk or next resistance

3. **Supply/Demand Zones**
   - Signal: Zone rejection
   - Entry: At zone edge
   - Stop: Beyond zone
   - Target: Opposite zone

4. **Candlestick Patterns**
   - Signal: Pattern completion
   - Entry: Pattern close
   - Stop: Pattern low/high
   - Target: Pattern projection

5. **Market Structure**
   - Signal: Break of structure
   - Entry: Retest of broken level
   - Stop: Previous structure
   - Target: Next structure level

## Notes
- This architecture supports 40+ trades/day across 28 pairs
- All analytics share the same price data for efficiency
- Trade setups can be generated individually or with confluence
- System is designed to scale to 7-12 analytics over time
- Frontend automatically displays new analytics when added