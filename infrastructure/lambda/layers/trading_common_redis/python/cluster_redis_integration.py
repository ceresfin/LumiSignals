"""
Redis Cluster Integration for Lambda Functions

ARCHITECTURE UPGRADE:
- Eliminates manual sharding logic from Lambda functions
- Uses single Redis Cluster endpoint
- Automatic key distribution across 4 shards
- Compatible with 100+ trading strategies
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import redis

# Configure logging
logger = logging.getLogger(__name__)


class ClusterRedisTradeWriter:
    """
    Redis Cluster writer for Lambda trading strategies
    
    Key Changes from Manual Sharding:
    - Single cluster endpoint (no shard selection logic)
    - Automatic key distribution by Redis
    - Simplified connection management  
    - Scales automatically for all strategies
    """
    
    def __init__(self, cluster_endpoint: str, auth_token: Optional[str] = None):
        """
        Initialize Redis Cluster connection
        
        Args:
            cluster_endpoint: Single configuration endpoint for Redis Cluster
            auth_token: Optional authentication token
        """
        self.cluster_endpoint = cluster_endpoint
        self.auth_token = auth_token
        self._client = None
        
        logger.info(f"Initializing Redis Cluster writer: {cluster_endpoint}")
    
    def _get_client(self):
        """Get or create Redis Cluster client"""
        if self._client is None:
            try:
                # Create Redis Cluster client - much simpler than manual sharding!
                self._client = redis.RedisCluster(
                    host=self.cluster_endpoint,
                    port=6379,
                    password=self.auth_token,
                    decode_responses=True,
                    skip_full_coverage_check=True,  # Good for AWS ElastiCache
                    socket_connect_timeout=10,
                    socket_timeout=10,
                    retry_on_timeout=True,
                    max_connections_per_node=10
                )
                
                # Test connection
                self._client.ping()
                logger.info("✅ Redis Cluster connection established")
                
            except Exception as e:
                logger.error(f"❌ Redis Cluster connection failed: {e}")
                raise
        
        return self._client
    
    def write_trade_signal(self, signal_data: Dict[str, Any], strategy_name: str) -> bool:
        """
        Write trade signal to Redis Cluster
        
        No manual sharding logic needed - Redis handles distribution automatically!
        """
        try:
            client = self._get_client()
            
            signal_id = signal_data.get('signal_id', f"signal_{int(datetime.now().timestamp())}")
            
            # Simple keys - Redis Cluster handles the routing
            signal_key = f"trade_signals:{strategy_name}:{signal_id}"
            latest_key = f"trade_signals:{strategy_name}:latest"
            
            # Serialize signal data
            serialized_signal = json.dumps(signal_data, default=str)
            
            # Write to cluster - automatic shard selection!
            pipe = client.pipeline()
            pipe.setex(signal_key, 7200, serialized_signal)  # 2 hour TTL
            pipe.setex(latest_key, 7200, serialized_signal)
            pipe.execute()
            
            logger.info(f"✅ Signal written to cluster: {strategy_name}/{signal_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to write signal for {strategy_name}: {e}")
            return False
    
    def write_trade_execution(self, trade_data: Dict[str, Any]) -> bool:
        """
        Write trade execution data to Redis Cluster
        """
        try:
            client = self._get_client()
            
            trade_id = trade_data.get('trade_id')
            if not trade_id:
                logger.error("Trade ID missing from trade data")
                return False
            
            # Simple key - automatic distribution
            trade_key = f"trade:active:{trade_id}"
            
            # Add timestamp
            trade_data['last_updated'] = datetime.now().isoformat()
            
            # Serialize and write
            serialized_trade = json.dumps(trade_data, default=str)
            client.setex(trade_key, 86400, serialized_trade)  # 24 hour TTL
            
            logger.info(f"✅ Trade execution written to cluster: {trade_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to write trade execution: {e}")
            return False
    
    def update_strategy_performance(self, strategy_name: str, performance_data: Dict[str, Any]) -> bool:
        """
        Update strategy performance metrics
        """
        try:
            client = self._get_client()
            
            # Performance key - automatic sharding
            performance_key = f"strategy:performance:{strategy_name}"
            
            # Add timestamp
            performance_data['last_updated'] = datetime.now().isoformat()
            
            # Serialize and write
            serialized_perf = json.dumps(performance_data, default=str)
            client.setex(performance_key, 86400, serialized_perf)  # 24 hour TTL
            
            logger.info(f"✅ Performance updated for {strategy_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update performance for {strategy_name}: {e}")
            return False
    
    def read_market_data(self, currency_pair: str) -> Optional[Dict[str, Any]]:
        """
        Read market data from Redis Cluster
        """
        try:
            client = self._get_client()
            
            # Simple key - Redis routes to correct shard automatically
            market_key = f"market_data:{currency_pair}:current"
            data = client.get(market_key)
            
            if data:
                return json.loads(data)
            else:
                logger.debug(f"No market data found for {currency_pair}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Failed to read market data for {currency_pair}: {e}")
            return None
    
    def get_cluster_status(self) -> Dict[str, Any]:
        """
        Get Redis Cluster health status
        """
        try:
            client = self._get_client()
            
            # Get cluster information
            cluster_info = client.cluster_info()
            
            return {
                "healthy": cluster_info.get('cluster_state') == 'ok',
                "cluster_state": cluster_info.get('cluster_state'),
                "slots_assigned": cluster_info.get('cluster_slots_assigned'),
                "cluster_size": cluster_info.get('cluster_size'),
                "endpoint": self.cluster_endpoint,
                "automatic_sharding": True
            }
            
        except Exception as e:
            logger.error(f"❌ Cluster status check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "endpoint": self.cluster_endpoint
            }
    
    def close(self):
        """Close Redis Cluster connection"""
        if self._client:
            try:
                self._client.close()
                logger.info("Redis Cluster connection closed")
            except Exception as e:
                logger.error(f"Error closing cluster connection: {e}")
            finally:
                self._client = None


# Factory function for easy Lambda integration
def create_cluster_redis_writer(cluster_endpoint: str, auth_token: Optional[str] = None) -> ClusterRedisTradeWriter:
    """
    Factory function to create Redis Cluster writer
    
    Usage in Lambda:
        redis_writer = create_cluster_redis_writer(
            cluster_endpoint=os.environ['REDIS_CLUSTER_ENDPOINT'],
            auth_token=os.environ.get('REDIS_AUTH_TOKEN')
        )
    """
    return ClusterRedisTradeWriter(cluster_endpoint, auth_token)