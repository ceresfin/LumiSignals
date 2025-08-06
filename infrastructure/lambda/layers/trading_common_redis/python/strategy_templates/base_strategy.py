#!/usr/bin/env python3
"""
Base Strategy Template for Renaissance Trading Strategies
Provides common functionality for building, debugging, testing, and optimization
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
        """Setup strategy-specific logger for debugging"""
        logger = logging.getLogger(self.strategy_id)
        logger.setLevel(logging.DEBUG)
        
        # Ensure debug_logs directory exists
        log_dir = 'debugging/debug_logs'
        os.makedirs(log_dir, exist_ok=True)
        
        # File handler for strategy logs
        log_file = os.path.join(log_dir, f'{self.strategy_id}.log')
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        
        # Console handler for important messages
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        
        # Avoid duplicate handlers
        if not logger.handlers:
            logger.addHandler(fh)
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
                self.analysis_history.append({
                    'timestamp': datetime.now(),
                    'analysis': analysis
                })
            
            # Generate signal
            signal = self.generate_signal(analysis)
            
            if signal and self.log_signals:
                self.signal_history.append(signal)
                self.logger.info(f"Signal generated: {signal['action']} {signal['instrument']}")
            
            if signal:
                # Validate signal
                is_valid, reason = self.validate_signal(signal)
                
                if not is_valid:
                    self.logger.warning(f"Signal rejected: {reason}")
                    return None
                
                # Add analysis context to signal
                signal['analysis'] = analysis
                
            return signal
            
        except Exception as e:
            self.logger.error(f"Strategy execution error: {e}", exc_info=True)
            return None
    
    def get_performance_summary(self) -> Dict:
        """Get current performance metrics"""
        return {
            'strategy_id': self.strategy_id,
            'strategy_type': getattr(self, 'strategy_type', 'UNKNOWN'),
            'timeframe': getattr(self, 'timeframe', 'UNKNOWN'),
            'session': getattr(self, 'session', 'UNKNOWN'),
            'total_signals': len(self.signal_history),
            'total_trades': len(self.trade_history),
            'config': self.config,
            'debug_mode': self.debug_mode
        }
    
    def get_debug_info(self) -> Dict:
        """Get debugging information"""
        return {
            'strategy_id': self.strategy_id,
            'analysis_history_count': len(self.analysis_history),
            'signal_history_count': len(self.signal_history),
            'trade_history_count': len(self.trade_history),
            'last_analysis': self.analysis_history[-1] if self.analysis_history else None,
            'last_signal': self.signal_history[-1] if self.signal_history else None,
            'debug_settings': {
                'debug_mode': self.debug_mode,
                'log_signals': self.log_signals,
                'save_analysis': self.save_analysis
            }
        }
    
    def reset_history(self):
        """Reset all history for fresh start"""
        self.trade_history.clear()
        self.signal_history.clear()
        self.analysis_history.clear()
        self.logger.info(f"History reset for {self.strategy_id}")
    
    def save_state(self, filepath: str):
        """Save strategy state to file"""
        import json
        
        state = {
            'strategy_id': self.strategy_id,
            'config': self.config,
            'trade_history': self.trade_history,
            'signal_history': self.signal_history,
            'analysis_history': self.analysis_history,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        
        self.logger.info(f"Strategy state saved to {filepath}")
    
    def load_state(self, filepath: str):
        """Load strategy state from file"""
        import json
        
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            self.trade_history = state.get('trade_history', [])
            self.signal_history = state.get('signal_history', [])
            self.analysis_history = state.get('analysis_history', [])
            
            self.logger.info(f"Strategy state loaded from {filepath}")
            
        except Exception as e:
            self.logger.error(f"Failed to load state from {filepath}: {e}")

def test_base_strategy():
    """Test the base strategy functionality"""
    
    # Create a mock strategy for testing
    class MockStrategy(BaseRenaissanceStrategy):
        def __init__(self, config):
            super().__init__("REN_TEST_H1_ALL_001", config)
            
        def analyze_market(self, market_data: Dict) -> Dict:
            return {
                'instrument': market_data['instrument'],
                'current_price': market_data['current_price'],
                'test_analysis': True
            }
        
        def generate_signal(self, analysis: Dict) -> Optional[Dict]:
            if analysis.get('test_analysis'):
                return {
                    'action': 'BUY',
                    'instrument': analysis['instrument'],
                    'entry_price': analysis['current_price'],
                    'confidence': 75
                }
            return None
        
        def validate_signal(self, signal: Dict) -> Tuple[bool, str]:
            if signal and signal.get('confidence', 0) > 50:
                return True, "Signal validated"
            return False, "Low confidence"
        
        def calculate_position_size(self, signal: Dict, account_balance: float) -> float:
            return 1000.0  # Mock position size
    
    # Test the mock strategy
    config = {
        'debug_mode': True,
        'log_signals': True,
        'save_analysis': True
    }
    
    strategy = MockStrategy(config)
    
    market_data = {
        'instrument': 'EUR_USD',
        'current_price': 1.1850
    }
    
    signal = strategy.execute_strategy(market_data)
    
    if signal:
        print(f"✅ Generated signal: {signal['action']} {signal['instrument']}")
        print(f"   Entry: {signal['entry_price']}, Confidence: {signal['confidence']}%")
    else:
        print("❌ No signal generated")
    
    # Test performance summary
    summary = strategy.get_performance_summary()
    print(f"\n📊 Performance Summary:")
    for key, value in summary.items():
        print(f"   {key}: {value}")

if __name__ == "__main__":
    test_base_strategy()