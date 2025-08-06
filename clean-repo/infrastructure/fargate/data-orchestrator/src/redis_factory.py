"""
Redis Manager Factory - Creates appropriate Redis manager based on configuration
"""

import os
import structlog
from .config import Settings
from .redis_manager import RedisManager
from .cluster_redis_manager import ClusterRedisManager

logger = structlog.get_logger()


def create_redis_manager(settings: Settings):
    """
    Create the appropriate Redis manager based on REDIS_MODE environment variable
    
    Returns:
        Either RedisManager (manual sharding) or ClusterRedisManager (automatic sharding)
    """
    redis_mode = os.getenv('REDIS_MODE', 'manual').lower()
    
    if redis_mode == 'cluster':
        logger.info("🎯 Using Redis Cluster Mode (automatic sharding)", 
                   endpoint=settings.redis_cluster_endpoint)
        return ClusterRedisManager(settings)
    else:
        logger.info("📊 Using Manual Sharding Mode (4 nodes)", 
                   nodes=len(settings.redis_cluster_nodes))
        return RedisManager(settings)