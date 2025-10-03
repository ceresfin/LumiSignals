# LumiSignals Momentum Calculation Analysis
*Current Implementation vs. Desired Multi-Timeframe Alignment*

**Analysis Date**: September 12, 2025  
**Scope**: Penny curve trading strategies momentum logic  
**Key Finding**: Current strategies do NOT implement the sophisticated multi-timeframe alignment approach

---

## 🔍 **Current Momentum Implementation**

### **What the Strategies Currently Use**
All penny curve strategies use very **basic momentum logic**:

```python
def _calculate_momentum(self, market_data: Dict) -> Dict:
    """Calculate momentum for direction determination"""
    return {
        'momentum_5m': market_data.get('momentum_5m', 0),
        'momentum_60m': market_data.get('momentum_60m', 0),  # PRIMARY
        'momentum_4h': market_data.get('momentum_4h', 0),
        'momentum_24h': market_data.get('momentum_24h', 0)
    }
    
# Primary momentum direction (only uses 60m):
primary_momentum = momentum_data.get('momentum_60m', 0)
if abs(primary_momentum) < self.momentum_threshold:
    return "No signal - insufficient momentum"
```

### **Simple Dual-Timeframe Alignment**
The `momentum_calculator.py` has basic alignment for **only 2 timeframes**:

```python
def determine_momentum_direction(momentum_60m: float, momentum_4h: float, 
                               threshold: float = 0.05) -> str:
    """Determine overall momentum direction"""
    # Both timeframes must agree
    if momentum_60m > threshold and momentum_4h > threshold:
        return 'POSITIVE'
    elif momentum_60m < -threshold and momentum_4h < -threshold:
        return 'NEGATIVE' 
    else:
        return 'NEUTRAL'
```

---

## 🎯 **Your Desired Implementation**

### **Multi-Timeframe Alignment Approach**
You want momentum calculated as:
1. **15 minutes**: % change over last 15 minutes
2. **60 minutes**: % change over last 60 minutes  
3. **4 hours**: % change over last 4 hours
4. **24 hours**: % change over last 24 hours
5. **48 hours**: % change over last 48 hours

### **Alignment Logic**
```python
# Desired approach:
momentum_alignment = {
    '15m': calculate_momentum_change(current_bid, bid_15min_ago),
    '60m': calculate_momentum_change(current_bid, bid_60min_ago), 
    '4h': calculate_momentum_change(current_bid, bid_4h_ago),
    '24h': calculate_momentum_change(current_bid, bid_24h_ago),
    '48h': calculate_momentum_change(current_bid, bid_48h_ago)
}

# Check if majority (3+ out of 5) are aligned in same direction
positive_count = sum(1 for m in momentum_alignment.values() if m > threshold)
negative_count = sum(1 for m in momentum_alignment.values() if m < -threshold)

if positive_count >= 3:
    overall_momentum = 'POSITIVE'
elif negative_count >= 3:
    overall_momentum = 'NEGATIVE'
else:
    overall_momentum = 'NEUTRAL'  # No clear alignment
```

---

## ❌ **Gap Analysis: What's Missing**

### **1. Missing Timeframes**
| Timeframe | Current Status | Your Requirement |
|-----------|----------------|------------------|
| 15 minutes | ❌ Not implemented | ✅ Required |
| 60 minutes | ✅ Basic implementation | ✅ Required |
| 4 hours | ✅ Basic implementation | ✅ Required |  
| 24 hours | ✅ Collected but unused | ✅ Required |
| 48 hours | ❌ Not implemented | ✅ Required |

### **2. Missing Alignment Logic**
- **Current**: Single-timeframe decision (60m only)
- **Desired**: Multi-timeframe consensus (3+ out of 5 must agree)

### **3. Missing Calculation Method**
- **Current**: Pre-calculated values from `market_data` 
- **Desired**: Real-time calculation using current bid vs. historical bids

### **4. Missing Sophisticated Filtering**
- **Current**: Simple 5% threshold on 60m momentum
- **Desired**: Majority alignment across 5 timeframes

---

## 🔧 **Implementation Required**

### **Enhanced Momentum Calculator**
```python
class MultiTimeframeMomentumCalculator:
    """
    Enhanced momentum calculator using 5-timeframe alignment approach
    """
    
    def __init__(self, threshold=0.05):
        self.threshold = threshold
        self.timeframes = {
            '15m': 15 * 60,      # 15 minutes in seconds
            '60m': 60 * 60,      # 1 hour in seconds  
            '4h': 4 * 60 * 60,   # 4 hours in seconds
            '24h': 24 * 60 * 60, # 24 hours in seconds
            '48h': 48 * 60 * 60  # 48 hours in seconds
        }
    
    def calculate_momentum_change(self, current_bid: float, historical_bid: float) -> float:
        """Calculate percentage change between current and historical price"""
        if historical_bid == 0:
            return 0.0
        return (current_bid - historical_bid) / historical_bid
    
    def get_historical_bids(self, instrument: str, current_time: datetime) -> Dict[str, float]:
        """
        Get historical bid prices for all required timeframes
        This would query your centralized data system
        """
        historical_bids = {}
        
        for timeframe, seconds_back in self.timeframes.items():
            historical_time = current_time - timedelta(seconds=seconds_back)
            # Query Redis/PostgreSQL for bid price at historical_time
            historical_bids[timeframe] = self.get_bid_at_time(instrument, historical_time)
        
        return historical_bids
    
    def calculate_multi_timeframe_momentum(self, instrument: str, current_bid: float) -> Dict:
        """
        Calculate momentum across all 5 timeframes and determine alignment
        """
        current_time = datetime.now()
        historical_bids = self.get_historical_bids(instrument, current_time)
        
        # Calculate momentum for each timeframe
        momentum_values = {}
        for timeframe in self.timeframes.keys():
            historical_bid = historical_bids.get(timeframe, current_bid)
            momentum_values[timeframe] = self.calculate_momentum_change(
                current_bid, historical_bid
            )
        
        # Determine alignment
        positive_count = sum(1 for m in momentum_values.values() if m > self.threshold)
        negative_count = sum(1 for m in momentum_values.values() if m < -self.threshold)
        neutral_count = 5 - positive_count - negative_count
        
        # Majority rule (3+ out of 5 must agree)
        if positive_count >= 3:
            overall_direction = 'POSITIVE'
            confidence = positive_count / 5  # 60%, 80%, or 100%
        elif negative_count >= 3:
            overall_direction = 'NEGATIVE'  
            confidence = negative_count / 5   # 60%, 80%, or 100%
        else:
            overall_direction = 'NEUTRAL'
            confidence = max(positive_count, negative_count) / 5
        
        return {
            'timeframe_momentum': momentum_values,
            'overall_direction': overall_direction,
            'confidence': confidence,
            'positive_timeframes': positive_count,
            'negative_timeframes': negative_count,
            'neutral_timeframes': neutral_count,
            'alignment_strength': max(positive_count, negative_count) / 5
        }
```

### **Integration with Penny Curve Strategies**
```python
# Replace simple momentum logic in penny curve strategies:
def _calculate_momentum(self, market_data: Dict) -> Dict:
    """Enhanced momentum using 5-timeframe alignment"""
    
    momentum_calc = MultiTimeframeMomentumCalculator(threshold=self.momentum_threshold)
    
    current_bid = market_data.get('bid', market_data.get('current_price'))
    instrument = market_data['instrument']
    
    # Get sophisticated momentum analysis
    momentum_analysis = momentum_calc.calculate_multi_timeframe_momentum(
        instrument, current_bid
    )
    
    # Only generate signals if 3+ timeframes align (60%+ confidence)
    if momentum_analysis['confidence'] < 0.6:
        return {
            'signal': None,
            'reason': f'Insufficient momentum alignment: {momentum_analysis["alignment_strength"]:.1%}',
            'momentum_analysis': momentum_analysis
        }
    
    return momentum_analysis
```

---

## 📊 **Comparison: Current vs. Desired**

| Aspect | Current Implementation | Your Desired Approach | Improvement |
|--------|----------------------|----------------------|-------------|
| **Timeframes** | 60m primary, 4h secondary | 15m, 60m, 4h, 24h, 48h | ⬆️ 150% more comprehensive |
| **Alignment Logic** | Single timeframe decision | 3+ out of 5 must agree | ⬆️ Much more reliable |
| **Calculation** | Pre-calculated values | Real-time bid comparison | ⬆️ More accurate and current |
| **Confidence Scoring** | Binary pass/fail | Graduated 60%-100% | ⬆️ Nuanced signal quality |
| **Signal Filtering** | 5% threshold on 60m | Majority consensus required | ⬆️ Higher quality signals |

---

## 🎯 **Implementation Impact**

### **Expected Improvements**
✅ **Higher Signal Quality**: 3+ timeframes must agree vs. single timeframe  
✅ **Reduced False Signals**: Multi-timeframe consensus filters noise  
✅ **Better Risk Management**: Confidence scoring for position sizing  
✅ **More Robust Entries**: 48h and 24h confirm longer-term trends  
✅ **Intraday Precision**: 15m momentum catches short-term reversals  

### **Trade-offs**
⚠️ **Fewer Signals**: More stringent requirements = less frequent trades  
⚠️ **More Complex**: 5x more momentum calculations required  
⚠️ **Data Dependencies**: Need historical bid data for all timeframes  

---

## 🚨 **Answer to Your Question**

**NO**, none of the current penny curve strategies implement your sophisticated **15min-60min-4hr-24hr-48hr momentum alignment approach**. 

**Current strategies use:**
- ❌ Simple 60m momentum threshold (5%)
- ❌ Basic 60m + 4h dual alignment  
- ❌ No 15min or 48hr momentum
- ❌ No majority consensus logic
- ❌ No confidence scoring

**Your approach would be a MAJOR enhancement** that could significantly improve signal quality and reduce false positives by requiring multi-timeframe momentum consensus before generating penny level trades.

**Recommendation**: Implement your multi-timeframe alignment approach as an **enhanced momentum module** that can be integrated into both V1 and V2 penny curve strategies for superior performance.