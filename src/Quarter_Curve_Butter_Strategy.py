# Quarter Curve Butter Middle Strategy - Institutional Level Protection
# 75-pip "bodyguard" zones protecting institutional numbers
# Integrates with existing Oanda API and metadata storage system

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import existing infrastructure
from momentum_calculator import MarketAwareMomentumCalculator, ForexMarketSchedule
from oanda_api import OandaAPI
from metadata_storage import TradeMetadataStore, TradeMetadata

# Config imports
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("SUCCESS: Imported Oanda config")
except ImportError as e:
    print(f"ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

class QuarterCurveInstitutionalAnalyzer:
    """
    Quarter Curve Institutional Level Analyzer
    
    Key Concepts:
    - Institutional Numbers: Quarters (X.X250, X.X750), Dimes (X.X000), Wildcards (X.X500)
    - Bodyguard Zones: 75 pips inside quarter boundaries
    - When price breaches bodyguards, enter at bodyguard level targeting 100 pips
    
    For Non-JPY:
    - Quarter levels: X.X000, X.X250, X.X500, X.X750
    - Bodyguard zones: 75 pips (±0.0075) inside quarter boundaries
    
    For JPY:
    - Quarter levels: XX0.00, XX2.50, XX5.00, XX7.50
    - Bodyguard zones: 75 pips (±0.75) inside quarter boundaries
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def is_jpy_pair(self, instrument: str) -> bool:
        """Check if instrument is a JPY pair"""
        return 'JPY' in instrument
    
    def find_quarter_boundaries(self, current_price: float, is_jpy: bool = False) -> Dict:
        """
        Find quarter boundaries above and below current price
        Set bodyguards 75 pips inside each boundary
        """
        
        pip_value = 0.01 if is_jpy else 0.0001
        bodyguard_distance = 75 * pip_value  # 75 pips in price units
        
        if is_jpy:
            # For JPY, quarter levels are at 0.00, 2.50, 5.00, 7.50
            quarter_levels = []
            base = int(current_price / 10) * 10  # Round down to nearest 10
            
            # Generate quarter levels around current price
            for major_level in range(base - 10, base + 30, 10):
                quarter_levels.extend([
                    major_level + 0.00,
                    major_level + 2.50,
                    major_level + 5.00,
                    major_level + 7.50
                ])
        else:
            # For non-JPY, quarter levels are at .0000, .0250, .0500, .0750
            quarter_levels = []
            base = int(current_price * 10) / 10  # Round down to nearest 0.1
            
            # Generate quarter levels around current price
            for major_level_cents in range(int(base * 10) - 1, int(base * 10) + 3):
                major_level = major_level_cents / 10
                quarter_levels.extend([
                    major_level + 0.0000,
                    major_level + 0.0250,
                    major_level + 0.0500,
                    major_level + 0.0750
                ])
        
        # Remove duplicates and sort
        quarter_levels = sorted(list(set(quarter_levels)))
        
        # Find quarter above and below current price
        quarter_above = None
        quarter_below = None
        
        for level in quarter_levels:
            if level > current_price and quarter_above is None:
                quarter_above = level
            if level < current_price:
                quarter_below = level
        
        if quarter_above is None or quarter_below is None:
            return {'error': 'Could not find quarter boundaries'}
        
        # Calculate bodyguards (75 pips inside the boundaries)
        upper_bodyguard = quarter_above - bodyguard_distance
        lower_bodyguard = quarter_below + bodyguard_distance
        
        return {
            "current_price": current_price,
            "is_jpy": is_jpy,
            "pip_value": pip_value,
            "bodyguard_distance_pips": 75,
            "quarter_above": round(quarter_above, 2 if is_jpy else 4),
            "quarter_below": round(quarter_below, 2 if is_jpy else 4),
            "upper_bodyguard": round(upper_bodyguard, 2 if is_jpy else 4),
            "lower_bodyguard": round(lower_bodyguard, 2 if is_jpy else 4),
            "trading_zone_size": upper_bodyguard - lower_bodyguard,
            "current_in_zone": lower_bodyguard <= current_price <= upper_bodyguard
        }

class QuarterCurve4HrCandlestickAnalyzer:
    """
    4-hour candlestick analyzer for Quarter Curve bodyguard zone breaches
    
    Monitors 4hr candlesticks for breaches beyond bodyguard zones
    When price breaches bodyguard, it signals entry at that bodyguard level
    """
    
    def __init__(self, api):
        self.api = api
        self.logger = logging.getLogger(__name__)
    
    def get_4hr_candlestick(self, instrument: str) -> Dict:
        """Get the most recent completed 4-hour candlestick"""
        try:
            candles = self.api.get_candles(instrument, granularity='H4', count=2)
            
            if not candles or 'candles' not in candles or len(candles['candles']) < 1:
                return {'error': 'Unable to get 4hr candles'}
            
            # Get the most recent completed candle
            last_candle = candles['candles'][-2] if len(candles['candles']) >= 2 else candles['candles'][-1]
            
            if not last_candle.get('complete', False):
                if len(candles['candles']) >= 2:
                    last_candle = candles['candles'][-2]
                else:
                    return {'error': 'No completed 4hr candle available'}
            
            # Extract OHLC data
            mid_data = last_candle['mid']
            return {
                'open': float(mid_data['o']),
                'high': float(mid_data['h']),
                'low': float(mid_data['l']),
                'close': float(mid_data['c']),
                'time': last_candle['time'],
                'complete': last_candle.get('complete', False)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting 4hr candlestick for {instrument}: {e}")
            return {'error': str(e)}
    
    def analyze_4hr_candlestick_strength(self, candle_data: Dict) -> str:
        """Analyze 4hr candlestick strength for bodyguard breach signals"""
        if 'error' in candle_data:
            return 'neutral'
        
        open_price = candle_data['open']
        high_price = candle_data['high']
        low_price = candle_data['low']
        close_price = candle_data['close']
        
        range_size = high_price - low_price
        if range_size == 0:
            return 'neutral'
        
        # Calculate where close is within the range
        close_position_percent = ((close_price - low_price) / range_size) * 100
        
        # For bodyguard breaches, we need strong directional moves
        if close_position_percent >= 75:
            return 'strong_bullish'
        elif close_position_percent >= 60:
            return 'bullish'
        elif close_position_percent >= 40:
            return 'neutral'
        elif close_position_percent >= 25:
            return 'bearish'
        else:
            return 'strong_bearish'
    
    def detect_bodyguard_breach(self, candlestick_data: Dict, quarter_data: Dict) -> Dict:
        """
        Detect if 4hr candlestick breached bodyguard zones
        
        Returns breach information for signal generation
        """
        if 'error' in quarter_data:
            return {'breach_detected': False, 'error': quarter_data['error']}
        
        candle_high = candlestick_data['high']
        candle_low = candlestick_data['low']
        candle_close = candlestick_data['close']
        strength = self.analyze_4hr_candlestick_strength(candlestick_data)
        
        upper_bodyguard = quarter_data['upper_bodyguard']
        lower_bodyguard = quarter_data['lower_bodyguard']
        
        breach_info = {
            "breach_detected": False,
            "breach_direction": None,
            "breach_type": None,
            "candlestick_strength": strength,
            "entry_level": None,
            "is_valid_breach": False
        }
        
        # Check for breach above upper bodyguard (bearish signal)
        if candle_high > upper_bodyguard and strength in ['strong_bearish', 'bearish']:
            breach_info.update({
                "breach_detected": True,
                "breach_direction": "above_upper_bodyguard",
                "breach_type": "bearish",
                "entry_level": upper_bodyguard,
                "is_valid_breach": True
            })
        
        # Check for breach below lower bodyguard (bullish signal)
        elif candle_low < lower_bodyguard and strength in ['strong_bullish', 'bullish']:
            breach_info.update({
                "breach_detected": True,
                "breach_direction": "below_lower_bodyguard", 
                "breach_type": "bullish",
                "entry_level": lower_bodyguard,
                "is_valid_breach": True
            })
        
        return breach_info

class QuarterCurveButterMiddleStrategy:
    """
    Quarter Curve Butter Middle Strategy
    
    Strategy Logic:
    1. Find quarter boundaries above and below current price
    2. Set bodyguards 75 pips inside each boundary
    3. Monitor 4hr candlesticks for bodyguard breaches
    4. When breached, place limit order at bodyguard level
    5. Target: 100 pips from entry (staying within quarter bounds)
    6. Stop: 25 pips from entry
    """
    
    def __init__(self, institutional_analyzer, candlestick_analyzer):
        self.institutional_analyzer = institutional_analyzer
        self.candlestick_analyzer = candlestick_analyzer
        self.logger = logging.getLogger(__name__)
    
    def analyze_butter_middle_opportunities(self, instrument: str) -> List[Dict]:
        """
        Analyze instrument for Quarter Curve Butter Middle opportunities
        
        Returns list of potential trades based on bodyguard breaches
        """
        opportunities = []
        
        try:
            # Get current price
            price_data = self.candlestick_analyzer.api.get_current_prices([instrument])
            if not price_data or 'prices' not in price_data:
                return opportunities
            
            current_price = float(price_data['prices'][0]['closeoutBid'])
            is_jpy = self.institutional_analyzer.is_jpy_pair(instrument)
            
            # Get 4hr candlestick
            candle_4hr = self.candlestick_analyzer.get_4hr_candlestick(instrument)
            if 'error' in candle_4hr:
                return opportunities
            
            # Find quarter boundaries and bodyguards
            quarter_data = self.institutional_analyzer.find_quarter_boundaries(current_price, is_jpy)
            if 'error' in quarter_data:
                return opportunities
            
            # Detect bodyguard breaches
            breach = self.candlestick_analyzer.detect_bodyguard_breach(candle_4hr, quarter_data)
            
            if breach["is_valid_breach"]:
                pip_value = quarter_data["pip_value"]
                entry_price = breach["entry_level"]
                
                # Calculate target and stop based on breach direction
                if breach["breach_type"] == "bearish":
                    # Sell at upper bodyguard, target 100 pips down
                    action = "SELL"
                    target_price = entry_price - (100 * pip_value)
                    stop_loss = entry_price + (25 * pip_value)
                    
                elif breach["breach_type"] == "bullish":
                    # Buy at lower bodyguard, target 100 pips up
                    action = "BUY"
                    target_price = entry_price + (100 * pip_value)
                    stop_loss = entry_price - (25 * pip_value)
                else:
                    return opportunities
                
                # Verify target stays within quarter bounds
                quarter_above = quarter_data["quarter_above"]
                quarter_below = quarter_data["quarter_below"]
                
                if action == "BUY" and target_price >= quarter_above:
                    self.logger.debug(f"Target {target_price:.4f} would cross quarter above {quarter_above:.4f}")
                    return opportunities
                
                if action == "SELL" and target_price <= quarter_below:
                    self.logger.debug(f"Target {target_price:.4f} would cross quarter below {quarter_below:.4f}")
                    return opportunities
                
                # Calculate confidence based on candlestick strength
                confidence = 75
                if breach["candlestick_strength"] in ["strong_bullish", "strong_bearish"]:
                    confidence = 85
                
                opportunity = {
                    'instrument': instrument,
                    'strategy_name': 'Quarter Curve Butter Middle',
                    'action': action,
                    'order_type': 'LIMIT',
                    'entry_price': round(entry_price, 2 if is_jpy else 4),
                    'stop_loss': round(stop_loss, 2 if is_jpy else 4),
                    'take_profit': round(target_price, 2 if is_jpy else 4),
                    'quarter_above': quarter_above,
                    'quarter_below': quarter_below,
                    'breach_direction': breach["breach_direction"],
                    'candlestick_strength': breach["candlestick_strength"],
                    'bodyguard_breached': entry_price,
                    'confidence': confidence,
                    'stop_pips': 25,
                    'target_pips': 100,
                    'reasoning': [
                        f"4hr {breach['candlestick_strength']} breach {breach['breach_direction']}",
                        f"Entry at bodyguard level: {entry_price:.4f}",
                        f"Target 100 pips: {target_price:.4f}",
                        f"Stays within quarters {quarter_below:.4f} - {quarter_above:.4f}",
                        f"Stop 25 pips: {stop_loss:.4f}"
                    ],
                    'expiration': 'END_OF_DAY'
                }
                
                opportunities.append(opportunity)
                
        except Exception as e:
            self.logger.error(f"Error analyzing Butter Middle for {instrument}: {e}")
        
        return opportunities

@dataclass
class QuarterCurveTradeOrder:
    """Quarter Curve trade order data class"""
    instrument: str
    action: str  # 'BUY' or 'SELL'
    order_type: str  # 'LIMIT'
    entry_price: float
    stop_loss: float
    take_profit: float
    units: int
    confidence: int
    reasoning: List[str]
    timestamp: str
    strategy_name: str  # 'Quarter Curve Butter Middle'
    quarter_above: float
    quarter_below: float
    breach_direction: str
    candlestick_strength: str
    bodyguard_breached: float
    stop_pips: int
    target_pips: int
    setup_type: str
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    # Metadata fields for integration
    momentum_analysis: Optional[Dict] = None
    zone_data: Optional[Dict] = None
    analysis_data: Optional[Dict] = None

class QuarterCurveIntegratedTradingBot:
    """
    Quarter Curve Trading Bot - Institutional Level Protection System
    
    Monitors 4hr candlesticks for bodyguard zone breaches
    Places limit orders at bodyguard levels targeting 100 pips within quarter bounds
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Initialize using existing infrastructure
        self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        self.momentum_calc = MarketAwareMomentumCalculator(self.api)
        
        # Initialize Quarter Curve components
        self.institutional_analyzer = QuarterCurveInstitutionalAnalyzer()
        self.candlestick_analyzer = QuarterCurve4HrCandlestickAnalyzer(self.api)
        self.butter_middle_strategy = QuarterCurveButterMiddleStrategy(
            self.institutional_analyzer, self.candlestick_analyzer
        )
        
        # Use existing metadata storage
        self.metadata_store = TradeMetadataStore()
        self.metadata_store.cleanup_old_metadata()
        
        # Risk management
        try:
            from Demo_Trading_Penny_Curve_Strategy import FixedDollarRiskManager
            self.risk_manager = FixedDollarRiskManager(self.api, max_risk_usd)
        except ImportError:
            self.logger.warning("Could not import FixedDollarRiskManager, using default position sizing")
            self.risk_manager = None
        
        self.max_risk_usd = max_risk_usd
        self.max_open_trades = max_open_trades
        
        # Trading instruments
        self.instruments = [
            'EUR_USD', 'GBP_USD', 'USD_CAD', 'AUD_USD', 'NZD_USD',
            'USD_JPY', 'EUR_JPY', 'GBP_JPY', 'CAD_JPY', 'AUD_JPY', 'NZD_JPY'
        ]
        
        # Trade tracking
        self.pending_orders = []
        self.open_positions = []
        self.trade_history = []
        
        # Market schedule
        self.market_schedule = ForexMarketSchedule()
        
        # Setup logging
        self.setup_logging()
        
        print("🎯 Quarter Curve Butter Middle Trading Bot Initialized!")
        print(f"   Strategy: 75-pip bodyguard protection within quarter bounds")
        print(f"   Timeframe: 4hr candlestick analysis")
        print(f"   Risk: 25 pip stops, 100 pip targets")
        print(f"   Max risk per trade: ${max_risk_usd:.2f}")
        print(f"   Monitoring {len(self.instruments)} pairs: {', '.join(self.instruments)}")
    
    def setup_logging(self):
        """Setup logging using existing structure"""
        log_dir = os.path.join(current_dir, 'trading_logs')
        os.makedirs(log_dir, exist_ok=True)
        
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(log_dir, f'quarter_curve_butter_{today}.log')
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info("Quarter Curve Butter Middle Trading Bot started")
    
    def create_airtable_metadata(self, trade_order: QuarterCurveTradeOrder) -> TradeMetadata:
        """Create metadata for Quarter Curve Butter Middle strategy matching existing Airtable schema"""
        try:
            instrument_clean = trade_order.instrument.replace('_', '/')
            setup_name = f"QCButterMiddle_{instrument_clean}_{trade_order.action}_{trade_order.bodyguard_breached:.4f}_{trade_order.candlestick_strength}"
            
            strategy_tag = "QuarterCurveButterMiddle"
            
            # Zone Position: Which zone was breached based on candlestick strength/direction
            # Use existing Airtable zone options
            candlestick_strength = trade_order.candlestick_strength
            
            if candlestick_strength in ["bullish", "strong_bullish"]:
                # Bullish candlestick = lower bodyguard (buy zone) was breached from below
                zone_position = "In_Buy_Zone"  # Price is now in the buy zone area
            elif candlestick_strength in ["bearish", "strong_bearish"]:
                # Bearish candlestick = upper bodyguard (sell zone) was breached from above  
                zone_position = "In_Sell_Zone"  # Price is now in the sell zone area
            else:
                zone_position = "Below_Sell_Zone"  # Safe fallback using existing value
            
            # Momentum Strength: Send as decimal (Airtable will format as percentage)
            # Convert confidence percentage to decimal for Airtable percentage field
            momentum_strength = trade_order.confidence / 100.0  # 75 -> 0.75, 85 -> 0.85
            
            # Momentum Direction: Map candlestick strength to existing Airtable options
            momentum_direction_map = {
                "strong_bullish": "STRONG_BULLISH",
                "bullish": "WEAK_BULLISH",  # Map regular bullish to weak bullish
                "neutral": "NEUTRAL",
                "bearish": "WEAK_BEARISH",  # Map regular bearish to weak bearish
                "strong_bearish": "STRONG_BEARISH"
            }
            momentum_direction = momentum_direction_map.get(trade_order.candlestick_strength, "NEUTRAL")
            
            # Strategy Bias: Match existing Airtable options (BUY/SELL/NEUTRAL)
            strategy_bias = trade_order.action  # "BUY" or "SELL"
            
            # Momentum Alignment: Use numeric values from your existing data (0.4, 0.6, 0.8, 1)
            confidence_to_alignment_map = {
                85: 1.0,    # Highest confidence -> 1.0
                80: 0.8,    # High confidence -> 0.8
                75: 0.6,    # Medium confidence -> 0.6
                70: 0.4,    # Lower confidence -> 0.4
            }
            momentum_alignment = confidence_to_alignment_map.get(trade_order.confidence, 0.6)  # Safe fallback
            
            metadata = TradeMetadata(
                setup_name=setup_name,
                strategy_tag=strategy_tag,
                momentum_strength=momentum_strength,  # Decimal for Airtable percentage field (0.75 = 75%)
                momentum_direction=momentum_direction,  # Candlestick strength mapped to Airtable options
                strategy_bias=strategy_bias,  # BUY/SELL
                momentum_alignment=momentum_alignment,  # Numeric value (not string)
                zone_position=zone_position,  # Where price is relative to breached zone
                distance_to_entry_pips=0.0,  # Limit orders at exact bodyguard levels
                signal_confidence=trade_order.confidence
            )
            
            self.logger.info(f"🎯 {trade_order.strategy_name} Setup: {setup_name}")
            self.logger.info(f"   Quarter Bounds: {trade_order.quarter_below:.4f} - {trade_order.quarter_above:.4f}")
            self.logger.info(f"   Bodyguard Breached: {trade_order.bodyguard_breached:.4f}")
            self.logger.info(f"   Breach Direction: {trade_order.breach_direction}")
            self.logger.info(f"   Entry: {trade_order.entry_price:.4f} | Stop: {trade_order.stop_loss:.4f} ({trade_order.stop_pips} pips)")
            self.logger.info(f"   Target: {trade_order.take_profit:.4f} ({trade_order.target_pips} pips)")
            self.logger.info(f"   📊 Setup Name: {setup_name}")
            self.logger.info(f"   📊 Strategy Tag: {strategy_tag}")
            self.logger.info(f"   📊 Momentum Strength: {momentum_strength} (decimal for {trade_order.confidence}% display)")
            self.logger.info(f"   📊 Momentum Direction: {momentum_direction} (candlestick strength)")
            self.logger.info(f"   📊 Strategy Bias: {strategy_bias}")
            self.logger.info(f"   📊 Zone Position: {zone_position} (price relative to breached zone)")
            self.logger.info(f"   📊 Momentum Alignment: {momentum_alignment} (numeric)")
            self.logger.info(f"   📊 Signal Confidence: {trade_order.confidence}")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Error creating metadata: {e}")
            return TradeMetadata(
                setup_name=f"QCButterMiddle_{trade_order.instrument}_{trade_order.action}_{trade_order.candlestick_strength}",
                strategy_tag="QuarterCurveButterMiddle",
                signal_confidence=trade_order.confidence,
                momentum_strength=0.75,  # Safe decimal value (75%)
                momentum_direction="NEUTRAL",  # Safe default
                strategy_bias=trade_order.action,  # BUY or SELL
                momentum_alignment=0.6,  # Safe numeric value
                zone_position="Below_Sell_Zone",  # Safe fallback
                distance_to_entry_pips=0.0
            )
    
    def calculate_position_size(self, instrument: str, entry_price: float, stop_loss_price: float, confidence: int) -> int:
        """Calculate position size using existing risk manager"""
        try:
            if self.risk_manager:
                result = self.risk_manager.calculate_position_size(
                    instrument, entry_price, stop_loss_price, confidence
                )
                
                if 'error' in result:
                    self.logger.error(f"Position sizing error for {instrument}: {result['error']}")
                    return 1000
                
                return result['position_size']
            else:
                return 1000
                
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 1000
    
    def scan_for_butter_middle_opportunities(self) -> List[QuarterCurveTradeOrder]:
        """Scan all instruments for Quarter Curve Butter Middle opportunities"""
        opportunities = []
        
        self.logger.info("🔍 Scanning for Quarter Curve Butter Middle opportunities...")
        
        for instrument in self.instruments:
            try:
                butter_opportunities = self.butter_middle_strategy.analyze_butter_middle_opportunities(instrument)
                
                for opp in butter_opportunities:
                    position_size = self.calculate_position_size(
                        instrument, opp['entry_price'], opp['stop_loss'], opp['confidence']
                    )
                    
                    trade_order = QuarterCurveTradeOrder(
                        instrument=instrument,
                        action=opp['action'],
                        order_type=opp['order_type'],
                        entry_price=opp['entry_price'],
                        stop_loss=opp['stop_loss'],
                        take_profit=opp['take_profit'],
                        units=position_size if opp['action'] == 'BUY' else -position_size,
                        confidence=opp['confidence'],
                        reasoning=opp['reasoning'],
                        timestamp=datetime.now().isoformat(),
                        strategy_name=opp['strategy_name'],
                        quarter_above=opp['quarter_above'],
                        quarter_below=opp['quarter_below'],
                        breach_direction=opp['breach_direction'],
                        candlestick_strength=opp['candlestick_strength'],
                        bodyguard_breached=opp['bodyguard_breached'],
                        stop_pips=opp['stop_pips'],
                        target_pips=opp['target_pips'],
                        setup_type=f"BODYGUARD_BREACH_{opp['breach_direction'].upper()}",
                        expiration=opp.get('expiration'),
                        momentum_analysis={'momentum_strength': None, 'direction': None},
                        zone_data={'quarter_analysis': True},
                        analysis_data=opp
                    )
                    
                    opportunities.append(trade_order)
                    
                    self.logger.info(f"🎯 {instrument}: {opp['strategy_name']} {opp['action']} @ {opp['entry_price']:.4f}")
                    self.logger.info(f"   Quarters: {opp['quarter_below']:.4f} - {opp['quarter_above']:.4f}")
                    self.logger.info(f"   Target: {opp['target_pips']} pips | Stop: {opp['stop_pips']} pips")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        return opportunities
    
    def place_limit_order(self, trade_order: QuarterCurveTradeOrder) -> bool:
        """Place limit order with metadata storage"""
        try:
            self.logger.info(f"🎯 Placing {trade_order.strategy_name} order for {trade_order.instrument}")
            
            metadata = self.create_airtable_metadata(trade_order)
            
            order_data = {
                "order": {
                    "type": "LIMIT",
                    "instrument": trade_order.instrument,
                    "units": str(trade_order.units),
                    "price": str(trade_order.entry_price),
                    "stopLossOnFill": {
                        "price": str(trade_order.stop_loss)
                    },
                    "takeProfitOnFill": {
                        "price": str(trade_order.take_profit)
                    }
                }
            }
            
            if trade_order.expiration == 'END_OF_DAY':
                eod_time = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
                if datetime.now() > eod_time:
                    eod_time += timedelta(days=1)
                order_data["order"]["timeInForce"] = "GTD"
                order_data["order"]["gtdTime"] = eod_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            order_data["order"]["clientExtensions"] = {
                "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                "tag": metadata.strategy_tag,
                "comment": f"Quarters:{trade_order.quarter_below:.4f}-{trade_order.quarter_above:.4f}|Stop:{trade_order.stop_pips}p|Target:{trade_order.target_pips}p"[:500]
            }
            
            response = self.api.place_order(order_data)
            
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                
                self.metadata_store.store_order_metadata(order_id, metadata)
                
                trade_order.order_id = order_id
                trade_order.status = 'PLACED'
                self.pending_orders.append(trade_order)
                
                self.logger.info(f"✅ Order placed successfully: {order_id}")
                return True
            else:
                self.logger.error(f"❌ Order placement failed: {response}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            return False
    
    def run_analysis_demo(self):
        """Run comprehensive analysis demo showing Quarter Curve Butter Middle system"""
        print("\n" + "="*80)
        print("QUARTER CURVE BUTTER MIDDLE STRATEGY")
        print("="*80)
        print("🏛️ Quarter Boundaries: .000, .250, .500, .750 levels (or XX0.00, XX2.50, XX5.00, XX7.50 for JPY)")
        print("👮 Bodyguard Protection: 75 pips inside each quarter boundary")
        print("🎯 Entry: Limit orders at bodyguard levels when breached by 4hr candles")
        print("📊 Risk: 25 pip stops, 100 pip targets, staying within quarter bounds")
        print("🔗 Integration: Uses existing Oanda API and metadata storage")
        print("="*80)
        
        for instrument in self.instruments:
            print(f"\n🔍 ANALYZING {instrument}:")
            print("-" * 50)
            
            try:
                # Get current price
                price_data = self.api.get_current_prices([instrument])
                if not price_data or 'prices' not in price_data:
                    print(f"❌ Error: Unable to get current price")
                    continue
                
                current_price = float(price_data['prices'][0]['closeoutBid'])
                is_jpy = self.institutional_analyzer.is_jpy_pair(instrument)
                
                # Get 4hr candlestick
                candle_4hr = self.candlestick_analyzer.get_4hr_candlestick(instrument)
                if 'error' in candle_4hr:
                    print(f"❌ 4hr candlestick error: {candle_4hr['error']}")
                    continue
                
                candlestick_strength = self.candlestick_analyzer.analyze_4hr_candlestick_strength(candle_4hr)
                
                # Find quarter boundaries and bodyguards
                quarter_data = self.institutional_analyzer.find_quarter_boundaries(current_price, is_jpy)
                if 'error' in quarter_data:
                    print(f"❌ Quarter boundary error: {quarter_data['error']}")
                    continue
                
                print(f"Current Price: {current_price:.4f}")
                print(f"Currency Type: {'JPY Pair' if is_jpy else 'Standard Pair'}")
                print(f"4hr Candlestick Strength: {candlestick_strength}")
                
                # Show quarter boundaries and bodyguards
                print(f"\n📊 Quarter Boundaries & Bodyguards:")
                print(f"  Quarter Above: {quarter_data['quarter_above']:.4f}")
                print(f"  Upper Bodyguard: {quarter_data['upper_bodyguard']:.4f} (75 pips below quarter above)")
                print(f"  -------- TRADING ZONE --------")
                print(f"  Current Price: {current_price:.4f} {'✓ In Zone' if quarter_data['current_in_zone'] else '✗ Outside Zone'}")
                print(f"  -------- TRADING ZONE --------")
                print(f"  Lower Bodyguard: {quarter_data['lower_bodyguard']:.4f} (75 pips above quarter below)")
                print(f"  Quarter Below: {quarter_data['quarter_below']:.4f}")
                
                trading_zone_pips = quarter_data['trading_zone_size'] / quarter_data['pip_value']
                print(f"  Trading Zone Size: {trading_zone_pips:.0f} pips")
                
                # Check for bodyguard breaches
                breach = self.candlestick_analyzer.detect_bodyguard_breach(candle_4hr, quarter_data)
                if breach["breach_detected"]:
                    print(f"\n🚨 BODYGUARD BREACH DETECTED:")
                    print(f"  Direction: {breach['breach_direction']}")
                    print(f"  Type: {breach['breach_type']} (Strength: {breach['candlestick_strength']})")
                    print(f"  Entry Level: {breach['entry_level']:.4f}")
                    print(f"  Valid Signal: {'✅' if breach['is_valid_breach'] else '❌'}")
                else:
                    print(f"\n⏰ No bodyguard breaches detected")
                
                # Show Butter Middle opportunities
                butter_opportunities = self.butter_middle_strategy.analyze_butter_middle_opportunities(instrument)
                if butter_opportunities:
                    print(f"\n🎯 BUTTER MIDDLE OPPORTUNITIES:")
                    for opp in butter_opportunities:
                        print(f"  {opp['action']} LIMIT @ {opp['entry_price']:.4f}")
                        print(f"    Stop: {opp['stop_loss']:.4f} ({opp['stop_pips']} pips)")
                        print(f"    Target: {opp['take_profit']:.4f} ({opp['target_pips']} pips)")
                        print(f"    Quarter Bounds: {opp['quarter_below']:.4f} - {opp['quarter_above']:.4f}")
                        print(f"    Breach: {opp['breach_direction']}")
                        print(f"    Confidence: {opp['confidence']}%")
                else:
                    print(f"\n⏰ No Butter Middle opportunities")
                
            except Exception as e:
                print(f"❌ Error analyzing {instrument}: {e}")
        
        print("\n" + "="*80)
        print("✅ Quarter Curve Butter Middle Analysis Complete!")
        print("🏛️ Monitoring quarter boundaries with 75-pip bodyguard protection")
        print("📊 4hr candlestick analysis for bodyguard breach detection")
        print("🎯 Entry at bodyguard levels, 100 pip targets within quarter bounds")
        print("🎪 Risk: 25 pip stops, 1:4 risk/reward ratio")
        print("="*80)
    
    def run_single_scan(self):
        """Run a single scan for Quarter Curve Butter Middle opportunities"""
        print("🔍 Running Quarter Curve Butter Middle scan...")
        
        opportunities = self.scan_for_butter_middle_opportunities()
        
        if opportunities:
            print(f"\n🎯 Found {len(opportunities)} Butter Middle opportunities:")
            for opp in opportunities:
                print(f"  {opp.instrument}: {opp.strategy_name}")
                print(f"    {opp.action} LIMIT @ {opp.entry_price:.4f}")
                print(f"    Stop: {opp.stop_loss:.4f} ({opp.stop_pips} pips) | Target: {opp.take_profit:.4f} ({opp.target_pips} pips)")
                print(f"    Quarter Bounds: {opp.quarter_below:.4f} - {opp.quarter_above:.4f}")
                print(f"    Breach: {opp.breach_direction} | Strength: {opp.candlestick_strength}")
                print(f"    Confidence: {opp.confidence}%")
                print()
        else:
            print("⏰ No Butter Middle opportunities found at this time")
        
        return opportunities

def main():
    """Main function for Quarter Curve Butter Middle system"""
    print("🎯 Quarter Curve Butter Middle Trading System")
    print("="*60)
    print("🏛️ 75-pip bodyguard protection within quarter bounds")
    print("📊 4hr candlestick analysis for bodyguard breaches")
    print("🎪 Risk: 25 pip stops, 100 pip targets (fixed)")
    print("="*60)
    
    # Risk management
    print("\nRisk Management:")
    print("1. Conservative: $5 USD max per trade")
    print("2. Standard: $10 USD max per trade") 
    print("3. Aggressive: $20 USD max per trade")
    
    risk_choice = input("Enter choice (1-3) or press Enter for Standard: ").strip()
    
    if risk_choice == "1":
        max_risk_usd = 5.0
    elif risk_choice == "3":
        max_risk_usd = 20.0
    else:
        max_risk_usd = 10.0
    
    # Initialize bot
    bot = QuarterCurveIntegratedTradingBot(max_risk_usd=max_risk_usd, max_open_trades=5)
    
    # Mode selection
    print("\nSelect Mode:")
    print("1. Analysis Demo (Show quarter boundaries and bodyguard breach detection)")
    print("2. Single Scan (Check for Butter Middle opportunities)")
    print("3. Place Orders (Execute found opportunities)")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        bot.run_analysis_demo()
    elif choice == "2":
        bot.run_single_scan()
    elif choice == "3":
        opportunities = bot.run_single_scan()
        if opportunities:
            confirm = input(f"\nFound {len(opportunities)} opportunities. Place orders? (y/N): ").strip().lower()
            if confirm == 'y':
                for opp in opportunities:
                    bot.place_limit_order(opp)
                print("✅ Butter Middle orders placed!")
            else:
                print("Orders not placed.")
        else:
            print("No opportunities to execute.")
    else:
        print("Invalid choice. Running analysis demo...")
        bot.run_analysis_demo()

if __name__ == "__main__":
    main()