# Dime Curve Butter Strategy - Quarter Value Trading
# Targets quarter transitions: X.X250 -> X.X750 (BUY) | X.X750 -> X.X250 (SELL)
# Fixed: 50 pip stops, 500 pip targets (2 quarters distance)

import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Set
import traceback
from dataclasses import dataclass

# Handle optional dependencies
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    print("⚠️ Warning: 'schedule' module not found. Install with: pip install schedule")
    SCHEDULE_AVAILABLE = False

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    print("⚠️ Warning: 'pytz' module not found. Install with: pip install pytz")
    PYTZ_AVAILABLE = False

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import existing classes
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

class QuarterLevelsDetector:
    """
    Quarter Values Detector for Dime Curve Butter Strategy
    
    Targets quarter institutional levels:
    - Non-JPY: X.X000, X.X250, X.X500, X.X750 (like 1.2000, 1.2250, 1.2500, 1.2750)
    - JPY: XX0.00, XX2.50, XX5.00, XX7.50 (like 120.00, 122.50, 125.00, 127.50)
    
    Strategy: Trade from X.X250 to X.X750 (long) or X.X750 to X.X250 (short)
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def is_jpy_pair(self, instrument: str) -> bool:
        """Check if instrument is a JPY pair"""
        return 'JPY' in instrument
    
    def get_quarter_levels(self, price: float, is_jpy: bool = False) -> List[float]:
        """
        Get all quarter levels around current price
        
        Returns sorted list of quarter levels
        """
        levels = []
        
        if is_jpy:
            # JPY Quarters: XX0.00, XX2.50, XX5.00, XX7.50
            # Get the base (tens place)
            base_tens = int(price / 10) * 10
            quarter_increments = [0.00, 2.50, 5.00, 7.50]
            
            # Generate levels for multiple ranges
            for base in [base_tens - 10, base_tens, base_tens + 10, base_tens + 20]:
                if base >= 0:
                    for increment in quarter_increments:
                        level = base + increment
                        levels.append(level)
        else:
            # Non-JPY Quarters: X.X000, X.X250, X.X500, X.X750
            # Get the base (hundredths place)
            base_hundredths = int(price * 100) / 100
            quarter_increments = [0.0000, 0.0250, 0.0500, 0.0750]
            
            # Generate levels for multiple ranges
            for cent_offset in [-0.02, -0.01, 0, 0.01, 0.02]:
                base = base_hundredths + cent_offset
                if base > 0:
                    for increment in quarter_increments:
                        level = base + increment
                        levels.append(round(level, 4))
        
        # Sort and remove duplicates
        levels = sorted(list(set(levels)))
        return levels
    
    def find_target_quarter_levels(self, price: float, is_jpy: bool = False) -> Dict:
        """
        Find the specific quarter levels for trading setups
        
        Returns:
        - closest_250_below: Closest X.X250 level below price
        - closest_750_below: Closest X.X750 level below price  
        - closest_250_above: Closest X.X250 level above price
        - closest_750_above: Closest X.X750 level above price
        """
        all_levels = self.get_quarter_levels(price, is_jpy)
        
        if is_jpy:
            # For JPY: look for XX2.50 and XX7.50
            levels_250 = [level for level in all_levels if abs(level % 10 - 2.50) < 0.01]
            levels_750 = [level for level in all_levels if abs(level % 10 - 7.50) < 0.01]
        else:
            # For Non-JPY: look for X.X250 and X.X750
            levels_250 = [level for level in all_levels if abs((level * 10000) % 1000 - 250) < 1]
            levels_750 = [level for level in all_levels if abs((level * 10000) % 1000 - 750) < 1]
        
        # Find closest levels above and below current price
        levels_250_below = [level for level in levels_250 if level < price]
        levels_250_above = [level for level in levels_250 if level > price]
        levels_750_below = [level for level in levels_750 if level < price]
        levels_750_above = [level for level in levels_750 if level > price]
        
        result = {
            'closest_250_below': max(levels_250_below) if levels_250_below else None,
            'closest_750_below': max(levels_750_below) if levels_750_below else None,
            'closest_250_above': min(levels_250_above) if levels_250_above else None,
            'closest_750_above': min(levels_750_above) if levels_750_above else None,
            'all_250_levels': levels_250,
            'all_750_levels': levels_750
        }
        
        return result
    
    def calculate_pip_distance(self, price1: float, price2: float, is_jpy: bool = False) -> float:
        """Calculate distance between two prices in pips"""
        pip_value = 0.01 if is_jpy else 0.0001
        return abs(price1 - price2) / pip_value
    
    def get_stop_and_target(self, entry_price: float, is_buy: bool, is_jpy: bool = False) -> Tuple[float, float]:
        """
        Calculate stop loss and take profit
        
        Fixed distances:
        - Stop loss: 50 pips from entry
        - Take profit: 500 pips from entry (2 quarters away)
        """
        pip_value = 0.01 if is_jpy else 0.0001
        
        if is_buy:
            stop_loss = entry_price - (50 * pip_value)
            take_profit = entry_price + (500 * pip_value)
        else:  # sell
            stop_loss = entry_price + (50 * pip_value)
            take_profit = entry_price - (500 * pip_value)
        
        return stop_loss, take_profit

class DailyCandlestickAnalyzer:
    """
    Daily Candlestick Pattern Analyzer for Dime Curve Butter Strategy
    
    Analyzes daily candlestick strength based on close position within range:
    - Very Bullish: Close >= 80% of range from low
    - Bullish: Close >= 60% but < 80% of range from low
    - Neutral: Close >= 40% but < 60% of range from low
    - Bearish: Close >= 20% but < 40% of range from low
    - Very Bearish: Close < 20% of range from low
    """
    
    def __init__(self, api):
        self.api = api
        self.logger = logging.getLogger(__name__)
    
    def get_daily_candlestick(self, instrument: str) -> Dict:
        """Get the most recent completed daily candlestick"""
        try:
            # Get daily candles - last 2 to ensure we have a completed candle
            candles = self.api.get_candles(instrument, granularity='D', count=2)
            
            if not candles or 'candles' not in candles or len(candles['candles']) < 1:
                return {'error': 'Unable to get daily candles'}
            
            # Get the most recent completed candle (not the current forming one)
            last_candle = candles['candles'][-2] if len(candles['candles']) >= 2 else candles['candles'][-1]
            
            if not last_candle.get('complete', False):
                # If the last candle isn't complete, use the previous one
                if len(candles['candles']) >= 2:
                    last_candle = candles['candles'][-2]
                else:
                    return {'error': 'No completed daily candle available'}
            
            # Extract OHLC data
            mid_data = last_candle['mid']
            open_price = float(mid_data['o'])
            high_price = float(mid_data['h'])
            low_price = float(mid_data['l'])
            close_price = float(mid_data['c'])
            
            return {
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'time': last_candle['time'],
                'complete': last_candle.get('complete', False)
            }
            
        except Exception as e:
            self.logger.error(f"Error getting daily candlestick for {instrument}: {e}")
            return {'error': str(e)}
    
    def analyze_candlestick_strength(self, candle_data: Dict) -> Dict:
        """
        Analyze the strength and bias of a daily candlestick
        
        Returns:
            Dict with strength, bias, and analysis details
        """
        if 'error' in candle_data:
            return candle_data
        
        open_price = candle_data['open']
        high_price = candle_data['high']
        low_price = candle_data['low']
        close_price = candle_data['close']
        
        # Calculate range and close position within range
        range_size = high_price - low_price
        
        if range_size == 0:
            return {
                'strength': 'NEUTRAL',
                'bias': 'NEUTRAL',
                'close_position_percent': 50.0,
                'range_size': 0,
                'body_size': abs(close_price - open_price),
                'analysis': 'Doji candle - no range'
            }
        
        # Calculate where close is within the range (0% = at low, 100% = at high)
        close_position_percent = ((close_price - low_price) / range_size) * 100
        
        # Determine candlestick strength based on close position
        if close_position_percent >= 80:
            strength = 'VERY_BULLISH'
            bias = 'BULLISH'
        elif close_position_percent >= 60:
            strength = 'BULLISH'
            bias = 'BULLISH'
        elif close_position_percent >= 40:
            strength = 'NEUTRAL'
            bias = 'NEUTRAL'
        elif close_position_percent >= 20:
            strength = 'BEARISH'
            bias = 'BEARISH'
        else:
            strength = 'VERY_BEARISH'
            bias = 'BEARISH'
        
        # Additional analysis
        body_size = abs(close_price - open_price)
        body_percent = (body_size / range_size) * 100 if range_size > 0 else 0
        
        analysis_details = f"Close at {close_position_percent:.1f}% of range, Body: {body_percent:.1f}% of range"
        
        return {
            'strength': strength,
            'bias': bias,
            'close_position_percent': close_position_percent,
            'range_size': range_size,
            'body_size': body_size,
            'body_percent': body_percent,
            'candle_data': candle_data,
            'analysis': analysis_details
        }

class DimeCurveButterStrategy:
    """
    Enhanced Dime Curve Butter Strategy - Quarter Value Transitions with Daily Candlestick Analysis
    
    Trading Rules:
    1. Daily Bullish/Very Bullish candle crosses ABOVE X.X250 (Non-JPY) or XX2.50 (JPY) → BUY limit at quarter level
    2. Daily Bearish/Very Bearish candle crosses BELOW X.X750 (Non-JPY) or XX7.50 (JPY) → SELL limit at quarter level
    3. Entry: Limit order at the crossed quarter level
    4. Fixed stops: 50 pips | Fixed targets: 500 pips
    """
    
    def __init__(self, momentum_calculator, quarter_detector: QuarterLevelsDetector):
        self.momentum_calc = momentum_calculator
        self.quarter_detector = quarter_detector
        self.candlestick_analyzer = DailyCandlestickAnalyzer(momentum_calculator.api)
        self.logger = logging.getLogger(__name__)
        
        # Track previous price to detect level breaks
        self.previous_prices = {}
    
    def analyze_dime_curve_butter_setup(self, instrument: str) -> Dict:
        """
        Analyze instrument for Dime Curve Butter trading opportunities
        
        Enhanced Strategy Logic:
        - BUY: Daily Bullish/Very Bullish candle crosses ABOVE X.X250 → Limit BUY at X.X250
        - SELL: Daily Bearish/Very Bearish candle crosses BELOW X.X750 → Limit SELL at X.X750
        
        Returns:
            Dict containing signals, analysis, and metadata
        """
        try:
            # Get current price
            price_data = self.momentum_calc.api.get_current_prices([instrument])
            if not price_data or 'prices' not in price_data:
                return {'error': 'Unable to get current price'}
            
            current_price = float(price_data['prices'][0]['closeoutBid'])
            is_jpy = self.quarter_detector.is_jpy_pair(instrument)
            
            # Get previous price for this instrument
            previous_price = self.previous_prices.get(instrument, current_price)
            
            # Get quarter levels analysis
            quarter_levels = self.quarter_detector.find_target_quarter_levels(current_price, is_jpy)
            
            # Get daily candlestick analysis
            daily_candle = self.candlestick_analyzer.get_daily_candlestick(instrument)
            if 'error' in daily_candle:
                return {'error': f'Daily candlestick analysis failed: {daily_candle["error"]}'}
            
            candlestick_analysis = self.candlestick_analyzer.analyze_candlestick_strength(daily_candle)
            if 'error' in candlestick_analysis:
                return {'error': f'Candlestick strength analysis failed: {candlestick_analysis["error"]}'}
            
            # Set momentum analysis to None (this strategy doesn't use momentum)
            momentum_analysis = {
                'momentum_strength': None,
                'direction': None,
                'strategy_bias': None,
                'alignment': None
            }
            
            # Update previous price
            self.previous_prices[instrument] = current_price
            
            # Analyze for trading setups using daily candlestick confirmation
            signals = self._analyze_quarter_crosses_with_candlesticks(
                instrument, current_price, quarter_levels, candlestick_analysis, momentum_analysis, is_jpy
            )
            
            # Prepare analysis data for metadata
            analysis_data = {
                'current_price': current_price,
                'quarter_levels': quarter_levels,
                'is_jpy': is_jpy,
                'momentum_analysis': momentum_analysis,
                'candlestick_analysis': candlestick_analysis,
                'daily_candle': daily_candle
            }
            
            return {
                'signals': signals,
                'analysis_data': analysis_data,
                'momentum_analysis': momentum_analysis,
                'zone_data': {
                    'current_price': current_price,
                    'is_jpy': is_jpy,
                    'quarter_levels': quarter_levels,
                    'candlestick_analysis': candlestick_analysis
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error in Dime Curve Butter analysis for {instrument}: {e}")
            return {'error': str(e)}
    
    def _analyze_quarter_crosses_with_candlesticks(self, instrument: str, current_price: float,
                                                 quarter_levels: Dict, candlestick_analysis: Dict, 
                                                 momentum_analysis: Dict, is_jpy: bool) -> Dict:
        """
        Analyze for quarter level crosses confirmed by daily candlestick patterns
        
        Enhanced Dime Curve Butter Logic:
        - BUY: Daily Bullish/Very Bullish candle crosses ABOVE X.X250 level
        - SELL: Daily Bearish/Very Bearish candle crosses BELOW X.X750 level
        """
        reasoning = []
        
        # Extract candlestick data
        candle_strength = candlestick_analysis.get('strength', 'NEUTRAL')
        candle_bias = candlestick_analysis.get('bias', 'NEUTRAL')
        close_position_percent = candlestick_analysis.get('close_position_percent', 50)
        daily_candle = candlestick_analysis.get('candle_data', {})
        
        daily_open = daily_candle.get('open', current_price)
        daily_high = daily_candle.get('high', current_price)
        daily_low = daily_candle.get('low', current_price)
        daily_close = daily_candle.get('close', current_price)
        
        # Confidence calculation based purely on candlestick strength and setup quality
        # Base confidence for having a valid setup
        base_confidence = 70  # Base for any valid quarter cross + candlestick setup
        
        # Candlestick strength bonus (primary and only signal source)
        if candle_strength in ['VERY_BULLISH', 'VERY_BEARISH']:
            candlestick_bonus = 25  # Very strong directional candle
        elif candle_strength in ['BULLISH', 'BEARISH']:
            candlestick_bonus = 15  # Good directional candle
        else:
            candlestick_bonus = 0   # Should not happen in this strategy
        
        # Close position bonus (how strong the rejection/acceptance was)
        if candle_strength in ['VERY_BULLISH', 'VERY_BEARISH']:
            # Very strong candles already have extreme close positions, no additional bonus needed
            close_position_bonus = 0
        elif candle_strength in ['BULLISH', 'BEARISH']:
            # For regular bullish/bearish, reward stronger close positions
            if (candle_strength == 'BULLISH' and close_position_percent >= 70) or \
               (candle_strength == 'BEARISH' and close_position_percent <= 30):
                close_position_bonus = 5
            else:
                close_position_bonus = 0
        else:
            close_position_bonus = 0
        
        # Calculate final confidence
        final_confidence = base_confidence + candlestick_bonus + close_position_bonus
        
        # Cap at 95% (never 100% certain in trading)
        final_confidence = min(95, final_confidence)
        
        reasoning.append(f"Daily candlestick: {candle_strength} (close at {close_position_percent:.1f}% of range)")
        reasoning.append(f"Current price: {current_price:.4f}")
        reasoning.append(f"Confidence calculation: Base(70) + Candlestick({candlestick_bonus}) + ClosePosition({close_position_bonus}) = {final_confidence}%")
        
        # Get quarter levels
        closest_250_below = quarter_levels.get('closest_250_below')
        closest_250_above = quarter_levels.get('closest_250_above') 
        closest_750_below = quarter_levels.get('closest_750_below')
        closest_750_above = quarter_levels.get('closest_750_above')
        
        # BUY Setup: Daily Bullish/Very Bullish candle crosses ABOVE X.X250 level
        if candle_strength in ['BULLISH', 'VERY_BULLISH']:
            # Check if candle crossed above any X.X250 level
            crossed_250_levels = []
            
            for level_250 in [closest_250_below, closest_250_above]:
                if level_250:
                    # Check if daily candle crossed above this X.X250 level
                    if (daily_low <= level_250 <= daily_high and daily_close > level_250):
                        crossed_250_levels.append(level_250)
            
            if crossed_250_levels:
                # Use the highest crossed X.X250 level for entry
                entry_level = max(crossed_250_levels)
                
                # Find target X.X750 level
                target_750 = None
                if closest_750_above and closest_750_above > entry_level:
                    target_750 = closest_750_above
                elif closest_750_below and closest_750_below > entry_level:
                    target_750 = closest_750_below
                
                if target_750:
                    # Validate distance (should be ~500 pips)
                    distance_pips = self.quarter_detector.calculate_pip_distance(entry_level, target_750, is_jpy)
                    
                    if 450 <= distance_pips <= 550:
                        stop_loss, take_profit = self.quarter_detector.get_stop_and_target(entry_level, True, is_jpy)
                        
                        confidence = min(95, final_confidence)
                        
                        reasoning.append(f"{candle_strength} candle crossed ABOVE X.X250 level: {entry_level:.4f}")
                        reasoning.append(f"Target X.X750 level: {target_750:.4f} ({distance_pips:.0f} pips)")
                        reasoning.append("Setting BUY limit at crossed X.X250 level")
                        
                        return {
                            'action': 'BUY',
                            'order_type': 'LIMIT',
                            'entry_price': entry_level,
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'confidence': confidence,
                            'reasoning': reasoning,
                            'expiration': 'END_OF_DAY',
                            'setup_type': f'QUARTER_250_CROSS_BUY_{candle_strength}'
                        }
        
        # SELL Setup: Daily Bearish/Very Bearish candle crosses BELOW X.X750 level
        if candle_strength in ['BEARISH', 'VERY_BEARISH']:
            # Check if candle crossed below any X.X750 level
            crossed_750_levels = []
            
            for level_750 in [closest_750_below, closest_750_above]:
                if level_750:
                    # Check if daily candle crossed below this X.X750 level
                    if (daily_low <= level_750 <= daily_high and daily_close < level_750):
                        crossed_750_levels.append(level_750)
            
            if crossed_750_levels:
                # Use the lowest crossed X.X750 level for entry
                entry_level = min(crossed_750_levels)
                
                # Find target X.X250 level
                target_250 = None
                if closest_250_below and closest_250_below < entry_level:
                    target_250 = closest_250_below
                elif closest_250_above and closest_250_above < entry_level:
                    target_250 = closest_250_above
                
                if target_250:
                    # Validate distance (should be ~500 pips)
                    distance_pips = self.quarter_detector.calculate_pip_distance(entry_level, target_250, is_jpy)
                    
                    if 450 <= distance_pips <= 550:
                        stop_loss, take_profit = self.quarter_detector.get_stop_and_target(entry_level, False, is_jpy)
                        
                        confidence = min(95, final_confidence)
                        
                        reasoning.append(f"{candle_strength} candle crossed BELOW X.X750 level: {entry_level:.4f}")
                        reasoning.append(f"Target X.X250 level: {target_250:.4f} ({distance_pips:.0f} pips)")
                        reasoning.append("Setting SELL limit at crossed X.X750 level")
                        
                        return {
                            'action': 'SELL',
                            'order_type': 'LIMIT',
                            'entry_price': entry_level,
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'confidence': confidence,
                            'reasoning': reasoning,
                            'expiration': 'END_OF_DAY',
                            'setup_type': f'QUARTER_750_CROSS_SELL_{candle_strength}'
                        }
        
        # Check for monitoring opportunities
        monitoring_info = []
        
        if candle_strength in ['BULLISH', 'VERY_BULLISH']:
            for level_250 in [closest_250_below, closest_250_above]:
                if level_250:
                    distance_pips = self.quarter_detector.calculate_pip_distance(current_price, level_250, is_jpy)
                    if distance_pips <= 30:
                        monitoring_info.append(f"Watching X.X250 level at {level_250:.4f} ({distance_pips:.1f} pips) with {candle_strength} candle")
        
        if candle_strength in ['BEARISH', 'VERY_BEARISH']:
            for level_750 in [closest_750_below, closest_750_above]:
                if level_750:
                    distance_pips = self.quarter_detector.calculate_pip_distance(current_price, level_750, is_jpy)
                    if distance_pips <= 30:
                        monitoring_info.append(f"Watching X.X750 level at {level_750:.4f} ({distance_pips:.1f} pips) with {candle_strength} candle")
        
        if monitoring_info:
            reasoning.extend(monitoring_info)
        else:
            reasoning.append(f"No quarter level crosses detected with {candle_strength} candlestick")
        
        return {
            'action': 'WAIT',
            'confidence': base_confidence,
            'reasoning': reasoning
        }

@dataclass
class DimeCurveButterTradeOrder:
    """Data class for Dime Curve Butter trade orders"""
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
    setup_type: str  # 'QUARTER_250_CROSS_BUY_BULLISH' or 'QUARTER_750_CROSS_SELL_BEARISH' etc.
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    # Metadata fields
    momentum_analysis: Optional[Dict] = None
    zone_data: Optional[Dict] = None
    analysis_data: Optional[Dict] = None

class DimeCurveButterTradingBot:
    """
    Enhanced Dime Curve Butter Trading Bot
    
    Automated trading system for quarter value crosses confirmed by daily candlesticks:
    - BUY: Daily Bullish/Very Bullish candle crosses ABOVE X.X250 → Limit BUY at X.X250
    - SELL: Daily Bearish/Very Bearish candle crosses BELOW X.X750 → Limit SELL at X.X750
    - Fixed 50 pip stops, 500 pip targets
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Initialize components
        self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        self.momentum_calc = MarketAwareMomentumCalculator(self.api)
        self.quarter_detector = QuarterLevelsDetector()
        self.strategy = DimeCurveButterStrategy(self.momentum_calc, self.quarter_detector)
        
        # Risk management
        from Demo_Trading_Penny_Curve_Strategy import FixedDollarRiskManager
        self.risk_manager = FixedDollarRiskManager(self.api, max_risk_usd)
        self.max_risk_usd = max_risk_usd
        self.max_open_trades = max_open_trades
        
        # Metadata storage
        self.metadata_store = TradeMetadataStore()
        self.metadata_store.cleanup_old_metadata()
        
        # Trading instruments
        self.instruments = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD']
        
        # Trade tracking
        self.pending_orders = []
        self.open_positions = []
        self.trade_history = []
        
        # Market schedule
        self.market_schedule = ForexMarketSchedule()
        
        # Logging
        self.setup_logging()
        
        print("🧈 Dime Curve Butter Trading Bot Initialized!")
        print(f"   Strategy: Quarter Level Crosses + Daily Candlestick Confirmation")
        print(f"   BUY: Bullish candle crosses ABOVE X.X250 | SELL: Bearish candle crosses BELOW X.X750")
        print(f"   Max risk per trade: ${self.max_risk_usd:.2f} USD")
        print(f"   Fixed stops: 50 pips | Fixed targets: 500 pips")
        print(f"   Monitoring: {', '.join(self.instruments)}")
    
    def setup_logging(self):
        """Setup logging for Dime Curve Butter strategy"""
        log_dir = os.path.join(current_dir, 'trading_logs')
        os.makedirs(log_dir, exist_ok=True)
        
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(log_dir, f'dime_curve_butter_{today}.log')
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info("Dime Curve Butter Trading Bot started")
    
    def get_quarter_level_type(self, trade_order: DimeCurveButterTradeOrder) -> str:
        """Extract quarter level type from setup type"""
        if 'QUARTER_250' in trade_order.setup_type:
            return "X.X250"
        elif 'QUARTER_750' in trade_order.setup_type:
            return "X.X750"
        else:
            return "Unknown"
    
    def get_candlestick_strength(self, trade_order: DimeCurveButterTradeOrder) -> str:
        """Extract candlestick strength from setup type"""
        if 'VERY_BULLISH' in trade_order.setup_type:
            return "VERY_BULLISH"
        elif 'VERY_BEARISH' in trade_order.setup_type:
            return "VERY_BEARISH"
        elif 'BULLISH' in trade_order.setup_type:
            return "BULLISH"
        elif 'BEARISH' in trade_order.setup_type:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def create_zone_position_value(self, trade_order: DimeCurveButterTradeOrder) -> str:
        """
        Create zone position value that matches Airtable's predefined options exactly
        
        Based on the Airtable options, we need to match:
        - QUARTER_750_CROSS_SELL_VERY_BEARISH
        - QUARTER_750_CROSS_SELL_BEARISH  
        - QUARTER_250_CROSS_BUY_VERY_BULLISH
        - QUARTER_250_CROSS_BUY_BULLISH
        """
        quarter_level_type = self.get_quarter_level_type(trade_order)
        candlestick_strength = self.get_candlestick_strength(trade_order)
        action = trade_order.action
        
        # Map to match Airtable's predefined options exactly
        if quarter_level_type == "X.X750" and action == "SELL":
            if candlestick_strength == "VERY_BEARISH":
                return "QUARTER_750_CROSS_SELL_VERY_BEARISH"
            elif candlestick_strength == "BEARISH":
                return "QUARTER_750_CROSS_SELL_BEARISH"
        elif quarter_level_type == "X.X250" and action == "BUY":
            if candlestick_strength == "VERY_BULLISH":
                return "QUARTER_250_CROSS_BUY_VERY_BULLISH"
            elif candlestick_strength == "BULLISH":
                return "QUARTER_250_CROSS_BUY_BULLISH"
        
        # Fallback to existing option that's safe
        return "Below_Sell_Zone"
    
    def create_dime_curve_butter_setup_name(self, trade_order: DimeCurveButterTradeOrder, momentum_analysis: Dict) -> str:
        """Create descriptive setup name for Dime Curve Butter trades"""
        instrument = trade_order.instrument.replace('_', '/')
        setup_type = trade_order.setup_type
        action = trade_order.action
        
        # Since we don't use momentum, just use a simple strength label based on candlestick
        candlestick_strength = self.get_candlestick_strength(trade_order)
        if candlestick_strength in ['VERY_BULLISH', 'VERY_BEARISH']:
            strength_label = "VeryStrong"
        elif candlestick_strength in ['BULLISH', 'BEARISH']:
            strength_label = "Strong"
        else:
            strength_label = "Standard"
        
        setup_name = f"DimeCurveButter_{instrument}_{setup_type}_{action}_{strength_label}"
        return setup_name
    
    def create_dime_curve_butter_metadata(self, trade_order: DimeCurveButterTradeOrder, momentum_analysis: Dict) -> TradeMetadata:
        """Create enhanced metadata for Dime Curve Butter trades optimized for Airtable logging with proper field validation"""
        try:
            setup_name = self.create_dime_curve_butter_setup_name(trade_order, momentum_analysis)
            
            # Create zone position that matches Airtable's valid options
            zone_position = self.create_zone_position_value(trade_order)
            
            # Create enhanced metadata optimized for Airtable with proper field validation
            metadata = TradeMetadata(
                setup_name=setup_name,
                strategy_tag="DimeCurveButter",
                # Set momentum fields to None (this strategy doesn't use momentum analysis)
                momentum_strength=None,
                momentum_direction=None,
                strategy_bias=None,
                momentum_alignment=None,
                # Enhanced fields specific to this strategy with proper validation
                zone_position=zone_position,  # Use mapped Airtable-valid value
                distance_to_entry_pips=0.0,  # Always 0.0 for limit orders at exact levels (float type)
                signal_confidence=trade_order.confidence
            )
            
            quarter_level_type = self.get_quarter_level_type(trade_order)
            candlestick_strength = self.get_candlestick_strength(trade_order)
            
            self.logger.info(f"🧈 Dime Curve Butter Setup: {setup_name}")
            self.logger.info(f"   Quarter Level: {quarter_level_type} | Candlestick: {candlestick_strength}")
            self.logger.info(f"   Trade Direction: {trade_order.action} | Confidence: {trade_order.confidence}%")
            self.logger.info(f"   Entry: {trade_order.entry_price:.4f} | Stop: {trade_order.stop_loss:.4f} | Target: {trade_order.take_profit:.4f}")
            
            # Log metadata values with Airtable compatibility info
            self.logger.info(f"   📊 Metadata: Momentum fields set to None (strategy doesn't use momentum)")
            self.logger.info(f"   📊 Zone Position: {metadata.zone_position} (mapped to valid Airtable option)")
            self.logger.info(f"   📊 Distance to Entry: {metadata.distance_to_entry_pips} pips (float type)")
            self.logger.info(f"   📊 Signal Confidence: {metadata.signal_confidence}%")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Error creating Dime Curve Butter metadata: {e}")
            # Return fallback with all momentum fields as None and safe zone position
            return TradeMetadata(
                setup_name=f"DimeCurveButter_{trade_order.instrument}_{trade_order.action}",
                strategy_tag="DimeCurveButter",
                signal_confidence=trade_order.confidence,
                # Set momentum fields to None for fallback too
                momentum_strength=None,
                momentum_direction=None,
                strategy_bias=None,
                momentum_alignment=None,
                zone_position="Below_Sell_Zone",  # Safe fallback that exists in Airtable
                distance_to_entry_pips=0.0  # Proper float type
            )
    
    def scan_for_dime_curve_butter_opportunities(self) -> List[DimeCurveButterTradeOrder]:
        """Scan for Dime Curve Butter quarter level transition opportunities"""
        opportunities = []
        
        self.logger.info("🔍 Scanning for Dime Curve Butter quarter level crosses with daily candlestick confirmation...")
        
        for instrument in self.instruments:
            try:
                # Analyze for Dime Curve Butter setups
                analysis = self.strategy.analyze_dime_curve_butter_setup(instrument)
                
                if 'error' in analysis:
                    self.logger.warning(f"❌ {instrument}: {analysis['error']}")
                    continue
                
                signals = analysis['signals']
                
                if signals['action'] != 'WAIT':
                    # Calculate position size
                    position_size = self.calculate_position_size(
                        instrument, signals['entry_price'], signals['stop_loss'], signals['confidence']
                    )
                    
                    # Create Dime Curve Butter trade order
                    trade_order = DimeCurveButterTradeOrder(
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
                        setup_type=signals['setup_type'],
                        expiration=signals.get('expiration'),
                        momentum_analysis=analysis.get('momentum_analysis', {}),
                        zone_data=analysis.get('zone_data', {}),
                        analysis_data=analysis.get('analysis_data', {})
                    )
                    
                    opportunities.append(trade_order)
                    
                    self.logger.info(f"🧈 {instrument}: {signals['setup_type']} {signals['action']} LIMIT "
                                   f"@ {signals['entry_price']:.4f} (Conf: {signals['confidence']}%)")
                    self.logger.info(f"   Stop: {signals['stop_loss']:.4f} (-50 pips) | Target: {signals['take_profit']:.4f} (+500 pips)")
                else:
                    # Log current monitoring status with candlestick info
                    analysis_data = analysis.get('analysis_data', {})
                    quarter_levels = analysis_data.get('quarter_levels', {})
                    candlestick_analysis = analysis_data.get('candlestick_analysis', {})
                    current_price = analysis_data.get('current_price', 0)
                    
                    candle_strength = candlestick_analysis.get('strength', 'UNKNOWN')
                    
                    if quarter_levels.get('closest_250_below') or quarter_levels.get('closest_750_below'):
                        self.logger.debug(f"📊 {instrument}: Monitoring @ {current_price:.4f} "
                                        f"(Daily: {candle_strength})")
                        if quarter_levels.get('closest_250_below'):
                            distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_250_below'], self.quarter_detector.is_jpy_pair(instrument))
                            self.logger.debug(f"   X.X250: {quarter_levels['closest_250_below']:.4f} ({distance:.1f} pips)")
                        if quarter_levels.get('closest_750_below'):
                            distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_750_below'], self.quarter_detector.is_jpy_pair(instrument))
                            self.logger.debug(f"   X.X750: {quarter_levels['closest_750_below']:.4f} ({distance:.1f} pips)")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        return opportunities
    
    def calculate_position_size(self, instrument: str, entry_price: float, stop_loss_price: float, confidence: int) -> int:
        """Calculate position size using risk manager"""
        try:
            result = self.risk_manager.calculate_position_size(
                instrument, entry_price, stop_loss_price, confidence
            )
            
            if 'error' in result:
                self.logger.error(f"Position sizing error for {instrument}: {result['error']}")
                return 1000
            
            return result['position_size']
            
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 1000
    
    def place_dime_curve_butter_limit_order(self, trade_order: DimeCurveButterTradeOrder) -> bool:
        """Place limit order for Dime Curve Butter setup with proper metadata handling"""
        try:
            self.logger.info(f"🧈 Placing Dime Curve Butter LIMIT {trade_order.action} for {trade_order.instrument} @ {trade_order.entry_price:.4f}")
            
            # Create and store metadata with proper field validation
            momentum_analysis = getattr(trade_order, 'momentum_analysis', {})
            metadata = self.create_dime_curve_butter_metadata(trade_order, momentum_analysis)
            
            # Create order payload
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
            
            # Add expiration
            if trade_order.expiration == 'END_OF_DAY':
                eod_time = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
                if datetime.now() > eod_time:
                    eod_time += timedelta(days=1)
                order_data["order"]["timeInForce"] = "GTD"
                order_data["order"]["gtdTime"] = eod_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # Add client extensions for tracking (Note: These may not be reliably stored by Oanda)
            quarter_level_type = self.get_quarter_level_type(trade_order)
            candlestick_strength = self.get_candlestick_strength(trade_order)
            zone_position = self.create_zone_position_value(trade_order)
            
            order_data["order"]["clientExtensions"] = {
                "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                "tag": "DimeCurveButter",
                "comment": f"Setup:{trade_order.setup_type}|Entry:{trade_order.entry_price:.4f}|Stop:50pips|Target:500pips|Conf:{trade_order.confidence}%|Quarter:{quarter_level_type}|Candle:{candlestick_strength}|Zone:{zone_position}"[:500]
            }
            
            # Place order
            response = self.api.place_order(order_data)
            
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                
                # Store metadata locally (this is the reliable method)
                self.metadata_store.store_order_metadata(order_id, metadata)
                self.logger.info(f"📝 Stored Dime Curve Butter metadata for order {order_id}")
                self.logger.info(f"📝 Metadata stored: Zone Position = {metadata.zone_position} (Airtable-compatible)")
                self.logger.info(f"📝 Metadata stored: Distance = {metadata.distance_to_entry_pips} (float type)")
                self.logger.info(f"📝 Metadata stored: Momentum fields = None (strategy doesn't use momentum)")
                
                trade_order.order_id = order_id
                trade_order.status = 'PENDING'
                self.pending_orders.append(trade_order)
                
                self.logger.info(f"✅ Dime Curve Butter limit order placed: {trade_order.instrument} "
                               f"{trade_order.action} @ {trade_order.entry_price:.4f}")
                self.logger.info(f"🧈 Setup: {metadata.setup_name}")
                return True
            else:
                self.logger.error(f"❌ Dime Curve Butter limit order failed: {response}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error placing Dime Curve Butter limit order: {e}")
            return False
    
    def run_dime_curve_butter_analysis_demo(self):
        """Run analysis demo showing Dime Curve Butter quarter level detection with daily candlestick analysis"""
        print("\n" + "="*80)
        print("DIME CURVE BUTTER STRATEGY - ENHANCED WITH DAILY CANDLESTICK ANALYSIS")
        print("="*80)
        print("Strategy: Quarter level crosses confirmed by daily candlestick patterns")
        print("BUY: Bullish/Very Bullish daily candle crosses ABOVE X.X250")
        print("SELL: Bearish/Very Bearish daily candle crosses BELOW X.X750")
        print("Stops: 50 pips | Targets: 500 pips (2 quarters)")
        print("Momentum Analysis: NOT USED (all momentum fields set to None)")
        print("="*80)
        
        for instrument in self.instruments[:3]:
            print(f"\n🔍 ANALYZING {instrument}:")
            print("-" * 50)
            
            try:
                # Get current price
                price_data = self.api.get_current_prices([instrument])
                if not price_data or 'prices' not in price_data:
                    print(f"❌ Error: Unable to get price for {instrument}")
                    continue
                
                current_price = float(price_data['prices'][0]['closeoutBid'])
                is_jpy = self.quarter_detector.is_jpy_pair(instrument)
                
                print(f"Current Price: {current_price:.4f}")
                print(f"Currency Type: {'JPY Pair' if is_jpy else 'Standard Pair'}")
                
                # Get daily candlestick analysis
                daily_candle = self.strategy.candlestick_analyzer.get_daily_candlestick(instrument)
                if 'error' not in daily_candle:
                    candlestick_analysis = self.strategy.candlestick_analyzer.analyze_candlestick_strength(daily_candle)
                    
                    if 'error' not in candlestick_analysis:
                        print(f"\n📅 DAILY CANDLESTICK ANALYSIS:")
                        print(f"  Strength: {candlestick_analysis['strength']}")
                        print(f"  Bias: {candlestick_analysis['bias']}")
                        print(f"  Close Position: {candlestick_analysis['close_position_percent']:.1f}% of range")
                        print(f"  OHLC: O:{daily_candle['open']:.4f} H:{daily_candle['high']:.4f} L:{daily_candle['low']:.4f} C:{daily_candle['close']:.4f}")
                        print(f"  Analysis: {candlestick_analysis['analysis']}")
                    else:
                        print(f"  ❌ Candlestick analysis error: {candlestick_analysis['error']}")
                else:
                    print(f"  ❌ Daily candle error: {daily_candle['error']}")
                
                # Get quarter levels
                quarter_levels = self.quarter_detector.find_target_quarter_levels(current_price, is_jpy)
                
                print(f"\n📊 QUARTER LEVELS:")
                if quarter_levels['closest_250_below']:
                    distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_250_below'], is_jpy)
                    print(f"  X.X250 Below: {quarter_levels['closest_250_below']:.4f} ({distance:.1f} pips away)")
                
                if quarter_levels['closest_750_below']:
                    distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_750_below'], is_jpy)
                    print(f"  X.X750 Below: {quarter_levels['closest_750_below']:.4f} ({distance:.1f} pips away)")
                
                if quarter_levels['closest_250_above']:
                    distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_250_above'], is_jpy)
                    print(f"  X.X250 Above: {quarter_levels['closest_250_above']:.4f} ({distance:.1f} pips away)")
                
                if quarter_levels['closest_750_above']:
                    distance = self.quarter_detector.calculate_pip_distance(current_price, quarter_levels['closest_750_above'], is_jpy)
                    print(f"  X.X750 Above: {quarter_levels['closest_750_above']:.4f} ({distance:.1f} pips away)")
                
                print(f"\n🧈 ENHANCED TRADING SETUPS:")
                print("  📊 Momentum Analysis: NOT USED (all fields set to None)")
                print("  Primary Signal: Daily Candlestick Patterns + Quarter Level Crosses")
                print()
                print("  BUY Conditions:")
                print("    - Daily candlestick: BULLISH or VERY_BULLISH")
                print("    - Candle crosses ABOVE any X.X250 level")
                print("    - Entry: Limit BUY at crossed X.X250 level")
                print("    - Target: Next X.X750 level (+500 pips)")
                print()
                print("  SELL Conditions:")
                print("    - Daily candlestick: BEARISH or VERY_BEARISH") 
                print("    - Candle crosses BELOW any X.X750 level")
                print("    - Entry: Limit SELL at crossed X.X750 level")
                print("    - Target: Next X.X250 level (-500 pips)")
                
                # Show example setups based on current candlestick
                if 'error' not in daily_candle and 'error' not in candlestick_analysis:
                    candle_strength = candlestick_analysis['strength']
                    print(f"\n  Current Setup Potential:")
                    if candle_strength in ['BULLISH', 'VERY_BULLISH']:
                        print(f"    ✅ {candle_strength} candle - WATCH for X.X250 level crosses")
                        for level_250 in [quarter_levels.get('closest_250_below'), quarter_levels.get('closest_250_above')]:
                            if level_250:
                                if daily_candle['low'] <= level_250 <= daily_candle['high'] and daily_candle['close'] > level_250:
                                    print(f"    🎯 ACTIVE: Crossed ABOVE {level_250:.4f} - BUY signal!")
                                    print(f"        📊 Metadata: Momentum fields = None, Zone = QUARTER_250_CROSS_BUY_{candle_strength}")
                    elif candle_strength in ['BEARISH', 'VERY_BEARISH']:
                        print(f"    ✅ {candle_strength} candle - WATCH for X.X750 level crosses")
                        for level_750 in [quarter_levels.get('closest_750_below'), quarter_levels.get('closest_750_above')]:
                            if level_750:
                                if daily_candle['low'] <= level_750 <= daily_candle['high'] and daily_candle['close'] < level_750:
                                    print(f"    🎯 ACTIVE: Crossed BELOW {level_750:.4f} - SELL signal!")
                                    print(f"        📊 Metadata: Momentum fields = None, Zone = QUARTER_750_CROSS_SELL_{candle_strength}")
                    else:
                        print(f"    ⏰ {candle_strength} candle - No directional bias")
                        print(f"        📊 All momentum analysis fields will be set to None")
                
            except Exception as e:
                print(f"❌ Error analyzing {instrument}: {e}")
        
        print("\n" + "="*80)
        print("Enhanced Demo completed. The Dime Curve Butter strategy:")
        print("• Sets ALL momentum fields to None (not applicable)")
        print("• Uses daily candlestick confirmation as primary signal")  
        print("• Combines quarter level crosses for entry timing")
        print("• Maps zone positions to valid Airtable options:")
        print("  - QUARTER_250_CROSS_BUY_VERY_BULLISH")
        print("  - QUARTER_250_CROSS_BUY_BULLISH")
        print("  - QUARTER_750_CROSS_SELL_VERY_BEARISH")
        print("  - QUARTER_750_CROSS_SELL_BEARISH")
        print("• Stores metadata locally for reliable Airtable sync")
        print("• Uses proper data types (float for distance, None for momentum)")
        print("="*80)
    
    def run_single_scan(self):
        """Run a single scan for Dime Curve Butter opportunities"""
        print("🔍 Running single Dime Curve Butter scan with daily candlestick confirmation...")
        print("📊 Note: Momentum fields will be set to None for this strategy")
        
        opportunities = self.scan_for_dime_curve_butter_opportunities()
        
        if opportunities:
            print(f"\n🧈 Found {len(opportunities)} Dime Curve Butter opportunities:")
            for opp in opportunities:
                print(f"  {opp.instrument}: {opp.setup_type}")
                print(f"    {opp.action} LIMIT @ {opp.entry_price:.4f}")
                print(f"    Stop: {opp.stop_loss:.4f} | Target: {opp.take_profit:.4f}")
                print(f"    Confidence: {opp.confidence}%")
                print(f"    Risk: ~${self.max_risk_usd:.2f}")
                print(f"    📊 Momentum Analysis: Not used (fields = None)")
                print()
        else:
            print("⏰ No Dime Curve Butter opportunities found at this time")
        
        return opportunities

def main():
    """Main function for Dime Curve Butter Strategy"""
    print("🧈 Dime Curve Butter Strategy - Enhanced with Daily Candlestick Analysis")
    print("="*70)
    print("BUY: Bullish candle crosses ABOVE X.X250 | SELL: Bearish candle crosses BELOW X.X750")
    print("Fixed stops: 50 pips | Fixed targets: 500 pips")
    print("📊 Momentum Analysis: NOT USED (all momentum fields set to None)")
    print("="*70)
    
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
    bot = DimeCurveButterTradingBot(max_risk_usd=max_risk_usd, max_open_trades=5)
    
    # Mode selection
    print("\nSelect Mode:")
    print("1. Analysis Demo (Show quarter levels + daily candlestick analysis)")
    print("2. Single Scan (Check for opportunities with candlestick confirmation)")
    print("3. Place Orders (Execute found opportunities)")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        bot.run_dime_curve_butter_analysis_demo()
    elif choice == "2":
        bot.run_single_scan()
    elif choice == "3":
        opportunities = bot.run_single_scan()
        if opportunities:
            confirm = input(f"\nFound {len(opportunities)} opportunities. Place orders? (y/N): ").strip().lower()
            if confirm == 'y':
                for opp in opportunities:
                    bot.place_dime_curve_butter_limit_order(opp)
                print("✅ Orders placed!")
            else:
                print("Orders not placed.")
        else:
            print("No opportunities to execute.")
    else:
        print("Invalid choice. Running analysis demo...")
        bot.run_dime_curve_butter_analysis_demo()

if __name__ == "__main__":
    main()