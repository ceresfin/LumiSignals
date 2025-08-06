#!/usr/bin/env python3
"""
Example of Redis Integration in Existing Strategy Lambda Functions
This shows how to modify existing strategy functions to include Redis writes
"""

import json
import logging
import os
import boto3
from datetime import datetime
from redis_integration import RedisTradeWriter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def lambda_handler(event, context):
    """
    Enhanced Lambda handler with Redis integration
    This is the pattern to apply to all strategy functions
    """
    
    # Initialize Redis writer
    redis_writer = None
    try:
        redis_writer = RedisTradeWriter()
        logger.info("✅ Redis writer initialized")
    except Exception as e:
        logger.warning(f"⚠️ Redis writer not available: {str(e)}")
    
    try:
        # === EXISTING STRATEGY LOGIC (UNCHANGED) ===
        # Your existing strategy initialization code here
        strategy_name = os.environ.get('STRATEGY_NAME', 'Unknown_Strategy')
        
        # Market data analysis (your existing code)
        market_data = get_market_data()  # Your existing function
        analysis = analyze_market_conditions(market_data)  # Your existing function
        
        # === REDIS INTEGRATION POINT 1: SIGNAL GENERATION ===
        # Generate trading signal (your existing code)
        signal = generate_trading_signal(analysis)  # Your existing function
        
        if signal and redis_writer:
            # NEW: Write signal to Redis for real-time dashboard
            redis_writer.write_trade_signal(signal, strategy_name)
        
        # === EXISTING TRADE EXECUTION (UNCHANGED) ===
        if signal:
            # Execute trade via OANDA API (your existing code)
            trade_result = execute_trade_via_oanda(signal)  # Your existing function
            
            # === REDIS INTEGRATION POINT 2: TRADE EXECUTION ===
            if trade_result and not trade_result.get('error') and redis_writer:
                # NEW: Write trade execution to Redis
                redis_writer.write_trade_execution(trade_result, strategy_name)
            
            # Store to PostgreSQL (your existing code)
            store_to_database(trade_result)  # Your existing function
        
        # === REDIS INTEGRATION POINT 3: PERFORMANCE METRICS ===
        # Calculate performance metrics (your existing or new code)
        performance_metrics = calculate_performance_metrics(strategy_name)
        
        if performance_metrics and redis_writer:
            # NEW: Update performance in Redis
            redis_writer.update_strategy_performance(strategy_name, performance_metrics)
        
        # === CLEANUP ===
        if redis_writer:
            redis_writer.close()
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Strategy {strategy_name} executed successfully',
                'signal_generated': signal is not None,
                'trade_executed': signal is not None and 'trade_result' in locals(),
                'redis_enabled': redis_writer is not None,
                'timestamp': datetime.now().isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"Strategy execution failed: {str(e)}", exc_info=True)
        
        # Cleanup on error
        if redis_writer:
            redis_writer.close()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Strategy execution failed: {str(e)}',
                'strategy': strategy_name,
                'timestamp': datetime.now().isoformat()
            })
        }

# === EXAMPLE IMPLEMENTATIONS FOR REDIS INTEGRATION ===

def calculate_performance_metrics(strategy_name: str) -> dict:
    """
    Calculate strategy performance metrics
    Add this function to your existing strategies or enhance existing ones
    """
    try:
        # This would connect to your PostgreSQL database
        # and calculate metrics from trade history
        
        # Example metrics structure:
        return {
            'total_trades': 45,
            'winning_trades': 31,
            'losing_trades': 14,
            'win_rate': 0.689,
            'total_pnl': 1247.50,
            'avg_win': 65.32,
            'avg_loss': -28.75,
            'max_drawdown': -125.00,
            'current_positions': 3,
            'last_trade_time': datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error calculating performance metrics: {str(e)}")
        return {}

# === SPECIFIC INTEGRATION PATTERNS FOR DIFFERENT STRATEGY TYPES ===

class PennyCurveRedisIntegration:
    """
    Example Redis integration for Penny Curve strategies
    """
    
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.redis_writer = RedisTradeWriter()
    
    def enhance_signal_with_redis(self, signal: dict) -> dict:
        """
        Enhance signal generation with Redis writing
        """
        if signal and self.redis_writer:
            # Add Redis-specific metadata
            signal['redis_timestamp'] = datetime.now().isoformat()
            signal['strategy_id'] = self.strategy_name
            
            # Write to Redis
            self.redis_writer.write_trade_signal(signal, self.strategy_name)
            
            logger.info(f"📡 Penny Curve signal published: {signal['action']} {signal['instrument']}")
        
        return signal
    
    def record_penny_curve_trade(self, trade_data: dict) -> bool:
        """
        Record Penny Curve trade execution
        """
        if self.redis_writer:
            # Add Penny Curve specific metadata
            enhanced_trade = trade_data.copy()
            enhanced_trade.update({
                'strategy_family': 'PENNY_CURVE',
                'curve_level': self.extract_curve_level(trade_data),
                'breakout_direction': self.determine_breakout_direction(trade_data)
            })
            
            return self.redis_writer.write_trade_execution(enhanced_trade, self.strategy_name)
        
        return False
    
    def extract_curve_level(self, trade_data: dict) -> float:
        """Extract the penny level from trade data"""
        # Implementation specific to Penny Curve strategy
        price = float(trade_data.get('price', 0))
        return round(price, 4)  # Penny level precision
    
    def determine_breakout_direction(self, trade_data: dict) -> str:
        """Determine breakout direction for Penny Curve"""
        units = float(trade_data.get('units', 0))
        return 'LONG' if units > 0 else 'SHORT'

class DimeCurveRedisIntegration:
    """
    Example Redis integration for Dime Curve strategies
    """
    
    def __init__(self, strategy_name: str):
        self.strategy_name = strategy_name
        self.redis_writer = RedisTradeWriter()
    
    def enhance_dime_signal(self, signal: dict, dime_analysis: dict) -> dict:
        """
        Enhance Dime Curve signal with specific metadata
        """
        if signal and self.redis_writer:
            # Add Dime Curve specific data
            signal.update({
                'dime_level': dime_analysis.get('dime_level'),
                'volatility_factor': dime_analysis.get('volatility'),
                'momentum_strength': dime_analysis.get('momentum'),
                'strategy_family': 'DIME_CURVE'
            })
            
            self.redis_writer.write_trade_signal(signal, self.strategy_name)
            
        return signal

# === ENVIRONMENT VARIABLE UPDATES ===
"""
Add these environment variables to your strategy Lambda functions:

REDIS_SECRET_ARN=lumisignals/redis/prod-pg17/config
REDIS_ENABLED=true
STRATEGY_FAMILY=PENNY_CURVE  # or DIME_CURVE, QUARTER_CURVE, etc.
"""

# === VPC CONFIGURATION UPDATES ===
"""
Update your strategy Lambda functions to use the production VPC:

VPC: vpc-097d4b25c59a73135
Subnets: 
  - subnet-024cb586b3d5de7e9
  - subnet-03554baeba75f8b43
Security Groups:
  - sg-03ea8a57cd478f756 (with Redis access on port 6379)
"""

# === LAYER DEPENDENCIES ===
"""
Add the redis layer to your strategy functions:

Layers:
  - lumisignals-trading-common (existing)
  - lumisignals-pg8000 (existing)
  - lumisignals-trading-dependencies (existing)
  - lumisignals-redis-py (NEW - add this layer with redis-py library)
"""