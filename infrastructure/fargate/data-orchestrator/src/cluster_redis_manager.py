"""
Redis Cluster Manager - True cluster mode with automatic sharding

ARCHITECTURE UPGRADE:
- Uses Redis Cluster Mode with automatic sharding
- Single configuration endpoint (no manual shard selection)
- Eliminates complex currency pair sharding logic
- Scales automatically for 100+ Lambda strategies
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import structlog
import redis.asyncio as redis
from .config import Settings

logger = structlog.get_logger()


class ClusterRedisManager:
    """
    Redis cluster manager with automatic sharding
    
    Key Features:
    - True Redis Cluster Mode (ClusterEnabled: true)  
    - Single configuration endpoint
    - Automatic key distribution across shards
    - No manual sharding logic required
    - Scales seamlessly for all asset classes
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cluster_client: Optional[redis.RedisCluster] = None
        
        # Performance metrics
        self.metrics = {
            "total_writes": 0,
            "successful_writes": 0,
            "failed_writes": 0,
            "total_reads": 0,
            "successful_reads": 0,
            "failed_reads": 0,
            "connection_errors": 0,
            "last_health_check": None
        }
        
        logger.info("Redis Cluster manager initialized", 
                   cluster_mode=True,
                   automatic_sharding=True)
    
    async def initialize(self):
        """Initialize Redis Cluster connection"""
        logger.info("🔗 Initializing Redis Cluster connection...")
        
        try:
            # Create Redis Cluster connection - single endpoint!
            self.cluster_client = redis.RedisCluster(
                host=self.settings.redis_cluster_endpoint,
                port=6379,
                password=self.settings.parsed_redis_auth_token if self.settings.parsed_redis_auth_token else None,
                decode_responses=False,
                socket_connect_timeout=self.settings.redis_connection_timeout,
                socket_timeout=self.settings.redis_socket_timeout
            )
            
            # Test cluster connection
            await self.cluster_client.ping()
            
            # Get cluster info
            cluster_info = await self.cluster_client.cluster_info()
            cluster_nodes = await self.cluster_client.cluster_nodes()
            
            logger.info("✅ Redis Cluster connected successfully", 
                       cluster_state=cluster_info.get('cluster_state'),
                       cluster_slots_assigned=cluster_info.get('cluster_slots_assigned'),
                       cluster_size=cluster_info.get('cluster_size'))
                       
        except Exception as e:
            self.metrics["connection_errors"] += 1
            logger.error("❌ Redis Cluster connection failed", error=str(e))
            raise
    
    async def write_market_data(self, currency_pair: str, data: Dict[str, Any]) -> bool:
        """Write market data - Redis automatically handles sharding"""
        try:
            self.metrics["total_writes"] += 1
            
            # Simple keys - no manual sharding logic needed!
            current_key = f"market_data:{currency_pair}:current"
            timestamp_key = f"market_data:{currency_pair}:last_update"
            
            # Serialize data
            serialized_data = self.serialize_data(data)
            
            # Write to cluster - Redis handles shard selection automatically
            pipe = self.cluster_client.pipeline()
            pipe.setex(current_key, self.settings.redis_ttl_seconds, serialized_data)
            pipe.setex(timestamp_key, self.settings.redis_ttl_seconds, datetime.now().isoformat())
            
            await pipe.execute()
            
            self.metrics["successful_writes"] += 1
            
            logger.debug(f"Market data written for {currency_pair} (auto-sharded)")
            
            return True
            
        except Exception as e:
            self.metrics["failed_writes"] += 1
            logger.error(f"Failed to write market data for {currency_pair}", error=str(e))
            return False
    
    async def read_market_data(self, currency_pair: str) -> Optional[Dict[str, Any]]:
        """Read market data - Redis automatically routes to correct shard"""
        try:
            self.metrics["total_reads"] += 1
            
            # Simple key - Redis handles shard routing
            current_key = f"market_data:{currency_pair}:current"
            data = await self.cluster_client.get(current_key)
            
            if data:
                self.metrics["successful_reads"] += 1
                return self.deserialize_data(data)
            else:
                logger.debug(f"No market data found for {currency_pair}")
                return None
                
        except Exception as e:
            self.metrics["failed_reads"] += 1
            logger.error(f"Failed to read market data for {currency_pair}", error=str(e))
            return None
    
    async def write_trade_signal(self, signal_data: Dict[str, Any], strategy_name: str) -> bool:
        """Write trade signal - automatic sharding by Redis"""
        try:
            self.metrics["total_writes"] += 1
            
            signal_id = signal_data.get('signal_id', f"signal_{int(datetime.now().timestamp())}")
            
            # Simple keys - Redis distributes automatically
            signal_key = f"trade_signals:{strategy_name}:{signal_id}"
            latest_key = f"trade_signals:{strategy_name}:latest"
            
            # Serialize signal data
            serialized_signal = self.serialize_data(signal_data)
            
            # Write to cluster
            pipe = self.cluster_client.pipeline()
            pipe.setex(signal_key, self.settings.redis_ttl_seconds, serialized_signal)
            pipe.setex(latest_key, self.settings.redis_ttl_seconds, serialized_signal)
            
            await pipe.execute()
            
            self.metrics["successful_writes"] += 1
            
            logger.debug(f"Trade signal written for {strategy_name} (auto-sharded)", signal_id=signal_id)
            
            return True
            
        except Exception as e:
            self.metrics["failed_writes"] += 1
            logger.error(f"Failed to write trade signal for {strategy_name}", error=str(e))
            return False
    
    async def get_all_market_data(self) -> Dict[str, Any]:
        """Get market data from all currency pairs - Redis handles routing"""
        all_data = {}
        
        for currency_pair in self.settings.currency_pairs:
            data = await self.read_market_data(currency_pair)
            if data:
                all_data[currency_pair] = data
        
        return all_data
    
    async def test_cluster_connection(self) -> Dict[str, Any]:
        """Test Redis Cluster connection and get status"""
        try:
            # Test basic connectivity
            await self.cluster_client.ping()
            
            # Get cluster information
            cluster_info = await self.cluster_client.cluster_info()
            cluster_nodes = await self.cluster_client.cluster_nodes()
            
            # Parse node information
            node_status = {}
            for node_id, node_info in cluster_nodes.items():
                node_status[node_id] = {
                    "host": node_info.get("host"),
                    "port": node_info.get("port"), 
                    "role": "master" if node_info.get("flags", []).count("master") > 0 else "slave",
                    "slots": node_info.get("slots", [])
                }
            
            self.metrics["last_health_check"] = datetime.now().isoformat()
            
            return {
                "cluster_healthy": cluster_info.get('cluster_state') == 'ok',
                "cluster_state": cluster_info.get('cluster_state'),
                "cluster_slots_assigned": cluster_info.get('cluster_slots_assigned'),
                "cluster_size": cluster_info.get('cluster_size'),
                "nodes": node_status,
                "metrics": self.metrics,
                "automatic_sharding": True,
                "configuration_endpoint": f"{self.settings.redis_cluster_endpoint}:6379"
            }
            
        except Exception as e:
            logger.error("Redis Cluster health check failed", error=str(e))
            return {
                "cluster_healthy": False,
                "error": str(e),
                "metrics": self.metrics
            }
    
    def serialize_data(self, data: Any) -> bytes:
        """Serialize data for Redis storage"""
        return json.dumps(data, default=str).encode('utf-8')
    
    def deserialize_data(self, data: bytes) -> Any:
        """Deserialize data from Redis storage"""
        return json.loads(data.decode('utf-8'))
    
    # COMPATIBILITY METHODS for DataOrchestrator
    async def get_connection(self, shard_index: int = 0):
        """Compatibility method - returns cluster client (ignores shard_index)"""
        return self.cluster_client
    
    async def test_all_connections(self) -> Dict[str, bool]:
        """Test cluster connection"""
        try:
            await self.cluster_client.ping()
            return {"cluster": True}
        except Exception as e:
            logger.error("Cluster connection test failed", error=str(e))
            return {"cluster": False}
    
    async def close_connection(self):
        """Close Redis Cluster connection"""
        if self.cluster_client:
            logger.info("Closing Redis Cluster connection...")
            await self.cluster_client.close()
            self.cluster_client = None
            logger.info("Redis Cluster connection closed")