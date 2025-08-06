#!/usr/bin/env python3
"""
Redis-Enhanced Base Strategy Template for Renaissance Trading Strategies
Extends the base strategy with Redis integration for real-time dashboard data
"""

from .base_strategy import BaseRenaissanceStrategy
from redis_integration import RedisTradeWriter
from typing import Dict, List, Optional, Tuple
import logging
import os
from datetime import datetime

class RedisEnhancedStrategy(BaseRenaissanceStrategy):
    """
    Enhanced base strategy with Redis integration for real-time data
    """
    
    def __init__(self, strategy_id: str, config: Dict):
        super().__init__(strategy_id, config)
        
        # Initialize Redis writer
        self.redis_writer = None
        try:
            self.redis_writer = RedisTradeWriter()
            self.logger.info("✅ Redis integration enabled for strategy")
        except Exception as e:
            self.logger.warning(f"⚠️ Redis integration not available: {str(e)}")
    
    def execute_strategy_with_redis(self, market_data: Dict) -> Optional[Dict]:
        """
        Enhanced strategy execution with Redis integration
        """
        try:
            # Execute base strategy logic
            signal = self.execute_strategy(market_data)
            
            if signal and self.redis_writer:
                # Write signal to Redis for real-time dashboard
                success = self.redis_writer.write_trade_signal(
                    signal, 
                    self.strategy_id
                )
                
                if success:
                    self.logger.info(f"📡 Signal published to Redis: {signal['action']} {signal['instrument']}")
                else:
                    self.logger.warning("⚠️ Failed to publish signal to Redis")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Strategy execution error: {e}", exc_info=True)
            return None
    
    def record_trade_execution(self, trade_data: Dict) -> bool:
        """
        Record trade execution in both local history and Redis
        
        Args:
            trade_data: Trade execution data from broker API
        
        Returns:
            bool: True if successfully recorded
        """
        try:
            # Record in local history (existing functionality)
            self.trade_history.append({
                'timestamp': datetime.now(),
                'trade_data': trade_data
            })
            
            # Write to Redis if available
            if self.redis_writer:
                success = self.redis_writer.write_trade_execution(
                    trade_data, 
                    self.strategy_id
                )
                
                if success:
                    self.logger.info(f"💰 Trade execution recorded in Redis: Trade {trade_data.get('trade_id')}")
                    return True
                else:
                    self.logger.warning("⚠️ Failed to record trade execution in Redis")
                    return False
            else:
                self.logger.warning("⚠️ Redis not available for trade recording")
                return False
                
        except Exception as e:
            self.logger.error(f"Error recording trade execution: {str(e)}")
            return False
    
    def update_performance_metrics(self, metrics: Dict) -> bool:
        """
        Update strategy performance metrics in Redis
        
        Args:
            metrics: Performance metrics dictionary
        
        Returns:
            bool: True if successfully updated
        """
        try:
            if self.redis_writer:
                success = self.redis_writer.update_strategy_performance(
                    self.strategy_id,
                    metrics
                )
                
                if success:
                    self.logger.info(f"📊 Performance metrics updated in Redis")
                    return True
                else:
                    self.logger.warning("⚠️ Failed to update performance metrics in Redis")
                    return False
            else:
                self.logger.warning("⚠️ Redis not available for performance update")
                return False
                
        except Exception as e:
            self.logger.error(f"Error updating performance metrics: {str(e)}")
            return False
    
    def get_enhanced_performance_summary(self) -> Dict:
        """
        Get performance summary with Redis status
        """
        base_summary = self.get_performance_summary()
        
        # Add Redis status
        base_summary.update({
            'redis_enabled': self.redis_writer is not None,
            'redis_status': 'connected' if self.redis_writer else 'disconnected',
            'last_redis_signal': datetime.now().isoformat() if self.signal_history else None,
            'last_redis_trade': datetime.now().isoformat() if self.trade_history else None
        })
        
        return base_summary
    
    def cleanup(self):
        """
        Cleanup strategy resources including Redis connection
        """
        try:
            if self.redis_writer:
                self.redis_writer.close()
                self.logger.info("🔌 Redis connection closed")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        self.cleanup()

# Convenience function for creating Redis-enhanced strategies
def create_redis_strategy(strategy_id: str, config: Dict) -> RedisEnhancedStrategy:
    """
    Create a Redis-enhanced strategy instance
    
    Args:
        strategy_id: Unique strategy identifier
        config: Strategy configuration dictionary
    
    Returns:
        RedisEnhancedStrategy: Strategy instance with Redis integration
    """
    return RedisEnhancedStrategy(strategy_id, config)