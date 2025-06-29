# Import with error handling for missing dependencies
import os
import sys
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
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

# POLARS INTEGRATION - Replace pandas with polars for AWS Lambda
try:
    import polars as pl
    print("✅ Using Polars for data processing (AWS Lambda compatible)")
    POLARS_AVAILABLE = True
except ImportError:
    print("⚠️ Warning: 'polars' module not found. Install with: pip install polars")
    print("📥 Polars is required for AWS Lambda deployment")
    POLARS_AVAILABLE = False
    # Fallback to pandas for local development
    try:
        import pandas as pd
        print("📊 Falling back to pandas for local development")
        PANDAS_FALLBACK = True
    except ImportError:
        print("❌ Neither polars nor pandas available!")
        sys.exit(1)

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import existing classes with error handling
try:
    from momentum_calculator import MarketAwareMomentumCalculator, ForexMarketSchedule
    print("✅ Successfully imported momentum_calculator")
except ImportError as e:
    print(f"❌ Failed to import momentum_calculator: {e}")
    sys.exit(1)

try:
    from oanda_api import OandaAPI
    print("✅ Successfully imported oanda_api")
except ImportError as e:
    print(f"❌ Failed to import oanda_api: {e}")
    sys.exit(1)

try:
    from psychological_levels_trader import EnhancedPennyCurveStrategy, PsychologicalLevelsDetector
    print("✅ Successfully imported psychological_levels_trader")
except ImportError as e:
    print(f"❌ Failed to import psychological_levels_trader: {e}")
    sys.exit(1)

# Import the metadata storage (now available)
try:
    from metadata_storage import TradeMetadataStore, TradeMetadata
    print("✅ Successfully imported metadata_storage")
except ImportError as e:
    print(f"❌ Failed to import metadata_storage: {e}")
    sys.exit(1)

# Config imports
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("✅ Successfully imported Oanda config")
except ImportError as e:
    print(f"❌ Failed to import Oanda config: {e}")
    print("Please ensure config/oanda_config.py exists with API_KEY and ACCOUNT_ID")
    sys.exit(1)

@dataclass
class TradeOrder:
    """Data class to represent a trade order"""
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
    expiration: Optional[str] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'
    # Enhanced metadata fields
    momentum_analysis: Optional[Dict] = None
    zone_data: Optional[Dict] = None

class PCMMetadataProcessor:
    """Enhanced metadata processor for Penny Curve Momentum strategy - AIRTABLE INTEGRATION"""
    
    def __init__(self):
        self.momentum_thresholds = {
            'very_strong': 0.7,    # >0.7%
            'strong': 0.5,         # 0.5-0.7%
            'moderate': 0.3,       # 0.3-0.5%
            'weak': 0.1            # 0.1-0.3%
        }
    
    def classify_momentum_strength(self, momentum_value: float) -> str:
        """Convert momentum percentage to descriptive string for Airtable"""
        abs_momentum = abs(momentum_value)
        
        if abs_momentum > self.momentum_thresholds['very_strong']:
            return "Very Strong"
        elif abs_momentum > self.momentum_thresholds['strong']:
            return "Strong"
        elif abs_momentum > self.momentum_thresholds['moderate']:
            return "Moderate"
        elif abs_momentum > self.momentum_thresholds['weak']:
            return "Weak"
        else:
            return "Very Weak"
    
    def determine_momentum_direction(self, momentum_analysis: Dict) -> str:
        """Create descriptive momentum direction for Airtable"""
        direction = momentum_analysis.get('direction', 'NEUTRAL')
        
        direction_mapping = {
            'STRONG_BULLISH': 'Strong Bullish',
            'WEAK_BULLISH': 'Weak Bullish', 
            'NEUTRAL': 'Neutral',
            'WEAK_BEARISH': 'Weak Bearish',
            'STRONG_BEARISH': 'Strong Bearish'
        }
        
        return direction_mapping.get(direction, 'Neutral')
    
    def determine_strategy_bias(self, momentum_analysis: Dict) -> str:
        """Determine overall strategy bias for Airtable"""
        direction = momentum_analysis.get('direction', 'NEUTRAL')
        
        if 'BULLISH' in direction:
            return "BULLISH"
        elif 'BEARISH' in direction:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    def determine_zone_position(self, trade_order, zone_data: Dict) -> str:
        """
        CRITICAL FIX: Determine position relative to penny zones for Airtable
        
        Logic:
        - MARKET BUY: In_Buy_Zone (buying at current market)
        - MARKET SELL: In_Sell_Zone (selling at current market) 
        - LIMIT BUY: Above_Buy_Zone (waiting to buy at LOWER price)
        - LIMIT SELL: Below_Sell_Zone (waiting to sell at HIGHER price)
        """
        order_type = getattr(trade_order, 'order_type', 'MARKET')
        action = getattr(trade_order, 'action', 'BUY')
        
        if order_type == "MARKET":
            if action == "BUY":
                return "In_Buy_Zone"
            else:
                return "In_Sell_Zone"
        else:  # LIMIT orders
            if action == "BUY":
                return "Above_Buy_Zone"  # CORRECT: Waiting to buy at lower price
            else:
                return "Below_Sell_Zone"  # CORRECT: Waiting to sell at higher price
    
    def calculate_distance_to_entry(self, trade_order, zone_data: Dict) -> float:
        """Calculate distance to entry in pips for Airtable"""
        if getattr(trade_order, 'order_type', 'MARKET') == "MARKET":
            return 0.0  # Already at market
        
        current_price = zone_data.get('current_price', 0)
        entry_price = getattr(trade_order, 'entry_price', 0)
        
        if current_price == 0 or entry_price == 0:
            return 0.0
        
        # Determine pip value based on instrument
        instrument = getattr(trade_order, 'instrument', '')
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        
        distance = abs(current_price - entry_price) / pip_value
        return round(distance, 1)
    
    def calculate_momentum_alignment(self, momentum_analysis: Dict) -> float:
        """Calculate momentum alignment score for Airtable"""
        alignment = momentum_analysis.get('alignment', 0)
        momentum_strength = momentum_analysis.get('momentum_strength', 0)
        
        if alignment != 0:
            return round(alignment, 3)
        else:
            # Derive from momentum strength if alignment not available
            return round(momentum_strength / 100, 3) if momentum_strength else 0.0

class PolarsDataProcessor:
    """
    Data processing utilities using Polars for AWS Lambda compatibility
    Replaces pandas operations with Polars equivalents
    """
    
    @staticmethod
    def create_price_dataframe(candles_data: List[Dict]) -> pl.DataFrame:
        """Create Polars DataFrame from OANDA candles data"""
        try:
            if not candles_data:
                return pl.DataFrame()
            
            # Convert candles to structured data
            processed_data = []
            for candle in candles_data:
                processed_data.append({
                    'time': candle.get('time'),
                    'open': float(candle.get('mid', {}).get('o', 0)),
                    'high': float(candle.get('mid', {}).get('h', 0)),
                    'low': float(candle.get('mid', {}).get('l', 0)),
                    'close': float(candle.get('mid', {}).get('c', 0)),
                    'volume': int(candle.get('volume', 0))
                })
            
            # Create Polars DataFrame
            df = pl.DataFrame(processed_data)
            
            # Convert time column to datetime
            df = df.with_columns([
                pl.col('time').str.strptime(pl.Datetime, format='%Y-%m-%dT%H:%M:%S.%fZ')
            ])
            
            return df
            
        except Exception as e:
            print(f"Error creating Polars DataFrame: {e}")
            return pl.DataFrame()
    
    @staticmethod
    def calculate_sma(df: pl.DataFrame, period: int, column: str = 'close') -> pl.DataFrame:
        """Calculate Simple Moving Average using Polars"""
        try:
            return df.with_columns([
                pl.col(column).rolling_mean(window_size=period).alias(f'sma_{period}')
            ])
        except Exception as e:
            print(f"Error calculating SMA: {e}")
            return df
    
    @staticmethod
    def calculate_ema(df: pl.DataFrame, period: int, column: str = 'close') -> pl.DataFrame:
        """Calculate Exponential Moving Average using Polars"""
        try:
            # Polars EMA calculation
            alpha = 2.0 / (period + 1)
            return df.with_columns([
                pl.col(column).ewm_mean(alpha=alpha).alias(f'ema_{period}')
            ])
        except Exception as e:
            print(f"Error calculating EMA: {e}")
            return df
    
    @staticmethod
    def calculate_rsi(df: pl.DataFrame, period: int = 14, column: str = 'close') -> pl.DataFrame:
        """Calculate RSI using Polars"""
        try:
            # Calculate price changes
            df = df.with_columns([
                (pl.col(column) - pl.col(column).shift(1)).alias('price_change')
            ])
            
            # Separate gains and losses
            df = df.with_columns([
                pl.when(pl.col('price_change') > 0).then(pl.col('price_change')).otherwise(0).alias('gain'),
                pl.when(pl.col('price_change') < 0).then(-pl.col('price_change')).otherwise(0).alias('loss')
            ])
            
            # Calculate average gains and losses
            df = df.with_columns([
                pl.col('gain').rolling_mean(window_size=period).alias('avg_gain'),
                pl.col('loss').rolling_mean(window_size=period).alias('avg_loss')
            ])
            
            # Calculate RSI
            df = df.with_columns([
                (100 - (100 / (1 + (pl.col('avg_gain') / pl.col('avg_loss'))))).alias('rsi')
            ])
            
            return df
            
        except Exception as e:
            print(f"Error calculating RSI: {e}")
            return df
    
    @staticmethod
    def find_support_resistance(df: pl.DataFrame, window: int = 20) -> Dict[str, List[float]]:
        """Find support and resistance levels using Polars"""
        try:
            if df.height < window * 2:
                return {'support': [], 'resistance': []}
            
            # Calculate rolling highs and lows
            df = df.with_columns([
                pl.col('high').rolling_max(window_size=window).alias('resistance_level'),
                pl.col('low').rolling_min(window_size=window).alias('support_level')
            ])
            
            # Extract unique levels
            resistance_levels = df.select('resistance_level').drop_nulls().unique().to_series().to_list()
            support_levels = df.select('support_level').drop_nulls().unique().to_series().to_list()
            
            return {
                'support': sorted(support_levels),
                'resistance': sorted(resistance_levels, reverse=True)
            }
            
        except Exception as e:
            print(f"Error finding support/resistance: {e}")
            return {'support': [], 'resistance': []}

class FixedDollarRiskManager:
    """
    Position sizing based on fixed dollar risk amount
    
    Key Features:
    - Fixed maximum risk per trade (default $10 USD)
    - Accurate pip value calculations for all currency pairs
    - Account currency conversion handling
    - Minimum position size enforcement
    - Real-time exchange rate support
    """
    
    def __init__(self, oanda_api, max_risk_usd: float = 10.0, account_currency: str = 'USD'):
        self.api = oanda_api
        self.max_risk_usd = max_risk_usd
        self.account_currency = account_currency
        self.logger = logging.getLogger(__name__)
        
        # Cache for exchange rates (refresh every calculation for accuracy)
        self.exchange_rates = {}
        
        # Pip value definitions for different instrument types
        self.pip_definitions = {
            'JPY_PAIRS': {
                'pip_decimal_place': 2,  # 123.45 (2 decimal places)
                'pip_value': 0.01        # 1 pip = 0.01
            },
            'STANDARD_PAIRS': {
                'pip_decimal_place': 4,  # 1.2345 (4 decimal places) 
                'pip_value': 0.0001      # 1 pip = 0.0001
            }
        }
    
    def get_pip_info(self, instrument: str) -> Dict:
        """Get pip information for any currency pair"""
        if 'JPY' in instrument:
            return self.pip_definitions['JPY_PAIRS'].copy()
        else:
            return self.pip_definitions['STANDARD_PAIRS'].copy()
    
    def get_current_exchange_rate(self, from_currency: str, to_currency: str) -> Optional[float]:
        """Get current exchange rate between two currencies"""
        if from_currency == to_currency:
            return 1.0
        
        # Try direct rate first
        direct_pair = f"{from_currency}_{to_currency}"
        try:
            price_data = self.api.get_current_prices([direct_pair])
            if 'prices' in price_data and price_data['prices']:
                price_info = price_data['prices'][0]
                if 'closeoutBid' in price_info and 'closeoutAsk' in price_info:
                    rate = (float(price_info['closeoutBid']) + float(price_info['closeoutAsk'])) / 2
                    self.logger.debug(f"Direct rate {direct_pair}: {rate}")
                    return rate
        except Exception as e:
            self.logger.debug(f"Could not get direct rate for {direct_pair}: {e}")
        
        # Try inverse rate
        inverse_pair = f"{to_currency}_{from_currency}"
        try:
            price_data = self.api.get_current_prices([inverse_pair])
            if 'prices' in price_data and price_data['prices']:
                price_info = price_data['prices'][0]
                if 'closeoutBid' in price_info and 'closeoutAsk' in price_info:
                    inverse_rate = (float(price_info['closeoutBid']) + float(price_info['closeoutAsk'])) / 2
                    rate = 1.0 / inverse_rate
                    self.logger.debug(f"Inverse rate {inverse_pair}: {inverse_rate} -> {rate}")
                    return rate
        except Exception as e:
            self.logger.debug(f"Could not get inverse rate for {inverse_pair}: {e}")
        
        # Try cross rate via USD
        if from_currency != 'USD' and to_currency != 'USD':
            try:
                from_to_usd = self.get_current_exchange_rate(from_currency, 'USD')
                usd_to_target = self.get_current_exchange_rate('USD', to_currency)
                
                if from_to_usd and usd_to_target:
                    rate = from_to_usd * usd_to_target
                    self.logger.debug(f"Cross rate {from_currency}->{to_currency} via USD: {rate}")
                    return rate
            except Exception as e:
                self.logger.debug(f"Could not get cross rate: {e}")
        
        self.logger.warning(f"Could not get exchange rate for {from_currency}/{to_currency}")
        return None
    
    def calculate_pip_value_usd(self, instrument: str, position_size: int) -> Optional[float]:
        """Calculate the USD value of 1 pip for given position size"""
        try:
            base_currency, quote_currency = instrument.split('_')
            pip_info = self.get_pip_info(instrument)
            pip_value = pip_info['pip_value']
            
            # Calculate pip value in quote currency
            pip_value_quote = pip_value * position_size
            
            # Convert to USD if quote currency is not USD
            if quote_currency == 'USD':
                pip_value_usd = pip_value_quote
                self.logger.debug(f"{instrument}: Pip value = {pip_value_usd:.4f} USD (direct)")
            else:
                # Need to convert quote currency to USD
                quote_to_usd_rate = self.get_current_exchange_rate(quote_currency, 'USD')
                if quote_to_usd_rate:
                    pip_value_usd = pip_value_quote * quote_to_usd_rate
                    self.logger.debug(f"{instrument}: Pip value = {pip_value_quote:.4f} {quote_currency} "
                                    f"* {quote_to_usd_rate:.4f} = {pip_value_usd:.4f} USD")
                else:
                    return None
            
            return pip_value_usd
            
        except Exception as e:
            self.logger.error(f"Error calculating pip value for {instrument}: {e}")
            return None
    
    def calculate_position_size(self, instrument: str, entry_price: float, 
                              stop_loss_price: float, confidence: int = 80) -> Dict:
        """Calculate position size based on fixed dollar risk"""
        try:
            # Calculate stop loss distance in pips
            pip_info = self.get_pip_info(instrument)
            pip_value = pip_info['pip_value']
            
            stop_loss_distance = abs(entry_price - stop_loss_price)
            stop_loss_pips = stop_loss_distance / pip_value
            
            self.logger.debug(f"{instrument}: Entry={entry_price}, SL={stop_loss_price}")
            self.logger.debug(f"Stop loss distance: {stop_loss_distance:.5f} = {stop_loss_pips:.1f} pips")
            
            # Check if stop loss distance is reasonable
            if stop_loss_pips < 5:
                self.logger.warning(f"{instrument}: Stop loss too tight ({stop_loss_pips:.1f} pips), minimum 5 pips")
                # Adjust stop loss to minimum 5 pips
                min_stop_distance = 5 * pip_value
                if entry_price > stop_loss_price:  # Long position
                    stop_loss_price = entry_price - min_stop_distance
                else:  # Short position
                    stop_loss_price = entry_price + min_stop_distance
                
                stop_loss_distance = abs(entry_price - stop_loss_price)
                stop_loss_pips = stop_loss_distance / pip_value
                self.logger.info(f"{instrument}: Adjusted SL to {stop_loss_price:.4f} ({stop_loss_pips:.1f} pips)")
            
            # Confidence-based risk adjustment
            if confidence >= 90:
                risk_multiplier = 1.0  # Full risk for very high confidence
            elif confidence >= 80:
                risk_multiplier = 0.9  # 90% of max risk
            elif confidence >= 70:
                risk_multiplier = 0.8  # 80% of max risk
            else:
                risk_multiplier = 0.7  # 70% of max risk for lower confidence
            
            adjusted_max_risk_usd = self.max_risk_usd * risk_multiplier
            
            # Start with a test position size to calculate pip value
            test_position_size = 1000  # 1 micro lot
            pip_value_usd = self.calculate_pip_value_usd(instrument, test_position_size)
            
            if not pip_value_usd:
                return {
                    'error': f'Could not calculate pip value for {instrument}',
                    'position_size': 1000,  # Fallback to minimum
                    'risk_usd': 0,
                    'stop_loss_price': stop_loss_price  # Return adjusted stop loss
                }
            
            # Calculate position size
            pip_value_per_unit = pip_value_usd / test_position_size
            max_position_size = adjusted_max_risk_usd / (stop_loss_pips * pip_value_per_unit)
            
            # Round to nearest 1000 (micro lot)
            position_size = max(1000, int(round(max_position_size / 1000) * 1000))
            
            # Maximum position size check (safety)
            max_allowed_position = 100000  # 1 standard lot maximum
            if position_size > max_allowed_position:
                position_size = max_allowed_position
                self.logger.warning(f"{instrument}: Position size above maximum, using {max_allowed_position}")
            
            # Calculate actual risk with final position size
            actual_pip_value_usd = self.calculate_pip_value_usd(instrument, position_size)
            actual_risk_usd = stop_loss_pips * (actual_pip_value_usd / position_size) * position_size if actual_pip_value_usd else 0
            
            # Convert position size to lots for display
            lots = position_size / 100000  # 100,000 = 1 standard lot
            micro_lots = position_size / 1000  # 1,000 = 1 micro lot
            
            result = {
                'position_size': position_size,
                'position_size_lots': round(lots, 2),
                'position_size_micro_lots': micro_lots,
                'stop_loss_pips': round(stop_loss_pips, 1),
                'pip_value_usd': round(pip_value_per_unit, 4),
                'risk_usd': round(actual_risk_usd, 2),
                'max_risk_usd': adjusted_max_risk_usd,
                'risk_multiplier': risk_multiplier,
                'confidence': confidence,
                'is_risk_acceptable': actual_risk_usd <= self.max_risk_usd * 1.1,  # Allow 10% tolerance
                'stop_loss_price': stop_loss_price,  # Return potentially adjusted stop loss
                'calculation_details': {
                    'entry_price': entry_price,
                    'original_stop_loss': stop_loss_price,
                    'stop_loss_distance': round(stop_loss_distance, 5),
                    'pip_definition': pip_info
                }
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error calculating position size for {instrument}: {e}")
            return {
                'error': str(e),
                'position_size': 1000,  # Fallback minimum
                'risk_usd': 0,
                'stop_loss_price': stop_loss_price
            }

class DemoTradingBot:
    """
    Demo Trading Bot for Penny Curve Strategy with Fixed Dollar Risk Management
    
    Features:
    - Runs every 15 minutes
    - Places real orders in practice account
    - Fixed dollar risk per trade (default $10 USD max)
    - Tracks open positions and orders
    - Market timing optimization
    - Liquidity-based execution
    - Enhanced setup naming and momentum tracking
    - LOCAL METADATA STORAGE for reliable trade journaling
    - POLARS INTEGRATION for AWS Lambda compatibility
    - ENHANCED AIRTABLE METADATA INTEGRATION - FIXED VERSION
    - ALL CRITICAL FIXES APPLIED
    """
    
    def __init__(self, max_risk_usd: float = 10.0, max_open_trades: int = 5):
        # Initialize components with error handling
        try:
            self.api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
            self.momentum_calc = MarketAwareMomentumCalculator(self.api)
            self.levels_detector = PsychologicalLevelsDetector()
            self.strategy = EnhancedPennyCurveStrategy(self.momentum_calc, self.levels_detector)
            
            # Initialize fixed dollar risk manager
            self.risk_manager = FixedDollarRiskManager(self.api, max_risk_usd)
            self.max_risk_usd = max_risk_usd
            self.max_open_trades = max_open_trades
            self.account_balance = None
            
            # Initialize metadata store for reliable journaling
            self.metadata_store = TradeMetadataStore()
            
            # Initialize Polars data processor
            self.data_processor = PolarsDataProcessor()
            
            # ENHANCED: Initialize metadata processor for Airtable integration
            self.metadata_processor = PCMMetadataProcessor()
            
            # Clean up old metadata on startup
            cleaned_count = self.metadata_store.cleanup_old_metadata()
            if cleaned_count > 0:
                print(f"🧹 Cleaned up {cleaned_count} old metadata entries")
            
        except Exception as e:
            print(f"❌ Error initializing trading bot: {e}")
            sys.exit(1)
        
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
        
        # Optimal trading windows (ET/EDT) - when spreads are tightest and liquidity highest
        self.trading_windows = {
            # Major USD pairs
            'EUR_USD': {'start': 3, 'end': 11},   # 03:00 – 11:00 ET (London + NY overlap)
            'GBP_USD': {'start': 3, 'end': 11},   # 03:00 – 11:00 ET (London + NY overlap)
            'USD_JPY': {'start': 19, 'end': 11},  # 19:00 – 11:00 ET (Tokyo + overlap)
            'USD_CAD': {'start': 8, 'end': 14},   # 08:00 – 14:00 ET (NY session)
            'AUD_USD': {'start': 19, 'end': 11},  # 19:00 – 11:00 ET (crosses midnight)
            'NZD_USD': {'start': 18, 'end': 10},  # 18:00 – 10:00 ET (crosses midnight)
            
            # EUR cross pairs
            'EUR_GBP': {'start': 3, 'end': 11},   # London session for EUR/GBP cross
            'EUR_JPY': {'start': 2, 'end': 10},   # 02:00 – 10:00 ET (London + Tokyo)
            'EUR_CAD': {'start': 7, 'end': 12},   # London + early NY for EUR/CAD
            'EUR_AUD': {'start': 20, 'end': 10},  # Sydney + London overlap
            'EUR_NZD': {'start': 19, 'end': 9},   # Wellington + London overlap
            
            # GBP cross pairs
            'GBP_JPY': {'start': 2, 'end': 10},   # 02:00 – 10:00 ET (London + Tokyo)
            'GBP_CAD': {'start': 7, 'end': 12},   # London + early NY for GBP/CAD
            'GBP_AUD': {'start': 20, 'end': 10},  # Sydney + London overlap
            'GBP_NZD': {'start': 19, 'end': 9},   # Wellington + London overlap
            
            # AUD cross pairs
            'AUD_JPY': {'start': 19, 'end': 11},  # 19:00 – 11:00 ET (crosses midnight)
            'AUD_CAD': {'start': 20, 'end': 11},  # Sydney + North America
            'AUD_NZD': {'start': 17, 'end': 6},   # 17:00 – 06:00 ET (Oceania session)
            
            # NZD cross pairs
            'NZD_JPY': {'start': 18, 'end': 10},  # 18:00 – 10:00 ET (crosses midnight)
            'NZD_CAD': {'start': 19, 'end': 10},  # Wellington + North America overlap
            
            # Additional JPY cross
            'CAD_JPY': {'start': 19, 'end': 10},  # 19:00 – 10:00 ET (crosses midnight)
        }
        
        # Times to AVOID trading (poor liquidity/wide spreads)
        self.avoid_periods = [
            {'start': 15, 'end': 17, 'reason': 'Daily rollover period (OANDA)'},
            {'start': 13, 'end': 15, 'reason': 'Midday liquidity lull'},
        ]
        
        # Friday cutoff (lower institutional volume)
        self.friday_cutoff_hour = 12  # Noon ET on Friday
        
        # Trade tracking
        self.pending_orders = []
        self.open_positions = []
        self.trade_history = []
        
        # Market schedule
        try:
            self.market_schedule = ForexMarketSchedule()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize market schedule: {e}")
            self.market_schedule = None
        
        # Logging setup
        self.setup_logging()
        
        print("🤖 Demo Trading Bot Initialized - ENHANCED WITH AIRTABLE METADATA!")
        print(f"   💰 Max risk per trade: ${self.max_risk_usd:.2f} USD")
        print(f"   📊 Max open trades: {self.max_open_trades}")
        print(f"   🎯 Monitoring {len(self.instruments)} pairs: {', '.join(self.instruments[:6])}...")
        print(f"   📝 Local metadata storage enabled for reliable trade journaling")
        print(f"   🚀 Polars integration for AWS Lambda compatibility")
        print(f"   📋 Enhanced Airtable metadata integration for all 9 fields")
        print(f"   ✅ API response handling fixed")
        print(f"   ✅ Liquidity scoring fixed")
        print(f"   ✅ Confidence thresholds lowered (65-80%)")
        print(f"   ✅ Trading window logic fixed")
        print(f"   ✅ Zone position logic FIXED")
    
    def setup_logging(self):
        """Setup comprehensive logging for trading activities"""
        try:
            log_dir = os.path.join(current_dir, 'trading_logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # Daily log file
            today = datetime.now().strftime('%Y-%m-%d')
            log_file = os.path.join(log_dir, f'demo_trading_{today}.log')
            
            # Create file handler with UTF-8 encoding
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            
            # Create console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            
            # Configure logger
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
            
            # Clear existing handlers
            self.logger.handlers.clear()
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
            
            self.logger.info("Demo Trading Bot started with ENHANCED AIRTABLE METADATA INTEGRATION - FIXED VERSION")
            
        except Exception as e:
            print(f"⚠️ Warning: Could not setup logging: {e}")
            # Create a basic logger
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
    
    def create_setup_name(self, trade_order: TradeOrder, momentum_analysis: Dict) -> str:
        """Create a more standardized setup name"""
        try:
            # Base strategy name - more standardized
            strategy_name = "PCM"  # Penny Curve Momentum abbreviation
            
            # Extract instrument (replace underscore with slash for readability)
            instrument = trade_order.instrument.replace('_', '/')
            
            # Order type and action
            order_type = trade_order.order_type  # MARKET or LIMIT
            action = trade_order.action  # BUY or SELL
            
            # ENHANCED: Use metadata processor for consistent strength classification
            momentum_strength = abs(momentum_analysis.get('momentum_strength', 0))
            strength_label = self.metadata_processor.classify_momentum_strength(momentum_strength).replace(' ', '')
            
            # Add session context for better categorization
            session_info = self.get_trading_session_info()
            session_context = ""
            if session_info.get('overlaps'):
                session_context = f"_{session_info['overlaps'][0].replace('-', '')}"
            elif session_info.get('active_sessions'):
                session_context = f"_{session_info['active_sessions'][0]}"
            
            # Create standardized setup name
            # Format: PCM_EUR/USD_MARKET_BUY_Strong_LondonNY
            setup_name = f"{strategy_name}_{instrument}_{order_type}_{action}_{strength_label}{session_context}"
            
            return setup_name
            
        except Exception as e:
            self.logger.error(f"Error creating setup name: {e}")
            return f"PCM_{trade_order.instrument}_{trade_order.action}"
    
    def create_trade_metadata(self, trade_order: TradeOrder, momentum_analysis: Dict, zone_data: Dict) -> TradeMetadata:
        """
        CRITICAL FIX: Create comprehensive metadata object with ALL Airtable fields
        
        Now properly handles all enhanced fields and zone position logic
        """
        try:
            # Get current session info
            session_info = self.get_trading_session_info()
            
            # Create setup name (existing logic)
            setup_name = self.create_setup_name(trade_order, momentum_analysis)
            
            # === FIXED: Process all metadata fields for Airtable ===
            
            # Momentum fields using metadata processor
            momentum_strength_val = momentum_analysis.get('momentum_strength', 0)
            momentum_strength_str = self.metadata_processor.classify_momentum_strength(momentum_strength_val)
            momentum_direction_str = self.metadata_processor.determine_momentum_direction(momentum_analysis)
            strategy_bias_str = self.metadata_processor.determine_strategy_bias(momentum_analysis)
            momentum_alignment = self.metadata_processor.calculate_momentum_alignment(momentum_analysis)
            
            # FIXED: Zone fields using corrected logic
            zone_position = self.metadata_processor.determine_zone_position(trade_order, zone_data)
            distance_to_entry_pips = self.metadata_processor.calculate_distance_to_entry(trade_order, zone_data)
            
            # CRITICAL FIX: Use the enhanced TradeMetadata class with all fields
            metadata = TradeMetadata(
                setup_name=setup_name,
                strategy_tag="PCM",  # Always PCM for Penny Curve Momentum
                
                # === ORIGINAL FIELDS (keep for compatibility) ===
                momentum_strength=momentum_strength_val,
                momentum_direction=momentum_analysis.get('direction'),
                strategy_bias=momentum_analysis.get('strategy_bias'),
                zone_position=zone_position,
                distance_to_entry_pips=distance_to_entry_pips,
                signal_confidence=trade_order.confidence,
                momentum_alignment=momentum_alignment,
                
                # === ENHANCED FIELDS FOR AIRTABLE (NEW) ===
                momentum_strength_str=momentum_strength_str,      # "Very Strong", "Strong", etc.
                momentum_direction_str=momentum_direction_str,    # "Strong Bullish", "Weak Bullish", etc.
                strategy_bias_str=strategy_bias_str,              # "BULLISH", "BEARISH", "NEUTRAL"
                
                # Session context
                session_info={
                    'current_session': session_info.get('active_sessions', ['Unknown'])[0] if session_info.get('active_sessions') else 'Unknown',
                    'liquidity_level': session_info.get('liquidity_level', 'Unknown'),
                    'overlaps': session_info.get('overlaps', []),
                    'market_time': session_info.get('current_time_et', 'Unknown')
                },
                
                notes=f"Reasoning: {'; '.join(trade_order.reasoning)}"
            )
            
            self.logger.info(f"📊 FIXED Enhanced Airtable metadata created: {setup_name}")
            self.logger.info(f"   Momentum: {momentum_strength_str} ({momentum_strength_val:.3f}) | Direction: {momentum_direction_str}")
            self.logger.info(f"   Bias: {strategy_bias_str} | Zone: {zone_position} | Distance: {distance_to_entry_pips} pips")
            self.logger.info(f"   Confidence: {trade_order.confidence}% | Alignment: {momentum_alignment}")
            
            # VALIDATION: Double-check zone position logic
            order_type = trade_order.order_type
            action = trade_order.action
            expected_zone = f"{order_type} {action} should be {zone_position}"
            self.logger.info(f"   Zone Logic Check: {expected_zone}")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"Error creating enhanced metadata: {e}")
            # Return minimal metadata as fallback
            return TradeMetadata(
                setup_name=f"Fallback_{trade_order.instrument}_{trade_order.action}",
                signal_confidence=trade_order.confidence,
                zone_position="Unknown_Zone"  # Fallback zone
            )
    
    def validate_metadata(self, metadata: TradeMetadata) -> bool:
        """Validate metadata meets quality standards"""
        try:
            # Check required fields
            required_fields = ['setup_name', 'strategy_tag', 'signal_confidence']
            for field in required_fields:
                if not hasattr(metadata, field) or getattr(metadata, field) is None:
                    self.logger.warning(f"Missing required field: {field}")
                    return False
            
            # Validate confidence range
            if not (0 <= metadata.signal_confidence <= 100):
                self.logger.warning(f"Invalid confidence: {metadata.signal_confidence}")
                return False
            
            # Validate momentum strength if present
            if metadata.momentum_strength is not None:
                if not (-1.0 <= metadata.momentum_strength <= 1.0):
                    self.logger.warning(f"Invalid momentum strength: {metadata.momentum_strength}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating metadata: {e}")
            return False
    
    def get_account_info(self) -> Dict:
        """Get current account information"""
        try:
            account_info = self.api.get_account_summary()
            if account_info and 'account' in account_info:
                self.account_balance = float(account_info['account']['balance'])
                
                return {
                    'balance': self.account_balance,
                    'currency': account_info['account']['currency'],
                    'margin_used': float(account_info['account']['marginUsed']),
                    'margin_available': float(account_info['account']['marginAvailable']),
                    'open_trades': int(account_info['account']['openTradeCount']),
                    'open_positions': int(account_info['account']['openPositionCount'])
                }
        except Exception as e:
            self.logger.error(f"Error getting account info: {e}")
        
        return {}
    
    def calculate_position_size(self, instrument: str, entry_price: float, 
                              stop_loss_price: float, confidence: int) -> int:
        """Calculate position size based on fixed dollar risk"""
        try:
            result = self.risk_manager.calculate_position_size(
                instrument, entry_price, stop_loss_price, confidence
            )
            
            if 'error' in result:
                self.logger.error(f"Position sizing error for {instrument}: {result['error']}")
                return 1000  # Minimum position size as fallback
            
            if not result['is_risk_acceptable']:
                self.logger.warning(f"Risk too high for {instrument}: ${result['risk_usd']:.2f}")
                return 1000  # Use minimum size if risk too high
            
            # Log the risk calculation
            self.logger.info(f"💰 {instrument} Risk: ${result['risk_usd']:.2f} USD "
                           f"({result['position_size_micro_lots']} micro lots, "
                           f"{result['stop_loss_pips']:.1f} pips)")
            
            return result['position_size']
            
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return 1000
    
    def get_market_time_et(self) -> datetime:
        """Get current time in ET/EDT (Eastern Time) - ENHANCED VERSION"""
        if PYTZ_AVAILABLE:
            try:
                et_tz = pytz.timezone('US/Eastern')
                return datetime.now(et_tz)
            except Exception as e:
                self.logger.debug(f"Error using pytz: {e}")
        
        # Fallback: assume UTC-4 (EDT) during summer or UTC-5 (EST) during winter
        utc_now = datetime.utcnow()
        
        # Simple DST check - DST typically runs March to November
        month = utc_now.month
        if 3 <= month <= 10:  # Rough DST period
            est_offset = timedelta(hours=-4)  # EDT
            tz_suffix = "EDT"
        else:
            est_offset = timedelta(hours=-5)  # EST
            tz_suffix = "EST"
            
        et_time = utc_now + est_offset
        
        # Add timezone info as an attribute for display
        et_time.tz_name = tz_suffix
        
        return et_time
    
    def is_market_open(self) -> bool:
        """Check if forex market is currently open"""
        try:
            if self.market_schedule:
                current_market_time = self.market_schedule.get_market_time()
                return self.market_schedule.is_market_open(current_market_time)
            else:
                # Simple fallback - assume market is always open except weekends
                current_time = self.get_market_time_et()
                return current_time.weekday() < 5  # Monday=0, Sunday=6
        except Exception as e:
            self.logger.error(f"Error checking market open status: {e}")
            return True  # Default to open if check fails
    
    def is_optimal_trading_time(self, instrument: str) -> Tuple[bool, str]:
        """Check if current time is optimal for trading specific instrument - FIXED VERSION"""
        try:
            current_et = self.get_market_time_et()
            current_hour = current_et.hour
            current_weekday = current_et.weekday()  # 0=Monday, 6=Sunday
            
            # Check if it's Friday after cutoff
            if current_weekday == 4 and current_hour >= self.friday_cutoff_hour:  # Friday
                return False, f"Friday after {self.friday_cutoff_hour}:00 ET - Lower institutional volume"
            
            # Check avoid periods
            for avoid_period in self.avoid_periods:
                start_hour = avoid_period['start']
                end_hour = avoid_period['end']
                
                if start_hour <= current_hour < end_hour:
                    return False, avoid_period['reason']
            
            # CRITICAL FIX: Check instrument-specific optimal window with correct logic
            if instrument in self.trading_windows:
                window = self.trading_windows[instrument]
                start_hour = window['start']
                end_hour = window['end']
                
                # Handle windows that cross midnight
                if start_hour > end_hour:  # e.g., 19:00 - 11:00
                    if current_hour >= start_hour or current_hour < end_hour:
                        return True, f"Optimal window: {start_hour:02d}:00-{end_hour:02d}:00 ET"
                    else:
                        return False, f"Outside optimal window: {start_hour:02d}:00-{end_hour:02d}:00 ET"
                else:  # Normal window e.g., 03:00 - 11:00
                    # CRITICAL FIX: Use <= for end hour to include 11:00
                    if start_hour <= current_hour <= end_hour:
                        return True, f"Optimal window: {start_hour:02d}:00-{end_hour:02d}:00 ET"
                    else:
                        return False, f"Outside optimal window: {start_hour:02d}:00-{end_hour:02d}:00 ET"
            
            # Default to trading if no specific window defined
            return True, "No specific window restriction"
            
        except Exception as e:
            self.logger.error(f"Error checking optimal trading time: {e}")
            return True, "Unknown timing status"
    
    def get_liquidity_score(self, instrument: str) -> int:
        """Get liquidity score for instrument at current time (1-5, 5 = highest liquidity) - FIXED VERSION"""
        try:
            current_et = self.get_market_time_et()
            current_hour = current_et.hour
            
            # Major pairs during London/NY overlap (8-11 ET) - HIGHEST liquidity
            if instrument in ['EUR_USD', 'GBP_USD'] and 8 <= current_hour <= 11:
                return 5
            
            # Major pairs during extended optimal windows (3-11 ET)
            if instrument in ['EUR_USD', 'GBP_USD'] and 3 <= current_hour <= 11:
                return 4
            
            # USD/JPY during Tokyo hours and overlaps
            if instrument == 'USD_JPY':
                if 19 <= current_hour or current_hour < 3:  # Tokyo session
                    return 5
                elif 3 <= current_hour <= 11:  # Tokyo-London overlap
                    return 4
            
            # USD/CAD during NY session
            if instrument == 'USD_CAD' and 8 <= current_hour < 14:
                return 4
            
            # Cross pairs during London session
            if instrument.startswith('EUR_') or instrument.startswith('GBP_'):
                if 3 <= current_hour <= 11:  # London session
                    return 4
            
            # JPY crosses during optimal windows
            if 'JPY' in instrument:
                if 19 <= current_hour or current_hour < 10:  # Tokyo overlap periods
                    return 4
            
            # AUD/NZD pairs during Oceania session
            if instrument in ['AUD_USD', 'NZD_USD', 'AUD_NZD']:
                if 17 <= current_hour or current_hour < 6:  # Oceania session
                    return 3
            
            # Check if timing is optimal but not in peak periods
            is_optimal, _ = self.is_optimal_trading_time(instrument)
            if is_optimal:
                return 3
            
            return 2  # Default moderate liquidity
            
        except Exception as e:
            self.logger.error(f"Error calculating liquidity score for {instrument}: {e}")
            return 3  # Default moderate liquidity
    
    def should_trade_instrument(self, instrument: str, signal_confidence: int) -> Tuple[bool, str]:
        """Determine if we should trade an instrument based on timing and confidence - FIXED VERSION"""
        try:
            # Check basic market timing
            is_optimal, timing_reason = self.is_optimal_trading_time(instrument)
            
            # Get liquidity score
            liquidity_score = self.get_liquidity_score(instrument)
            
            # FIX: More realistic confidence requirements
            if liquidity_score >= 4:
                min_confidence = 65  # Much lower threshold during high liquidity
            elif liquidity_score >= 3:
                min_confidence = 70  # Lower for medium liquidity
            elif liquidity_score >= 2:
                min_confidence = 75  # Standard threshold
            else:
                min_confidence = 80  # Higher threshold during lower liquidity
            
            # Allow trading if confidence is sufficient
            confidence_sufficient = signal_confidence >= min_confidence
            
            # For very high confidence signals, be even more flexible
            if signal_confidence >= 85:
                confidence_sufficient = True
                min_confidence = 60  # Very low threshold for high confidence
            
            if not confidence_sufficient:
                return False, f"Confidence {signal_confidence}% < required {min_confidence}% for liquidity level {liquidity_score}"
            
            # CRITICAL FIX: Don't reject good signals just for timing during London-NY overlap
            current_et = self.get_market_time_et()
            current_hour = current_et.hour
            
            # During London-NY overlap, be very flexible with timing
            if 8 <= current_hour <= 11 and liquidity_score >= 3:
                return True, f"London-NY overlap trading: Confidence {signal_confidence}% >= {min_confidence}% (Liquidity: {liquidity_score}/5)"
            
            # During London session, be flexible for major pairs
            if 3 <= current_hour <= 11 and instrument in ['EUR_USD', 'GBP_USD', 'EUR_GBP']:
                return True, f"London session trading: Confidence {signal_confidence}% >= {min_confidence}% (Liquidity: {liquidity_score}/5)"
            
            # If confidence is good but timing isn't perfect, still allow if liquidity is decent
            if not is_optimal and liquidity_score < 2:
                return False, f"Poor timing and low liquidity: {timing_reason}"
            
            # Default: allow if confidence is sufficient
            return True, f"Trading approved: Confidence {signal_confidence}% >= {min_confidence}% (Liquidity: {liquidity_score}/5)"
            
        except Exception as e:
            self.logger.error(f"Error checking should trade instrument: {e}")
            return False, f"Error checking timing: {e}"
    
    def get_trading_session_info(self) -> Dict:
        """Get enhanced session information with overlap detection"""
        try:
            current_et = self.get_market_time_et()
            current_hour = current_et.hour
            
            # Define major trading sessions (ET/EDT)
            sessions = {
                'Tokyo': {'start': 19, 'end': 4},      # 7 PM - 4 AM ET
                'London': {'start': 3, 'end': 12},     # 3 AM - 12 PM ET  
                'New York': {'start': 8, 'end': 17}    # 8 AM - 5 PM ET
            }
            
            active_sessions = []
            overlaps = []
            
            for session_name, times in sessions.items():
                start, end = times['start'], times['end']
                
                # Handle sessions that cross midnight
                if start > end:  # e.g., Tokyo 19-4
                    if current_hour >= start or current_hour < end:
                        active_sessions.append(session_name)
                else:  # Normal sessions
                    if start <= current_hour <= end:
                        active_sessions.append(session_name)
            
            # Detect overlaps
            if 'Tokyo' in active_sessions and 'London' in active_sessions:
                overlaps.append('Tokyo-London')
            if 'London' in active_sessions and 'New York' in active_sessions:
                overlaps.append('London-NY')
            
            # Determine overall liquidity
            if len(overlaps) > 0:
                liquidity_level = 'HIGH'
            elif len(active_sessions) >= 2:
                liquidity_level = 'MEDIUM'
            elif len(active_sessions) == 1:
                liquidity_level = 'MEDIUM'
            else:
                liquidity_level = 'LOW'
            
            return {
                'current_time_et': current_et.strftime('%Y-%m-%d %H:%M:%S') + f" {getattr(current_et, 'tz_name', 'EDT')}",
                'active_sessions': active_sessions,
                'overlaps': overlaps,
                'liquidity_level': liquidity_level
            }
            
        except Exception as e:
            self.logger.error(f"Error getting session info: {e}")
            return {
                'current_time_et': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'active_sessions': [],
                'overlaps': [],
                'liquidity_level': 'UNKNOWN'
            }
    
    def scan_for_opportunities(self) -> List[TradeOrder]:
        """Scan all instruments for trading opportunities with timing optimization"""
        opportunities = []
        
        self.logger.info("🔍 Scanning for trading opportunities with fixed dollar risk...")
        
        # Get current session info
        session_info = self.get_trading_session_info()
        self.logger.info(f"📅 Current session: {session_info['current_time_et']} - "
                        f"Active: {', '.join(session_info['active_sessions'])} - "
                        f"Liquidity: {session_info['liquidity_level']}")
        
        for instrument in self.instruments:
            try:
                # Analyze with momentum-first strategy
                analysis = self.strategy.analyze_penny_curve_setup(instrument)
                
                if 'error' in analysis:
                    self.logger.warning(f"❌ {instrument}: {analysis['error']}")
                    continue
                
                signals = analysis['signals']
                
                if signals['action'] != 'WAIT':
                    # Check if timing is optimal for this instrument
                    should_trade, timing_reason = self.should_trade_instrument(
                        instrument, signals['confidence']
                    )
                    
                    if not should_trade:
                        self.logger.info(f"⏰ {instrument}: {signals['action']} signal found but "
                                       f"skipping - {timing_reason}")
                        continue
                    
                    # Calculate position size using fixed dollar risk
                    position_size = self.calculate_position_size(
                        instrument,
                        signals['entry_price'],
                        signals['stop_loss'],
                        signals['confidence']
                    )
                    
                    # Create trade order with timing info and enhanced metadata
                    trade_order = TradeOrder(
                        instrument=instrument,
                        action=signals['action'],
                        order_type=signals['order_type'],
                        entry_price=signals['entry_price'],
                        stop_loss=signals['stop_loss'],
                        take_profit=signals['take_profit'],
                        units=position_size if signals['action'] == 'BUY' else -position_size,
                        confidence=signals['confidence'],
                        reasoning=signals['reasoning'] + [f"Market timing: {timing_reason}"],
                        timestamp=datetime.now().isoformat(),
                        expiration=signals.get('expiration'),
                        # Attach analysis data for metadata
                        momentum_analysis=analysis.get('momentum_analysis', {}),
                        zone_data=analysis.get('zone_data', {})
                    )
                    
                    opportunities.append(trade_order)
                    
                    liquidity_score = self.get_liquidity_score(instrument)
                    self.logger.info(f"🎯 {instrument}: {signals['action']} {signals['order_type']} "
                                   f"@ {signals['entry_price']:.4f} (Confidence: {signals['confidence']}%, "
                                   f"Liquidity: {liquidity_score}/5)")
                else:
                    # Still log timing info for monitoring
                    is_optimal, timing_reason = self.is_optimal_trading_time(instrument)
                    timing_status = "✅" if is_optimal else "⏰"
                    self.logger.debug(f"{timing_status} {instrument}: No signal - {timing_reason}")
                
            except Exception as e:
                self.logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        return opportunities
    
    def place_market_order(self, trade_order: TradeOrder) -> bool:
        """Enhanced market order placement with Airtable metadata"""
        try:
            self.logger.info(f"📈 Placing MARKET {trade_order.action} for {trade_order.instrument}")
            
            # Get analysis data
            momentum_analysis = getattr(trade_order, 'momentum_analysis', {})
            zone_data = getattr(trade_order, 'zone_data', {})
            
            # Create and validate metadata BEFORE placing order
            metadata = self.create_trade_metadata(trade_order, momentum_analysis, zone_data)
            
            # ENHANCED: Validate metadata quality
            if not self.validate_metadata(metadata):
                self.logger.warning(f"Metadata validation failed for {trade_order.instrument}")
                # Continue anyway but log the issue
            
            # Create order payload
            order_data = {
                "order": {
                    "type": "MARKET",
                    "instrument": trade_order.instrument,
                    "units": str(trade_order.units),
                    "stopLossOnFill": {
                        "price": str(trade_order.stop_loss)
                    },
                    "takeProfitOnFill": {
                        "price": str(trade_order.take_profit)
                    }
                }
            }
            
            # ENHANCED: Add clientExtensions with Airtable fields
            try:
                # Create enhanced comment with Airtable fields
                airtable_fields = {
                    'setup': metadata.setup_name,
                    'strategy': metadata.strategy_tag,
                    'momentum': getattr(metadata, 'momentum_strength_str', 'Unknown'),
                    'direction': getattr(metadata, 'momentum_direction_str', 'Unknown'),
                    'bias': getattr(metadata, 'strategy_bias_str', 'Unknown'),
                    'zone': metadata.zone_position,
                    'distance': metadata.distance_to_entry_pips,
                    'confidence': metadata.signal_confidence,
                    'alignment': metadata.momentum_alignment
                }
                
                # Create compact comment for OANDA (500 char limit)
                comment = json.dumps(airtable_fields, separators=(',', ':'))[:490]
                
                order_data["order"]["clientExtensions"] = {
                    "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                    "tag": metadata.strategy_tag,
                    "comment": comment
                }
                
                self.logger.info(f"📝 Added enhanced clientExtensions with Airtable fields")
                
            except Exception as e:
                self.logger.warning(f"Could not add enhanced client extensions: {e}")
                # Fallback to simple extensions
                order_data["order"]["clientExtensions"] = {
                    "id": metadata.setup_name.replace('/', '_')[:50],
                    "tag": "PCM"
                }
            
            # Place order
            response = self.api.place_order(order_data)
            
            if response and 'orderFillTransaction' in response:
                fill_transaction = response['orderFillTransaction']
                order_id = fill_transaction.get('orderID')
                trade_id = fill_transaction.get('id')
                
                # Store metadata with both order_id and trade_id for reliable lookup
                if order_id:
                    self.metadata_store.store_order_metadata(order_id, metadata)
                    self.logger.info(f"📝 Stored metadata for order {order_id}")
                if trade_id and trade_id != order_id:
                    self.metadata_store.store_order_metadata(trade_id, metadata)
                    self.logger.info(f"📝 Stored metadata for trade {trade_id}")
                
                trade_order.order_id = trade_id
                trade_order.status = 'FILLED'
                self.open_positions.append(trade_order)
                
                self.logger.info(f"✅ Market order filled: {trade_order.instrument} "
                               f"{trade_order.action} @ {trade_order.entry_price:.4f}")
                self.logger.info(f"📝 Setup: {metadata.setup_name}")
                return True
            else:
                self.logger.error(f"❌ Market order failed: {response}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error placing market order: {e}")
            self.logger.error(traceback.format_exc())
            return False
    
    def place_limit_order(self, trade_order: TradeOrder) -> bool:
        """Enhanced limit order placement with Airtable metadata"""
        try:
            self.logger.info(f"📋 Placing LIMIT {trade_order.action} for {trade_order.instrument} @ {trade_order.entry_price:.4f}")
            
            # Get analysis data
            momentum_analysis = getattr(trade_order, 'momentum_analysis', {})
            zone_data = getattr(trade_order, 'zone_data', {})
            
            # Create and validate metadata BEFORE placing order
            metadata = self.create_trade_metadata(trade_order, momentum_analysis, zone_data)
            
            # ENHANCED: Validate metadata quality
            if not self.validate_metadata(metadata):
                self.logger.warning(f"Metadata validation failed for {trade_order.instrument}")
                # Continue anyway but log the issue
            
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
            
            # Add expiration if specified
            if trade_order.expiration == 'END_OF_DAY':
                eod_time = datetime.now().replace(hour=17, minute=0, second=0, microsecond=0)
                if datetime.now() > eod_time:
                    eod_time += timedelta(days=1)
                order_data["order"]["timeInForce"] = "GTD"
                order_data["order"]["gtdTime"] = eod_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            
            # ENHANCED: Add clientExtensions with Airtable fields
            try:
                # Create enhanced comment with Airtable fields
                airtable_fields = {
                    'setup': metadata.setup_name,
                    'strategy': metadata.strategy_tag,
                    'momentum': getattr(metadata, 'momentum_strength_str', 'Unknown'),
                    'direction': getattr(metadata, 'momentum_direction_str', 'Unknown'),
                    'bias': getattr(metadata, 'strategy_bias_str', 'Unknown'),
                    'zone': metadata.zone_position,
                    'distance': metadata.distance_to_entry_pips,
                    'confidence': metadata.signal_confidence,
                    'alignment': metadata.momentum_alignment
                }
                
                # Create compact comment for OANDA (500 char limit)
                comment = json.dumps(airtable_fields, separators=(',', ':'))[:490]
                
                order_data["order"]["clientExtensions"] = {
                    "id": metadata.setup_name.replace('/', '_').replace(' ', '_')[:50],
                    "tag": metadata.strategy_tag,
                    "comment": comment
                }
                
                self.logger.info(f"📝 Added enhanced clientExtensions with Airtable fields")
                
            except Exception as e:
                self.logger.warning(f"Could not add enhanced client extensions: {e}")
                # Fallback to simple extensions
                order_data["order"]["clientExtensions"] = {
                    "id": metadata.setup_name.replace('/', '_')[:50],
                    "tag": "PCM"
                }
            
            # Place order
            response = self.api.place_order(order_data)
            
            if response and 'orderCreateTransaction' in response:
                order_id = response['orderCreateTransaction']['id']
                
                # Store metadata with order_id for reliable lookup during sync
                self.metadata_store.store_order_metadata(order_id, metadata)
                self.logger.info(f"📝 Stored metadata for limit order {order_id}")
                
                trade_order.order_id = order_id
                trade_order.status = 'PENDING'
                self.pending_orders.append(trade_order)
                
                self.logger.info(f"✅ Limit order placed: {trade_order.instrument} "
                               f"{trade_order.action} @ {trade_order.entry_price:.4f}")
                self.logger.info(f"📝 Setup: {metadata.setup_name}")
                return True
            else:
                self.logger.error(f"❌ Limit order failed: {response}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error placing limit order: {e}")
            self.logger.error(traceback.format_exc())
            return False
    
    def check_existing_orders(self) -> None:
        """Check status of existing orders and positions - FIXED VERSION"""
        try:
            # Get pending orders - FIX: Handle different response formats
            try:
                response = self.api.get_open_orders()
                # Handle both list and dict response formats
                if isinstance(response, list):
                    pending_orders = response
                    active_order_ids = [order.get('id') if isinstance(order, dict) else str(order) for order in pending_orders]
                elif isinstance(response, dict) and 'orders' in response:
                    pending_orders = response['orders']
                    active_order_ids = [order['id'] for order in pending_orders]
                else:
                    self.logger.warning(f"Unexpected pending orders response format: {type(response)}")
                    active_order_ids = []
            except Exception as e:
                self.logger.warning(f"Could not get pending orders: {e}")
                active_order_ids = []
            
            # Update our tracking
            self.pending_orders = [order for order in self.pending_orders 
                                 if order.order_id in active_order_ids]
            
            # Get open positions - FIX: Handle different response formats
            try:
                positions_response = self.api.get_open_positions()
                if isinstance(positions_response, list):
                    num_positions = len(positions_response)
                elif isinstance(positions_response, dict) and 'positions' in positions_response:
                    num_positions = len(positions_response['positions'])
                else:
                    num_positions = 0
            except Exception as e:
                self.logger.warning(f"Could not get open positions: {e}")
                num_positions = 0
            
            self.logger.info(f"Status: {len(active_order_ids)} pending orders, {num_positions} open positions")
            
        except Exception as e:
            self.logger.error(f"Error checking existing orders: {e}")
    
    def execute_trades(self, opportunities: List[TradeOrder]) -> None:
        """Execute trading opportunities with enhanced metadata"""
        if not opportunities:
            self.logger.info("No trading opportunities found")
            return
        
        # Check if we're at max positions
        current_positions = len(self.open_positions) + len(self.pending_orders)
        if current_positions >= self.max_open_trades:
            self.logger.warning(f"Max trades reached ({self.max_open_trades}). Skipping new orders.")
            return
        
        # Sort by confidence (highest first)
        opportunities.sort(key=lambda x: x.confidence, reverse=True)
        
        for trade_order in opportunities[:self.max_open_trades - current_positions]:
            try:
                # Check if we already have a position in this instrument
                existing_instruments = [pos.instrument for pos in self.open_positions + self.pending_orders]
                if trade_order.instrument in existing_instruments:
                    self.logger.info(f"Skipping {trade_order.instrument} - already have position")
                    continue
                
                # Execute based on order type
                if trade_order.order_type == 'MARKET':
                    success = self.place_market_order(trade_order)
                else:  # LIMIT
                    success = self.place_limit_order(trade_order)
                
                if success:
                    self.trade_history.append(trade_order)
                    
                    # Log enhanced trade details
                    momentum_analysis = getattr(trade_order, 'momentum_analysis', {})
                    setup_name = self.create_setup_name(trade_order, momentum_analysis)
                    self.logger.info(f"📊 Setup executed: {setup_name}")
                    self.logger.info(f"Trade reasoning for {trade_order.instrument}:")
                    for reason in trade_order.reasoning:
                        self.logger.info(f"   {reason}")
                
            except Exception as e:
                self.logger.error(f"Error executing trade for {trade_order.instrument}: {e}")
    
    def get_strategy_analytics(self) -> Dict:
        """Get enhanced Penny Curve strategy analytics with Airtable field analysis"""
        try:
            all_metadata = self.metadata_store.get_all_metadata()
            
            if not all_metadata:
                return {"message": "No metadata available"}
            
            # Existing analytics
            momentum_strengths = []
            confidence_levels = []
            session_performance = {}
            setup_types = {}
            
            # === ENHANCED: Airtable field analytics ===
            momentum_strength_distribution = {}
            momentum_direction_distribution = {}
            strategy_bias_distribution = {}
            zone_position_distribution = {}
            
            for order_id, metadata in all_metadata.items():
                # Existing logic
                if metadata.momentum_strength is not None:
                    momentum_strengths.append(metadata.momentum_strength)
                
                if metadata.signal_confidence is not None:
                    confidence_levels.append(metadata.signal_confidence)
                
                # === ENHANCED: Airtable field analytics ===
                
                # Momentum strength distribution
                if hasattr(metadata, 'momentum_strength_str') and metadata.momentum_strength_str:
                    momentum_strength_distribution[metadata.momentum_strength_str] = \
                        momentum_strength_distribution.get(metadata.momentum_strength_str, 0) + 1
                
                # Momentum direction distribution  
                if hasattr(metadata, 'momentum_direction_str') and metadata.momentum_direction_str:
                    momentum_direction_distribution[metadata.momentum_direction_str] = \
                        momentum_direction_distribution.get(metadata.momentum_direction_str, 0) + 1
                
                # Strategy bias distribution
                if hasattr(metadata, 'strategy_bias_str') and metadata.strategy_bias_str:
                    strategy_bias_distribution[metadata.strategy_bias_str] = \
                        strategy_bias_distribution.get(metadata.strategy_bias_str, 0) + 1
                
                # Zone position distribution
                if metadata.zone_position:
                    zone_position_distribution[metadata.zone_position] = \
                        zone_position_distribution.get(metadata.zone_position, 0) + 1
                
                # Session analysis
                if hasattr(metadata, 'session_info') and metadata.session_info:
                    session = metadata.session_info.get('current_session', 'Unknown')
                    if session not in session_performance:
                        session_performance[session] = {'count': 0, 'total_confidence': 0}
                    session_performance[session]['count'] += 1
                    session_performance[session]['total_confidence'] += metadata.signal_confidence or 0
                
                # Setup type analysis
                setup_name = metadata.setup_name or 'Unknown'
                setup_key = setup_name.split('_')[4] if len(setup_name.split('_')) > 4 else 'Unknown'  # Strength level
                setup_types[setup_key] = setup_types.get(setup_key, 0) + 1
            
            # Calculate session averages
            for session in session_performance:
                count = session_performance[session]['count']
                if count > 0:
                    session_performance[session]['avg_confidence'] = session_performance[session]['total_confidence'] / count
            
            return {
                'total_trades': len(all_metadata),
                'avg_momentum_strength': sum(momentum_strengths) / len(momentum_strengths) if momentum_strengths else 0,
                'avg_confidence': sum(confidence_levels) / len(confidence_levels) if confidence_levels else 0,
                'min_confidence': min(confidence_levels) if confidence_levels else 0,
                'max_confidence': max(confidence_levels) if confidence_levels else 0,
                
                # === ENHANCED: Airtable field analytics ===
                'momentum_strength_breakdown': momentum_strength_distribution,
                'momentum_direction_breakdown': momentum_direction_distribution,
                'strategy_bias_breakdown': strategy_bias_distribution,
                'zone_position_breakdown': zone_position_distribution,
                
                # Existing analytics
                'session_performance': session_performance,
                'setup_type_distribution': setup_types,
                'momentum_distribution': {
                    'very_strong': len([m for m in momentum_strengths if m > 0.7]),
                    'strong': len([m for m in momentum_strengths if 0.5 < m <= 0.7]),
                    'moderate': len([m for m in momentum_strengths if 0.3 < m <= 0.5]),
                    'weak': len([m for m in momentum_strengths if m <= 0.3])
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error generating enhanced strategy analytics: {e}")
            return {"error": str(e)}
    
    def generate_trading_report(self) -> str:
        """Generate enhanced trading report with strategy analytics"""
        try:
            account_info = self.get_account_info()
            session_info = self.get_trading_session_info()
            
            report = []
            report.append("="*80)
            report.append("DEMO TRADING BOT - ENHANCED WITH AIRTABLE METADATA INTEGRATION - FIXED")
            report.append("="*80)
            
            # FIXED: Use proper timezone for timestamp
            current_et = self.get_market_time_et()
            tz_name = current_et.strftime('%Z') if hasattr(current_et, 'strftime') and current_et.tzinfo else 'EDT'
            report.append(f"Timestamp: {current_et.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}")
            report.append(f"Market Open: {'✅ Yes' if self.is_market_open() else '❌ No'}")
            report.append("")
            
            # Risk management information
            report.append("💰 RISK MANAGEMENT:")
            report.append(f"   Max Risk per Trade: ${self.max_risk_usd:.2f} USD")
            report.append(f"   Max Open Trades: {self.max_open_trades}")
            
            # Calculate total current risk
            total_current_risk = len(self.open_positions + self.pending_orders) * self.max_risk_usd
            report.append(f"   Current Total Risk: ${total_current_risk:.2f} USD")
            report.append("")
            
            # ENHANCED: Add strategy-specific analytics with Airtable fields
            report.append("📊 PENNY CURVE STRATEGY ANALYTICS (ENHANCED & FIXED):")
            try:
                strategy_analytics = self.get_strategy_analytics()
                
                if 'error' not in strategy_analytics and 'message' not in strategy_analytics:
                    report.append(f"   Total PCM Trades: {strategy_analytics.get('total_trades', 0)}")
                    report.append(f"   Avg Momentum Strength: {strategy_analytics.get('avg_momentum_strength', 0):.3f}")
                    report.append(f"   Avg Confidence: {strategy_analytics.get('avg_confidence', 0):.1f}%")
                    report.append(f"   Confidence Range: {strategy_analytics.get('min_confidence', 0):.0f}% - {strategy_analytics.get('max_confidence', 0):.0f}%")
                    
                    # ENHANCED: Airtable field breakdowns
                    momentum_breakdown = strategy_analytics.get('momentum_strength_breakdown', {})
                    if momentum_breakdown:
                        report.append("   Airtable Momentum Strength Breakdown:")
                        for strength, count in sorted(momentum_breakdown.items()):
                            report.append(f"      {strength}: {count} trades")
                    
                    direction_breakdown = strategy_analytics.get('momentum_direction_breakdown', {})
                    if direction_breakdown:
                        report.append("   Airtable Momentum Direction Breakdown:")
                        for direction, count in sorted(direction_breakdown.items()):
                            report.append(f"      {direction}: {count} trades")
                    
                    bias_breakdown = strategy_analytics.get('strategy_bias_breakdown', {})
                    if bias_breakdown:
                        report.append("   Airtable Strategy Bias Breakdown:")
                        for bias, count in sorted(bias_breakdown.items()):
                            report.append(f"      {bias}: {count} trades")
                    
                    zone_breakdown = strategy_analytics.get('zone_position_breakdown', {})
                    if zone_breakdown:
                        report.append("   Airtable Zone Position Breakdown:")
                        for zone, count in sorted(zone_breakdown.items()):
                            report.append(f"      {zone}: {count} trades")
                    
                    # Session performance
                    session_perf = strategy_analytics.get('session_performance', {})
                    if session_perf:
                        report.append("   Session Performance:")
                        for session, data in session_perf.items():
                            report.append(f"      {session}: {data['count']} trades, {data.get('avg_confidence', 0):.1f}% avg confidence")
                else:
                    report.append(f"   {strategy_analytics.get('message', strategy_analytics.get('error', 'No analytics available'))}")
            except Exception as e:
                report.append(f"   Analytics Error: {e}")
            report.append("")
            
            # Market timing information
            report.append("🌍 MARKET TIMING & LIQUIDITY:")
            report.append(f"   Current Time: {session_info['current_time_et']}")
            report.append(f"   Active Sessions: {', '.join(session_info['active_sessions'])}")
            if session_info['overlaps']:
                report.append(f"   Session Overlaps: {', '.join(session_info['overlaps'])} 🔥")
            report.append(f"   Overall Liquidity: {session_info['liquidity_level']}")
            report.append("")
            
            # Instrument-specific timing - show subset for readability
            report.append("📊 INSTRUMENT TIMING STATUS (Top 12):")
            main_instruments = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD', 
                               'EUR_GBP', 'EUR_JPY', 'GBP_JPY', 'AUD_JPY', 'NZD_JPY', 'CAD_JPY']
            
            for instrument in main_instruments:
                try:
                    is_optimal, reason = self.is_optimal_trading_time(instrument)
                    liquidity = self.get_liquidity_score(instrument)
                    status = "✅ OPTIMAL" if is_optimal else "⏰ SUBOPTIMAL"
                    report.append(f"   {instrument}: {status} (Liquidity: {liquidity}/5)")
                except Exception as e:
                    report.append(f"   {instrument}: ❌ Error checking timing")
            
            if len(self.instruments) > 12:
                report.append(f"   ... and {len(self.instruments) - 12} more pairs")
            report.append("")
            
            # Account information
            if account_info:
                report.append("💰 ACCOUNT INFORMATION:")
                report.append(f"   Balance: ${account_info['balance']:,.2f} {account_info['currency']}")
                report.append(f"   Margin Used: ${account_info['margin_used']:,.2f}")
                report.append(f"   Open Trades: {account_info['open_trades']}")
                report.append("")
            
            # Current positions
            report.append(f"📈 CURRENT POSITIONS ({len(self.open_positions)}):")
            if self.open_positions:
                for pos in self.open_positions:
                    # Create setup name for display
                    momentum_analysis = getattr(pos, 'momentum_analysis', {})
                    setup_name = self.create_setup_name(pos, momentum_analysis)
                    report.append(f"   {pos.instrument}: {pos.action} @ {pos.entry_price:.4f}")
                    report.append(f"      Setup: {setup_name}")
                    report.append(f"      Target: {pos.take_profit:.4f} | Stop: {pos.stop_loss:.4f}")
                    report.append(f"      Risk: ${self.max_risk_usd:.2f} USD max")
            else:
                report.append("   No open positions")
            report.append("")
            
            # Pending orders
            report.append(f"📋 PENDING ORDERS ({len(self.pending_orders)}):")
            if self.pending_orders:
                for order in self.pending_orders:
                    # Create setup name for display
                    momentum_analysis = getattr(order, 'momentum_analysis', {})
                    setup_name = self.create_setup_name(order, momentum_analysis)
                    report.append(f"   {order.instrument}: {order.action} LIMIT @ {order.entry_price:.4f}")
                    report.append(f"      Setup: {setup_name}")
                    report.append(f"      Target: {order.take_profit:.4f} | Stop: {order.stop_loss:.4f}")
                    report.append(f"      Risk: ${self.max_risk_usd:.2f} USD max")
            else:
                report.append("   No pending orders")
            report.append("")
            
            # Recent trade history
            recent_trades = self.trade_history[-5:] if self.trade_history else []
            report.append(f"📜 RECENT TRADES ({len(recent_trades)}):")
            if recent_trades:
                for trade in recent_trades:
                    momentum_analysis = getattr(trade, 'momentum_analysis', {})
                    setup_name = self.create_setup_name(trade, momentum_analysis)
                    report.append(f"   {trade.timestamp[:16]} - {trade.instrument}: {trade.action} @ {trade.entry_price:.4f}")
                    report.append(f"      Setup: {setup_name}")
            else:
                report.append("   No recent trades")
            
            # Trading tips based on current time
            report.append("")
            report.append("💡 CURRENT MARKET CONDITIONS:")
            if session_info['liquidity_level'] == 'HIGH':
                report.append("   🔥 HIGH LIQUIDITY - Excellent time for trading major pairs")
            elif session_info['liquidity_level'] == 'MEDIUM':
                report.append("   📊 MEDIUM LIQUIDITY - Good for established trends")
            else:
                report.append("   ⏰ LOW LIQUIDITY - Consider avoiding new positions")
            
            if 'London-NY' in session_info['overlaps']:
                report.append("   🚀 London-NY overlap - Best time for EUR/USD, GBP/USD")
            elif 'Tokyo-London' in session_info['overlaps']:
                report.append("   🌅 Tokyo-London overlap - Good for JPY crosses")
            
            # Technical status and fixes applied
            report.append("")
            report.append("🔧 CRITICAL FIXES APPLIED:")
            report.append(f"   ✅ Zone Position Logic FIXED: LIMIT BUY now shows 'Above_Buy_Zone'")
            report.append(f"   ✅ Enhanced Metadata Fields: All Airtable fields now supported")
            report.append(f"   ✅ Zone Logic Validation: Added logging to verify correctness")
            report.append(f"   ✅ Fallback Metadata: Includes zone position for error handling")
            report.append(f"   ✅ Field Validation: Checks all required metadata fields")
            report.append("")
            report.append("📋 AIRTABLE FIELDS POPULATED (FIXED):")
            report.append(f"   • Setup Name: Unique identifier for each setup")
            report.append(f"   • Strategy Tag: Always 'PCM' for Penny Curve Momentum")
            report.append(f"   • Momentum Strength: Very Strong/Strong/Moderate/Weak/Very Weak")
            report.append(f"   • Momentum Direction: Strong Bullish/Weak Bullish/Neutral/etc.")
            report.append(f"   • Strategy Bias: BULLISH/BEARISH/NEUTRAL")
            report.append(f"   • Zone Position: FIXED - Above_Buy_Zone for LIMIT BUY orders")
            report.append(f"   • Distance to Entry (Pips): Numerical distance")
            report.append(f"   • Signal Confidence: 0-100 percentage")
            report.append(f"   • Momentum Alignment: -1.0 to +1.0 alignment score")
            
            report.append("="*80)
            
            return "\n".join(report)
            
        except Exception as e:
            self.logger.error(f"Error generating trading report: {e}")
            return f"Error generating report: {e}"
    
    def trading_cycle(self) -> None:
        """Main trading cycle - runs every 15 minutes"""
        try:
            self.logger.info("🔄 Starting trading cycle...")
            
            # Check if market is open
            if not self.is_market_open():
                self.logger.info("🏁 Market closed - skipping cycle")
                return
            
            # Update account info
            self.get_account_info()
            
            # Check existing orders
            self.check_existing_orders()
            
            # Scan for new opportunities
            opportunities = self.scan_for_opportunities()
            
            # Execute trades
            self.execute_trades(opportunities)
            
            # Generate and log report
            report = self.generate_trading_report()
            print(report)
            
            self.logger.info("✅ Trading cycle completed")
            
        except Exception as e:
            self.logger.error(f"❌ Error in trading cycle: {e}")
            self.logger.error(traceback.format_exc())
    
    def start_trading(self) -> None:
        """Start the automated trading bot"""
        if not SCHEDULE_AVAILABLE:
            print("❌ Cannot start automated trading: 'schedule' module not installed")
            print("📥 Install with: pip install schedule")
            print("🧪 Running single test cycle instead...")
            self.run_single_cycle()
            return
        
        print("🚀 Starting Demo Trading Bot - ENHANCED WITH AIRTABLE METADATA - FIXED!")
        print("⏰ Trading every 15 minutes during market hours")
        print("⏹️  Press Ctrl+C to stop")
        
        # Schedule trading every 15 minutes
        schedule.every(15).minutes.do(self.trading_cycle)
        
        # Run initial cycle
        self.trading_cycle()
        
        # Main loop
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            self.logger.info("🛑 Trading bot stopped by user")
            print("\n🛑 Demo Trading Bot stopped")
    
    def run_single_cycle(self) -> None:
        """Run a single trading cycle for testing"""
        print("🧪 Running single trading cycle - ENHANCED WITH AIRTABLE METADATA - FIXED...")
        self.trading_cycle()

def main():
    """Main function to run the demo trading bot"""
    print("🤖 Demo Trading Bot - ENHANCED WITH AIRTABLE METADATA INTEGRATION - FIXED")
    print("="*80)
    
    # Check Polars availability for AWS Lambda
    if not POLARS_AVAILABLE:
        print("⚠️ WARNING: Polars not available - this will cause issues on AWS Lambda!")
        print("📥 Install Polars: pip install polars")
        print("🚀 Polars is required for AWS Lambda deployment due to pandas size limitations")
        
        # Ask if user wants to continue without Polars
        try:
            continue_choice = input("\nContinue anyway? (y/N): ").strip().lower()
            if continue_choice != 'y':
                print("Exiting. Please install Polars and try again.")
                return
        except KeyboardInterrupt:
            print("\nExiting...")
            return
    
    # Configuration options
    print("\n💰 Risk Management Options:")
    print("1. Conservative: $5 USD max risk per trade")
    print("2. Standard: $10 USD max risk per trade (recommended)")
    print("3. Aggressive: $20 USD max risk per trade")
    print("4. Custom: Enter your own amount")
    
    try:
        risk_choice = input("\nEnter choice (1-4) or press Enter for standard: ").strip()
        
        if risk_choice == "1":
            max_risk_usd = 5.0
            print("Selected: Conservative ($5 USD max risk)")
        elif risk_choice == "3":
            max_risk_usd = 20.0
            print("Selected: Aggressive ($20 USD max risk)")
        elif risk_choice == "4":
            try:
                max_risk_usd = float(input("Enter max risk per trade (USD): $"))
                print(f"Selected: Custom (${max_risk_usd:.2f} USD max risk)")
            except ValueError:
                max_risk_usd = 10.0
                print("Invalid input, using $10 default")
        else:
            max_risk_usd = 10.0
            print("Selected: Standard ($10 USD max risk)")
        
        print(f"\n🎯 Initializing bot with ${max_risk_usd:.2f} USD max risk per trade...")
        
        # Initialize bot
        bot = DemoTradingBot(
            max_risk_usd=max_risk_usd,
            max_open_trades=5
        )
        
        # Ask user for mode
        print("\n🚀 Select trading mode:")
        print("1. Run single test cycle")
        print("2. Start automated trading (every 15 minutes)")
        
        choice = input("\nEnter choice (1 or 2): ").strip()
        
        if choice == "1":
            print("\n🧪 Running single test cycle...")
            bot.run_single_cycle()
        elif choice == "2":
            print("\n⚡ Starting automated trading...")
            bot.start_trading()
        else:
            print("\nInvalid choice. Running single test cycle...")
            bot.run_single_cycle()
            
    except KeyboardInterrupt:
        print("\n\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n❌ Error running bot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Starting main function...")
    main()