#!/usr/bin/env python3
"""
Enhanced Metadata Storage for Comprehensive Trading Analytics with Price Tracking
Now includes backward compatibility with original TradeMetadata and TradeMetadataStore classes
"""

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Union
import json
import logging

# ==================================================
# ORIGINAL CLASSES FOR BACKWARD COMPATIBILITY
# ==================================================

@dataclass
class TradeMetadata:
    """
    Original trade metadata class for backward compatibility
    """
    setup_name: str
    strategy_tag: str = "PennyCurveMomentum"
    momentum_strength: Optional[float] = None
    momentum_direction: Optional[str] = None
    strategy_bias: Optional[str] = None
    zone_position: Optional[str] = None
    distance_to_entry_pips: Optional[float] = None
    signal_confidence: Optional[int] = None
    momentum_alignment: Optional[float] = None
    
    # Timestamps
    created_at: str = None
    
    # Additional metadata
    notes: Optional[str] = None
    session_info: Optional[Dict] = None
    
    def __post_init__(self):
        """Set created_at timestamp if not provided"""
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeMetadata':
        """Create TradeMetadata from dictionary"""
        return cls(**data)

class TradeMetadataStore:
    """
    Original metadata store class for backward compatibility
    """
    
    def __init__(self, storage_file: str = "trade_metadata.json", max_age_days: int = 30):
        """
        Initialize the metadata storage system
        """
        self.storage_file = storage_file
        self.max_age_days = max_age_days
        self.logger = logging.getLogger(__name__)
        
        # In-memory cache for performance
        self._metadata_cache: Dict[str, TradeMetadata] = {}
        self._last_loaded = 0
        self._cache_timeout = 300  # 5 minutes
        
        # Ensure storage directory exists
        self._ensure_storage_directory()
        
        # Load existing metadata
        self._load_metadata()
        
        if self.logger.handlers:
            self.logger.info(f"TradeMetadataStore initialized with {len(self._metadata_cache)} entries")
        else:
            print(f"TradeMetadataStore initialized with {len(self._metadata_cache)} entries")
    
    def _ensure_storage_directory(self):
        """Ensure the storage directory exists"""
        storage_dir = os.path.dirname(os.path.abspath(self.storage_file))
        if storage_dir and not os.path.exists(storage_dir):
            os.makedirs(storage_dir, exist_ok=True)
            if self.logger.handlers:
                self.logger.info(f"Created storage directory: {storage_dir}")
    
    def _load_metadata(self) -> None:
        """Load metadata from file into memory cache"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Convert dictionaries back to TradeMetadata objects
                for order_id, metadata_dict in data.items():
                    try:
                        self._metadata_cache[order_id] = TradeMetadata.from_dict(metadata_dict)
                    except Exception as e:
                        if self.logger.handlers:
                            self.logger.warning(f"Failed to load metadata for order {order_id}: {e}")
                
                import time
                self._last_loaded = time.time()
                if self.logger.handlers:
                    self.logger.info(f"Loaded {len(self._metadata_cache)} metadata entries from {self.storage_file}")
            else:
                if self.logger.handlers:
                    self.logger.info(f"No existing metadata file found at {self.storage_file}")
                
        except json.JSONDecodeError as e:
            if self.logger.handlers:
                self.logger.error(f"Invalid JSON in metadata file: {e}")
            self._backup_corrupted_file()
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error loading metadata: {e}")
    
    def _backup_corrupted_file(self):
        """Create backup of corrupted file and start fresh"""
        try:
            if os.path.exists(self.storage_file):
                import time
                backup_name = f"{self.storage_file}.corrupted.{int(time.time())}"
                os.rename(self.storage_file, backup_name)
                if self.logger.handlers:
                    self.logger.warning(f"Corrupted metadata file backed up as {backup_name}")
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Failed to backup corrupted file: {e}")
    
    def _save_metadata(self) -> None:
        """Save metadata cache to file"""
        try:
            # Convert TradeMetadata objects to dictionaries
            data_to_save = {}
            for order_id, metadata in self._metadata_cache.items():
                data_to_save[order_id] = metadata.to_dict()
            
            # Write to temporary file first (atomic operation)
            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            
            # Atomic rename
            if os.path.exists(self.storage_file):
                backup_file = f"{self.storage_file}.bak"
                os.rename(self.storage_file, backup_file)
            
            os.rename(temp_file, self.storage_file)
            
            # Clean up backup if save was successful
            backup_file = f"{self.storage_file}.bak"
            if os.path.exists(backup_file):
                os.remove(backup_file)
            
            if self.logger.handlers:
                self.logger.debug(f"Saved {len(self._metadata_cache)} metadata entries to {self.storage_file}")
            
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error saving metadata: {e}")
            # Try to restore from backup
            backup_file = f"{self.storage_file}.bak"
            if os.path.exists(backup_file):
                try:
                    os.rename(backup_file, self.storage_file)
                    if self.logger.handlers:
                        self.logger.info("Restored metadata file from backup")
                except:
                    pass
    
    def _refresh_cache_if_needed(self):
        """Refresh cache if it's stale"""
        import time
        if time.time() - self._last_loaded > self._cache_timeout:
            self._load_metadata()
    
    def store_order_metadata(self, order_id: str, metadata: TradeMetadata) -> None:
        """Store metadata for an order/trade"""
        try:
            self._refresh_cache_if_needed()
            
            # Store in cache
            self._metadata_cache[order_id] = metadata
            
            # Save to file
            self._save_metadata()
            
            if self.logger.handlers:
                self.logger.info(f"Stored metadata for order {order_id}: {metadata.setup_name}")
            
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error storing metadata for order {order_id}: {e}")
    
    def get_order_metadata(self, order_id: str) -> Optional[TradeMetadata]:
        """Retrieve metadata for an order/trade"""
        try:
            self._refresh_cache_if_needed()
            return self._metadata_cache.get(order_id)
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error retrieving metadata for order {order_id}: {e}")
            return None
    
    def get_all_metadata(self) -> Dict[str, TradeMetadata]:
        """Get all stored metadata"""
        try:
            self._refresh_cache_if_needed()
            return self._metadata_cache.copy()
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error retrieving all metadata: {e}")
            return {}
    
    def cleanup_old_metadata(self) -> int:
        """Remove metadata older than max_age_days"""
        try:
            self._refresh_cache_if_needed()
            
            cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
            initial_count = len(self._metadata_cache)
            
            # Find old entries
            old_order_ids = []
            for order_id, metadata in self._metadata_cache.items():
                try:
                    created_at = datetime.fromisoformat(metadata.created_at.replace('Z', '+00:00'))
                    if created_at.replace(tzinfo=None) < cutoff_date:
                        old_order_ids.append(order_id)
                except Exception as e:
                    if self.logger.handlers:
                        self.logger.warning(f"Invalid created_at timestamp for order {order_id}: {e}")
            
            # Remove old entries
            for order_id in old_order_ids:
                del self._metadata_cache[order_id]
            
            # Save if anything was removed
            if old_order_ids:
                self._save_metadata()
                removed_count = len(old_order_ids)
                if self.logger.handlers:
                    self.logger.info(f"Cleaned up {removed_count} old metadata entries")
                return removed_count
            
            return 0
            
        except Exception as e:
            if self.logger.handlers:
                self.logger.error(f"Error during metadata cleanup: {e}")
            return 0

# ==================================================
# ENHANCED CLASSES WITH FULL PRICE TRACKING
# ==================================================

@dataclass
class EnhancedTradeMetadata:
    """Enhanced trade metadata with comprehensive price tracking and analytics-focused fields"""
    
    # Core Setup Information
    setup_name: str
    strategy_tag: str = "PennyCurveMomentum"
    
    # ENHANCED: Comprehensive Price Management Fields
    stop_loss_price: Optional[float] = None
    target_price: Optional[float] = None
    current_price_at_order: Optional[float] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    
    # ENHANCED: Advanced Risk Management Calculations
    risk_amount: Optional[float] = None
    reward_amount: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    stop_loss_pips: Optional[float] = None
    target_pips: Optional[float] = None
    risk_percentage: Optional[float] = None
    position_size_percentage: Optional[float] = None
    
    # Market Analysis Data
    momentum_strength: Optional[float] = None
    momentum_direction: Optional[str] = None
    strategy_bias: Optional[str] = None
    zone_position: Optional[str] = None
    signal_confidence: Optional[int] = None
    momentum_alignment: Optional[float] = None
    
    # Order Management Data
    distance_to_entry_pips: Optional[float] = None
    market_condition: Optional[str] = None  # Trending, Ranging, Volatile
    session_type: Optional[str] = None      # London, NY, Tokyo, Overlap
    order_type: Optional[str] = None        # MARKET_ORDER, LIMIT_ORDER, STOP_ORDER
    
    # ENHANCED: Account Context and Position Sizing
    account_balance_at_order: Optional[float] = None
    intended_risk_percent: Optional[float] = None
    max_daily_risk_percent: Optional[float] = None
    units: Optional[int] = None
    direction: Optional[str] = None  # Long, Short
    
    # Setup Performance Tracking
    setup_frequency: Optional[int] = None    # How often this setup type occurs
    historical_win_rate: Optional[float] = None  # Win rate for this setup type
    avg_hold_time_days: Optional[float] = None   # Average hold time for this setup
    
    # Risk Management
    correlation_exposure: Optional[float] = None  # Correlation with other open trades
    portfolio_heat: Optional[float] = None        # Total portfolio risk %
    
    # ENHANCED: Timing and Execution Information
    created_time: str = None
    market_open_time: Optional[str] = None
    expected_duration: Optional[str] = None  # Scalp, Intraday, Swing, Position
    order_placement_time: Optional[str] = None
    fill_time: Optional[str] = None
    
    # ENHANCED: Instrument and Market Data
    instrument: Optional[str] = None
    spread_at_order: Optional[float] = None
    volatility_at_order: Optional[float] = None
    
    # External References
    chart_screenshot_path: Optional[str] = None
    trade_journal_notes: Optional[str] = None
    oanda_order_id: Optional[str] = None
    oanda_trade_id: Optional[str] = None
    
    def __post_init__(self):
        if self.created_time is None:
            self.created_time = datetime.now().isoformat()
        
        # Auto-calculate risk/reward metrics if prices are provided
        self._calculate_risk_reward_metrics()
        
        # Auto-calculate position sizing if account balance and risk are provided
        self._calculate_position_sizing()
    
    def _calculate_risk_reward_metrics(self):
        """Calculate comprehensive risk/reward metrics from price levels"""
        if not all([self.entry_price, self.stop_loss_price, self.target_price]):
            return
        
        try:
            # Determine if this is a long or short position based on stop loss
            is_long = self.stop_loss_price < self.entry_price
            
            # Check if instrument has JPY (different pip calculation)
            is_jpy_pair = self.instrument and 'JPY' in self.instrument
            pip_multiplier = 100 if is_jpy_pair else 10000
            
            if is_long:
                self.stop_loss_pips = abs(self.entry_price - self.stop_loss_price) * pip_multiplier
                self.target_pips = abs(self.target_price - self.entry_price) * pip_multiplier
            else:
                self.stop_loss_pips = abs(self.stop_loss_price - self.entry_price) * pip_multiplier
                self.target_pips = abs(self.entry_price - self.target_price) * pip_multiplier
            
            # Calculate risk/reward ratio
            if self.stop_loss_pips and self.stop_loss_pips > 0:
                self.risk_reward_ratio = self.target_pips / self.stop_loss_pips
            
            # Calculate monetary amounts if units are provided
            if self.units and self.units > 0:
                pip_value = 0.01 if is_jpy_pair else 0.0001  # Standard pip value
                self.risk_amount = self.stop_loss_pips * pip_value * abs(self.units)
                self.reward_amount = self.target_pips * pip_value * abs(self.units)
                
                # Calculate risk percentage if account balance is provided
                if self.account_balance_at_order and self.account_balance_at_order > 0:
                    self.risk_percentage = (self.risk_amount / self.account_balance_at_order) * 100
            
        except (TypeError, ZeroDivisionError, AttributeError):
            pass  # Keep None values if calculation fails
    
    def _calculate_position_sizing(self):
        """Calculate position sizing metrics"""
        try:
            if all([self.account_balance_at_order, self.intended_risk_percent, self.stop_loss_pips]):
                # Calculate optimal position size based on risk percentage
                risk_amount_target = (self.intended_risk_percent / 100) * self.account_balance_at_order
                is_jpy_pair = self.instrument and 'JPY' in self.instrument
                pip_value = 0.01 if is_jpy_pair else 0.0001
                optimal_units = risk_amount_target / (self.stop_loss_pips * pip_value)
                
                # Calculate actual position size percentage if units are provided
                if self.units:
                    self.position_size_percentage = (abs(self.units) / optimal_units) * 100
            
        except (TypeError, ZeroDivisionError, AttributeError):
            pass
    
    def update_prices(self, stop_loss: Optional[float] = None, 
                     target: Optional[float] = None, 
                     current: Optional[float] = None,
                     exit_price: Optional[float] = None):
        """Update price levels and recalculate metrics"""
        if stop_loss is not None:
            self.stop_loss_price = stop_loss
        if target is not None:
            self.target_price = target
        if current is not None:
            self.current_price_at_order = current
        if exit_price is not None:
            self.exit_price = exit_price
        
        # Recalculate metrics
        self._calculate_risk_reward_metrics()
        self._calculate_position_sizing()
    
    def get_price_summary(self) -> Dict:
        """Get a summary of all price-related data"""
        return {
            'entry_price': self.entry_price,
            'stop_loss_price': self.stop_loss_price,
            'target_price': self.target_price,
            'current_price_at_order': self.current_price_at_order,
            'exit_price': self.exit_price,
            'risk_reward_ratio': self.risk_reward_ratio,
            'stop_loss_pips': self.stop_loss_pips,
            'target_pips': self.target_pips,
            'risk_amount': self.risk_amount,
            'reward_amount': self.reward_amount,
            'risk_percentage': self.risk_percentage
        }

@dataclass
class MarketContextData:
    """Enhanced market context at time of order placement"""
    
    # Economic Calendar
    high_impact_news_today: bool = False
    news_events_next_4h: List[str] = None
    
    # Technical Context
    key_support_level: Optional[float] = None
    key_resistance_level: Optional[float] = None
    daily_range_position: Optional[float] = None  # 0-1, where 0 is daily low, 1 is daily high
    
    # ENHANCED: Price Action Context
    current_bid: Optional[float] = None
    current_ask: Optional[float] = None
    current_spread: Optional[float] = None
    price_at_key_level: Optional[bool] = None
    
    # Volatility Context
    atr_percentile: Optional[float] = None      # Where current ATR sits vs 30-day range
    volatility_regime: Optional[str] = None     # Low, Normal, High
    current_atr: Optional[float] = None
    
    # Correlation Context
    correlation_with_dxy: Optional[float] = None
    correlation_with_gold: Optional[float] = None
    
    # ENHANCED: Session and Timing Context
    market_session: Optional[str] = None        # London, NY, Tokyo, Sydney
    session_overlap: Optional[bool] = None      # True if in overlap period
    time_to_major_news: Optional[int] = None    # Minutes until next major news
    
    def __post_init__(self):
        if self.news_events_next_4h is None:
            self.news_events_next_4h = []
        
        # Calculate spread if bid/ask available
        if self.current_bid and self.current_ask:
            self.current_spread = self.current_ask - self.current_bid

class EnhancedTradeMetadataStore:
    """
    Enhanced metadata store with comprehensive price tracking and analytics capabilities
    """
    
    def __init__(self, storage_file: str = "enhanced_trade_metadata.json"):
        self.storage_file = storage_file
        self._metadata_cache = {}
        self._market_context_cache = {}
        self.logger = logging.getLogger(__name__)
        self.load_metadata()
    
    def store_enhanced_metadata(self, order_id: str, 
                               trade_metadata: EnhancedTradeMetadata,
                               market_context: Optional[MarketContextData] = None) -> None:
        """Store enhanced metadata with comprehensive price tracking"""
        try:
            self._metadata_cache[order_id] = asdict(trade_metadata)
            
            if market_context:
                self._market_context_cache[order_id] = asdict(market_context)
            
            self.save_metadata()
            
            message = f"💰 Stored enhanced metadata with price tracking for order {order_id}\n"
            message += f"   Entry: {trade_metadata.entry_price}\n"
            message += f"   Stop Loss: {trade_metadata.stop_loss_price}\n"
            message += f"   Target: {trade_metadata.target_price}\n"
            message += f"   R:R Ratio: {trade_metadata.risk_reward_ratio}"
            
            if self.logger.handlers:
                self.logger.info(message)
            else:
                print(message)
            
        except Exception as e:
            error_msg = f"❌ Error storing enhanced metadata: {e}"
            if self.logger.handlers:
                self.logger.error(error_msg)
            else:
                print(error_msg)
    
    def get_order_metadata(self, order_id: str) -> Optional[Dict]:
        """Get metadata for a specific order ID"""
        return self._metadata_cache.get(order_id)
    
    def update_order_prices(self, order_id: str, 
                           stop_loss: Optional[float] = None,
                           target: Optional[float] = None,
                           current: Optional[float] = None,
                           exit_price: Optional[float] = None) -> bool:
        """Update price levels for an existing order"""
        try:
            if order_id not in self._metadata_cache:
                message = f"⚠️ Order {order_id} not found in metadata cache"
                if self.logger.handlers:
                    self.logger.warning(message)
                else:
                    print(message)
                return False
            
            metadata_dict = self._metadata_cache[order_id]
            
            # Update prices
            if stop_loss is not None:
                metadata_dict['stop_loss_price'] = stop_loss
            if target is not None:
                metadata_dict['target_price'] = target
            if current is not None:
                metadata_dict['current_price_at_order'] = current
            if exit_price is not None:
                metadata_dict['exit_price'] = exit_price
            
            # Recreate EnhancedTradeMetadata object to recalculate metrics
            enhanced_metadata = EnhancedTradeMetadata(**metadata_dict)
            self._metadata_cache[order_id] = asdict(enhanced_metadata)
            
            self.save_metadata()
            
            message = f"💰 Updated prices for order {order_id}\n"
            message += f"   Stop Loss: {enhanced_metadata.stop_loss_price}\n"
            message += f"   Target: {enhanced_metadata.target_price}\n"
            message += f"   R:R Ratio: {enhanced_metadata.risk_reward_ratio}"
            
            if self.logger.handlers:
                self.logger.info(message)
            else:
                print(message)
            
            return True
            
        except Exception as e:
            error_msg = f"❌ Error updating order prices: {e}"
            if self.logger.handlers:
                self.logger.error(error_msg)
            else:
                print(error_msg)
            return False
    
    def cleanup_old_metadata(self, days_old: int = 30) -> int:
        """Clean up metadata older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)
            
            orders_to_remove = []
            for order_id, metadata in self._metadata_cache.items():
                created_time = metadata.get('created_time')
                if created_time:
                    try:
                        created_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                        if created_dt.replace(tzinfo=None) < cutoff_date:
                            orders_to_remove.append(order_id)
                    except:
                        continue
            
            # Remove old entries
            for order_id in orders_to_remove:
                del self._metadata_cache[order_id]
                if order_id in self._market_context_cache:
                    del self._market_context_cache[order_id]
            
            if orders_to_remove:
                self.save_metadata()
                message = f"🧹 Cleaned up {len(orders_to_remove)} old metadata entries"
                if self.logger.handlers:
                    self.logger.info(message)
                else:
                    print(message)
                return len(orders_to_remove)
            
            return 0
            
        except Exception as e:
            error_msg = f"❌ Error cleaning up old metadata: {e}"
            if self.logger.handlers:
                self.logger.error(error_msg)
            else:
                print(error_msg)
            return 0
    
    def save_metadata(self):
        """Save both metadata and market context with enhanced price tracking"""
        try:
            data = {
                'trade_metadata': self._metadata_cache,
                'market_context': self._market_context_cache,
                'version': '2.0',  # Version for compatibility
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            error_msg = f"❌ Error saving enhanced metadata: {e}"
            if self.logger.handlers:
                self.logger.error(error_msg)
            else:
                print(error_msg)
    
    def load_metadata(self):
        """Load both metadata and market context with enhanced price tracking"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Handle both old and new format
                if 'trade_metadata' in data:
                    self._metadata_cache = data.get('trade_metadata', {})
                    self._market_context_cache = data.get('market_context', {})
                    version = data.get('version', '1.0')
                    message = f"💰 Loaded enhanced metadata store v{version} with {len(self._metadata_cache)} entries"
                else:
                    # Old format compatibility
                    self._metadata_cache = data
                    self._market_context_cache = {}
                    message = f"💰 Loaded metadata store (legacy format) with {len(self._metadata_cache)} entries"
                
                if self.logger.handlers:
                    self.logger.info(message)
                else:
                    print(message)
            else:
                self._metadata_cache = {}
                self._market_context_cache = {}
                message = "💰 Created new enhanced metadata store"
                if self.logger.handlers:
                    self.logger.info(message)
                else:
                    print(message)
                
        except Exception as e:
            error_msg = f"❌ Error loading enhanced metadata: {e}"
            if self.logger.handlers:
                self.logger.error(error_msg)
            else:
                print(error_msg)
            self._metadata_cache = {}
            self._market_context_cache = {}

# Convenience functions for working with metadata
def create_setup_metadata(setup_name: str, **kwargs) -> TradeMetadata:
    """
    Convenience function to create TradeMetadata with setup name
    """
    return TradeMetadata(setup_name=setup_name, **kwargs)

def format_metadata_summary(metadata: TradeMetadata) -> str:
    """
    Format metadata into a readable summary string
    """
    try:
        summary_parts = [f"Setup: {metadata.setup_name}"]
        
        if metadata.momentum_strength is not None:
            summary_parts.append(f"Momentum: {metadata.momentum_strength:.3f}")
        
        if metadata.momentum_direction:
            summary_parts.append(f"Direction: {metadata.momentum_direction}")
        
        if metadata.signal_confidence is not None:
            summary_parts.append(f"Confidence: {metadata.signal_confidence}%")
        
        if metadata.zone_position:
            summary_parts.append(f"Zone: {metadata.zone_position}")
        
        return " | ".join(summary_parts)
        
    except Exception:
        return f"Setup: {metadata.setup_name}"

# Example usage and testing
if __name__ == "__main__":
    # Setup logging for testing
    logging.basicConfig(level=logging.INFO)
    
    # Test original classes for backward compatibility
    print("🧪 Testing backward compatibility...")
    
    # Create test metadata store
    store = TradeMetadataStore("test_metadata.json")
    
    # Create test metadata
    test_metadata = TradeMetadata(
        setup_name="Penny_Curve_EUR/USD_MARKET_BUY_Strong",
        momentum_strength=0.75,
        momentum_direction="BULLISH",
        signal_confidence=85,
        zone_position="In_Buy_Zone"
    )
    
    # Store and retrieve
    store.store_order_metadata("12345", test_metadata)
    retrieved = store.get_order_metadata("12345")
    
    print(f"Stored: {format_metadata_summary(test_metadata)}")
    print(f"Retrieved: {format_metadata_summary(retrieved)}")
    
    print("✅ Backward compatibility test completed!")
    
    # Test enhanced classes
    print("\n🧪 Testing enhanced features...")
    
    enhanced_store = EnhancedTradeMetadataStore("test_enhanced.json")
    
    enhanced_metadata = EnhancedTradeMetadata(
        setup_name="Enhanced_Penny_Curve_EUR/USD_BUY_Strong",
        instrument="EUR_USD",
        entry_price=1.0850,
        stop_loss_price=1.0830,
        target_price=1.0890,
        units=10000,
        account_balance_at_order=50000,
        intended_risk_percent=1.0,
        momentum_strength=0.85,
        signal_confidence=90
    )
    
    enhanced_store.store_enhanced_metadata("ENH_12345", enhanced_metadata)
    
    print("✅ Enhanced features test completed!")