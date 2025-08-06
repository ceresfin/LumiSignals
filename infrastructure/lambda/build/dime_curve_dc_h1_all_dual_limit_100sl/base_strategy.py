#!/usr/bin/env python3
"""
Base Strategy Template for Renaissance Trading Strategies
Modified for AWS Lambda - no file system writes
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import logging
import os
from datetime import datetime

class BaseRenaissanceStrategy(ABC):
    """
    Abstract base class for all Renaissance strategies
    Provides common functionality for building, debugging, testing
    """
    
    def __init__(self, strategy_id: str, config: Dict):
        self.strategy_id = strategy_id
        self.config = config
        self.logger = self._setup_logger()
        
        # Debug mode flags
        self.debug_mode = config.get('debug_mode', False)
        self.log_signals = config.get('log_signals', False)
        self.save_analysis = config.get('save_analysis', False)
        
        # Performance tracking
        self.trade_history = []
        self.signal_history = []
        self.analysis_history = []
        
        # Strategy metadata
        parts = strategy_id.split('_')
        if len(parts) >= 5:
            self.desk = parts[0]           # REN
            self.strategy_type = parts[1]  # PC, QC, DC, HYBRID
            self.timeframe = parts[2]      # H1, M15, etc.
            self.session = parts[3]        # NY, LON, ASIA, ALL
            self.variant = parts[4]        # 001, 002, etc.
        
    def _setup_logger(self) -> logging.Logger:
        """Setup strategy-specific logger for Lambda environment"""
        logger = logging.getLogger(self.strategy_id)
        logger.setLevel(logging.DEBUG if self.config.get('debug_mode', False) else logging.INFO)
        
        # For Lambda, only use console handler
        if not logger.handlers:
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG if self.config.get('debug_mode', False) else logging.INFO)
            
            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            ch.setFormatter(formatter)
            logger.addHandler(ch)
        
        return logger
    
    @abstractmethod
    def analyze_market(self, market_data: Dict) -> Dict:
        """Analyze market conditions and generate analysis"""
        pass
    
    @abstractmethod
    def generate_signal(self, analysis: Dict) -> Optional[Dict]:
        """Generate trading signal from analysis"""
        pass
    
    @abstractmethod
    def validate_signal(self, signal: Dict) -> Tuple[bool, str]:
        """Validate trading signal before execution"""
        pass
    
    @abstractmethod
    def calculate_position_size(self, signal: Dict, account_balance: float) -> float:
        """Calculate position size based on risk management"""
        pass
    
    def execute_strategy(self, market_data: Dict) -> Optional[Dict]:
        """Main strategy execution with debugging"""
        try:
            # Log market data if in debug mode
            if self.debug_mode:
                self.logger.debug(f"Market data: {market_data}")
            
            # Analyze market
            analysis = self.analyze_market(market_data)
            
            if self.save_analysis:
                self.analysis_history.append(analysis)
            
            # Generate signal
            signal = self.generate_signal(analysis)
            
            if signal and self.log_signals:
                self.logger.info(f"Signal generated: {signal}")
                self.signal_history.append(signal)
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Strategy execution error: {str(e)}", exc_info=True)
            return None