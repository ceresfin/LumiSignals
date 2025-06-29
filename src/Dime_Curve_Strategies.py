# Integrated Dime Curve Trading System - All Three Strategies
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

class DimeCurveLevelIdentifier:
    """
    Unified level identification for all three Dime Curve strategies
    
    Identifies key levels for:
    - Non-JPY: X.X000 (dime), X.X250 (2nd quarter), X.X500 (wildcard), X.X750 (4th quarter)
    - JPY: XX0.00 (dime), XX2.50 (2nd quarter), XX5.00 (wildcard), XX7.50 (4th quarter)
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def is_jpy_pair(self, instrument: str) -> bool:
        """Check if instrument is a JPY pair"""
        return 'JPY' in instrument
    
    def identify_level_type(self, price: float, is_jpy: bool = False) -> str:
        """Identify if a price is a dime, quarter, or wildcard level"""
        price = round(price, 2 if is_jpy else 4)
        
        if is_jpy:
            # JPY pairs: check for XX0.00, XX2.50, XX5.00, XX7.50
            decimal_part = int((price * 100) % 1000)
            
            if decimal_part % 1000 == 0:  # XX0.00
                return "dime"
            elif decimal_part % 1000 == 250:  # XX2.50  
                return "2nd_quarter"
            elif decimal_part % 1000 == 500:  # XX5.00
                return "wildcard"
            elif decimal_part % 1000 == 750:  # XX7.50
                return "4th_quarter"
        else:
            # Non-JPY pairs: check for X.X000, X.X250, X.X500, X.X750
            decimal_part = int((price * 10000) % 1000)
            
            if decimal_part == 0:  # X.X000
                return "dime"
            elif decimal_part == 250:  # X.X250
                return "2nd_quarter"
            elif decimal_part == 500:  # X.X500
                return "wildcard"
            elif decimal_part == 750:  # X.X750
                return "4th_quarter"
        
        return "other"
    
    def find_closest_levels(self, current_price: float, is_jpy: bool = False, num_levels: int = 4) -> Dict:
        """Find the closest key levels around current price"""
        
        if is_jpy:
            increment = 2.5  # JPY increment between quarters
            base = round(current_price / 2.5) * 2.5
        else:
            increment = 0.025  # Non-JPY increment between quarters  
            base = round(current_price / 0.025) * 0.025
        
        levels_above = []
        levels_below = []
        
        # Generate levels above current price
        for i in range(1, num_levels * 4 + 1):
            level = base + (i * (2.5 if is_jpy else 0.025))
            level_type = self.identify_level_type(level, is_jpy)
            
            if level_type in ["dime", "2nd_quarter", "wildcard", "4th_quarter"]:
                levels_above.append({
                    "price": round(level, 2 if is_jpy else 4),
                    "type": level_type,
                    "distance": level - current_price
                })
            
            if len(levels_above) >= num_levels:
                break
        
        # Generate levels below current price
        for i in range(1, num_levels * 4 + 1):
            level = base - (i * (2.5 if is_jpy else 0.025))
            level_type = self.identify_level_type(level, is_jpy)
            
            if level_type in ["dime", "2nd_quarter", "wildcard", "4th_quarter"]:
                levels_below.append({
                    "price": round(level, 2 if is_jpy else 4),
                    "type": level_type,
                    "distance": current_price - level
                })
            
            if len(levels_below) >= num_levels:
                break
        
        return {
            "current_price": current_price,
            "is_jpy": is_jpy,
            "levels_above": levels_above,
            "levels_below": levels_below
        }

class DimeCurveCandlestickAnalyzer:
    """
    Enhanced candlestick analyzer using existing infrastructure
    Integrates with your existing DailyCandlestickAnalyzer approach
    """
    
    def __init__(self, api):
        self.api = api
        self.logger = logging.getLogger(__name__)
    
    def get_daily_candlestick(self, instrument: str) -> Dict:
        """Get the most recent completed daily candlestick using existing API"""
        try:
            # Use your existing API method
            candles = self.api.get_candles(instrument, granularity='D', count=2)
            
            if not candles or 'candles' not in candles or len(candles['candles']) < 1:
                return {'error': 'Unable to get daily candles'}
            
            # Get the most recent completed candle
            last_candle = candles['candles'][-2] if len(candles['candles']) >= 2 else candles['candles'][-1]
            
            if not last_candle.get('complete', False):
                if len(candles['candles']) >= 2:
                    last_candle = candles['candles'][-2]
                else:
                    return {'error': 'No completed daily candle available'}
            
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
            self.logger.error(f"Error getting daily candlestick for {instrument}: {e}")
            return {'error': str(e)}
    
    def analyze_candlestick_strength(self, candle_data: Dict) -> str:
        """Analyze candlestick strength - simplified for consistency"""
        if 'error' in candle_data:
            return 'neutral'
        
        open_price = candle_data['open']
        high_price = candle_data['high']
        low_price = candle_data['low']
        close_price = candle_data['close']
        
        range_size = high_price - low_price
        if range_size == 0:
            return 'neutral'
        
        # Calculate where close is within the range (0% = at low, 100% = at high)
        close_position_percent = ((close_price - low_price) / range_size) * 100
        
        # Determine strength based on close position (matches your existing logic)
        if close_position_percent >= 80:
            return 'very_bullish'
        elif close_position_percent >= 60:
            return 'bullish'
        elif close_position_percent >= 40:
            return 'neutral'
        elif close_position_percent >= 20:
            return 'bearish'
        else:
            return 'very_bearish'
    
    def detect_level_breach(self, candlestick_data: Dict, target_level: float) -> Dict:
        """Detect if a candlestick breached a specific level"""
        open_price = candlestick_data['open']
        high_price = candlestick_data['high'] 
        low_price = candlestick_data['low']
        close_price = candlestick_data['close']
        
        strength = self.analyze_candlestick_strength(candlestick_data)
        
        breach_info = {
            "level": target_level,
            "breached": False,
            "direction": None,
            "strength": strength,
            "candlestick": candlestick_data
        }
        
        # Check if level was breached from above
        if open_price > target_level and low_price <= target_level:
            breach_info["breached"] = True
            breach_info["direction"] = "from_above"
        
        # Check if level was breached from below
        elif open_price < target_level and high_price >= target_level:
            breach_info["breached"] = True
            breach_info["direction"] = "from_below"
        
        return breach_info

class DimeCurveStrategyAnalyzer:
    """
    Unified strategy analyzer for all three Dime Curve strategies
    Integrates with existing momentum calculator infrastructure
    """
    
    def __init__(self, momentum_calculator):
        self.momentum_calc = momentum_calculator
        self.api = momentum_calculator.api
        self.level_identifier = DimeCurveLevelIdentifier()
        self.candlestick_analyzer = DimeCurveCandlestickAnalyzer(self.api)
        self.logger = logging.getLogger(__name__)
    
    def classify_strategy(self, level_type: str, breach_direction: str) -> str:
        """Classify which Dime Curve strategy applies based on breach pattern"""
        if level_type == "2nd_quarter" and breach_direction == "from_below":
            return "Dime Curve Butter Middle"
        elif level_type == "4th_quarter" and breach_direction == "from_above":
            return "Dime Curve Butter Middle"
        elif level_type == "2nd_quarter" and breach_direction == "from_above":
            return "Dime Curve Dime Middle"
        elif level_type == "4th_quarter" and breach_direction == "from_below":
            return "Dime Curve Dime Middle"
        elif level_type == "wildcard" and breach_direction == "from_below":
            return "Dime Curve Quarter Middle"
        elif level_type == "dime" and breach_direction == "from_above":
            return "Dime Curve Quarter Middle"
        else:
            return "No Strategy"
    
    def calculate_stop_and_target(self, entry_price: float, is_buy: bool, is_jpy: bool = False) -> Tuple[float, float]:
        """Calculate stop loss and take profit (always 50 pip stop, 500 pip target)"""
        pip_value = 0.01 if is_jpy else 0.0001
        
        if is_buy:
            stop_loss = entry_price - (50 * pip_value)
            take_profit = entry_price + (500 * pip_value)
        else:
            stop_loss = entry_price + (50 * pip_value)
            take_profit = entry_price - (500 * pip_value)
        
        return stop_loss, take_profit
    
    def analyze_instrument(self, instrument: str) -> Dict:
        """
        Complete analysis of an instrument for all Dime Curve strategies
        Returns signals, analysis data, and metadata for integration
        """
        try:
            # Get current price using existing API
            price_data = self.api.get_current_prices([instrument])
            if not price_data or 'prices' not in price_data:
                return {'error': 'Unable to get current price'}
            
            current_price = float(price_data['prices'][0]['closeoutBid'])
            is_jpy = self.level_identifier.is_jpy_pair(instrument)
            
            # Get daily candlestick
            daily_candle = self.candlestick_analyzer.get_daily_candlestick(instrument)
            if 'error' in daily_candle:
                return {'error': f'Daily candlestick analysis failed: {daily_candle["error"]}'}
            
            # Find closest levels
            levels_info = self.level_identifier.find_closest_levels(current_price, is_jpy, num_levels=4)
            
            # Check for breaches and opportunities
            opportunities = []
            all_levels = levels_info["levels_above"] + levels_info["levels_below"]
            
            for level_info in all_levels:
                breach = self.candlestick_analyzer.detect_level_breach(daily_candle, level_info["price"])
                
                if breach["breached"]:
                    breach["level_type"] = level_info["type"]
                    strategy_name = self.classify_strategy(level_info["type"], breach["direction"])
                    
                    # Only generate orders for strong directional moves
                    if ((breach["direction"] == "from_below" and breach["strength"] in ["bullish", "very_bullish"]) or
                        (breach["direction"] == "from_above" and breach["strength"] in ["bearish", "very_bearish"])):
                        
                        is_buy = breach["direction"] == "from_below"
                        stop_loss, take_profit = self.calculate_stop_and_target(level_info["price"], is_buy, is_jpy)
                        
                        opportunity = {
                            'instrument': instrument,
                            'strategy_name': strategy_name,
                            'action': 'BUY' if is_buy else 'SELL',
                            'order_type': 'LIMIT',
                            'entry_price': level_info["price"],
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'level_type': level_info["type"],
                            'candlestick_strength': breach["strength"],
                            'breach_direction': breach["direction"],
                            'confidence': 85 if 'very' in breach["strength"] else 75,
                            'reasoning': [f"{breach['strength'].title()} breach {breach['direction']} at {level_info['type']} level"],
                            'expiration': 'END_OF_DAY'
                        }
                        
                        opportunities.append(opportunity)
            
            # Prepare analysis data for metadata (matching your existing structure)
            analysis_data = {
                'current_price': current_price,
                'is_jpy': is_jpy,
                'daily_candle': daily_candle,
                'candlestick_strength': self.candlestick_analyzer.analyze_candlestick_strength(daily_candle),
                'levels_info': levels_info,
                'opportunities': opportunities
            }
            
            return {
                'signals': opportunities[0] if opportunities else {'action': 'WAIT'},
                'analysis_data': analysis_data,
                'momentum_analysis': {
                    'momentum_strength': None,  # Dime Curve doesn't use momentum
                    'direction': None,
                    'strategy_bias': None,
                    'alignment': None
                },
                'zone_data': {
                    'current_price': current_price,
                    'is_jpy': is_jpy,
                    'levels_info': levels_info
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error analyzing {instrument}: {e}")
            return {'error': str(e)}

@dataclass
class DimeCurveTradeOrder:
    """Enhanced trade order data class matching your existing structure"""
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
    strategy_name: str  # 'Dime Curve Butter Middle', etc.
    level_type: str  # 'dime', '2nd_quarter', 'wildcard', '4th_quarter'
    candlestick_strength: str
    breach_direction: str
    setup_type: str
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    # Metadata fields for integration
    momentum_analysis: Optional[Dict] = None
    zone_data: Optional[Dict] = None
    analysis_data: Optional[Dict] = None

class DimeCurveIntegratedTradingBot:
    """
    Integrated Dime Curve Trading Bot using existing infrastructure
    Works with your existing Oanda API, metadata storage, and risk management
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Initialize using existing infrastructure
        self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        self.momentum_calc = MarketAwareMomentumCalculator(self.api)
        self.strategy_analyzer = DimeCurveStrategyAnalyzer(self.momentum_calc)
        
        # Use existing metadata storage
        self.metadata_store = TradeMetadataStore()
        self.metadata_store.cleanup_old_metadata()
        
        # Risk management (using existing risk manager)
        try:
            from Demo_Trading_Penny_Curve_Strategy import FixedDollarRiskManager
            self.risk_manager = FixedDollarRiskManager(self.api, max_risk_usd)
        except ImportError:
            self.logger.warning("Could not import FixedDollarRiskManager, using default position sizing")
            self.risk_manager = None
        
        self.max_risk_usd = max_risk_usd
        self.max_open_trades = max_open_trades
        
        # Trading instruments - All 21 currency pairs
        self.instruments = [
            # Major USD pairs
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD',
            # Cross pairs (EUR)
            'EUR_GBP', 'EUR_JPY', 'EUR_CAD', 'EUR_AUD', 'EUR_NZD',
            # Cross pairs (GBP)
            'GBP_JPY', 'GBP_CAD', 'GBP_AUD', 'GBP_NZD',
            # Cross pairs (AUD)
            'AUD_JPY', 'AUD_CAD', 'AUD_NZD',
            # Cross pairs (NZD)
            'NZD_JPY', 'NZD_CAD',
            # JPY cross
            'CAD_JPY'
        ]
        
        # Trade tracking
        self.pending_orders = []
        self.open_positions = []
        self.trade_history = []
        
        # Market schedule (using existing)
        self.market_schedule = ForexMarketSchedule()
        
        # Setup logging
        self.setup_logging()
        
        print("🎯 Integrated Dime Curve Trading Bot Initialized!")
        print(f"   All Three Strategies: Butter Middle, Dime Middle, Quarter Middle")
        print(f"   Using existing Oanda API and metadata infrastructure")
        print(f"   Max risk per trade: ${max_risk_usd:.2f}")
        print(f"   Fixed stops: 50 pips | Fixed targets: 500 pips")
        print(f"   Monitoring {len(self.instruments)} pairs: {', '.join(self.instruments)}")
    
    def setup_logging(self):
        """Setup logging using existing structure"""
        log_dir = os.path.join(current_dir, 'trading_logs')
        os.makedirs(log_dir, exist_ok=True)
        
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(log_dir, f'dime_curve_integrated_{today}.log')
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info("Integrated Dime Curve Trading Bot started")
    
    def create_airtable_metadata(self, trade_order: DimeCurveTradeOrder) -> TradeMetadata:
        """
        Create metadata using existing TradeMetadata structure
        Maps Dime Curve strategy details to Airtable-compatible fields
        """
        try:
            # Create setup name
            instrument_clean = trade_order.instrument.replace('_', '/')
            setup_name = f"{trade_order.strategy_name.replace(' ', '')}_{instrument_clean}_{trade_order.action}_{trade_order.candlestick_strength.title().replace('_', '')}"
            
            # Map strategy to tag
            strategy_tag_map = {
                "Dime Curve Butter Middle": "DimeCurveButterMiddle",
                "Dime Curve Dime Middle": "DimeCurveDimeMiddle", 
                "Dime Curve Quarter Middle": "DimeCurveQuarterMiddle"
            }
            strategy_tag = strategy_tag_map.get(trade_order.strategy_name, "DimeCurve")
            
            # Map to Airtable zone positions
            zone_position_map = {
                ("Dime Curve Butter Middle", "2nd_quarter", "from_below", "bullish"): "QUARTER_250_CROSS_BUY_BULLISH",
                ("Dime Curve Butter Middle", "2nd_quarter", "from_below", "very_bullish"): "QUARTER_250_CROSS_BUY_VERY_BULLISH",
                ("Dime Curve Butter Middle", "4th_quarter", "from_above", "bearish"): "QUARTER_750_CROSS_SELL_BEARISH",
                ("Dime Curve Butter Middle", "4th_quarter", "from_above", "very_bearish"): "QUARTER_750_CROSS_SELL_VERY_BEARISH",
                ("Dime Curve Dime Middle", "2nd_quarter", "from_above", "bearish"): "DIME_MIDDLE_250_SELL_BEARISH",
                ("Dime Curve Dime Middle", "2nd_quarter", "from_above", "very_bearish"): "DIME_MIDDLE_250_SELL_VERY_BEARISH",
                ("Dime Curve Dime Middle", "4th_quarter", "from_below", "bullish"): "DIME_MIDDLE_750_BUY_BULLISH",
                ("Dime Curve Dime Middle", "4th_quarter", "from_below", "very_bullish"): "DIME_MIDDLE_750_BUY_VERY_BULLISH",
                ("Dime Curve Quarter Middle", "wildcard", "from_below", "bullish"): "QUARTER_WILDCARD_BUY_BULLISH",
                ("Dime Curve Quarter Middle", "wildcard", "from_below", "very_bullish"): "QUARTER_WILDCARD_BUY_VERY_BULLISH",
                ("Dime Curve Quarter Middle", "dime", "from_above", "bearish"): "QUARTER_DIME_SELL_BEARISH",
                ("Dime Curve Quarter Middle", "dime", "from_above", "very_bearish"): "QUARTER_DIME_SELL_VERY_BEARISH",
            }
            
            zone_key = (trade_order.strategy_name, trade_order.level_type, trade_order.breach_direction, trade_order.candlestick_strength)
            zone_position = zone_position_map.get(zone_key, "Below_Sell_Zone")  # Safe fallback
            
            # Create metadata using existing structure
            metadata = TradeMetadata(
                setup_name=setup_name,
                strategy_tag=strategy_tag,
                # Set momentum fields to None (Dime Curve doesn't use momentum)
                momentum_strength=None,
                momentum_direction=None,
                strategy_bias=None,
                momentum_alignment=None,
                # Dime Curve specific fields
                zone_position=zone_position,
                distance_to_entry_pips=0.0,  # Limit orders at exact levels
                signal_confidence=trade_order.confidence
            )
            
            self.logger.info(f"🎯 {trade_order.strategy_name} Setup: {setup_name}")
            self.logger.info(f"   Level: {trade_order.level_type} | Strength: {trade_order.candlestick_strength}")
            self.logger.info(f"   Entry: {trade_order.entry_price:.4f} | Stop: {trade_order.stop_loss:.4f} | Target: {trade_order.take_profit:.4f}")
            self.logger.info(f"   📊 Zone Position: {zone_position}")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Error creating metadata: {e}")
            # Return safe fallback
            return TradeMetadata(
                setup_name=f"DimeCurve_{trade_order.instrument}_{trade_order.action}",
                strategy_tag="DimeCurve",
                signal_confidence=trade_order.confidence,
                momentum_strength=None,
                momentum_direction=None,
                strategy_bias=None,
                momentum_alignment=None,
                zone_position="Below_Sell_Zone",
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
                # Fallback position sizing
                return 1000
                
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 1000
    
    def scan_for_opportunities(self) -> List[DimeCurveTradeOrder]:
        """Scan all instruments for Dime Curve opportunities"""
        opportunities = []
        
        self.logger.info("🔍 Scanning for Dime Curve opportunities (all three strategies)...")
        
        for instrument in self.instruments:
            try:
                analysis = self.strategy_analyzer.analyze_instrument(instrument)
                
                if 'error' in analysis:
                    self.logger.warning(f"❌ {instrument}: {analysis['error']}")
                    continue
                
                signals = analysis['signals']
                
                if isinstance(signals, dict) and signals.get('action') != 'WAIT':
                    # Calculate position size
                    position_size = self.calculate_position_size(
                        instrument, signals['entry_price'], signals['stop_loss'], signals['confidence']
                    )
                    
                    # Create trade order
                    trade_order = DimeCurveTradeOrder(
                        instrument=instrument,
                        action=signals['action'],
                        order_type=signals['order_type'],
                        entry_price=signals['entry_price'],
                        stop_loss=signals['stop_loss'],
                        take_profit=signals['take_profit'],
                        units=position_size if signals['action'] == 'BUY' else -position_size,
                        confidence=signals['confidence'],
                        reasoning=signals['reasoning'],
                        timestamp=datetime.now().isoformat(),
                        strategy_name=signals['strategy_name'],
                        level_type=signals['level_type'],
                        candlestick_strength=signals['candlestick_strength'],
                        breach_direction=signals['breach_direction'],
                        setup_type=f"{signals['level_type'].upper()}_BREACH_{signals['candlestick_strength'].upper()}",
                        expiration=signals.get('expiration'),
                        momentum_analysis=analysis.get('momentum_analysis', {}),
                        zone_data=analysis.get('zone_data', {}),
                        analysis_data=analysis.get('analysis_data', {})
                    )
                    
                    opportunities.append(trade_order)
                    
                    self.logger.info(f"🎯 {instrument}: {signals['strategy_name']} {signals['action']} @ {signals['entry_price']:.4f}")
                    self.logger.info(f"   Level: {signals['level_type']} | Strength: {signals['candlestick_strength']} | Confidence: {signals['confidence']}%")
                else:
                    self.logger.debug(f"📊 {instrument}: No opportunities")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        return opportunities
    
    def place_limit_order(self, trade_order: DimeCurveTradeOrder) -> bool:
        """Place limit order using existing Oanda API with metadata storage"""
        try:
            self.logger.info(f"🎯 Placing {trade_order.strategy_name} {trade_order.action} order for {trade_order.instrument}")
            
            # Create metadata using existing structure
            metadata = self.create_airtable_metadata(trade_order)
            
            # Create order payload (matches your existing structure)
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
            
            # Add expiration (matches your existing logic)
            if trade_order.expiration == 'END_OF_DAY':
                eod_time = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
                if datetime.now() > eod_time:
                    eod_time += timedelta(days=1)
                order_data["order"]["timeInForce"] = "GTD"
                order_data["order"]["gtdTime"] = eod_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # Add client extensions (matches your existing approach)
            order_data["order"]["clientExtensions"] = {
                "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                "tag": metadata.strategy_tag,
                "comment": f"Strategy:{trade_order.strategy_name}|Level:{trade_order.level_type}|Strength:{trade_order.candlestick_strength}|Confidence:{trade_order.confidence}%"[:500]
            }
            
            # Place order using existing API
            response = self.api.place_order(order_data)
            
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                
                # Store metadata using existing system
                self.metadata_store.store_order_metadata(order_id, metadata)
                
                trade_order.order_id = order_id
                trade_order.status = 'PLACED'
                self.pending_orders.append(trade_order)
                
                self.logger.info(f"✅ Order placed successfully: {order_id}")
                self.logger.info(f"📝 Metadata stored for Airtable sync")
                return True
            else:
                self.logger.error(f"❌ Order placement failed: {response}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            return False
    
    def run_analysis_demo(self):
        """Run comprehensive analysis demo showing all three strategies"""
        print("\n" + "="*80)
        print("INTEGRATED DIME CURVE TRADING SYSTEM - ALL THREE STRATEGIES")
        print("="*80)
        print("🧈 Butter Middle: 2nd quarter from below OR 4th quarter from above (through wildcard)")
        print("🎯 Dime Middle: 2nd quarter from above OR 4th quarter from below (through dime)")
        print("🔲 Quarter Middle: Wildcard from below OR dime from above (starts/ends at dime)")
        print("📊 Momentum Analysis: NOT USED (all momentum fields set to None)")
        print("🔗 Integration: Uses existing Oanda API and metadata storage")
        print("="*80)
        
        for instrument in self.instruments:  # Show all pairs in demo
            print(f"\n🔍 ANALYZING {instrument}:")
            print("-" * 50)
            
            try:
                analysis = self.strategy_analyzer.analyze_instrument(instrument)
                
                if 'error' in analysis:
                    print(f"❌ Error: {analysis['error']}")
                    continue
                
                analysis_data = analysis['analysis_data']
                current_price = analysis_data['current_price']
                is_jpy = analysis_data['is_jpy']
                levels_info = analysis_data['levels_info']
                candlestick_strength = analysis_data['candlestick_strength']
                
                print(f"Current Price: {current_price:.4f}")
                print(f"Currency Type: {'JPY Pair' if is_jpy else 'Standard Pair'}")
                print(f"Candlestick Strength: {candlestick_strength}")
                
                print(f"\n📊 Key Levels:")
                for level in levels_info['levels_above'][:3]:
                    pips = (level['distance'] / (0.01 if is_jpy else 0.0001))
                    print(f"  Above: {level['price']:.4f} ({level['type']}) - {pips:.1f} pips")
                
                for level in levels_info['levels_below'][:3]:
                    pips = (level['distance'] / (0.01 if is_jpy else 0.0001))
                    print(f"  Below: {level['price']:.4f} ({level['type']}) - {pips:.1f} pips")
                
                # Show opportunities
                opportunities = analysis_data['opportunities']
                if opportunities:
                    print(f"\n🎯 TRADING OPPORTUNITIES:")
                    for opp in opportunities:
                        print(f"  {opp['strategy_name']} {opp['action']} @ {opp['entry_price']:.4f}")
                        print(f"    Stop: {opp['stop_loss']:.4f} | Target: {opp['take_profit']:.4f}")
                        print(f"    Level: {opp['level_type']} | Strength: {opp['candlestick_strength']}")
                        print(f"    Confidence: {opp['confidence']}%")
                else:
                    print(f"\n⏰ No opportunities found")
                
            except Exception as e:
                print(f"❌ Error analyzing {instrument}: {e}")
        
        print("\n" + "="*80)
        print("✅ Integration Demo Complete!")
        print("🔗 Using existing Oanda API and metadata infrastructure")
        print("📊 All momentum fields set to None (not applicable)")
        print("🎯 All three strategies working with unified level detection")
        print("📝 Metadata ready for Airtable sync via existing system")
        print("="*80)
    
    def run_single_scan(self):
        """Run a single scan for opportunities"""
        print("🔍 Running single Dime Curve scan (all strategies)...")
        
        opportunities = self.scan_for_opportunities()
        
        if opportunities:
            print(f"\n🎯 Found {len(opportunities)} opportunities:")
            for opp in opportunities:
                print(f"  {opp.instrument}: {opp.strategy_name}")
                print(f"    {opp.action} LIMIT @ {opp.entry_price:.4f}")
                print(f"    Stop: {opp.stop_loss:.4f} | Target: {opp.take_profit:.4f}")
                print(f"    Level: {opp.level_type} | Strength: {opp.candlestick_strength}")
                print(f"    Confidence: {opp.confidence}%")
                print()
        else:
            print("⏰ No opportunities found at this time")
        
        return opportunities

def main():
    """Main function for integrated Dime Curve system"""
    print("🎯 Integrated Dime Curve Trading System")
    print("="*60)
    print("🧈 Butter Middle | 🎯 Dime Middle | 🔲 Quarter Middle")
    print("🔗 Integrated with existing Oanda API & metadata")
    print("📊 Momentum fields set to None (not applicable)")
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
    
    # Initialize integrated bot
    bot = DimeCurveIntegratedTradingBot(max_risk_usd=max_risk_usd, max_open_trades=5)
    
    # Mode selection
    print("\nSelect Mode:")
    print("1. Analysis Demo (Show all strategies with level detection)")
    print("2. Single Scan (Check for opportunities)")
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
                print("✅ Orders placed!")
            else:
                print("Orders not placed.")
        else:
            print("No opportunities to execute.")
    else:
        print("Invalid choice. Running analysis demo...")
        bot.run_analysis_demo()

if __name__ == "__main__":
    main()