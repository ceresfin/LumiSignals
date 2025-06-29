# Enhanced Dime Curve Strategies with Complete Metadata Integration
# All Three Strategies: Butter Middle, Dime Middle, Quarter Middle
# Following Trading Strategy Architecture Blueprint for Airtable sync

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
    print("✅ SUCCESS: Imported Oanda config")
except ImportError as e:
    print(f"❌ ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

class DimeCurveMetadataProcessor:
    """
    Dime Curve Metadata Processor for Airtable Integration
    
    Generates standardized metadata following the Trading Strategy Architecture Blueprint
    """
    
    def __init__(self):
        self.candlestick_strength_thresholds = {
            'very_strong': 0.9,    # >90% (very_bullish/very_bearish)
            'strong': 0.7,         # 70-90% (bullish/bearish)
            'moderate': 0.5,       # 50-70% (neutral leaning)
            'weak': 0.3            # 30-50% (weak signals)
        }
    
    def classify_momentum_strength(self, candlestick_strength: str, confidence: int) -> str:
        """Convert candlestick strength to momentum strength for Airtable"""
        if candlestick_strength in ['very_bullish', 'very_bearish']:
            return "Very Strong"
        elif candlestick_strength in ['bullish', 'bearish']:
            return "Strong"
        elif candlestick_strength == 'neutral':
            return "Moderate"
        else:
            return "Weak"
    
    def determine_momentum_direction(self, candlestick_strength: str, action: str) -> str:
        """Create descriptive momentum direction for Airtable"""
        # Map candlestick strength to Airtable momentum direction options
        direction_mapping = {
            'very_bullish': 'STRONG_BULLISH',
            'bullish': 'WEAK_BULLISH',
            'neutral': 'NEUTRAL',
            'bearish': 'WEAK_BEARISH',
            'very_bearish': 'STRONG_BEARISH'
        }
        
        return direction_mapping.get(candlestick_strength, 'NEUTRAL')
    
    def determine_strategy_bias(self, action: str) -> str:
        """Determine overall strategy bias for Airtable"""
        if action == 'BUY':
            return "BULLISH"
        elif action == 'SELL':
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def determine_zone_position(self, strategy_name: str, level_type: str, 
                              candlestick_strength: str, breach_direction: str) -> str:
        """
        Determine position relative to Dime Curve zones for Airtable
        
        Enhanced zone mapping based on strategy and level context
        """
        # Strategy-specific zone mapping
        if strategy_name == "Dime Curve Butter Middle":
            if level_type == "2nd_quarter" and breach_direction == "from_below":
                if candlestick_strength == "very_bullish":
                    return "QUARTER_250_CROSS_BUY_VERY_BULLISH"
                else:
                    return "QUARTER_250_CROSS_BUY_BULLISH"
            elif level_type == "4th_quarter" and breach_direction == "from_above":
                if candlestick_strength == "very_bearish":
                    return "QUARTER_750_CROSS_SELL_VERY_BEARISH"
                else:
                    return "QUARTER_750_CROSS_SELL_BEARISH"
        
        elif strategy_name == "Dime Curve Dime Middle":
            if level_type == "2nd_quarter" and breach_direction == "from_above":
                return "In_Sell_Zone"  # Selling from quarter level
            elif level_type == "4th_quarter" and breach_direction == "from_below":
                return "In_Buy_Zone"   # Buying from quarter level
        
        elif strategy_name == "Dime Curve Quarter Middle":
            if level_type == "wildcard" and breach_direction == "from_below":
                return "In_Buy_Zone"   # Buying from wildcard level
            elif level_type == "dime" and breach_direction == "from_above":
                return "In_Sell_Zone"  # Selling from dime level
        
        # Safe fallback
        if "BUY" in breach_direction or "from_below" in breach_direction:
            return "In_Buy_Zone"
        else:
            return "In_Sell_Zone"
    
    def calculate_distance_to_entry(self, entry_price: float, current_price: float, 
                                  order_type: str, instrument: str) -> float:
        """Calculate distance to entry in pips for Airtable"""
        if order_type == "MARKET":
            return 0.0  # Already at market
        
        if current_price == 0 or entry_price == 0:
            return 0.0
        
        # Determine pip value based on instrument
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        
        distance = abs(current_price - entry_price) / pip_value
        return round(distance, 1)
    
    def calculate_momentum_alignment(self, candlestick_strength: str, confidence: int) -> float:
        """Calculate momentum alignment score for Airtable"""
        # Convert candlestick strength to alignment score
        strength_to_alignment = {
            'very_bullish': 0.95,
            'bullish': 0.75,
            'neutral': 0.50,
            'bearish': 0.75,
            'very_bearish': 0.95
        }
        
        base_alignment = strength_to_alignment.get(candlestick_strength, 0.50)
        
        # Adjust based on confidence
        confidence_multiplier = confidence / 100.0
        
        final_alignment = base_alignment * confidence_multiplier
        return round(final_alignment, 2)

class DimeCurveLevelIdentifier:
    """
    Enhanced level identification for all three Dime Curve strategies
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
    Enhanced candlestick analyzer with signal quality metrics
    """
    
    def __init__(self, api):
        self.api = api
        self.logger = logging.getLogger(__name__)
    
    def get_daily_candlestick(self, instrument: str) -> Dict:
        """Get the most recent completed daily candlestick"""
        try:
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
                'complete': last_candle.get('complete', False),
                'range': float(mid_data['h']) - float(mid_data['l'])
            }
            
        except Exception as e:
            self.logger.error(f"Error getting daily candlestick for {instrument}: {e}")
            return {'error': str(e)}
    
    def analyze_candlestick_strength(self, candle_data: Dict) -> str:
        """Analyze candlestick strength with enhanced precision"""
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
        
        # Enhanced strength classification for better signal quality
        if close_position_percent >= 85:
            return 'very_bullish'
        elif close_position_percent >= 65:
            return 'bullish'
        elif close_position_percent >= 35:
            return 'neutral'
        elif close_position_percent >= 15:
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
            "candlestick": candlestick_data,
            "breach_quality": "none"
        }
        
        # Check if level was breached from above
        if open_price > target_level and low_price <= target_level:
            breach_info["breached"] = True
            breach_info["direction"] = "from_above"
            # Assess breach quality
            breach_distance = abs(low_price - target_level)
            breach_info["breach_quality"] = "strong" if breach_distance > (candlestick_data.get('range', 0) * 0.3) else "weak"
        
        # Check if level was breached from below
        elif open_price < target_level and high_price >= target_level:
            breach_info["breached"] = True
            breach_info["direction"] = "from_below"
            # Assess breach quality
            breach_distance = abs(high_price - target_level)
            breach_info["breach_quality"] = "strong" if breach_distance > (candlestick_data.get('range', 0) * 0.3) else "weak"
        
        return breach_info

class DimeCurveSignalMetrics:
    """
    Dime Curve Signal Quality Calculations
    Following Trading Strategy Architecture Blueprint standards
    """
    
    def calculate_momentum_strength(self, candlestick_strength: str, breach_quality: str, level_type: str) -> float:
        """
        Calculate momentum strength for Dime Curve (0.50-0.95 decimal)
        
        Components:
        - Base strength from candlestick pattern (0.50-0.80)
        - Level importance bonus (0.0-0.10)
        - Breach quality bonus (0.0-0.05)
        """
        base_strength = 0.60  # Starting point (60%)
        
        # Candlestick strength component
        candlestick_strength_map = {
            'very_bullish': 0.20,    # 80% total strength
            'very_bearish': 0.20,    # 80% total strength
            'bullish': 0.15,         # 75% total strength
            'bearish': 0.15,         # 75% total strength
            'neutral': 0.05          # 65% total strength
        }
        
        candlestick_component = candlestick_strength_map.get(candlestick_strength, 0.05)
        
        # Level importance bonus (dime and wildcard are more important)
        level_importance = {
            'dime': 0.10,         # Most important levels
            'wildcard': 0.10,     # Wildcard levels are key
            '2nd_quarter': 0.07,  # Quarter levels
            '4th_quarter': 0.07   # Quarter levels
        }
        
        level_bonus = level_importance.get(level_type, 0.05)
        
        # Breach quality bonus
        breach_bonus = 0.05 if breach_quality == "strong" else 0.02
        
        total_strength = base_strength + candlestick_component + level_bonus + breach_bonus
        return max(0.50, min(0.95, total_strength))
    
    def calculate_signal_confidence(self, candlestick_strength: str, level_type: str, 
                                  breach_quality: str, session_data: Dict) -> int:
        """
        Calculate signal confidence for Dime Curve (60-95 percentage)
        
        Components:
        - Base confidence (70)
        - Candlestick pattern quality (0-15 points)
        - Level importance (0-10 points)
        - Breach quality (0-5 points)
        - Session timing (0-5 points)
        """
        base_confidence = 70
        
        # Candlestick pattern quality
        pattern_quality_map = {
            'very_bullish': 15, 'very_bearish': 15,
            'bullish': 10, 'bearish': 10,
            'neutral': 3
        }
        
        pattern_points = pattern_quality_map.get(candlestick_strength, 3)
        
        # Level importance (dime and wildcard levels are most reliable)
        level_importance_points = {
            'dime': 10,         # Highest confidence at dime levels
            'wildcard': 8,      # High confidence at wildcard
            '2nd_quarter': 6,   # Medium confidence at quarters
            '4th_quarter': 6    # Medium confidence at quarters
        }
        
        level_points = level_importance_points.get(level_type, 3)
        
        # Breach quality assessment
        breach_points = 5 if breach_quality == "strong" else 2
        
        # Session timing assessment
        liquidity_level = session_data.get('liquidity_level', 'LOW')
        session_points = {'HIGH': 5, 'MEDIUM': 3, 'LOW': 1}.get(liquidity_level, 1)
        
        total_confidence = (base_confidence + pattern_points + 
                          level_points + breach_points + session_points)
        
        return max(60, min(95, int(total_confidence)))

class DimeCurveStrategyAnalyzer:
    """
    Enhanced strategy analyzer with complete metadata integration
    """
    
    def __init__(self, momentum_calculator):
        self.momentum_calc = momentum_calculator
        self.api = momentum_calculator.api
        self.level_identifier = DimeCurveLevelIdentifier()
        self.candlestick_analyzer = DimeCurveCandlestickAnalyzer(self.api)
        self.signal_metrics = DimeCurveSignalMetrics()
        self.metadata_processor = DimeCurveMetadataProcessor()
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
        """Calculate stop loss and take profit (50 pip stop, 500 pip target)"""
        pip_value = 0.01 if is_jpy else 0.0001
        
        if is_buy:
            stop_loss = entry_price - (50 * pip_value)
            take_profit = entry_price + (500 * pip_value)
        else:
            stop_loss = entry_price + (50 * pip_value)
            take_profit = entry_price - (500 * pip_value)
        
        return stop_loss, take_profit
    
    def get_session_context(self) -> Dict:
        """Get current trading session context"""
        try:
            # Use existing market schedule if available
            if hasattr(self.momentum_calc, 'market_schedule'):
                current_time = self.momentum_calc.market_schedule.get_market_time()
                active_sessions = self.momentum_calc.market_schedule.get_active_sessions(current_time)
                
                if len(active_sessions) > 1:
                    liquidity_level = 'HIGH'
                elif len(active_sessions) == 1:
                    liquidity_level = 'MEDIUM'
                else:
                    liquidity_level = 'LOW'
                
                return {
                    'active_sessions': active_sessions,
                    'liquidity_level': liquidity_level
                }
        except:
            pass
        
        # Fallback session detection
        current_hour = datetime.now().hour
        
        if 8 <= current_hour <= 17:  # Business hours
            return {'liquidity_level': 'HIGH', 'active_sessions': ['NY']}
        elif 2 <= current_hour <= 12:  # London hours
            return {'liquidity_level': 'MEDIUM', 'active_sessions': ['London']}
        else:
            return {'liquidity_level': 'LOW', 'active_sessions': []}
    
    def analyze_dime_curve_opportunities(self, instrument: str) -> List[Dict]:
        """
        Main analysis method for all Dime Curve opportunities
        
        Returns list of opportunities with complete metadata
        """
        opportunities = []
        
        try:
            # Get current price
            price_data = self.api.get_current_prices([instrument])
            if not price_data or 'prices' not in price_data:
                return opportunities
            
            current_price = float(price_data['prices'][0]['closeoutBid'])
            is_jpy = self.level_identifier.is_jpy_pair(instrument)
            
            # Get daily candlestick
            daily_candle = self.candlestick_analyzer.get_daily_candlestick(instrument)
            if 'error' in daily_candle:
                return opportunities
            
            # Find closest levels
            levels_info = self.level_identifier.find_closest_levels(current_price, is_jpy, num_levels=4)
            
            # Get session context for signal quality
            session_data = self.get_session_context()
            
            # Check for breaches and opportunities
            all_levels = levels_info["levels_above"] + levels_info["levels_below"]
            
            for level_info in all_levels:
                breach = self.candlestick_analyzer.detect_level_breach(daily_candle, level_info["price"])
                
                if breach["breached"]:
                    breach["level_type"] = level_info["type"]
                    strategy_name = self.classify_strategy(level_info["type"], breach["direction"])
                    
                    # Only generate orders for strong directional moves
                    candlestick_strength = breach["strength"]
                    if ((breach["direction"] == "from_below" and candlestick_strength in ["bullish", "very_bullish"]) or
                        (breach["direction"] == "from_above" and candlestick_strength in ["bearish", "very_bearish"])):
                        
                        is_buy = breach["direction"] == "from_below"
                        stop_loss, take_profit = self.calculate_stop_and_target(level_info["price"], is_buy, is_jpy)
                        
                        # Calculate signal quality metrics
                        momentum_strength = self.signal_metrics.calculate_momentum_strength(
                            candlestick_strength, breach.get("breach_quality", "weak"), level_info["type"]
                        )
                        signal_confidence = self.signal_metrics.calculate_signal_confidence(
                            candlestick_strength, level_info["type"], 
                            breach.get("breach_quality", "weak"), session_data
                        )
                        
                        opportunity = {
                            'instrument': instrument,
                            'strategy_name': strategy_name,
                            'action': 'BUY' if is_buy else 'SELL',
                            'order_type': 'LIMIT',
                            'entry_price': level_info["price"],
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'level_type': level_info["type"],
                            'candlestick_strength': candlestick_strength,
                            'breach_direction': breach["direction"],
                            'confidence': signal_confidence,
                            'momentum_strength_calculated': momentum_strength,
                            'breach_quality': breach.get("breach_quality", "weak"),
                            'reasoning': [
                                f"{candlestick_strength.title()} breach {breach['direction']} at {level_info['type']} level",
                                f"Entry at {level_info['price']:.4f}, Stop: 50 pips, Target: 500 pips",
                                f"Strategy: {strategy_name}"
                            ],
                            'expiration': 'END_OF_DAY',
                            # Analysis data for metadata creation
                            'daily_candle': daily_candle,
                            'levels_info': levels_info,
                            'session_data': session_data,
                            'current_price': current_price,
                            'is_jpy': is_jpy
                        }
                        
                        opportunities.append(opportunity)
            
        except Exception as e:
            self.logger.error(f"Error analyzing Dime Curve for {instrument}: {e}")
        
        return opportunities

class DimeCurveStrategy:
    """
    Enhanced Dime Curve Strategy with Complete Metadata Integration
    
    All Three Strategies:
    - Butter Middle: 2nd quarter from below OR 4th quarter from above
    - Dime Middle: 2nd quarter from above OR 4th quarter from below
    - Quarter Middle: Wildcard from below OR dime from above
    """
    
    def __init__(self, momentum_calculator):
        self.momentum_calc = momentum_calculator
        self.strategy_analyzer = DimeCurveStrategyAnalyzer(momentum_calculator)
        self.metadata_processor = DimeCurveMetadataProcessor()
        
        self.strategy_name = "Dime Curve Strategies"
        self.strategy_tag = "DCM"  # Dime Curve Multi-strategy
        self.logger = logging.getLogger(__name__)
    
    def analyze_dime_curve_opportunities(self, instrument: str) -> List[Dict]:
        """
        Main strategy interface method
        """
        return self.strategy_analyzer.analyze_dime_curve_opportunities(instrument)
    
    def create_airtable_metadata(self, trade_order, opportunity_data: Dict) -> TradeMetadata:
        """
        Create comprehensive metadata for Airtable integration
        Following Trading Strategy Architecture Blueprint standards
        """
        try:
            # Extract data from opportunity
            level_type = opportunity_data.get('level_type', 'unknown')
            candlestick_strength = opportunity_data.get('candlestick_strength', 'neutral')
            breach_direction = opportunity_data.get('breach_direction', 'unknown')
            session_data = opportunity_data.get('session_data', {})
            current_price = opportunity_data.get('current_price', 0)
            
            # Generate setup name
            instrument_clean = trade_order.instrument.replace('_', '/')
            strategy_short = trade_order.strategy_name.replace('Dime Curve ', '').replace(' ', '')
            strength_short = candlestick_strength.replace('_', '').title()
            
            setup_name = f"DCM_{strategy_short}_{instrument_clean}_{trade_order.action}_{level_type}_{strength_short}"
            
            # Map strategy to tag
            strategy_tag_map = {
                "Dime Curve Butter Middle": "DCButterMiddle",
                "Dime Curve Dime Middle": "DCDimeMiddle", 
                "Dime Curve Quarter Middle": "DCQuarterMiddle"
            }
            strategy_tag = strategy_tag_map.get(trade_order.strategy_name, "DCM")
            
            # Calculate signal quality metrics
            momentum_strength = opportunity_data.get('momentum_strength_calculated', 0.60)
            signal_confidence = opportunity_data.get('confidence', 70)
            
            # Process all metadata fields for Airtable using metadata processor
            momentum_direction_str = self.metadata_processor.determine_momentum_direction(
                candlestick_strength, trade_order.action
            )
            strategy_bias_str = self.metadata_processor.determine_strategy_bias(trade_order.action)
            zone_position = self.metadata_processor.determine_zone_position(
                trade_order.strategy_name, level_type, candlestick_strength, breach_direction
            )
            momentum_alignment = self.metadata_processor.calculate_momentum_alignment(
                candlestick_strength, signal_confidence
            )
            distance_to_entry_pips = self.metadata_processor.calculate_distance_to_entry(
                trade_order.entry_price, current_price, trade_order.order_type, trade_order.instrument
            )
            
            # Create comprehensive metadata object
            metadata = TradeMetadata(
                setup_name=setup_name,
                strategy_tag=strategy_tag,
                
                # Signal quality metrics (converted for Dime Curve from candlestick analysis)
                momentum_strength=momentum_strength,
                momentum_direction=candlestick_strength.upper().replace('_', '_'),  # Raw candlestick strength
                strategy_bias=trade_order.action,
                zone_position=zone_position,
                distance_to_entry_pips=distance_to_entry_pips,
                signal_confidence=signal_confidence,
                momentum_alignment=momentum_alignment,
                
                # Enhanced Airtable fields
                momentum_strength_str=self.metadata_processor.classify_momentum_strength(
                    candlestick_strength, signal_confidence
                ),
                momentum_direction_str=momentum_direction_str,
                strategy_bias_str=strategy_bias_str,
                
                # Session and market context
                session_info={
                    'current_session': session_data.get('active_sessions', ['Unknown'])[0] if session_data.get('active_sessions') else 'Unknown',
                    'liquidity_level': session_data.get('liquidity_level', 'Unknown'),
                    'level_type': level_type,
                    'breach_direction': breach_direction,
                    'candlestick_strength': candlestick_strength,
                    'market_time': datetime.now().isoformat()
                },
                
                notes=f"Dime Curve {level_type} level breach {breach_direction}: {'; '.join(trade_order.reasoning)}"
            )
            
            self.logger.info(f"📊 DCM Enhanced metadata created: {setup_name}")
            self.logger.info(f"   Strategy: {trade_order.strategy_name}")
            self.logger.info(f"   Level: {level_type} | Strength: {candlestick_strength} | Direction: {momentum_direction_str}")
            self.logger.info(f"   Bias: {strategy_bias_str} | Zone: {zone_position} | Distance: {distance_to_entry_pips} pips")
            self.logger.info(f"   Confidence: {signal_confidence}% | Alignment: {momentum_alignment}")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Error creating DCM metadata: {e}")
            # Return minimal fallback metadata
            return TradeMetadata(
                setup_name=f"DCM_{trade_order.instrument}_{trade_order.action}",
                strategy_tag="DCM",
                signal_confidence=75,
                momentum_strength=0.70,
                momentum_direction="NEUTRAL",
                strategy_bias=trade_order.action,
                zone_position="In_Buy_Zone" if trade_order.action == "BUY" else "In_Sell_Zone",
                distance_to_entry_pips=0.0,
                momentum_alignment=0.70
            )

@dataclass
class DimeCurveTradeOrder:
    """Enhanced Dime Curve trade order data class with complete metadata support"""
    # Universal fields (all strategies)
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
    
    # Dime Curve specific fields
    level_type: str  # 'dime', '2nd_quarter', 'wildcard', '4th_quarter'
    candlestick_strength: str
    breach_direction: str
    breach_quality: str
    momentum_strength_calculated: float
    
    # Standard optional fields
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    
    # Integration fields for metadata
    opportunity_data: Optional[Dict] = None

class DimeCurveIntegratedTradingBot:
    """
    Dime Curve Trading Bot with Complete Metadata Integration
    
    Following Trading Strategy Architecture Blueprint patterns
    Uses existing infrastructure with Dime Curve specific components
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Use existing infrastructure
        self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        self.momentum_calc = MarketAwareMomentumCalculator(self.api)
        
        # Initialize Dime Curve strategy
        self.strategy = DimeCurveStrategy(self.momentum_calc)
        
        # Use existing metadata storage
        self.metadata_store = TradeMetadataStore()
        self.metadata_store.cleanup_old_metadata()
        
        # Risk management (import existing risk manager)
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
        
        # Market schedule
        try:
            self.market_schedule = ForexMarketSchedule()
        except:
            self.market_schedule = None
        
        # Setup logging
        self.setup_logging()
        
        print("🎯 Dime Curve Strategies Trading Bot Initialized!")
        print(f"   All Three Strategies: Butter Middle, Dime Middle, Quarter Middle")
        print(f"   Risk: 50 pip stops, 500 pip targets")
        print(f"   Max risk per trade: ${max_risk_usd:.2f}")
        print(f"   Monitoring {len(self.instruments)} pairs: {', '.join(self.instruments)}")
    
    def setup_logging(self):
        """Setup logging following existing pattern"""
        log_dir = os.path.join(current_dir, 'trading_logs')
        os.makedirs(log_dir, exist_ok=True)
        
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(log_dir, f'dime_curve_strategies_{today}.log')
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info("Dime Curve Strategies Trading Bot started with complete metadata integration")
    
    def calculate_position_size(self, instrument: str, entry_price: float, 
                              stop_loss_price: float, confidence: int) -> int:
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
    
    def scan_for_dime_curve_opportunities(self) -> List[DimeCurveTradeOrder]:
        """Scan all instruments for Dime Curve opportunities"""
        opportunities = []
        
        self.logger.info("🔍 Scanning for Dime Curve opportunities (all three strategies)...")
        
        for instrument in self.instruments:
            try:
                # Get strategy opportunities
                strategy_opportunities = self.strategy.analyze_dime_curve_opportunities(instrument)
                
                for opp in strategy_opportunities:
                    # Calculate position size
                    position_size = self.calculate_position_size(
                        instrument, opp['entry_price'], opp['stop_loss'], opp['confidence']
                    )
                    
                    # Create trade order with all metadata
                    trade_order = DimeCurveTradeOrder(
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
                        level_type=opp['level_type'],
                        candlestick_strength=opp['candlestick_strength'],
                        breach_direction=opp['breach_direction'],
                        breach_quality=opp.get('breach_quality', 'unknown'),
                        momentum_strength_calculated=opp.get('momentum_strength_calculated', 0.70),
                        expiration=opp.get('expiration'),
                        opportunity_data=opp  # Store full opportunity for metadata creation
                    )
                    
                    opportunities.append(trade_order)
                    
                    self.logger.info(f"🎯 {instrument}: {opp['strategy_name']} {opp['action']} @ {opp['entry_price']:.4f}")
                    self.logger.info(f"   Level: {opp['level_type']} | Strength: {opp['candlestick_strength']}")
                    self.logger.info(f"   Confidence: {opp['confidence']}%")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        return opportunities
    
    def place_limit_order(self, trade_order: DimeCurveTradeOrder) -> bool:
        """Place limit order with complete metadata storage"""
        try:
            self.logger.info(f"🎯 Placing {trade_order.strategy_name} order for {trade_order.instrument}")
            
            # Create metadata BEFORE placing order
            metadata = self.strategy.create_airtable_metadata(trade_order, trade_order.opportunity_data)
            
            # Create OANDA order
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
            
            # Add expiration if specified
            if trade_order.expiration == 'END_OF_DAY':
                eod_time = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
                if datetime.now() > eod_time:
                    eod_time += timedelta(days=1)
                order_data["order"]["timeInForce"] = "GTD"
                order_data["order"]["gtdTime"] = eod_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # Add client extensions for identification
            order_data["order"]["clientExtensions"] = {
                "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                "tag": metadata.strategy_tag,
                "comment": f"Level:{trade_order.level_type}|Strength:{trade_order.candlestick_strength}|Strategy:{trade_order.strategy_name.replace(' ', '')}|Confidence:{trade_order.confidence}%"[:500]
            }
            
            # Place order
            response = self.api.place_order(order_data)
            
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                
                # Store metadata with order ID
                self.metadata_store.store_order_metadata(order_id, metadata)
                
                trade_order.order_id = order_id
                trade_order.status = 'PLACED'
                self.pending_orders.append(trade_order)
                
                self.logger.info(f"✅ Order placed successfully: {order_id}")
                self.logger.info(f"📝 Setup: {metadata.setup_name}")
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
        print("DIME CURVE STRATEGIES - ALL THREE WITH COMPLETE METADATA INTEGRATION")
        print("="*80)
        print("🧈 Butter Middle: 2nd quarter from below OR 4th quarter from above")
        print("🎯 Dime Middle: 2nd quarter from above OR 4th quarter from below")
        print("🔲 Quarter Middle: Wildcard from below OR dime from above")
        print("📊 Signal Quality: Candlestick strength converted to momentum metrics")
        print("🔗 Integration: Complete metadata storage for Airtable sync")
        print("="*80)
        
        for instrument in self.instruments:
            print(f"\n🔍 ANALYZING {instrument}:")
            print("-" * 50)
            
            try:
                # Get strategy opportunities
                opportunities = self.strategy.analyze_dime_curve_opportunities(instrument)
                
                if opportunities:
                    for opp in opportunities:
                        print(f"Current Price: {opp.get('current_price', 0):.4f}")
                        print(f"Currency Type: {'JPY Pair' if opp.get('is_jpy', False) else 'Standard Pair'}")
                        
                        # Show candlestick analysis
                        candle = opp.get('daily_candle', {})
                        if candle and 'open' in candle:
                            print(f"Daily Candle: O:{candle['open']:.4f} H:{candle['high']:.4f} L:{candle['low']:.4f} C:{candle['close']:.4f}")
                            print(f"Candlestick Strength: {opp['candlestick_strength']}")
                        
                        # Show opportunity details
                        print(f"\n🎯 {opp['strategy_name'].upper()}:")
                        print(f"  {opp['action']} {opp['order_type']} @ {opp['entry_price']:.4f}")
                        print(f"  Level: {opp['level_type']} | Breach: {opp['breach_direction']}")
                        print(f"  Stop: {opp['stop_loss']:.4f} (50 pips) | Target: {opp['take_profit']:.4f} (500 pips)")
                        print(f"  Confidence: {opp['confidence']}% | Momentum: {opp.get('momentum_strength_calculated', 0):.3f}")
                        print(f"  Quality: {opp.get('breach_quality', 'unknown')} breach")
                else:
                    # Still show analysis for educational purposes
                    print(f"Current Price: [Getting price...]")
                    print(f"⏰ No opportunities found")
                
            except Exception as e:
                print(f"❌ Error analyzing {instrument}: {e}")
        
        print("\n" + "="*80)
        print("✅ Dime Curve Strategies Analysis Complete!")
        print("🎯 All three strategies working with unified level detection")
        print("📊 Candlestick analysis converted to momentum metrics for Airtable")
        print("📝 Complete metadata integration ready for sync_all.py")
        print("="*80)
    
    def run_single_scan(self):
        """Run a single scan for Dime Curve opportunities"""
        print("🔍 Running Dime Curve strategies scan...")
        
        opportunities = self.scan_for_dime_curve_opportunities()
        
        if opportunities:
            print(f"\n🎯 Found {len(opportunities)} Dime Curve opportunities:")
            for opp in opportunities:
                print(f"  {opp.instrument}: {opp.strategy_name}")
                print(f"    {opp.action} LIMIT @ {opp.entry_price:.4f}")
                print(f"    Stop: {opp.stop_loss:.4f} | Target: {opp.take_profit:.4f}")
                print(f"    Level: {opp.level_type} | Strength: {opp.candlestick_strength}")
                print(f"    Confidence: {opp.confidence}% | Momentum: {opp.momentum_strength_calculated:.3f}")
                print()
        else:
            print("⏰ No Dime Curve opportunities found at this time")
        
        return opportunities

def main():
    """Main function for Dime Curve Strategies system"""
    print("🎯 Dime Curve Strategies Trading System")
    print("="*60)
    print("🧈 Butter Middle | 🎯 Dime Middle | 🔲 Quarter Middle")
    print("📊 Complete metadata integration for Airtable sync")
    print("🔗 Using existing infrastructure with enhanced signal quality")
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
    bot = DimeCurveIntegratedTradingBot(max_risk_usd=max_risk_usd, max_open_trades=5)
    
    # Mode selection
    print("\nSelect Mode:")
    print("1. Analysis Demo (Show all strategies with complete analysis)")
    print("2. Single Scan (Check for Dime Curve opportunities)")
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
                print("✅ Dime Curve orders placed!")
            else:
                print("Orders not placed.")
        else:
            print("No opportunities to execute.")
    else:
        print("Invalid choice. Running analysis demo...")
        bot.run_analysis_demo()

if __name__ == "__main__":
    main()