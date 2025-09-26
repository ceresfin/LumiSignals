#!/usr/bin/env python3
"""
Fibonacci Strategy Naming Convention Generator
Generates detailed strategy names based on setup characteristics for RDS/Airtable logging
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class FibonacciStrategyNaming:
    """
    Generates detailed strategy names for Fibonacci trade setups
    
    Format: Fibonacci {Type} {Level} {Timeframe} {Direction} {Target}
    Example: "Fibonacci Retracement 61.8% M5 Trend Continuation Near Target"
    """
    
    def __init__(self):
        self.setup_types = {
            'retracement_continuation': 'Retracement',
            'retracement_reversal': 'Reversal',
            'breakout_extension': 'Breakout',
            'extension': 'Extension'
        }
        
        self.trend_directions = {
            'continuation': 'Trend Continuation',
            'reversal': 'Trend Reversal', 
            'breakout': 'Extension'
        }
        
        self.target_classifications = {
            'near': 'Near Target',
            'mid': 'Mid Target',
            'far': 'Far Target'
        }
    
    def generate_strategy_name(self, setup: Dict[str, Any], fibonacci_data: Dict[str, Any] = None, timeframe: str = 'M5') -> str:
        """
        Generate detailed strategy name from trade setup characteristics
        
        Args:
            setup: Trade setup dict containing setup details
            fibonacci_data: Fibonacci analysis data (for trend context)
            timeframe: Trading timeframe (M5, H1, etc.)
            
        Returns:
            Detailed strategy name string
        """
        try:
            # Determine strategy type and trend direction based on setup and context
            setup_type, trend_direction = self._determine_strategy_type_and_direction(setup, fibonacci_data)
            fibonacci_level = self._format_fibonacci_level(setup)
            target_classification = self._classify_target(setup)
            
            # Generate strategy name
            strategy_name = f"Fibonacci {setup_type} {fibonacci_level} {timeframe} {trend_direction} {target_classification}"
            
            logger.info(f"Generated strategy name: {strategy_name}")
            return strategy_name
            
        except Exception as e:
            logger.error(f"Error generating strategy name: {e}")
            # Fallback to basic name
            level = setup.get('retracement_level', 'Unknown')
            return f"Fibonacci {level} {timeframe} Strategy"
    
    def _determine_strategy_type_and_direction(self, setup: Dict[str, Any], fibonacci_data: Dict[str, Any] = None) -> tuple:
        """
        Determine strategy type and trend direction based on setup characteristics and Fibonacci context
        
        Returns:
            tuple: (setup_type, trend_direction)
        """
        setup_type_raw = setup.get('type', '').lower()
        retracement_level = self._get_numeric_retracement_level(setup)
        
        # Get Fibonacci trend context if available
        fib_direction = 'neutral'
        if fibonacci_data:
            fib_direction = fibonacci_data.get('direction', 'neutral').lower()
        
        # 1. BREAKOUT/EXTENSION STRATEGIES (100%+ levels or explicit breakout)
        if 'breakout' in setup_type_raw or retracement_level >= 100:
            return 'Breakout', 'Extension'
        
        # 2. DEEP RETRACEMENT LEVELS (78.6%+) - Can be EITHER continuation or reversal
        elif retracement_level >= 78.6:
            # Check setup characteristics to determine if expecting continuation or reversal
            risk_reward = setup.get('risk_reward_ratio', 0)
            
            # Heuristic: Higher R:R often indicates reversal trades (bigger moves expected)
            # Lower R:R often indicates continuation (smaller bounce expected)
            if risk_reward >= 2.5 or 'reversal' in setup.get('entry_reason', '').lower():
                return 'Reversal', 'Trend Reversal'
            else:
                return 'Retracement', 'Trend Continuation'
        
        # 3. NORMAL RETRACEMENT LEVELS (38.2%, 50%, 61.8%) - Always continuation
        else:
            return 'Retracement', 'Trend Continuation'
    
    def _get_numeric_retracement_level(self, setup: Dict[str, Any]) -> float:
        """Convert retracement level to numeric value for comparison"""
        retracement_level = setup.get('retracement_level', 0)
        
        if isinstance(retracement_level, str):
            try:
                # Extract numeric value from percentage string like "61.8%"
                numeric_value = float(retracement_level.replace('%', ''))
                # If it's already a percentage (61.8), return as is
                # If it's a decimal (0.618), convert to percentage
                return numeric_value if numeric_value > 1 else numeric_value * 100
            except:
                return 50.0  # Default fallback
        elif isinstance(retracement_level, (int, float)):
            # Convert decimal to percentage if needed
            return retracement_level if retracement_level > 1 else retracement_level * 100
        
        return 50.0  # Default fallback
    
    def _format_fibonacci_level(self, setup: Dict[str, Any]) -> str:
        """
        Format Fibonacci level consistently (e.g., "61.8%")
        """
        retracement_level = setup.get('retracement_level', '')
        
        if isinstance(retracement_level, str):
            # Already formatted as percentage
            if '%' in retracement_level:
                return retracement_level
            else:
                # Convert decimal string to percentage
                try:
                    level_float = float(retracement_level)
                    if level_float <= 1.0:
                        return f"{level_float * 100:.1f}%"
                    else:
                        return f"{level_float:.1f}%"
                except ValueError:
                    return retracement_level
        
        elif isinstance(retracement_level, (int, float)):
            # Convert numeric to percentage
            if retracement_level <= 1.0:
                return f"{retracement_level * 100:.1f}%"
            else:
                return f"{retracement_level:.1f}%"
        
        return "Unknown%"
    
    def _determine_trend_direction(self, setup: Dict[str, Any]) -> str:
        """
        Determine if this is trend continuation, reversal, or breakout
        """
        # Check if explicitly provided
        if 'trend_direction' in setup:
            direction = setup['trend_direction'].lower()
            if direction in self.trend_directions:
                return self.trend_directions[direction]
        
        # Determine from setup characteristics
        setup_type = setup.get('type', '').lower()
        retracement_level = setup.get('retracement_level', 0)
        
        # Convert percentage string to float if needed
        if isinstance(retracement_level, str):
            try:
                retracement_level = float(retracement_level.replace('%', '')) / 100
            except:
                retracement_level = 0.5
        
        # Logic for trend direction based on Fibonacci levels
        if 'breakout' in setup_type:
            return self.trend_directions['breakout']
        
        elif retracement_level >= 0.786:
            # Deep retracements often indicate potential reversal
            return self.trend_directions['reversal']
        
        elif retracement_level <= 0.618:
            # Shallow to moderate retracements typically continuation
            return self.trend_directions['continuation']
        
        else:
            # 61.8% to 78.6% - could be either, default to continuation
            return self.trend_directions['continuation']
    
    def _classify_target(self, setup: Dict[str, Any]) -> str:
        """
        Classify target as Near, Mid, or Far based on risk/reward ratio
        """
        risk_reward = setup.get('risk_reward_ratio', 0)
        
        if risk_reward <= 0:
            return self.target_classifications['near']  # Default for invalid R:R
        elif risk_reward <= 2.0:
            return self.target_classifications['near']   # Conservative: 1.67-2.0 R:R
        elif risk_reward <= 3.0:
            return self.target_classifications['mid']    # Moderate: 2.0-3.0 R:R
        else:
            return self.target_classifications['far']    # Aggressive: 3.0+ R:R
    
    def _determine_setup_type(self, setup: Dict[str, Any]) -> str:
        """
        Determine the basic setup type (Retracement, Breakout, etc.)
        """
        setup_type_raw = setup.get('type', '').lower()
        retracement_level = self._get_numeric_retracement_level(setup)
        
        # Determine setup type based on level and characteristics
        if 'breakout' in setup_type_raw or retracement_level >= 100:
            return 'Breakout'
        elif retracement_level >= 78.6:
            # Check if this is reversal or continuation based on context
            risk_reward = setup.get('risk_reward_ratio', 0)
            if risk_reward >= 2.5 or 'reversal' in setup.get('entry_reason', '').lower():
                return 'Reversal'
            else:
                return 'Retracement'
        else:
            return 'Retracement'
    
    def generate_short_code(self, setup: Dict[str, Any], timeframe: str = 'M5') -> str:
        """
        Generate short strategy code for Redis metadata storage
        
        Example: "FIB_RET_618_M5_CONT_NEAR"
        """
        try:
            # Setup type
            setup_type = self._determine_setup_type(setup)
            type_code = 'RET' if 'Retracement' in setup_type else 'BRK' if 'Breakout' in setup_type else 'EXT'
            
            # Fibonacci level
            level = self._format_fibonacci_level(setup).replace('%', '').replace('.', '')
            
            # Trend direction
            trend = self._determine_trend_direction(setup)
            trend_code = 'CONT' if 'Continuation' in trend else 'REV' if 'Reversal' in trend else 'BRK'
            
            # Target
            target = self._classify_target(setup)
            target_code = 'NEAR' if 'Near' in target else 'MID' if 'Mid' in target else 'FAR'
            
            return f"FIB_{type_code}_{level}_{timeframe}_{trend_code}_{target_code}"
            
        except Exception as e:
            logger.error(f"Error generating short code: {e}")
            return f"FIB_UNKNOWN_{timeframe}"
    
    def get_strategy_metadata(self, setup: Dict[str, Any], timeframe: str = 'M5') -> Dict[str, Any]:
        """
        Generate complete strategy metadata for Redis storage
        """
        return {
            'strategy_name': self.generate_strategy_name(setup, timeframe=timeframe),
            'strategy_code': self.generate_short_code(setup, timeframe),
            'strategy_type': 'fibonacci',
            'setup_type': self._determine_setup_type(setup),
            'fibonacci_level': self._format_fibonacci_level(setup),
            'trend_direction': self._determine_trend_direction(setup),
            'target_classification': self._classify_target(setup),
            'timeframe': timeframe,
            'risk_reward_ratio': setup.get('risk_reward_ratio', 0),
            'retracement_level': setup.get('retracement_level', ''),
            'entry_reason': setup.get('entry_reason', ''),
            'setup_quality': setup.get('setup_quality', 'medium')
        }


def test_strategy_naming():
    """Test the strategy naming function with sample setups"""
    naming = FibonacciStrategyNaming()
    
    # Test cases
    test_setups = [
        {
            'type': 'bullish',
            'retracement_level': '61.8%',
            'risk_reward_ratio': 1.75,
            'entry_reason': '61.8% Fibonacci retracement in uptrend'
        },
        {
            'type': 'bullish', 
            'retracement_level': '50.0%',
            'risk_reward_ratio': 2.5,
            'entry_reason': '50% Fibonacci retracement'
        },
        {
            'type': 'bearish',
            'retracement_level': '78.6%', 
            'risk_reward_ratio': 3.2,
            'entry_reason': 'Deep retracement reversal'
        },
        {
            'type': 'fibonacci_breakout',
            'retracement_level': '100%',
            'risk_reward_ratio': 2.1,
            'entry_reason': 'Breakout above previous high'
        }
    ]
    
    print("=== Fibonacci Strategy Naming Test ===\n")
    
    for i, setup in enumerate(test_setups, 1):
        print(f"Test {i}: {setup}")
        
        strategy_name = naming.generate_strategy_name(setup, timeframe='M5')
        short_code = naming.generate_short_code(setup, 'M5') 
        metadata = naming.get_strategy_metadata(setup, 'M5')
        
        print(f"  Strategy Name: {strategy_name}")
        print(f"  Short Code: {short_code}")
        print(f"  Metadata: {metadata}")
        print()


if __name__ == "__main__":
    test_strategy_naming()