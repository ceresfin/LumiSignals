"""
Redis Cluster Manager - 4-node sharding for currency pairs

ARCHITECTURE COMPLIANCE:
- Manages 4-node Redis cluster with currency pair sharding
- Provides sub-millisecond access for 100+ Lambda strategies
- Handles connection pooling and failover
- Implements intelligent currency pair distribution
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
import structlog
import redis.asyncio as redis
from .config import Settings
from .strategy_mapper import StrategyMapper

logger = structlog.get_logger()


class RedisManager:
    """
    Redis cluster manager for intelligent currency pair sharding
    
    Key Features:
    - 4-node cluster management
    - Currency pair sharding
    - Connection pooling
    - Health monitoring
    - Failover handling
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.connections: Dict[int, redis.Redis] = {}
        self.node_status: Dict[int, bool] = {}
        
        # Initialize strategy mapper for intelligent strategy name resolution
        self.strategy_mapper = StrategyMapper()
        
        # Performance metrics
        self.metrics = {
            "total_writes": 0,
            "successful_writes": 0,
            "failed_writes": 0,
            "total_reads": 0,
            "successful_reads": 0,
            "failed_reads": 0,
            "connection_errors": 0,
            "last_health_check": None,
            "strategy_mappings_resolved": 0
        }
        
        logger.info("Redis manager initialized", 
                   nodes=len(settings.redis_cluster_nodes),
                   sharding_enabled=True)
    
    async def initialize(self):
        """Initialize all Redis connections"""
        logger.info("🔗 Initializing Redis cluster connections...")
        
        for i, node_url in enumerate(self.settings.redis_cluster_nodes):
            try:
                # Parse node URL
                host, port = self._parse_node_url(node_url)
                
                # Create Redis connection using the same pattern as working Lambda functions
                conn = redis.Redis(
                    host=host,
                    port=port,
                    password=self.settings.parsed_redis_auth_token if self.settings.parsed_redis_auth_token else None,
                    decode_responses=False,
                    socket_connect_timeout=self.settings.redis_connection_timeout,
                    socket_timeout=self.settings.redis_socket_timeout,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                
                # Test connection
                await conn.ping()
                
                self.connections[i] = conn
                self.node_status[i] = True
                
                logger.info(f"✅ Redis node {i} connected", host=host, port=port)
                
            except Exception as e:
                self.node_status[i] = False
                self.metrics["connection_errors"] += 1
                logger.error(f"❌ Redis node {i} connection failed", 
                           node_url=node_url, error=str(e))
                raise
        
        logger.info(f"✅ All {len(self.connections)} Redis nodes connected")
    
    def _parse_node_url(self, node_url: str) -> tuple[str, int]:
        """Parse Redis node URL into host and port"""
        if ":" in node_url:
            host, port_str = node_url.rsplit(":", 1)
            return host, int(port_str)
        else:
            return node_url, 6379
    
    async def get_connection(self, node_index: int) -> redis.Redis:
        """Get Redis connection for specific node"""
        if node_index not in self.connections:
            raise ValueError(f"Redis node {node_index} not configured")
        
        if not self.node_status.get(node_index, False):
            raise ConnectionError(f"Redis node {node_index} is not healthy")
        
        return self.connections[node_index]
    
    async def get_connection_for_pair(self, currency_pair: str) -> redis.Redis:
        """Get Redis connection for specific currency pair based on sharding"""
        node_index = self.settings.get_redis_node_for_pair(currency_pair)
        return await self.get_connection(node_index)
    
    async def write_market_data(self, currency_pair: str, data: Dict[str, Any]) -> bool:
        """Write market data to appropriate Redis shard"""
        try:
            self.metrics["total_writes"] += 1
            
            # Get connection for this currency pair
            conn = await self.get_connection_for_pair(currency_pair)
            
            # Prepare keys
            current_key = f"market_data:{currency_pair}:current"
            timestamp_key = f"market_data:{currency_pair}:last_update"
            
            # Serialize data
            serialized_data = self.serialize_data(data)
            
            # Write to Redis with TTL
            pipe = conn.pipeline()
            pipe.setex(current_key, self.settings.redis_ttl_seconds, serialized_data)
            pipe.setex(timestamp_key, self.settings.redis_ttl_seconds, datetime.now().isoformat())
            
            await pipe.execute()
            
            self.metrics["successful_writes"] += 1
            
            logger.debug(f"Market data written for {currency_pair}",
                        node=self.settings.get_redis_node_for_pair(currency_pair))
            
            return True
            
        except Exception as e:
            self.metrics["failed_writes"] += 1
            logger.error(f"Failed to write market data for {currency_pair}", error=str(e))
            return False
    
    async def read_market_data(self, currency_pair: str) -> Optional[Dict[str, Any]]:
        """Read market data from appropriate Redis shard"""
        try:
            self.metrics["total_reads"] += 1
            
            # Get connection for this currency pair
            conn = await self.get_connection_for_pair(currency_pair)
            
            # Read current data
            current_key = f"market_data:{currency_pair}:current"
            data = await conn.get(current_key)
            
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
        """Write trade signal to Redis (strategy -> dashboard communication)"""
        try:
            self.metrics["total_writes"] += 1
            
            # Use first node for trade signals (shared data)
            conn = await self.get_connection(0)
            
            signal_id = signal_data.get('signal_id', f"signal_{int(datetime.now().timestamp())}")
            
            # Keys for trade signals
            signal_key = f"trade_signals:{strategy_name}:{signal_id}"
            latest_key = f"trade_signals:{strategy_name}:latest"
            
            # Serialize signal data
            serialized_signal = self.serialize_data(signal_data)
            
            # Write to Redis
            pipe = conn.pipeline()
            pipe.setex(signal_key, self.settings.redis_ttl_seconds, serialized_signal)
            pipe.setex(latest_key, self.settings.redis_ttl_seconds, serialized_signal)
            
            await pipe.execute()
            
            self.metrics["successful_writes"] += 1
            
            logger.debug(f"Trade signal written for {strategy_name}", signal_id=signal_id)
            
            return True
            
        except Exception as e:
            self.metrics["failed_writes"] += 1
            logger.error(f"Failed to write trade signal for {strategy_name}", error=str(e))
            return False
    
    async def write_trade_data_with_strategy_mapping(self, trade_data: Dict[str, Any]) -> bool:
        """
        Write trade data with intelligent strategy name mapping
        Replaces dummy strategy names with real strategy names using Lambda-compatible logic
        """
        try:
            self.metrics["total_writes"] += 1
            
            # Use strategy mapper to determine real strategy name
            real_strategy_name = self.strategy_mapper.get_strategy_name(trade_data)
            self.metrics["strategy_mappings_resolved"] += 1
            
            # Enhance trade data with proper metadata
            enhanced_trade_data = {
                **trade_data,
                'strategy_name': real_strategy_name,
                'strategy_tag': self.strategy_mapper.get_strategy_tag(real_strategy_name),
                'setup_name': self.strategy_mapper.get_setup_name(real_strategy_name),
                'metadata_source': 'strategy_mapper',
                'updated_at': datetime.now().isoformat()
            }
            
            # Get trade ID for key generation
            trade_id = trade_data.get('id', trade_data.get('trade_id', f"trade_{int(datetime.now().timestamp())}"))
            
            # Use first node for trade data (shared across strategies)
            conn = await self.get_connection(0)
            
            # Keys for enhanced trade storage
            trade_key = f"trades:{real_strategy_name}:{trade_id}"
            active_trades_key = f"active_trades:{trade_id}"
            strategy_trades_key = f"strategy_trades:{real_strategy_name}"
            
            # Serialize enhanced data
            serialized_data = self.serialize_data(enhanced_trade_data)
            
            # Write to multiple Redis keys for different access patterns
            pipe = conn.pipeline()
            pipe.setex(trade_key, self.settings.redis_ttl_seconds, serialized_data)
            pipe.setex(active_trades_key, self.settings.redis_ttl_seconds, serialized_data)
            pipe.sadd(strategy_trades_key, trade_id)
            pipe.expire(strategy_trades_key, self.settings.redis_ttl_seconds)
            
            await pipe.execute()
            
            self.metrics["successful_writes"] += 1
            
            logger.info(f"Trade data written with strategy mapping", 
                       trade_id=trade_id,
                       strategy_name=real_strategy_name,
                       original_strategy=trade_data.get('strategy_name', 'unknown'))
            
            return True
            
        except Exception as e:
            self.metrics["failed_writes"] += 1
            logger.error(f"Failed to write trade data with strategy mapping", error=str(e))
            return False
    
    async def get_all_market_data(self) -> Dict[str, Any]:
        """Get market data from all currency pairs across all shards"""
        all_data = {}
        
        for currency_pair in self.settings.currency_pairs:
            data = await self.read_market_data(currency_pair)
            if data:
                all_data[currency_pair] = data
        
        return all_data
    
    async def test_all_connections(self) -> bool:
        """Test all Redis connections"""
        all_healthy = True
        
        for node_index, conn in self.connections.items():
            try:
                await conn.ping()
                self.node_status[node_index] = True
                logger.debug(f"Redis node {node_index} ping successful")
            except Exception as e:
                self.node_status[node_index] = False
                all_healthy = False
                logger.error(f"Redis node {node_index} ping failed", error=str(e))
        
        return all_healthy
    
    async def get_cluster_status(self) -> Dict[str, Any]:
        """Get Redis cluster health status"""
        node_statuses = {}
        
        for node_index in range(len(self.settings.redis_cluster_nodes)):
            if node_index in self.connections:
                try:
                    conn = self.connections[node_index]
                    await conn.ping()
                    
                    # Get node info
                    info = await conn.info()
                    node_statuses[f"node_{node_index}"] = {
                        "healthy": True,
                        "url": self.settings.redis_cluster_nodes[node_index],
                        "connected_clients": info.get("connected_clients", 0),
                        "used_memory_human": info.get("used_memory_human", "unknown"),
                        "uptime_in_seconds": info.get("uptime_in_seconds", 0)
                    }
                    
                except Exception as e:
                    node_statuses[f"node_{node_index}"] = {
                        "healthy": False,
                        "url": self.settings.redis_cluster_nodes[node_index],
                        "error": str(e)
                    }
            else:
                node_statuses[f"node_{node_index}"] = {
                    "healthy": False,
                    "url": self.settings.redis_cluster_nodes[node_index],
                    "error": "Not initialized"
                }
        
        healthy_nodes = sum(1 for status in node_statuses.values() if status["healthy"])
        
        return {
            "cluster_healthy": healthy_nodes == len(self.settings.redis_cluster_nodes),
            "healthy_nodes": healthy_nodes,
            "total_nodes": len(self.settings.redis_cluster_nodes),
            "nodes": node_statuses,
            "metrics": self.metrics,
            "last_health_check": datetime.now().isoformat(),
            "shard_configuration": self.settings.shard_configuration
        }
    
    def serialize_data(self, data: Any) -> bytes:
        """Serialize data for Redis storage"""
        return json.dumps(data, default=str).encode('utf-8')
    
    def deserialize_data(self, data: bytes) -> Any:
        """Deserialize data from Redis storage"""
        return json.loads(data.decode('utf-8'))
    
    async def close_all_connections(self):
        """Close all Redis connections"""
        logger.info("Closing all Redis connections...")
        
        for node_index, conn in self.connections.items():
            try:
                await conn.close()
                logger.debug(f"Redis node {node_index} connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis node {node_index}", error=str(e))
        
        # Clear connections dictionary
        self.connections.clear()
        self.node_status.clear()
        
        logger.info("All Redis connections closed")