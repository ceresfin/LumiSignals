# LumiSignals Trading Core - Lambda Layer

**Shared trading infrastructure for psychological level trading strategies**

## Overview

The `lumisignals-trading-core` Lambda layer provides sophisticated market-aware momentum calculations and forex market schedule handling for LumiSignals trading strategies. This layer enables consistent, high-quality momentum analysis across all penny, quarter, dime, and small quarter trading Lambda functions.

## Features

### 🎯 Market-Aware Momentum Calculator
- **5-timeframe analysis**: 15m, 60m, 4h, 24h, 48h momentum calculations
- **Forex trading hours**: Proper weekend gap handling and start-of-week logic
- **Multi-strategy support**: Pennies, quarters, dimes, small quarters
- **Adaptive API granularity**: Optimal OANDA API usage based on lookback period
- **Consensus signal generation**: 3+ out of 5 timeframe alignment detection

### 📅 Forex Market Schedule
- **Trading session awareness**: Sunday 5pm EST to Friday 5pm EST
- **Timezone handling**: Automatic EST/EDT conversion with DST support
- **Weekend gap logic**: Intelligent historical lookback that skips market closures
- **Session information**: Sydney, Tokyo, London, New York session detection

## Quick Start

### 1. Deploy the Layer
```bash
./deploy-layer.sh
```

### 2. Add to Your Lambda Function
Add the layer ARN to your Lambda function configuration, then import:

```python
from lumisignals_trading_core import MarketAwareMomentumCalculator, ForexMarketSchedule
```

### 3. Basic Usage
```python
# Initialize momentum calculator
calc = MarketAwareMomentumCalculator(oanda_api)

# Get momentum summary for EUR/USD penny strategy
momentum_data = calc.get_momentum_summary('EUR_USD', 'pennies')

# Check overall bias
bias = momentum_data['momentum_summary']['overall_bias']
confidence = momentum_data['momentum_summary']['confidence']

print(f"EUR/USD momentum: {bias} (confidence: {confidence:.1%})")

# Get consensus trading signal
consensus = calc.get_consensus_signal('EUR_USD', 'pennies', required_confidence=0.6)

if consensus['trading_ready']:
    print(f"Trading signal: {consensus['signal']} - {consensus['aligned_timeframes']}/5 timeframes aligned")
```

## Strategy Types

The momentum calculator supports different timeframe sets optimized for each psychological level strategy:

### Pennies Strategy (Default)
- **15m**: 0.25 hours - Intraday momentum
- **60m**: 1 hour - Hourly momentum  
- **4h**: 4 hours - Quarter day momentum
- **24h**: 24 hours - Daily momentum
- **48h**: 48 hours - 2-day momentum

### Quarters Strategy
- **30m**: 0.5 hours - Intraday momentum
- **2h**: 2 hours - Short-term momentum
- **8h**: 8 hours - Third-day momentum  
- **24h**: 24 hours - Daily momentum
- **72h**: 72 hours - 3-day momentum

### Dimes Strategy  
- **1h**: 1 hour - Hourly momentum
- **4h**: 4 hours - Quarter-day momentum
- **24h**: 24 hours - Daily momentum
- **72h**: 72 hours - 3-day momentum
- **168h**: 168 hours - Weekly momentum

## API Reference

### MarketAwareMomentumCalculator

#### `get_momentum_data(instrument, strategy_type='pennies')`
Returns comprehensive momentum data across all timeframes for the specified strategy.

#### `get_momentum_summary(instrument, strategy_type='pennies')`  
Returns momentum summary with overall bias, strength, and directional analysis.

#### `get_consensus_signal(instrument, strategy_type='pennies', required_confidence=0.6)`
Returns trading consensus signal based on multi-timeframe alignment.

### ForexMarketSchedule

#### `get_market_time(utc_time=None)`
Converts UTC time to market time (EST/EDT).

#### `is_market_open(market_time)`
Checks if forex market is open at given market time.

#### `get_last_trading_time(from_market_time, hours_back)`
Gets last trading time going back specified hours with weekend gap handling.

### Utility Functions

#### `get_current_market_time()`
Gets current market time (EST/EDT).

#### `is_market_currently_open()`  
Checks if forex market is currently open.

#### `calculate_instrument_momentum(oanda_api, instrument, strategy_type)`
Quick momentum calculation for single instrument.

#### `get_trading_consensus(oanda_api, instrument, strategy_type)`
Quick consensus signal for single instrument.

#### `is_momentum_aligned(momentum_data, required_confidence=0.6)`
Checks if momentum meets alignment requirements.

## Integration with Existing Lambda Functions

### Replace Basic Momentum Calculator

**Before (basic momentum_calculator.py):**
```python
from momentum_calculator import calculate_momentum

momentum_60m = calculate_momentum(candles_60m)
momentum_4h = calculate_momentum(candles_4h)

if momentum_60m > 0.05 and momentum_4h > 0.05:
    direction = 'POSITIVE'
```

**After (with lumisignals-trading-core):**
```python
from lumisignals_trading_core import MarketAwareMomentumCalculator

calc = MarketAwareMomentumCalculator(oanda_api)
consensus = calc.get_consensus_signal('EUR_USD', 'pennies')

if consensus['trading_ready'] and consensus['confidence'] >= 0.6:
    direction = consensus['signal']  # BULLISH, BEARISH, or NEUTRAL
```

### Penny Curve Strategy Integration
```python
# In penny curve Lambda function handler
def lambda_handler(event, context):
    # Initialize momentum calculator  
    momentum_calc = MarketAwareMomentumCalculator(oanda_api)
    
    for instrument, market_data in market_data_dict.items():
        # Get sophisticated momentum consensus
        consensus = momentum_calc.get_consensus_signal(instrument, 'pennies')
        
        # Only proceed if 3+ timeframes aligned (60% confidence)
        if consensus['confidence'] >= 0.6:
            # Initialize penny strategy
            strategy = PC_H1_ALL_DUAL_LIMIT_20SL(config)
            
            # Enhance market data with momentum
            enhanced_market_data = {
                **market_data,
                'momentum_consensus': consensus,
                'momentum_direction': consensus['signal'],
                'momentum_strength': consensus['strength']
            }
            
            # Generate and validate signal
            analysis = strategy.analyze_market(enhanced_market_data)
            signal = strategy.generate_signal(analysis)
            
            if signal and strategy.validate_signal(signal)[0]:
                execute_trade(signal, oanda_api)
```

## Deployment

### Requirements
- AWS CLI configured with appropriate permissions
- Python 3.9+ environment  
- Zip utility

### Deploy Command
```bash
./deploy-layer.sh
```

The script will:
1. Package the Python modules and dependencies
2. Create deployment ZIP file
3. Upload to AWS Lambda as a new layer version
4. Display the Layer ARN for use in functions

### Layer Configuration
- **Compatible Runtimes**: python3.9, python3.10, python3.11
- **Compatible Architectures**: x86_64
- **Size**: ~50KB (lightweight, minimal dependencies)

## Testing

```python
# Test layer functionality
from lumisignals_trading_core import validate_layer

status = validate_layer()
print(status)
# Output: {'layer_status': 'healthy', 'version': '1.0.0', ...}

# Test momentum module
from lumisignals_trading_core.momentum import validate_module

momentum_status = validate_module()  
print(momentum_status)
# Output: {'status': 'success', 'current_market_time': '2025-09-12T14:30:00-04:00', ...}
```

## Architecture Integration

This layer is designed to integrate with the existing LumiSignals infrastructure:

- **Data Orchestrator**: Provides 500 H1/M5 candles via tiered Redis storage
- **Lambda Functions**: Use this layer for consistent momentum calculations
- **Frontend Dashboard**: Can connect to momentum API for validation
- **Penny Strategies**: Replace basic momentum with sophisticated 5-timeframe analysis

## Performance

- **Cold Start**: Minimal impact due to lightweight dependencies
- **Memory Usage**: ~10-15MB additional memory per Lambda function
- **API Efficiency**: Adaptive granularity reduces OANDA API calls
- **Caching**: Designed for easy integration with Redis caching

## Next Steps

1. **Deploy the layer** using the provided script
2. **Update penny curve Lambda functions** to use the new momentum calculator
3. **Remove TODO placeholders** and integrate consensus-based trading logic
4. **Add momentum API endpoint** for frontend validation
5. **Expand layer** with sentiment analysis and other shared components

---

**Version**: 1.0.0  
**Author**: LumiSignals Trading Team  
**Last Updated**: September 12, 2025