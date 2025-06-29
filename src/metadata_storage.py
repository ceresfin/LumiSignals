# metadata_storage.py - MINIMAL FIX VERSION 
# Only adding dict-like methods to existing TradeMetadata class

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

@dataclass
class TradeMetadata:
    """
    Enhanced Trade Metadata with ALL Airtable Fields for ALL Strategies
    
    CRITICAL FIX: Added all missing enhanced fields for complete compatibility
    """
    # === CORE FIELDS (Required) ===
    setup_name: str = ""
    strategy_tag: str = "PCM"
    signal_confidence: int = 0
    
    # === ORIGINAL FIELDS (Numeric/Raw) ===
    momentum_strength: Optional[float] = None
    momentum_direction: Optional[str] = None
    strategy_bias: Optional[str] = None
    zone_position: Optional[str] = None
    distance_to_entry_pips: float = 0.0
    momentum_alignment: float = 0.0
    
    # === ENHANCED AIRTABLE FIELDS (Human Readable) - FIXED ===
    momentum_strength_str: Optional[str] = None      # "Very Strong", "Strong", etc.
    momentum_direction_str: Optional[str] = None     # "Strong Bullish", "Weak Bullish", etc.
    strategy_bias_str: Optional[str] = None          # "BULLISH", "BEARISH", "NEUTRAL"
    
    # === ADDITIONAL METADATA ===
    session_info: Optional[Dict] = field(default_factory=dict)
    notes: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # === DICT-LIKE METHODS FOR SYNC COMPATIBILITY ===
    def get(self, key: str, default=None):
        """Dict-like get method for sync_all.py compatibility"""
        return getattr(self, key, default)
    
    def __getitem__(self, key: str):
        """Dict-like item access"""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"'{key}' not found in TradeMetadata")
    
    def __setitem__(self, key: str, value):
        """Dict-like item setting"""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"'{key}' is not a valid TradeMetadata field")
    
    def __contains__(self, key: str):
        """Dict-like 'in' operator"""
        return hasattr(self, key)
    
    def keys(self):
        """Dict-like keys method"""
        return [field.name for field in self.__dataclass_fields__.values()]
    
    def values(self):
        """Dict-like values method"""
        return [getattr(self, field.name) for field in self.__dataclass_fields__.values()]
    
    def items(self):
        """Dict-like items method"""
        return [(field.name, getattr(self, field.name)) for field in self.__dataclass_fields__.values()]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TradeMetadata':
        """Create from dictionary - handles missing fields gracefully"""
        # Remove any fields that don't exist in the dataclass
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        # Handle nested dicts properly
        if 'session_info' in filtered_data and filtered_data['session_info'] is None:
            filtered_data['session_info'] = {}
            
        return cls(**filtered_data)

@dataclass
class EnhancedTradeMetadata:
    """Enhanced Trade Metadata with price levels and market context"""
    # Core setup fields
    setup_name: str = ""
    strategy_tag: str = "PCM"
    
    # Price levels
    stop_loss_price: Optional[float] = None
    target_price: Optional[float] = None
    current_price_at_order: Optional[float] = None
    entry_price: Optional[float] = None
    
    # Original metadata fields
    momentum_strength: Optional[float] = None
    momentum_direction: Optional[str] = None
    strategy_bias: Optional[str] = None
    zone_position: Optional[str] = None
    signal_confidence: int = 0
    distance_to_entry_pips: float = 0.0
    momentum_alignment: float = 0.0
    
    # Enhanced Airtable fields
    momentum_strength_str: Optional[str] = None
    momentum_direction_str: Optional[str] = None
    strategy_bias_str: Optional[str] = None
    
    # Market context
    market_context: Optional[Dict] = field(default_factory=dict)
    session_info: Optional[Dict] = field(default_factory=dict)
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # === DICT-LIKE METHODS FOR SYNC COMPATIBILITY ===
    def get(self, key: str, default=None):
        """Dict-like get method for sync_all.py compatibility"""
        return getattr(self, key, default)
    
    def __getitem__(self, key: str):
        """Dict-like item access"""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"'{key}' not found in EnhancedTradeMetadata")
    
    def __setitem__(self, key: str, value):
        """Dict-like item setting"""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise KeyError(f"'{key}' is not a valid EnhancedTradeMetadata field")
    
    def __contains__(self, key: str):
        """Dict-like 'in' operator"""
        return hasattr(self, key)
    
    def keys(self):
        """Dict-like keys method"""
        return [field.name for field in self.__dataclass_fields__.values()]
    
    def values(self):
        """Dict-like values method"""
        return [getattr(self, field.name) for field in self.__dataclass_fields__.values()]
    
    def items(self):
        """Dict-like items method"""
        return [(field.name, getattr(self, field.name)) for field in self.__dataclass_fields__.values()]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'EnhancedTradeMetadata':
        """Create from dictionary"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        
        # Handle nested dicts
        for field_name in ['market_context', 'session_info']:
            if field_name in filtered_data and filtered_data[field_name] is None:
                filtered_data[field_name] = {}
                
        return cls(**filtered_data)

@dataclass
class MarketContextData:
    """Market context information for enhanced analysis"""
    active_sessions: List[str] = field(default_factory=list)
    session_overlaps: List[str] = field(default_factory=list)
    liquidity_level: str = "UNKNOWN"
    market_time_et: str = ""
    volatility_level: str = "NORMAL"
    
    def to_dict(self) -> Dict:
        return asdict(self)

class TradeMetadataStore:
    """
    Enhanced Trade Metadata Storage with Airtable Field Support
    
    CRITICAL FIX: Now handles all enhanced Airtable fields properly for ALL strategies
    """
    
    def __init__(self, storage_file: str = None):
        if storage_file is None:
            # Default to trading_logs directory
            current_dir = os.path.dirname(os.path.abspath(__file__))
            logs_dir = os.path.join(current_dir, 'trading_logs')
            os.makedirs(logs_dir, exist_ok=True)
            storage_file = os.path.join(logs_dir, 'trade_metadata.json')
        
        self.storage_file = storage_file
        self.metadata_cache: Dict[str, TradeMetadata] = {}
        self.logger = logging.getLogger(__name__)
        
        # Load existing metadata
        self._load_metadata()
        
        print(f"TradeMetadataStore initialized with {len(self.metadata_cache)} entries")
    
    def _load_metadata(self) -> None:
        """Load metadata from storage file"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Convert each entry back to TradeMetadata object
                for order_id, metadata_dict in data.items():
                    try:
                        self.metadata_cache[order_id] = TradeMetadata.from_dict(metadata_dict)
                    except Exception as e:
                        self.logger.warning(f"Could not load metadata for order {order_id}: {e}")
                        # Skip invalid entries
                        continue
                        
        except Exception as e:
            self.logger.error(f"Error loading metadata: {e}")
            self.metadata_cache = {}
    
    def _save_metadata(self) -> None:
        """Save metadata to storage file"""
        try:
            # Convert all metadata objects to dictionaries
            data = {
                order_id: metadata.to_dict() 
                for order_id, metadata in self.metadata_cache.items()
            }
            
            # Write to file with proper encoding
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"Error saving metadata: {e}")
    
    def store_order_metadata(self, order_id: str, metadata: TradeMetadata) -> bool:
        """
        Store metadata for an order with enhanced Airtable field validation
        
        CRITICAL FIX: Now validates all enhanced fields are properly set
        """
        try:
            # Validate required fields
            if not metadata.setup_name:
                self.logger.warning(f"Order {order_id}: Missing setup_name")
                metadata.setup_name = f"Unknown_Setup_{order_id}"
            
            if not metadata.strategy_tag:
                metadata.strategy_tag = "PCM"
            
            # ENHANCED: Validate Airtable fields are populated
            airtable_fields = {
                'momentum_strength_str': metadata.momentum_strength_str,
                'momentum_direction_str': metadata.momentum_direction_str,
                'strategy_bias_str': metadata.strategy_bias_str,
                'zone_position': metadata.zone_position
            }
            
            missing_fields = [field for field, value in airtable_fields.items() if not value]
            if missing_fields:
                self.logger.warning(f"Order {order_id}: Missing Airtable fields: {missing_fields}")
            
            # Store metadata
            self.metadata_cache[order_id] = metadata
            self._save_metadata()
            
            self.logger.info(f"✅ Stored enhanced metadata for order {order_id}")
            self.logger.info(f"   Setup: {metadata.setup_name}")
            self.logger.info(f"   Zone: {metadata.zone_position}")
            self.logger.info(f"   Momentum: {metadata.momentum_strength_str}")
            self.logger.info(f"   Direction: {metadata.momentum_direction_str}")
            self.logger.info(f"   Bias: {metadata.strategy_bias_str}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error storing metadata for order {order_id}: {e}")
            return False
    
    def get_order_metadata(self, order_id: str) -> Optional[TradeMetadata]:
        """Get metadata for specific order"""
        return self.metadata_cache.get(order_id)
    
    def get_all_metadata(self) -> Dict[str, TradeMetadata]:
        """Get all stored metadata"""
        return self.metadata_cache.copy()
    
    def cleanup_old_metadata(self, days_old: int = 30) -> int:
        """Remove metadata older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_old)
            initial_count = len(self.metadata_cache)
            
            # Filter out old entries
            filtered_cache = {}
            for order_id, metadata in self.metadata_cache.items():
                try:
                    created_at = datetime.fromisoformat(metadata.created_at.replace('Z', '+00:00'))
                    if created_at >= cutoff_date:
                        filtered_cache[order_id] = metadata
                except:
                    # Keep entries with invalid dates
                    filtered_cache[order_id] = metadata
            
            self.metadata_cache = filtered_cache
            self._save_metadata()
            
            removed_count = initial_count - len(self.metadata_cache)
            if removed_count > 0:
                self.logger.info(f"Cleaned up {removed_count} old metadata entries")
            
            return removed_count
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            return 0
    
    def update_order_metadata(self, order_id: str, updates: Dict[str, Any]) -> bool:
        """Update specific fields in existing metadata"""
        try:
            if order_id not in self.metadata_cache:
                self.logger.warning(f"Order {order_id} not found for update")
                return False
            
            metadata = self.metadata_cache[order_id]
            
            # Update fields
            for field, value in updates.items():
                if hasattr(metadata, field):
                    setattr(metadata, field, value)
                else:
                    self.logger.warning(f"Unknown field '{field}' for order {order_id}")
            
            self._save_metadata()
            self.logger.info(f"Updated metadata for order {order_id}: {list(updates.keys())}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating metadata for order {order_id}: {e}")
            return False
    
    def get_metadata_summary(self) -> Dict:
        """Get summary statistics of stored metadata"""
        try:
            total = len(self.metadata_cache)
            if total == 0:
                return {"total": 0, "message": "No metadata stored"}
            
            # Count by strategy
            strategy_counts = {}
            confidence_levels = []
            zone_positions = {}
            momentum_strengths = {}
            
            for metadata in self.metadata_cache.values():
                # Strategy counts
                strategy = metadata.strategy_tag or "Unknown"
                strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
                
                # Confidence levels
                if metadata.signal_confidence:
                    confidence_levels.append(metadata.signal_confidence)
                
                # ENHANCED: Airtable field analysis
                if metadata.zone_position:
                    zone_positions[metadata.zone_position] = zone_positions.get(metadata.zone_position, 0) + 1
                
                if metadata.momentum_strength_str:
                    momentum_strengths[metadata.momentum_strength_str] = momentum_strengths.get(metadata.momentum_strength_str, 0) + 1
            
            return {
                "total": total,
                "strategy_breakdown": strategy_counts,
                "avg_confidence": sum(confidence_levels) / len(confidence_levels) if confidence_levels else 0,
                "zone_position_breakdown": zone_positions,
                "momentum_strength_breakdown": momentum_strengths,
                "storage_file": self.storage_file
            }
            
        except Exception as e:
            self.logger.error(f"Error generating metadata summary: {e}")
            return {"total": 0, "error": str(e)}

class EnhancedTradeMetadataStore(TradeMetadataStore):
    """Enhanced metadata store with additional functionality"""
    
    def __init__(self, storage_file: str = None):
        super().__init__(storage_file)
        
        # Enhanced storage for additional metadata
        self.enhanced_storage_file = self.storage_file.replace('.json', '_enhanced.json')
        self._enhanced_cache: Dict[str, EnhancedTradeMetadata] = {}
        self._load_enhanced_metadata()
        
        print(f"EnhancedTradeMetadataStore initialized with {len(self._enhanced_cache)} enhanced entries")
    
    def _load_enhanced_metadata(self) -> None:
        """Load enhanced metadata from storage"""
        try:
            if os.path.exists(self.enhanced_storage_file):
                with open(self.enhanced_storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for order_id, metadata_dict in data.items():
                    try:
                        self._enhanced_cache[order_id] = EnhancedTradeMetadata.from_dict(metadata_dict)
                    except Exception as e:
                        self.logger.warning(f"Could not load enhanced metadata for order {order_id}: {e}")
                        continue
                        
        except Exception as e:
            self.logger.error(f"Error loading enhanced metadata: {e}")
            self._enhanced_cache = {}
    
    def _save_enhanced_metadata(self) -> None:
        """Save enhanced metadata to storage"""
        try:
            data = {
                order_id: metadata.to_dict() 
                for order_id, metadata in self._enhanced_cache.items()
            }
            
            with open(self.enhanced_storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            self.logger.error(f"Error saving enhanced metadata: {e}")
    
    def store_enhanced_metadata(self, order_id: str, metadata: EnhancedTradeMetadata) -> bool:
        """Store enhanced metadata for an order"""
        try:
            self._enhanced_cache[order_id] = metadata
            self._save_enhanced_metadata()
            
            self.logger.info(f"✅ Stored enhanced metadata for order {order_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error storing enhanced metadata for order {order_id}: {e}")
            return False
    
    def get_enhanced_metadata(self, order_id: str) -> Optional[EnhancedTradeMetadata]:
        """Get enhanced metadata for specific order"""
        return self._enhanced_cache.get(order_id)
    
    def get_metadata_stats(self) -> Dict:
        """Get comprehensive metadata statistics"""
        try:
            base_stats = self.get_metadata_summary()
            
            enhanced_stats = {
                'enhanced_entries': len(self._enhanced_cache),
                'entries_with_prices': sum(1 for m in self._enhanced_cache.values() 
                                         if m.stop_loss_price or m.target_price),
                'instruments': list(set(m.setup_name.split('_')[1] if '_' in m.setup_name else 'Unknown' 
                                      for m in self._enhanced_cache.values()))
            }
            
            return {**base_stats, **enhanced_stats}
            
        except Exception as e:
            self.logger.error(f"Error generating metadata stats: {e}")
            return {"error": str(e)}
    
    def convert_to_enhanced(self, order_id: str) -> bool:
        """Convert regular metadata to enhanced format"""
        try:
            regular_metadata = self.get_order_metadata(order_id)
            if not regular_metadata:
                return False
            
            # Convert to enhanced format
            enhanced = EnhancedTradeMetadata(
                setup_name=regular_metadata.setup_name,
                strategy_tag=regular_metadata.strategy_tag,
                momentum_strength=regular_metadata.momentum_strength,
                momentum_direction=regular_metadata.momentum_direction,
                strategy_bias=regular_metadata.strategy_bias,
                zone_position=regular_metadata.zone_position,
                signal_confidence=regular_metadata.signal_confidence,
                distance_to_entry_pips=regular_metadata.distance_to_entry_pips,
                momentum_alignment=regular_metadata.momentum_alignment,
                momentum_strength_str=getattr(regular_metadata, 'momentum_strength_str', None),
                momentum_direction_str=getattr(regular_metadata, 'momentum_direction_str', None),
                strategy_bias_str=getattr(regular_metadata, 'strategy_bias_str', None),
                session_info=getattr(regular_metadata, 'session_info', {}),
                created_at=getattr(regular_metadata, 'created_at', datetime.now().isoformat())
            )
            
            return self.store_enhanced_metadata(order_id, enhanced)
            
        except Exception as e:
            self.logger.error(f"Error converting metadata to enhanced: {e}")
            return False

# Export for easy import
__all__ = ['TradeMetadata', 'TradeMetadataStore', 'EnhancedTradeMetadata', 'EnhancedTradeMetadataStore', 'MarketContextData']