"""
Strategy Name Mapper - Lambda-compatible strategy resolution
Maps trade IDs and metadata to real strategy names instead of dummy values
"""

import re
from typing import Dict, Optional, Any
import structlog

logger = structlog.get_logger()


class StrategyMapper:
    """
    Maps trade IDs and metadata to actual strategy names
    Compatible with Lambda strategy naming conventions
    """
    
    # Strategy configurations from Lambda dashboard API
    STRATEGY_CONFIGS = {
        # Penny Curve Strategies
        'str1_Penny_Curve_Strategy': {'name': 'Penny Curve Main', 'type': 'PC', 'timeframe': 'H1'},
        'penny_curve_pc_h1_all_dual_limit_20sl': {'name': 'PC H1 Dual Limit 20SL', 'type': 'PC', 'timeframe': 'H1'},
        'penny_curve_pc_h1_all_dual_limit_20sl_v2': {'name': 'PC H1 Dual Limit v2', 'type': 'PC', 'timeframe': 'H1'},
        
        # Dime Curve Strategies
        'str1_Dime_Curve_Strategies': {'name': 'Dime Curve Main', 'type': 'DC', 'timeframe': 'H1'},
        'dime_curve_dc_h1_all_dual_limit_100sl': {'name': 'DC H1 Dual Limit 100SL', 'type': 'DC', 'timeframe': 'H1'},
        
        # Quarter Curve Strategies
        'str1_Quarter_Curve_Butter_Strategy': {'name': 'Quarter Curve Butter', 'type': 'QC', 'timeframe': 'H1'},
        'quarter_curve_qc_h1_all_dual_limit_50sl': {'name': 'QC H1 Dual Limit 50SL', 'type': 'QC', 'timeframe': 'H1'},
        
        # Additional strategies from deployments
        'momentum_m5_strategy': {'name': 'Momentum M5', 'type': 'MOM', 'timeframe': 'M5'},
        'scalping_m1_strategy': {'name': 'Scalping M1', 'type': 'SCALP', 'timeframe': 'M1'},
        'breakout_h4_strategy': {'name': 'Breakout H4', 'type': 'BO', 'timeframe': 'H4'},
        'reversal_d1_strategy': {'name': 'Reversal Daily', 'type': 'REV', 'timeframe': 'D'},
    }
    
    # Trade ID patterns that might indicate strategy origin
    TRADE_ID_PATTERNS = {
        r'PC.*': 'Penny Curve',
        r'DC.*': 'Dime Curve', 
        r'QC.*': 'Quarter Curve',
        r'MOM.*': 'Momentum',
        r'SCALP.*': 'Scalping',
        r'BO.*': 'Breakout',
        r'REV.*': 'Reversal',
    }
    
    # Client extensions mapping (if OANDA trades have extensions)
    CLIENT_EXTENSION_MAPPING = {
        'dime_curve': 'Dime Curve DC H1 Dual Limit 100SL',
        'penny_curve': 'Penny Curve PC H1 Dual Limit 20SL',
        'quarter_curve': 'Quarter Curve QC H1 Dual Limit 50SL',
        'momentum': 'Momentum M5',
        'scalping': 'Scalping M1',
        'breakout': 'Breakout H4',
        'reversal': 'Reversal Daily',
    }
    
    def __init__(self):
        self.cache: Dict[str, str] = {}
        
    def get_strategy_name(self, trade_data: Dict[str, Any]) -> str:
        """
        Determine strategy name from trade data
        Uses multiple heuristics to map trades to actual strategies
        """
        
        # Try trade ID if available
        trade_id = trade_data.get('id', trade_data.get('trade_id', ''))
        if trade_id and str(trade_id) in self.cache:
            return self.cache[str(trade_id)]
        
        # Method 1: Check client extensions (highest priority)
        strategy_from_extensions = self._get_strategy_from_client_extensions(trade_data)
        if strategy_from_extensions:
            if trade_id:
                self.cache[str(trade_id)] = strategy_from_extensions
            return strategy_from_extensions
        
        # Method 2: Check trade ID patterns
        strategy_from_id = self._get_strategy_from_trade_id(trade_id)
        if strategy_from_id:
            if trade_id:
                self.cache[str(trade_id)] = strategy_from_id
            return strategy_from_id
        
        # Method 3: Analyze trade characteristics
        strategy_from_characteristics = self._get_strategy_from_characteristics(trade_data)
        if strategy_from_characteristics:
            if trade_id:
                self.cache[str(trade_id)] = strategy_from_characteristics
            return strategy_from_characteristics
        
        # Method 4: Return None for unidentifiable strategies (no dummy data)
        logger.debug(f"Could not identify strategy for trade {trade_id} - returning None")
        
        if trade_id:
            self.cache[str(trade_id)] = None
        return None
    
    def _get_strategy_from_client_extensions(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """Extract strategy from OANDA client extensions"""
        
        # Check clientExtensions field
        client_ext = trade_data.get('clientExtensions', {})
        if isinstance(client_ext, dict):
            # Check comment field
            comment = client_ext.get('comment', '').lower()
            for key, strategy_name in self.CLIENT_EXTENSION_MAPPING.items():
                if key in comment:
                    logger.debug(f"Found strategy from client extension comment: {strategy_name}")
                    return strategy_name
                    
            # Check id field
            ext_id = client_ext.get('id', '').lower()
            for key, strategy_name in self.CLIENT_EXTENSION_MAPPING.items():
                if key in ext_id:
                    logger.debug(f"Found strategy from client extension ID: {strategy_name}")
                    return strategy_name
        
        return None
    
    def _get_strategy_from_trade_id(self, trade_id: str) -> Optional[str]:
        """Extract strategy from trade ID patterns"""
        if not trade_id:
            return None
            
        trade_id_str = str(trade_id).upper()
        
        for pattern, strategy_type in self.TRADE_ID_PATTERNS.items():
            if re.match(pattern, trade_id_str):
                logger.debug(f"Matched trade ID pattern {pattern} -> {strategy_type}")
                return strategy_type
        
        return None
    
    def _get_strategy_from_characteristics(self, trade_data: Dict[str, Any]) -> Optional[str]:
        """
        Infer strategy from trade characteristics like:
        - Units size patterns
        - Stop loss levels
        - Take profit patterns
        - Currency pairs
        """
        
        # Get trade characteristics
        units = abs(float(trade_data.get('currentUnits', trade_data.get('units', 0))))
        currency_pair = trade_data.get('instrument', '')
        
        # Analyze stop loss if available
        stop_loss_distance = self._get_stop_loss_distance(trade_data)
        
        # Strategy inference based on characteristics
        if stop_loss_distance:
            # Large stop loss (100+ pips) -> Dime Curve
            if stop_loss_distance >= 0.01:  # 100 pips for major pairs
                return 'Dime Curve DC H1 Dual Limit 100SL'
            # Medium stop loss (50 pips) -> Quarter Curve  
            elif stop_loss_distance >= 0.005:  # 50 pips
                return 'Quarter Curve QC H1 Dual Limit 50SL'
            # Small stop loss (20 pips) -> Penny Curve
            elif stop_loss_distance >= 0.002:  # 20 pips
                return 'Penny Curve PC H1 Dual Limit 20SL'
        
        # Analyze units size patterns
        if units > 0:
            # Very large positions -> Scalping/Short-term
            if units >= 100000:
                return 'Scalping M1'
            # Large positions -> Main strategies
            elif units >= 50000:
                return 'Dime Curve DC H1 Dual Limit 100SL'
            # Medium positions -> Secondary strategies
            elif units >= 25000:
                return 'Penny Curve PC H1 Dual Limit 20SL'
            # Small positions -> Conservative strategies
            else:
                return 'Quarter Curve QC H1 Dual Limit 50SL'
        
        return None
    
    def _get_stop_loss_distance(self, trade_data: Dict[str, Any]) -> Optional[float]:
        """Calculate stop loss distance from current price"""
        try:
            current_price = float(trade_data.get('price', 0))
            stop_loss_price = float(trade_data.get('stopLossOrder', {}).get('price', 0))
            
            if current_price > 0 and stop_loss_price > 0:
                return abs(current_price - stop_loss_price)
        except (ValueError, TypeError, KeyError):
            pass
        
        return None
    
    def get_strategy_tag(self, strategy_name: str) -> str:
        """Get short strategy tag from full strategy name"""
        
        if 'Dime Curve' in strategy_name:
            return 'DC'
        elif 'Penny Curve' in strategy_name:
            return 'PC'
        elif 'Quarter Curve' in strategy_name:
            return 'QC'
        elif 'Momentum' in strategy_name:
            return 'MOM'
        elif 'Scalping' in strategy_name:
            return 'SCALP'
        elif 'Breakout' in strategy_name:
            return 'BO'
        elif 'Reversal' in strategy_name:
            return 'REV'
        else:
            return 'AUTO'
    
    def get_setup_name(self, strategy_name: str) -> str:
        """Get setup name from strategy name"""
        
        # Extract setup pattern from strategy name
        if 'DC H1 Dual Limit 100SL' in strategy_name:
            return 'DC_H1_ALL_DUAL_LIMIT_100SL'
        elif 'PC H1 Dual Limit 20SL' in strategy_name:
            return 'PC_H1_ALL_DUAL_LIMIT_20SL'
        elif 'QC H1 Dual Limit 50SL' in strategy_name:
            return 'QC_H1_ALL_DUAL_LIMIT_50SL'
        elif 'M5' in strategy_name:
            return 'MOMENTUM_M5_SETUP'
        elif 'M1' in strategy_name:
            return 'SCALPING_M1_SETUP'
        elif 'H4' in strategy_name:
            return 'BREAKOUT_H4_SETUP'
        elif 'Daily' in strategy_name:
            return 'REVERSAL_D1_SETUP'
        else:
            return 'AUTO_TRADING_SETUP'