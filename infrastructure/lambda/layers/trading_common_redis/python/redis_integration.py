"""
Redis Integration Module for LumiSignals Trading Strategies
Provides Redis connectivity and data writing capabilities for strategy functions
"""
import json
import logging
import os
import boto3
import redis
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import uuid

logger = logging.getLogger(__name__)

class RedisTradeWriter:
    """Handles Redis operations for trading strategy functions"""
    
    def __init__(self, redis_secret_name: str = "lumisignals/redis/market-data/auth-token"):
        self.redis_client = None
        self.redis_secret_name = redis_secret_name
        self._connect_redis()
    
    def _connect_redis(self) -> bool:
        """Establish Redis connection using AWS Secrets Manager"""
        try:
            secrets_client = boto3.client('secretsmanager')
            secret_response = secrets_client.get_secret_value(SecretId=self.redis_secret_name)
            redis_credentials = json.loads(secret_response['SecretString'])
            
            self.redis_client = redis.StrictRedis(
                host=redis_credentials['endpoint'],
                port=redis_credentials.get('port', 6379),
                password=redis_credentials.get('auth_token'),
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            
            # Test connection
            self.redis_client.ping()
            logger.info(f"✅ Redis connected successfully to {redis_credentials['endpoint']}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {str(e)}")
            self.redis_client = None
            return False
    
    def write_trade_signal(self, signal: Dict[str, Any], strategy_name: str) -> bool:
        """
        Write trading signal to Redis for real-time dashboard access
        
        Args:
            signal: Trading signal data from strategy
            strategy_name: Name of the strategy generating the signal
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.redis_client:
            logger.warning("Redis client not available, skipping signal write")
            return False
        
        # Protect against None strategy_name
        if strategy_name is None:
            strategy_name = "Unknown_Strategy"
            logger.warning("⚠️ strategy_name was None, using fallback: Unknown_Strategy")
        
        try:
            # Generate unique signal ID if not present
            signal_id = signal.get('signal_id', str(uuid.uuid4()))
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Prepare signal data for Redis with None protection
            redis_signal = {
                'signal_id': signal_id,
                'strategy_name': strategy_name,
                'instrument': signal.get('instrument') or 'UNKNOWN',
                'action': signal.get('action') or 'UNKNOWN',
                'order_type': signal.get('order_type', 'MARKET'),
                'entry_price': signal.get('entry_price') or 0.0,
                'stop_loss': signal.get('stop_loss') or 0.0,
                'take_profit': signal.get('take_profit') or 0.0,
                'risk_amount': signal.get('risk_amount') or 0.0,
                'rr_ratio': signal.get('rr_ratio') or 0.0,
                'confidence': signal.get('confidence') or 0,
                'reasoning': signal.get('reasoning', []),
                'timestamp': timestamp,
                'status': 'GENERATED'
            }
            
            # Write to individual signal key
            instrument = signal.get('instrument') or 'UNKNOWN'
            signal_key = f"signal:latest:{strategy_name}:{instrument}"
            self.redis_client.setex(signal_key, 3600, json.dumps(redis_signal, default=str))
            
            # Add to strategy signals list
            signals_list_key = f"signals:list:{strategy_name}"
            self.redis_client.lpush(signals_list_key, json.dumps(redis_signal, default=str))
            self.redis_client.ltrim(signals_list_key, 0, 49)  # Keep last 50 signals
            
            # Add to global signals stream
            self.redis_client.xadd("signals:stream", redis_signal, maxlen=1000)
            
            logger.info(f"✅ Signal written to Redis: {strategy_name} {signal.get('action') or 'UNKNOWN'} {instrument}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to write signal to Redis: {str(e)}")
            return False
    
    def write_trade_execution(self, trade_data: Dict[str, Any], strategy_name: str) -> bool:
        """
        Write trade execution to Redis for active trades tracking
        
        Args:
            trade_data: Trade execution data from OANDA API
            strategy_name: Name of the strategy that executed the trade
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.redis_client:
            logger.warning("Redis client not available, skipping trade write")
            return False
        
        try:
            trade_id = trade_data.get('trade_id') or trade_data.get('tradeID')
            if not trade_id:
                logger.warning("No trade_id found in trade_data, skipping Redis write")
                return False
            
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Prepare trade data for Redis - matching dashboard expectations
            redis_trade = {
                'id': trade_id,
                'instrument': trade_data.get('instrument'),
                'strategy': strategy_name,
                'direction': 'Long' if float(trade_data.get('units', 0)) > 0 else 'Short',
                'entry_price': float(trade_data.get('price', 0)),
                'current_price': float(trade_data.get('price', 0)),  # Will be updated by sync process
                'stop_loss': float(trade_data.get('stopLossPrice', 0)) if trade_data.get('stopLossPrice') else 0,
                'take_profit': float(trade_data.get('takeProfitPrice', 0)) if trade_data.get('takeProfitPrice') else 0,
                'units': abs(int(float(trade_data.get('units', 0)))),
                'unrealized_pnl': float(trade_data.get('unrealizedPL', 0)),
                'risk_reward_ratio': 2.0,  # Default, can be calculated
                'status': 'ACTIVE',
                'entry_time': timestamp,
                'time_opened': datetime.now().strftime('%H:%M'),
                'source': 'strategy_execution'
            }
            
            # Write to active trades hash
            active_trade_key = f"trade:active:{trade_id}"
            self.redis_client.hset(active_trade_key, mapping=redis_trade)
            self.redis_client.expire(active_trade_key, 86400)  # 24 hour expiry
            
            # Add to strategy active trades list
            strategy_trades_key = f"trades:active:{strategy_name}"
            self.redis_client.sadd(strategy_trades_key, trade_id)
            self.redis_client.expire(strategy_trades_key, 86400)
            
            # Add to global active trades set
            self.redis_client.sadd("trades:active:all", trade_id)
            
            # Write to trade execution stream
            self.redis_client.xadd("trades:executions:stream", redis_trade, maxlen=5000)
            
            logger.info(f"✅ Trade written to Redis: {strategy_name} trade {trade_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to write trade to Redis: {str(e)}")
            return False
    
    def update_strategy_performance(self, strategy_name: str, performance_data: Dict[str, Any]) -> bool:
        """
        Update strategy performance metrics in Redis
        
        Args:
            strategy_name: Name of the strategy
            performance_data: Performance metrics
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.redis_client:
            return False
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Prepare performance data
            redis_performance = {
                'strategy_name': strategy_name,
                'total_trades': performance_data.get('total_trades', 0),
                'winning_trades': performance_data.get('winning_trades', 0),
                'losing_trades': performance_data.get('losing_trades', 0),
                'win_rate': performance_data.get('win_rate', 0.0),
                'total_pnl': performance_data.get('total_pnl', 0.0),
                'avg_win': performance_data.get('avg_win', 0.0),
                'avg_loss': performance_data.get('avg_loss', 0.0),
                'max_drawdown': performance_data.get('max_drawdown', 0.0),
                'sharpe_ratio': performance_data.get('sharpe_ratio', 0.0),
                'last_updated': timestamp
            }
            
            # Write to strategy performance key
            performance_key = f"strategy:performance:{strategy_name}"
            self.redis_client.hset(performance_key, mapping=redis_performance)
            self.redis_client.expire(performance_key, 3600)  # 1 hour expiry
            
            logger.info(f"✅ Strategy performance updated in Redis: {strategy_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update strategy performance in Redis: {str(e)}")
            return False
    
    def close(self):
        """Close Redis connection"""
        if self.redis_client:
            try:
                self.redis_client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {str(e)}")

# Convenience function for easy integration
def get_redis_writer() -> Optional[RedisTradeWriter]:
    """Get a Redis writer instance"""
    try:
        return RedisTradeWriter()
    except Exception as e:
        logger.error(f"Failed to create Redis writer: {str(e)}")
        return None