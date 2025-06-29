# Trading Strategy Architecture Blueprint
## **Comprehensive Guide for Multi-Strategy Trading Bot Development**

---

## 📋 **Table of Contents**
1. [System Overview](#system-overview)
2. [Core Architecture Components](#core-architecture-components)
3. [Data Flow & Integration Points](#data-flow--integration-points)
4. [Strategy Development Template](#strategy-development-template)
5. [Metadata & Analytics Framework](#metadata--analytics-framework)
6. [Airtable Integration Specifications](#airtable-integration-specifications)
7. [File Structure & Naming Conventions](#file-structure--naming-conventions)
8. [Implementation Checklist](#implementation-checklist)
9. [Scaling Considerations](#scaling-considerations)

---

## 🏗️ **System Overview**

### **High-Level Architecture**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Strategy 1    │    │   Strategy 2    │    │   Strategy N    │
│ (Penny Curve)   │    │ (Quarter Curve) │    │   (Future)      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │  Main Trading   │
                    │     Engine      │
                    └─────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Metadata Store  │    │  OANDA API      │    │ Airtable Sync   │
│ (Local JSON)    │    │ (Orders/Data)   │    │ (Analytics)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### **Strategy Lifecycle**
1. **Market Analysis** → Signal Detection
2. **Order Creation** → Metadata Generation  
3. **Local Storage** → Metadata Persistence
4. **OANDA Execution** → Order Placement
5. **Sync Process** → Airtable Population
6. **Analytics** → Performance Tracking

---

## 🧩 **Core Architecture Components**

### **1. Strategy Engine (Per Strategy)**
**File Pattern**: `{Strategy_Name}_Strategy.py`
- **Purpose**: Contains strategy-specific logic
- **Key Functions**:
  - `analyze_setup()` - Market analysis
  - `generate_signals()` - Trade signal creation
  - `calculate_risk_reward()` - R:R calculations
  - `create_metadata()` - Strategy-specific metadata

### **2. Unified Trading Bot**
**File**: `Demo_Trading_Multi_Strategy.py`
- **Purpose**: Orchestrates all strategies
- **Key Functions**:
  - Strategy selection and rotation
  - Risk management across strategies
  - Order execution and tracking
  - Metadata coordination

### **3. Metadata Storage System**
**File**: `metadata_storage.py`
- **Purpose**: Centralized metadata management
- **Key Functions**:
  - Strategy-agnostic metadata storage
  - Enhanced field mapping for Airtable
  - Validation and cleanup
  - Cross-strategy analytics

### **4. OANDA API Integration**
**File**: `oanda_api.py`
- **Purpose**: Unified broker interface
- **Key Functions**:
  - Order placement (all order types)
  - Account management
  - Price data retrieval
  - Error handling and retries

### **5. Airtable Sync Engine**
**File**: `sync_all.py`
- **Purpose**: Data pipeline to analytics platform
- **Key Functions**:
  - Transaction processing
  - Metadata enrichment
  - Price tracking and updates
  - Strategy-specific field mapping

---

## 🔄 **Data Flow & Integration Points**

### **Metadata Flow Architecture**
```
Strategy Analysis
        │
        ▼
┌─────────────────┐
│ Signal Created  │
│ + Metadata Gen  │
└─────────────────┘
        │
        ▼
┌─────────────────┐      ┌─────────────────┐
│ Local Storage   │────▶ │ OANDA Order     │
│ metadata.json   │      │ (No metadata)   │
└─────────────────┘      └─────────────────┘
        │                         │
        ▼                         ▼
┌─────────────────┐      ┌─────────────────┐
│ Sync Process    │◀─────│ Transaction     │
│ Metadata Lookup │      │ Monitoring      │
└─────────────────┘      └─────────────────┘
        │
        ▼
┌─────────────────┐
│ Airtable Update │
│ All Fields Pop. │
└─────────────────┘
```

### **Critical Integration Points**
1. **Strategy → Metadata**: Each strategy must generate standardized metadata
2. **Metadata → Storage**: Local persistence before order execution
3. **Storage → Sync**: Metadata retrieval during transaction processing
4. **Sync → Airtable**: Field mapping and data population

---

## 📐 **Strategy Development Template**

### **Standard Strategy Structure**
```python
class {StrategyName}Strategy:
    """
    {Strategy Description}
    
    Key Features:
    - {Feature 1}
    - {Feature 2}
    - {Feature 3}
    """
    
    def __init__(self, specialized_analyzer1, specialized_analyzer2):
        # Strategy-specific analyzers (not just momentum_calc)
        self.analyzer1 = specialized_analyzer1
        self.analyzer2 = specialized_analyzer2
        self.strategy_name = "{StrategyName}"
        self.strategy_tag = "{TAG}"  # 3-4 char abbreviation
        self.logger = logging.getLogger(__name__)
    
    def analyze_{strategy_specific}_opportunities(self, instrument: str) -> List[Dict]:
        """
        Strategy-specific analysis method - returns list of opportunities
        
        Returns:
        List[{
            'instrument': str,
            'strategy_name': str,
            'action': 'BUY'|'SELL',
            'order_type': 'MARKET'|'LIMIT',
            'entry_price': float,
            'stop_loss': float,
            'take_profit': float,
            'confidence': int (0-100),
            'reasoning': List[str],
            'expiration': str|None,
            # Strategy-specific fields
            'custom_field_1': Any,
            'custom_field_2': Any,
        }]
        """
        opportunities = []
        
        try:
            # 1. Get market data
            # 2. Apply strategy-specific analysis
            # 3. Detect signals
            # 4. Calculate entry/exit levels
            # 5. Validate opportunities
            # 6. Return opportunity list
            
        except Exception as e:
            self.logger.error(f"Error analyzing {instrument}: {e}")
        
        return opportunities
```

### **Trade Order Data Class Pattern**
```python
@dataclass
class {Strategy}TradeOrder:
    """Strategy-specific trade order data class"""
    # Universal fields (all strategies)
    instrument: str
    action: str  # 'BUY' or 'SELL'
    order_type: str  # 'MARKET' or 'LIMIT'
    entry_price: float
    stop_loss: float
    take_profit: float
    units: int
    confidence: int
    reasoning: List[str]
    timestamp: str
    strategy_name: str
    
    # Strategy-specific fields
    custom_field_1: Any
    custom_field_2: Any
    
    # Standard optional fields
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    
    # Integration fields
    momentum_analysis: Optional[Dict] = None
    zone_data: Optional[Dict] = None
    analysis_data: Optional[Dict] = None

# Example from Quarter Curve:
@dataclass
class QuarterCurveTradeOrder:
    # ... universal fields ...
    quarter_above: float          # Strategy-specific
    quarter_below: float          # Strategy-specific
    breach_direction: str         # Strategy-specific
    candlestick_strength: str     # Strategy-specific
    bodyguard_breached: float     # Strategy-specific
    stop_pips: int               # Strategy-specific
    target_pips: int             # Strategy-specific
```

### **Mandatory Strategy Methods**
1. **`analyze_{strategy_name}_opportunities()`** - Core strategy logic returning opportunity list
2. **`create_airtable_metadata()`** - Metadata generation from trade order  
3. **`calculate_position_size()`** - Position sizing (can delegate to risk manager)
4. **Strategy-specific analyzers** - Separate classes for complex analysis logic

### **Strategy Component Pattern**
```python
# Separate analyzer classes for complex logic
class {Strategy}SpecializedAnalyzer:
    """Handles strategy-specific market analysis"""
    
class {Strategy}SignalDetector:
    """Detects strategy-specific trading signals"""

# Main strategy class coordinates components
class {Strategy}Strategy:
    def __init__(self, analyzer1, analyzer2):
        self.analyzer1 = analyzer1
        self.analyzer2 = analyzer2
```

---

## 📊 **Metadata & Analytics Framework**

### **Signal Quality Metrics Framework**

#### **Universal Signal Metrics (All Strategies)**
Every strategy must implement these two core signal quality metrics:

1. **Momentum Strength** (0.50-0.95 decimal): Power and intensity of the price movement
2. **Signal Confidence** (60-95 integer): Reliability and probability of success

```python
# Standard implementation template for all strategies
class StrategySignalMetrics:
    """Base class for strategy signal quality calculations"""
    
    def calculate_momentum_strength(self, price_data: Dict, pattern_data: Dict) -> float:
        """
        Calculate momentum strength based on price movement intensity
        
        Returns: 0.50-0.95 (50%-95%) representing movement power
        - 0.50-0.69: Weak momentum (small moves, low conviction)
        - 0.70-0.79: Standard momentum (normal price action)  
        - 0.80-0.89: Strong momentum (powerful moves, high conviction)
        - 0.90-0.95: Exceptional momentum (explosive price action)
        """
        base_strength = 0.60
        
        # Strategy-specific momentum factors
        pattern_strength = self._calculate_pattern_strength(pattern_data)
        volume_factor = self._calculate_volume_impact(price_data)
        conviction_factor = self._calculate_conviction_score(price_data)
        
        total_strength = base_strength + pattern_strength + volume_factor + conviction_factor
        return max(0.50, min(0.95, total_strength))
    
    def calculate_signal_confidence(self, setup_data: Dict, market_context: Dict) -> int:
        """
        Calculate signal confidence based on setup quality and reliability
        
        Returns: 60-95 (percentage) representing probability of success
        - 60-69: Low confidence (marginal setups, poor conditions)
        - 70-79: Standard confidence (good setups, normal conditions)
        - 80-89: High confidence (excellent setups, favorable conditions)  
        - 90-95: Exceptional confidence (perfect setups, ideal conditions)
        """
        base_confidence = 70
        
        # Strategy-specific confidence factors
        setup_quality = self._assess_setup_quality(setup_data)
        market_conditions = self._assess_market_conditions(market_context)
        confluence_bonus = self._calculate_confluence_score(setup_data)
        
        total_confidence = base_confidence + setup_quality + market_conditions + confluence_bonus
        return max(60, min(95, int(total_confidence)))

# Quarter Curve Butter Middle specific implementation
class QuarterCurveSignalMetrics(StrategySignalMetrics):
    """Quarter Curve specific signal quality calculations"""
    
    def calculate_momentum_strength(self, candlestick_data: Dict, breach_data: Dict) -> float:
        """Quarter Curve momentum strength calculation"""
        base_strength = 0.60
        
        # Candlestick pattern contribution (0.0-0.25)
        candle_strength_map = {
            'strong_bearish': 0.25,    # 85% total strength
            'strong_bullish': 0.25,    # 85% total strength  
            'bearish': 0.15,          # 75% total strength
            'bullish': 0.15,          # 75% total strength
            'weak': 0.05              # 65% total strength
        }
        
        # Bodyguard breach conviction (0.0-0.15)
        breach_conviction = min(0.15, breach_data.get('conviction_score', 0.1))
        
        # Volume support factor (0.0-0.05)  
        volume_factor = min(0.05, breach_data.get('volume_ratio', 1.0) * 0.05)
        
        pattern = candlestick_data.get('strength', 'weak')
        total_strength = (base_strength + 
                         candle_strength_map.get(pattern, 0.05) + 
                         breach_conviction + 
                         volume_factor)
        
        return max(0.50, min(0.95, total_strength))
    
    def calculate_signal_confidence(self, quarter_setup: Dict, session_data: Dict) -> int:
        """Quarter Curve signal confidence calculation"""
        base_confidence = 70
        
        # Bodyguard breach quality (0-15 points)
        breach_quality = self._assess_bodyguard_breach_quality(quarter_setup)
        
        # Candlestick pattern clarity (0-10 points)  
        pattern_clarity = self._assess_candlestick_clarity(quarter_setup)
        
        # Market session timing (0-5 points)
        session_bonus = self._assess_session_timing(session_data)
        
        # Quarter boundary proximity (0-5 points)
        proximity_bonus = self._assess_quarter_proximity(quarter_setup)
        
        total_confidence = (base_confidence + breach_quality + 
                          pattern_clarity + session_bonus + proximity_bonus)
        
        return max(60, min(95, int(total_confidence)))
    
    def _assess_bodyguard_breach_quality(self, setup: Dict) -> int:
        """Assess quality of bodyguard breach (0-15 points)"""
        breach_distance = setup.get('breach_distance_pips', 0)
        breach_speed = setup.get('breach_speed', 'normal')
        
        quality_score = 0
        
        # Distance through bodyguard
        if breach_distance > 15:
            quality_score += 8  # Strong breach
        elif breach_distance > 5:
            quality_score += 5  # Standard breach
        else:
            quality_score += 2  # Weak breach
        
        # Speed of breach  
        speed_bonus = {'fast': 7, 'normal': 4, 'slow': 1}
        quality_score += speed_bonus.get(breach_speed, 1)
        
        return min(15, quality_score)
    
    def _assess_candlestick_clarity(self, setup: Dict) -> int:
        """Assess candlestick pattern clarity (0-10 points)"""
        pattern_type = setup.get('candlestick_pattern', 'weak')
        body_ratio = setup.get('body_to_range_ratio', 0.3)
        
        # Pattern strength contribution
        pattern_scores = {
            'strong_bearish': 6, 'strong_bullish': 6,
            'bearish': 4, 'bullish': 4,
            'weak': 1
        }
        
        clarity_score = pattern_scores.get(pattern_type, 1)
        
        # Body ratio bonus (larger bodies = more conviction)
        if body_ratio > 0.7:
            clarity_score += 4
        elif body_ratio > 0.5:
            clarity_score += 2
        
        return min(10, clarity_score)
```

### **Airtable Metadata Creation Pattern**
```python
def create_airtable_metadata(self, trade_order: {Strategy}TradeOrder) -> TradeMetadata:
    """Create metadata matching Airtable schema from trade order"""
    try:
        # 1. Generate setup name
        setup_name = f"{self.strategy_tag}_{trade_order.instrument.replace('_', '/')}_{trade_order.action}_{trade_order.specific_identifier}"
        
        # 2. Calculate signal quality metrics using strategy-specific methods
        signal_metrics = self.signal_metrics_calculator
        momentum_strength = signal_metrics.calculate_momentum_strength(
            trade_order.price_data, trade_order.pattern_data
        )
        signal_confidence = signal_metrics.calculate_signal_confidence(
            trade_order.setup_data, trade_order.market_context
        )
        
        # 3. Map strategy-specific data to universal fields
        momentum_direction = self.map_to_airtable_direction(trade_order.momentum_direction)
        strategy_bias = trade_order.action  # BUY/SELL
        zone_position = self.map_to_airtable_zones(trade_order.zone_data)
        
        # 4. Calculate alignment score from momentum and confidence
        momentum_alignment = self.calculate_momentum_alignment(momentum_strength, signal_confidence)
        
        # 5. Create metadata object
        return TradeMetadata(
            setup_name=setup_name,
            strategy_tag=self.strategy_tag,
            momentum_strength=momentum_strength,  # 0.50-0.95 decimal
            momentum_direction=momentum_direction,
            strategy_bias=strategy_bias,
            zone_position=zone_position,
            distance_to_entry_pips=0.0,  # Strategy-specific calculation
            signal_confidence=signal_confidence,  # 60-95 integer
            momentum_alignment=momentum_alignment  # Derived from above metrics
        )
        
    except Exception as e:
        self.logger.error(f"Error creating metadata: {e}")
        return self.create_fallback_metadata(trade_order)

def map_to_airtable_direction(self, strategy_field: str) -> str:
    """Map strategy-specific analysis to Airtable direction options"""
    # Strategy-specific mapping logic
    pass

def calculate_momentum_alignment(self, momentum_strength: float, signal_confidence: int) -> float:
    """Calculate alignment score from momentum and confidence"""
    # Convert confidence to 0-1 scale
    confidence_decimal = signal_confidence / 100.0
    
    # Weight momentum strength more heavily (60/40 split)
    alignment = (momentum_strength * 0.6) + (confidence_decimal * 0.4)
    
    return round(alignment, 2)
```

### **Zone Position Mapping (Strategy-Specific)**
```python
# Penny Curve Strategy
PENNY_ZONES = {
    "In_Buy_Zone": "Price in penny buy zone",
    "Above_Buy_Zone": "Price above penny buy zone", 
    "In_Sell_Zone": "Price in penny sell zone",
    "Below_Sell_Zone": "Price below penny sell zone"
}

# Quarter Curve Strategy (Based on your implementation)
QUARTER_ZONES = {
    "In_Buy_Zone": "Price in bodyguard buy zone (lower bodyguard breached)",
    "In_Sell_Zone": "Price in bodyguard sell zone (upper bodyguard breached)",
    "Above_Buy_Zone": "Price above buy zone (waiting for lower bodyguard breach)",
    "Below_Sell_Zone": "Price below sell zone (waiting for upper bodyguard breach)"
}

# Advanced Quarter Curve Options (for future enhancement)
QUARTER_ADVANCED_ZONES = {
    "QUARTER_250_CROSS_BUY_VERY_BULLISH": "Very bullish quarter cross",
    "QUARTER_250_CROSS_BUY_BULLISH": "Bullish quarter cross", 
    "QUARTER_750_CROSS_SELL_VERY_BEARISH": "Very bearish quarter cross",
    "QUARTER_750_CROSS_SELL_BEARISH": "Bearish quarter cross"
}

# Strategy-specific zone mapping function
def map_strategy_zones(candlestick_strength: str, breach_direction: str) -> str:
    """Map strategy-specific analysis to Airtable zones"""
    if candlestick_strength in ["bullish", "strong_bullish"]:
        return "In_Buy_Zone"  # Lower bodyguard breached
    elif candlestick_strength in ["bearish", "strong_bearish"]:
        return "In_Sell_Zone"  # Upper bodyguard breached
    else:
        return "Below_Sell_Zone"  # Safe fallback
```

---

## 🎯 **Airtable Integration Specifications**

### **Complete Airtable Field Mapping**

#### **Core Trading Fields**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **OANDA Order ID** | Number | transaction.id | Unique OANDA order identifier | 302, 303, 304 |
| **Fill ID** | Number | transaction.tradeOpened.tradeID | Unique trade fill identifier | 248, 231, 203 |
| **Instrument** | Single select | transaction.instrument | Currency pair | EUR/USD, GBP/USD, EUR/JPY |
| **Order Type** | Single select | transaction.type | Type of order placed | LIMIT_ORDER, MARKET_ORDER, STOP_ORDER |
| **Order Status** | Single select | calculated | Current order status | Pending, Filled, Cancelled |
| **Direction** | Single select | calculated from units | Trade direction | Long, Short |
| **Order Time** | Date | transaction.time | When order was placed | 2025-06-27T17:13:05Z |
| **Units** | Number | abs(transaction.units) | Position size in units | 3000, 4000, 50000 |
| **Entry Price** | Currency | transaction.price | Order entry price | 1.1675, 1.3675, 169.25 |
| **Filled Price** | Currency | transaction.price (fills) | Actual fill price | 1.1675, 1.3675, 169.25 |
| **Execution Time** | Date | transaction.time (fills) | When order was filled | 2025-06-27T17:13:05Z |

#### **Price Tracking Fields**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **Stop Loss** | Currency | stopLossOnFill.price | Stop loss price level | 1.17, 1.37, 169.5 |
| **Target Price** | Currency | takeProfitOnFill.price | Take profit price level | 1.1575, 1.3575, 168.25 |
| **Current Price** | Currency | live pricing API | Real-time market price | 1.17185, 1.372055, 169.525 |
| **Exit Price** | Currency | transaction.price (close) | Price when trade closed | 1.1680, 1.3580, 169.30 |

#### **Strategy Metadata Fields**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **Setup Name** | Single line text | metadata.setup_name | Unique setup identifier | QCButterMiddle_EUR/USD_SELL_1.1675_bearish |
| **Strategy Tag** | Single select | metadata.strategy_tag | Strategy abbreviation | QuarterCurveButterMiddle, PennyCurveMomentum |
| **Momentum Strength** | Percent | metadata.momentum_strength | Signal strength as decimal | 0.75 (75%), 0.85 (85%) |
| **Momentum Direction** | Single select | metadata.momentum_direction | Momentum direction | WEAK_BEARISH, STRONG_BEARISH, WEAK_BULLISH, STRONG_BULLISH, NEUTRAL |
| **Strategy Bias** | Single select | metadata.strategy_bias | Overall strategy bias | BUY, SELL, NEUTRAL |
| **Zone Position** | Single select | metadata.zone_position | Price zone analysis | In_Sell_Zone, In_Buy_Zone, Above_Buy_Zone, Below_Sell_Zone |
| **Distance to Entry (Pips)** | Number | metadata.distance_to_entry_pips | Distance to entry in pips | 0.0, 2.5, 5.0 |
| **Signal Confidence** | Number | metadata.signal_confidence | Confidence percentage | 75, 85, 95 |
| **Momentum Alignment** | Number | metadata.momentum_alignment | Alignment score -1 to +1 | 0.6, 0.8, 1.0 |

#### **Quarter Curve Butter Middle Specific Metrics**

##### **Momentum Strength Calculation (0.50-0.95)**
The momentum strength for Quarter Curve represents the **power and intensity of the bodyguard breach**:

```python
# Quarter Curve Momentum Strength Components:
base_strength = 0.60  # Starting point (60%)

# Candlestick Pattern Contribution (0.0-0.25)
candlestick_strength = {
    'strong_bearish': 0.25,    # → 85% total momentum strength
    'strong_bullish': 0.25,    # → 85% total momentum strength
    'bearish': 0.15,          # → 75% total momentum strength  
    'bullish': 0.15,          # → 75% total momentum strength
    'weak': 0.05              # → 65% total momentum strength
}

# Bodyguard Breach Conviction (0.0-0.15)
# - How decisively price broke through the 75-pip bodyguard
# - Clean breaks vs. hesitant moves

# Volume Support Factor (0.0-0.05)  
# - Trading volume behind the breach movement
# - Higher volume = stronger momentum

# Final Range: 0.50-0.95 (50%-95%)
```

##### **Signal Confidence Calculation (60-95)**
The signal confidence for Quarter Curve represents the **reliability and probability of success**:

```python
# Quarter Curve Signal Confidence Components:
base_confidence = 70  # Starting point (70%)

# Bodyguard Breach Quality (0-15 points)
# - Distance price moved through bodyguard (5-25+ pips)
# - Speed of breach (fast/normal/slow)
# - Conviction of the move

# Candlestick Pattern Clarity (0-10 points)
# - Pattern recognition strength
# - Body-to-range ratio (larger bodies = more conviction)
# - Rejection characteristics

# Market Session Timing (0-5 points)  
# - Active trading session (London/New York) = higher confidence
# - Session overlaps = bonus points
# - Holiday/quiet periods = reduced confidence

# Quarter Boundary Proximity (0-5 points)
# - Closer to actual quarter levels = higher confidence
# - Perfect 0.25/0.75 hits = maximum points

# Final Range: 60-95 (60%-95%)
```

##### **Real Examples from Quarter Curve Trades:**

| Trade | Candlestick | Momentum Strength | Signal Confidence | Reasoning |
|-------|-------------|------------------|-------------------|-----------|
| **EUR_USD** | bearish | 0.75 (75%) | 75% | Standard bearish pattern, clean bodyguard breach |
| **GBP_USD** | strong_bearish | 0.85 (85%) | 85% | Strong bearish pattern, powerful bodyguard breach |
| **EUR_JPY** | bearish | 0.75 (75%) | 75% | Standard bearish pattern, normal breach conviction |

##### **Metric Relationships:**
```python
# Momentum Alignment Calculation (derived from both metrics)
def calculate_momentum_alignment(momentum_strength: float, signal_confidence: int) -> float:
    """Calculate alignment score from momentum and confidence"""
    # Convert confidence to 0-1 scale
    confidence_decimal = signal_confidence / 100.0
    
    # Weight momentum strength more heavily (60/40 split)
    alignment = (momentum_strength * 0.6) + (confidence_decimal * 0.4)
    
    # Examples:
    # 75% momentum + 75% confidence = (0.75 * 0.6) + (0.75 * 0.4) = 0.75
    # 85% momentum + 85% confidence = (0.85 * 0.6) + (0.85 * 0.4) = 0.85
    
    return round(alignment, 2)
```

#### **Financial Metrics Fields**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **Realized PL** | Currency | transaction.pl | Profit/Loss when closed | -15.50, 25.75, 0.00 |
| **Unrealized PL** | Currency | openTrades.unrealizedPL | Current P/L for open trades | 3.96, 1.74, -0.19 |
| **Account Balance After** | Currency | transaction.accountBalance | Account balance after trade | 99982.73, 99975.23 |
| **Account Balance Before** | Currency | calculated | Account balance before trade | 99990.23, 99982.73 |
| **Spread Cost** | Currency | transaction.halfSpreadCost | Cost of spread | 0.75, 1.25, 2.50 |
| **Initial Margin Required** | Currency | transaction.initialMarginRequired | Margin required | 116.99, 342.48, 164.15 |
| **Financing** | Currency | transaction.financing | Financing charges | -0.22, 0.00, -0.53 |
| **Margin Used** | Currency | openTrades.marginUsed | Currently used margin | 46.87, 68.60, 164.06 |

#### **Calculated Risk Metrics**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **R:R Ratio Calculated** | Number | calculated from prices | Risk/Reward ratio | 4.00, 3.50, 2.00 |
| **Risk Amount Calculated** | Currency | calculated from stop loss | Dollar risk amount | 7.50, 10.00, 25.00 |
| **Risk Per Trade % Calculated** | Percent | calculated from account | Risk as % of account | 0.0075 (0.75%), 0.01 (1%) |
| **Position Size % Calculated** | Percent | calculated from account | Position size as % | 0.12 (0.12%), 0.34 (0.34%) |
| **ROI Calculated** | Percent | calculated from P/L | Return on investment | 0.0396 (3.96%), -0.019 (-1.9%) |
| **Pips Gained/Lost Calculated** | Number | calculated from prices | Pips gained or lost | 25.0, -15.0, 50.0 |

#### **Trade State & Timing Fields**
| Airtable Field Name | Field Type | Source | Description | Example Values |
|---------------------|------------|---------|-------------|----------------|
| **Trade State** | Single select | calculated | Current state of trade | Open, Closed |
| **Reason** | Single line text | transaction.reason | Reason for order action | LIMIT_ORDER, MARKET_ORDER, CANCELLED |
| **Days Pending** | Number | calculated | Days order was pending | 0, 1, 2 |
| **Days Held Calculated** | Number | calculated | Days trade was held | 1.5, 3.2, 0.8 |
| **Fill Rate Calculated** | Percent | calculated | Order fill success rate | 1.0 (100%), 0.0 (0%) |
| **Trade Result Calculated** | Single select | calculated from P/L | Win/Loss classification | Win, Loss, Breakeven |

#### **Advanced Quarter Curve Zone Options**
| Zone Position Value | Description |
|---------------------|-------------|
| **In_Buy_Zone** | Price in buy zone (lower bodyguard breached) |
| **In_Sell_Zone** | Price in sell zone (upper bodyguard breached) |
| **Above_Buy_Zone** | Price above buy zone |
| **Below_Sell_Zone** | Price below sell zone |
| **QUARTER_250_CROSS_BUY_VERY_BULLISH** | Very bullish quarter cross signal |
| **QUARTER_250_CROSS_BUY_BULLISH** | Bullish quarter cross signal |
| **QUARTER_750_CROSS_SELL_VERY_BEARISH** | Very bearish quarter cross signal |
| **QUARTER_750_CROSS_SELL_BEARISH** | Bearish quarter cross signal |

#### **Field Type Specifications**
- **Single select**: Predefined dropdown options
- **Number**: Numeric values (integers or decimals)
- **Currency**: Monetary values with currency formatting
- **Percent**: Percentage values (0-1 decimal format)
- **Date**: ISO timestamp format
- **Single line text**: Short text strings

### **Strategy-Specific Field Extensions**
Each strategy can add custom fields by extending the base metadata:

```python
# Example: Quarter Curve specific fields (future enhancement)
QUARTER_CURVE_EXTENDED_FIELDS = {
    "Bodyguard Breach Direction": "Single select",     # above_upper_bodyguard, below_lower_bodyguard
    "Candlestick Strength": "Single select",           # bearish, strong_bearish, bullish, strong_bullish
    "Quarter Level": "Number",                          # 0.25 or 0.75
    "Breach Confirmation": "Checkbox",                  # True/False
    "Bodyguard Distance (Pips)": "Number",            # Distance to bodyguard
    "Session Overlap": "Single select"                 # London, New York, Asian, Overlap
}

# Example: Penny Curve specific fields
PENNY_CURVE_EXTENDED_FIELDS = {
    "Penny Level": "Currency",                         # Exact penny level (1.1700, 1.3600)
    "Momentum Confluence": "Single select",            # High, Medium, Low
    "Session Timing": "Single select",                 # Opening, Mid-session, Closing
    "Volume Analysis": "Single select"                 # High, Normal, Low
}
```

---

### **Integration Bot Pattern (Based on Quarter Curve)**
```python
class {Strategy}IntegratedTradingBot:
    """
    Integrated trading bot for {Strategy}
    Uses existing infrastructure with strategy-specific components
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Use existing infrastructure
        self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        
        # Strategy-specific components
        self.analyzer1 = {Strategy}SpecializedAnalyzer()
        self.analyzer2 = {Strategy}SignalDetector(self.api)
        self.strategy = {Strategy}Strategy(self.analyzer1, self.analyzer2)
        
        # Shared infrastructure
        self.metadata_store = TradeMetadataStore()
        self.risk_manager = FixedDollarRiskManager(self.api, max_risk_usd)
        
        # Configuration
        self.instruments = [/* strategy-appropriate instruments */]
        self.max_risk_usd = max_risk_usd
        self.max_open_trades = max_open_trades
        
        # Trade tracking
        self.pending_orders = []
        self.open_positions = []
        self.trade_history = []
    
    def scan_for_{strategy}_opportunities(self) -> List[{Strategy}TradeOrder]:
        """Main scanning method - converts opportunities to trade orders"""
        opportunities = []
        
        for instrument in self.instruments:
            try:
                # Get strategy opportunities
                strategy_opportunities = self.strategy.analyze_{strategy}_opportunities(instrument)
                
                # Convert to trade orders
                for opp in strategy_opportunities:
                    position_size = self.calculate_position_size(
                        instrument, opp['entry_price'], opp['stop_loss'], opp['confidence']
                    )
                    
                    trade_order = {Strategy}TradeOrder(
                        instrument=instrument,
                        action=opp['action'],
                        # ... populate all fields from opportunity ...
                        units=position_size if opp['action'] == 'BUY' else -position_size,
                    )
                    
                    opportunities.append(trade_order)
                    
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
        
        return opportunities
    
    def place_limit_order(self, trade_order: {Strategy}TradeOrder) -> bool:
        """Place order with metadata storage"""
        try:
            # Create metadata
            metadata = self.strategy.create_airtable_metadata(trade_order)
            
            # Create OANDA order
            order_data = {/* standard OANDA order format */}
            
            # Place order
            response = self.api.place_order(order_data)
            
            # Store metadata
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                self.metadata_store.store_order_metadata(order_id, metadata)
                trade_order.order_id = order_id
                trade_order.status = 'PLACED'
                self.pending_orders.append(trade_order)
                return True
                
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
        
        return False
```

## 📁 **File Structure & Naming Conventions**

### **Project Structure**
```
oanda-trading-project/
├── src/
│   ├── strategies/
│   │   ├── penny_curve_strategy.py
│   │   ├── quarter_curve_strategy.py  
│   │   ├── dime_curve_strategy.py
│   │   ├── [future_strategies].py
│   │   └── strategy_base.py           # Base class
│   ├── core/
│   │   ├── trading_engine.py          # Main orchestrator
│   │   ├── metadata_storage.py        # Universal metadata
│   │   ├── oanda_api.py              # Broker interface
│   │   ├── risk_management.py         # Risk calculations
│   │   └── market_analysis.py         # Shared analysis tools
│   ├── sync/
│   │   ├── sync_all.py               # Main sync engine
│   │   ├── airtable_integration.py   # Airtable specific
│   │   └── field_mapping.py          # Strategy field maps
│   ├── config/
│   │   ├── oanda_config.py
│   │   ├── airtable_config.py
│   │   └── strategy_config.py        # Strategy parameters
│   ├── utils/
│   │   ├── diagnostics.py            # Debug utilities
│   │   ├── validation.py             # Data validation
│   │   └── helpers.py                # Common utilities
│   └── trading_logs/                 # Logs and metadata
├── tests/
│   ├── test_strategies/
│   ├── test_integration/
│   └── test_data/
└── docs/
    ├── strategy_guides/
    ├── api_documentation/
    └── troubleshooting/
```

### **Naming Conventions**
1. **Strategy Files**: `{strategy_name}_strategy.py` (lowercase, underscores)
2. **Strategy Classes**: `{StrategyName}Strategy` (PascalCase)
3. **Strategy Tags**: 3-4 character abbreviations (PCM, QCB, DCB)
4. **Setup Names**: `{TAG}_{INSTRUMENT}_{TYPE}_{ACTION}_{STRENGTH}_{SESSION}`
5. **Metadata Keys**: snake_case for consistency
6. **Airtable Fields**: Title Case with spaces

---

## ✅ **Implementation Checklist**

### **New Strategy Development**
- [ ] **Strategy Logic**
  - [ ] Implement `analyze_setup()` method
  - [ ] Define strategy-specific zones
  - [ ] Create confidence scoring system
  - [ ] Add momentum analysis integration
  
- [ ] **Metadata Generation**
  - [ ] Implement `create_metadata()` method
  - [ ] Map to universal metadata fields
  - [ ] Add strategy-specific custom fields
  - [ ] Validate all required Airtable fields
  
- [ ] **Setup Naming**
  - [ ] Implement `get_setup_name()` method
  - [ ] Follow naming convention
  - [ ] Ensure uniqueness per trade
  
- [ ] **Risk Management** 
  - [ ] Implement `calculate_risk_reward()` method
  - [ ] Define stop loss logic
  - [ ] Set take profit targets
  - [ ] Calculate position sizing
  
- [ ] **Integration Testing**
  - [ ] Test metadata storage
  - [ ] Verify sync process
  - [ ] Confirm Airtable population
  - [ ] Validate field mappings

### **Strategy Registration**
- [ ] **Core System Updates**
  - [ ] Add strategy to main trading engine
  - [ ] Update metadata storage mappings
  - [ ] Add sync field mappings
  - [ ] Update Airtable schema if needed
  
- [ ] **Configuration**
  - [ ] Add strategy parameters to config
  - [ ] Set default risk parameters
  - [ ] Configure market timing windows
  - [ ] Add instrument specifications

### **Quality Assurance**
- [ ] **Testing**
  - [ ] Unit tests for strategy logic
  - [ ] Integration tests with metadata
  - [ ] End-to-end sync testing
  - [ ] Airtable field validation
  
- [ ] **Documentation**
  - [ ] Strategy logic documentation
  - [ ] Setup examples and screenshots
  - [ ] Troubleshooting guide
  - [ ] Performance benchmarks

---

## 📈 **Scaling Considerations**

### **Multi-Strategy Coordination**
1. **Resource Management**: CPU, memory, API rate limits
2. **Risk Allocation**: Per-strategy risk budgets
3. **Correlation Analysis**: Strategy overlap detection
4. **Priority Systems**: Strategy execution order

### **Performance Optimization**
1. **Parallel Processing**: Concurrent strategy analysis
2. **Caching**: Market data and analysis results
3. **Batch Operations**: Bulk order processing
4. **Database Optimization**: Metadata indexing

### **Monitoring & Alerting**
1. **Strategy Health**: Performance monitoring per strategy
2. **Error Tracking**: Strategy-specific error logging
3. **Performance Metrics**: Real-time analytics dashboard
4. **Alert Systems**: Automated notifications

### **Future Extensibility**
1. **Plugin Architecture**: Easy strategy addition
2. **API Standardization**: Consistent interfaces
3. **Data Pipeline**: Scalable metadata processing
4. **Cloud Migration**: AWS Lambda compatibility

---

## 🔧 **Common Integration Patterns**

### **Strategy Registration Pattern**
```python
# In main trading engine
AVAILABLE_STRATEGIES = {
    'penny_curve': PennyCurveStrategy,
    'quarter_curve': QuarterCurveStrategy,
    'dime_curve': DimeCurveStrategy,
    # Add new strategies here
}

def load_strategy(strategy_name: str):
    if strategy_name in AVAILABLE_STRATEGIES:
        return AVAILABLE_STRATEGIES[strategy_name]()
    raise ValueError(f"Unknown strategy: {strategy_name}")
```

### **Metadata Enrichment Pattern**
```python
# Universal metadata enhancement
def enrich_metadata(base_metadata: TradeMetadata, strategy_data: Dict) -> TradeMetadata:
    # Add market session info
    base_metadata.session_info = get_current_session_info()
    
    # Add strategy-specific fields
    if 'custom_fields' in strategy_data:
        base_metadata.custom_fields.update(strategy_data['custom_fields'])
    
    # Validate required fields
    validate_airtable_fields(base_metadata)
    
    return base_metadata
```

### **Sync Field Mapping Pattern**
```python
# Strategy-specific field mappings
STRATEGY_FIELD_MAPPINGS = {
    'PCM': {
        'zone_position': PENNY_ZONES,
        'custom_fields': {}
    },
    'QCB': {
        'zone_position': QUARTER_ZONES,
        'custom_fields': QUARTER_CURVE_FIELDS
    }
}

def map_strategy_fields(metadata: TradeMetadata) -> Dict:
    strategy_tag = metadata.strategy_tag
    mapping = STRATEGY_FIELD_MAPPINGS.get(strategy_tag, {})
    
    # Apply strategy-specific mappings
    return apply_field_mappings(metadata, mapping)
```

---

## 📚 **Documentation Standards**

### **Strategy Documentation Template**
```markdown
# {Strategy Name} Strategy

## Overview
- **Purpose**: [What this strategy does]
- **Market Conditions**: [When to use]
- **Risk Profile**: [Risk characteristics]

## Logic Flow
1. [Step 1]
2. [Step 2] 
3. [Step 3]

## Metadata Fields
| Field | Values | Description |
|-------|--------|-------------|
| zone_position | [Values] | [Description] |
| custom_field_1 | [Values] | [Description] |

## Examples
[Setup examples with screenshots]

## Performance Notes
[Backtesting results, optimization notes]
```

### **Code Documentation Standards**
1. **Docstrings**: All public methods
2. **Type Hints**: All function parameters and returns
3. **Comments**: Complex logic explanation
4. **Examples**: Usage examples in docstrings

---

## 🎯 **Success Criteria**

### **Strategy Implementation Success**
- [ ] Strategy generates signals correctly
- [ ] Metadata populates all Airtable fields
- [ ] Sync process works without errors
- [ ] Performance meets expectations
- [ ] Documentation is complete

### **System Integration Success**
- [ ] No conflicts with existing strategies
- [ ] Metadata storage remains performant
- [ ] Airtable sync handles increased volume
- [ ] Error handling works properly
- [ ] Monitoring shows healthy metrics

---

**This blueprint ensures consistent, scalable strategy development while maintaining clean separation of concerns and robust data flow through your trading system architecture.**