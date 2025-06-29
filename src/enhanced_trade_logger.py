"""
Enhanced Trade Logger - Comprehensive trade data logging for Airtable journal
Fixes issues with metadata classification and ensures all trades are captured
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict

@dataclass
class ComprehensiveTradeLog:
    """Complete trade information for comprehensive journaling"""
    # Order Information
    order_id: str
    trade_id: Optional[str] = None
    instrument: str
    order_type: str  # MARKET, LIMIT, STOP
    direction: str  # BUY/SELL
    units: int
    
    # Execution Details
    order_time: str
    execution_time: Optional[str] = None
    order_status: str  # PENDING, FILLED, CANCELLED
    
    # Price Levels
    entry_price: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    current_price: Optional[float] = None
    filled_price: Optional[float] = None
    
    # Strategy Metadata
    setup_name: str
    strategy_tag: str
    strategy_variant: Optional[str] = None  # e.g., "Quarter Curve Butter"
    
    # Market Analysis
    momentum_strength: Optional[float] = None
    momentum_strength_str: Optional[str] = None
    momentum_direction: Optional[str] = None
    momentum_direction_str: Optional[str] = None
    strategy_bias: Optional[str] = None
    strategy_bias_str: Optional[str] = None
    zone_position: Optional[str] = None
    signal_confidence: Optional[int] = None
    momentum_alignment: Optional[float] = None
    distance_to_entry_pips: Optional[float] = None
    
    # Session Context
    trading_session: Optional[str] = None
    session_overlap: Optional[str] = None
    liquidity_level: Optional[str] = None
    market_time_et: Optional[str] = None
    
    # Risk Metrics
    risk_amount_usd: Optional[float] = None
    risk_percentage: Optional[float] = None
    rr_ratio: Optional[float] = None
    position_size_calculation: Optional[Dict] = None
    
    # Additional Context
    reasoning: Optional[List[str]] = None
    notes: Optional[str] = None
    is_weekend_test: bool = False
    
    # Tracking
    created_at: str = None
    updated_at: str = None
    sync_status: str = "pending"  # pending, synced, error
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON storage"""
        return asdict(self)
    
    def to_airtable_record(self) -> Dict:
        """Convert to Airtable-compatible record format"""
        # Map internal fields to Airtable field names
        return {
            # Order Info
            "OANDA Order ID": self.order_id,
            "Fill ID": self.trade_id,
            "Instrument": self.instrument,
            "Order Type": self.order_type,
            "Direction": self.direction,
            "Units": self.units,
            
            # Execution
            "Order Time": self.order_time,
            "Execution Time": self.execution_time,
            "Order Status": self.order_status,
            
            # Prices
            "Entry Price": self.entry_price,
            "Stop Loss": self.stop_loss_price,
            "Target Price": self.take_profit_price,
            "Current Price": self.current_price,
            "Filled Price": self.filled_price or self.entry_price,
            
            # Strategy
            "Setup Name": self.setup_name,
            "Strategy Tag": self.strategy_tag,
            "Strategy Variant": self.strategy_variant,
            
            # Market Analysis
            "Momentum Strength": self.momentum_strength,
            "Momentum Strength (Text)": self.momentum_strength_str,
            "Momentum Direction": self.momentum_direction_str,  # Use mapped version
            "Strategy Bias": self.strategy_bias_str,  # Use mapped version
            "Zone Position": self.zone_position,
            "Signal Confidence": self.signal_confidence,
            "Momentum Alignment": self.momentum_alignment,
            "Distance to Entry (Pips)": self.distance_to_entry_pips,
            
            # Session
            "Trading Session": self.trading_session,
            "Session Overlap": self.session_overlap,
            "Liquidity Level": self.liquidity_level,
            "Market Time ET": self.market_time_et,
            
            # Risk
            "Risk Amount (USD)": self.risk_amount_usd,
            "Risk Percentage": self.risk_percentage,
            "R:R Ratio Calculated": self.rr_ratio,
            
            # Context
            "Notes": self.notes,
            "Is Weekend Test": self.is_weekend_test,
            
            # Metadata
            "Created At": self.created_at,
            "Updated At": self.updated_at,
            "Sync Status": self.sync_status
        }


class EnhancedTradeLogger:
    """
    Enhanced trade logger that ensures all trades are properly logged
    with complete metadata for Airtable synchronization
    """
    
    def __init__(self, log_directory: str = None):
        """Initialize the enhanced trade logger"""
        if log_directory is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            log_directory = os.path.join(current_dir, 'trading_logs')
        
        self.log_directory = log_directory
        os.makedirs(self.log_directory, exist_ok=True)
        
        # Main comprehensive log file
        self.comprehensive_log_file = os.path.join(self.log_directory, 'comprehensive_trade_log.json')
        
        # Separate files for different stages
        self.pending_orders_file = os.path.join(self.log_directory, 'pending_orders.json')
        self.filled_trades_file = os.path.join(self.log_directory, 'filled_trades.json')
        self.cancelled_orders_file = os.path.join(self.log_directory, 'cancelled_orders.json')
        
        # Logger
        self.logger = logging.getLogger(__name__)
        
        # Load existing logs
        self.comprehensive_log: Dict[str, ComprehensiveTradeLog] = self._load_comprehensive_log()
        self.pending_orders: Dict[str, ComprehensiveTradeLog] = self._load_json_file(self.pending_orders_file)
        self.filled_trades: Dict[str, ComprehensiveTradeLog] = self._load_json_file(self.filled_trades_file)
        self.cancelled_orders: Dict[str, ComprehensiveTradeLog] = self._load_json_file(self.cancelled_orders_file)
        
        self.logger.info(f"Enhanced Trade Logger initialized with {len(self.comprehensive_log)} existing logs")
    
    def _load_comprehensive_log(self) -> Dict[str, ComprehensiveTradeLog]:
        """Load existing comprehensive log"""
        try:
            if os.path.exists(self.comprehensive_log_file):
                with open(self.comprehensive_log_file, 'r') as f:
                    data = json.load(f)
                # Convert back to ComprehensiveTradeLog objects
                logs = {}
                for key, log_dict in data.items():
                    try:
                        logs[key] = ComprehensiveTradeLog(**log_dict)
                    except Exception as e:
                        self.logger.warning(f"Could not load log entry {key}: {e}")
                return logs
        except Exception as e:
            self.logger.error(f"Error loading comprehensive log: {e}")
        return {}
    
    def _load_json_file(self, filepath: str) -> Dict:
        """Load a JSON file safely"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading {filepath}: {e}")
        return {}
    
    def _save_comprehensive_log(self):
        """Save the comprehensive log to file"""
        try:
            # Convert all logs to dictionaries
            data = {
                key: log.to_dict() 
                for key, log in self.comprehensive_log.items()
            }
            with open(self.comprehensive_log_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving comprehensive log: {e}")
    
    def _save_json_file(self, data: Dict, filepath: str):
        """Save data to JSON file"""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving {filepath}: {e}")
    
    def log_order_placement(self, order_data: Dict, metadata: Dict, strategy_context: Dict) -> str:
        """
        Log when an order is placed (LIMIT or MARKET)
        Returns the log entry key for tracking
        """
        try:
            # Create comprehensive log entry
            log_entry = ComprehensiveTradeLog(
                # Order info
                order_id=order_data.get('order_id', f"temp_{datetime.now().timestamp()}"),
                instrument=order_data['instrument'],
                order_type=order_data.get('order_type', 'MARKET'),
                direction=order_data['direction'],
                units=order_data['units'],
                
                # Timing
                order_time=order_data.get('order_time', datetime.now().isoformat()),
                order_status='PENDING',
                
                # Prices
                entry_price=order_data['entry_price'],
                stop_loss_price=order_data.get('stop_loss'),
                take_profit_price=order_data.get('take_profit'),
                current_price=order_data.get('current_price'),
                
                # Strategy metadata
                setup_name=metadata.get('setup_name', 'Unknown'),
                strategy_tag=metadata.get('strategy_tag', 'Unknown'),
                strategy_variant=metadata.get('strategy_variant'),
                
                # Market analysis
                momentum_strength=metadata.get('momentum_strength'),
                momentum_strength_str=metadata.get('momentum_strength_str'),
                momentum_direction=metadata.get('momentum_direction'),
                momentum_direction_str=metadata.get('momentum_direction_str'),
                strategy_bias=metadata.get('strategy_bias'),
                strategy_bias_str=metadata.get('strategy_bias_str'),
                zone_position=metadata.get('zone_position'),
                signal_confidence=metadata.get('signal_confidence'),
                momentum_alignment=metadata.get('momentum_alignment'),
                distance_to_entry_pips=metadata.get('distance_to_entry_pips'),
                
                # Session context
                trading_session=strategy_context.get('trading_session'),
                session_overlap=strategy_context.get('session_overlap'),
                liquidity_level=strategy_context.get('liquidity_level'),
                market_time_et=strategy_context.get('market_time_et'),
                
                # Risk metrics
                risk_amount_usd=order_data.get('risk_amount_usd'),
                risk_percentage=order_data.get('risk_percentage'),
                rr_ratio=order_data.get('rr_ratio'),
                position_size_calculation=order_data.get('position_size_calculation'),
                
                # Additional
                reasoning=metadata.get('reasoning', []),
                notes=metadata.get('notes'),
                is_weekend_test=strategy_context.get('is_weekend_test', False)
            )
            
            # Store in comprehensive log
            log_key = f"{log_entry.instrument}_{log_entry.order_id}"
            self.comprehensive_log[log_key] = log_entry
            
            # Also store in pending orders
            self.pending_orders[log_key] = log_entry.to_dict()
            
            # Save immediately
            self._save_comprehensive_log()
            self._save_json_file(self.pending_orders, self.pending_orders_file)
            
            self.logger.info(f"✅ Logged order placement: {log_key}")
            self.logger.info(f"   Setup: {log_entry.setup_name}")
            self.logger.info(f"   Strategy: {log_entry.strategy_tag} - {log_entry.strategy_variant}")
            self.logger.info(f"   Momentum: {log_entry.momentum_strength_str} ({log_entry.momentum_strength})")
            
            return log_key
            
        except Exception as e:
            self.logger.error(f"Error logging order placement: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def update_order_filled(self, order_id: str, fill_data: Dict):
        """Update log when an order is filled"""
        try:
            # Find the log entry
            log_key = None
            for key, log in self.comprehensive_log.items():
                if log.order_id == order_id:
                    log_key = key
                    break
            
            if not log_key:
                self.logger.warning(f"No log entry found for order {order_id}")
                return
            
            # Update the log entry
            log_entry = self.comprehensive_log[log_key]
            log_entry.trade_id = fill_data.get('trade_id')
            log_entry.execution_time = fill_data.get('execution_time', datetime.now().isoformat())
            log_entry.order_status = 'FILLED'
            log_entry.filled_price = fill_data.get('filled_price', log_entry.entry_price)
            log_entry.updated_at = datetime.now().isoformat()
            
            # Move from pending to filled
            if log_key in self.pending_orders:
                del self.pending_orders[log_key]
            self.filled_trades[log_key] = log_entry.to_dict()
            
            # Save
            self._save_comprehensive_log()
            self._save_json_file(self.pending_orders, self.pending_orders_file)
            self._save_json_file(self.filled_trades, self.filled_trades_file)
            
            self.logger.info(f"✅ Updated order fill: {order_id} -> Trade {log_entry.trade_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating order fill: {e}")
    
    def update_order_cancelled(self, order_id: str, reason: str = None):
        """Update log when an order is cancelled"""
        try:
            # Find the log entry
            log_key = None
            for key, log in self.comprehensive_log.items():
                if log.order_id == order_id:
                    log_key = key
                    break
            
            if not log_key:
                self.logger.warning(f"No log entry found for order {order_id}")
                return
            
            # Update the log entry
            log_entry = self.comprehensive_log[log_key]
            log_entry.order_status = 'CANCELLED'
            log_entry.updated_at = datetime.now().isoformat()
            if reason:
                log_entry.notes = f"{log_entry.notes or ''} | Cancelled: {reason}".strip(' |')
            
            # Move from pending to cancelled
            if log_key in self.pending_orders:
                del self.pending_orders[log_key]
            self.cancelled_orders[log_key] = log_entry.to_dict()
            
            # Save
            self._save_comprehensive_log()
            self._save_json_file(self.pending_orders, self.pending_orders_file)
            self._save_json_file(self.cancelled_orders, self.cancelled_orders_file)
            
            self.logger.info(f"✅ Updated order cancellation: {order_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating order cancellation: {e}")
    
    def get_unsyced_logs(self) -> List[ComprehensiveTradeLog]:
        """Get all logs that haven't been synced to Airtable"""
        return [
            log for log in self.comprehensive_log.values()
            if log.sync_status == 'pending'
        ]
    
    def mark_as_synced(self, log_keys: List[str]):
        """Mark logs as synced to Airtable"""
        for key in log_keys:
            if key in self.comprehensive_log:
                self.comprehensive_log[key].sync_status = 'synced'
                self.comprehensive_log[key].updated_at = datetime.now().isoformat()
        self._save_comprehensive_log()
    
    def get_trade_statistics(self) -> Dict:
        """Get statistics about logged trades"""
        total = len(self.comprehensive_log)
        pending = len(self.pending_orders)
        filled = len(self.filled_trades)
        cancelled = len(self.cancelled_orders)
        unsynced = len(self.get_unsyced_logs())
        
        # Strategy breakdown
        strategy_counts = {}
        for log in self.comprehensive_log.values():
            strategy = f"{log.strategy_tag}_{log.strategy_variant or 'base'}"
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        
        return {
            'total_logs': total,
            'pending_orders': pending,
            'filled_trades': filled,
            'cancelled_orders': cancelled,
            'unsynced_logs': unsynced,
            'strategy_breakdown': strategy_counts,
            'log_file': self.comprehensive_log_file
        }


# Singleton instance
_trade_logger_instance = None

def get_trade_logger() -> EnhancedTradeLogger:
    """Get or create the singleton trade logger instance"""
    global _trade_logger_instance
    if _trade_logger_instance is None:
        _trade_logger_instance = EnhancedTradeLogger()
    return _trade_logger_instance