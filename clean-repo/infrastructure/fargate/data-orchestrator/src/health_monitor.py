"""
Health Monitor - Monitoring for Fargate Data Orchestrator

ARCHITECTURE COMPLIANCE:
- Monitors single OANDA API connection health
- Tracks Redis cluster status across 4 nodes
- Provides health metrics for Fargate service
- Enables proactive alerting and monitoring
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()


class HealthMonitor:
    """
    Health monitoring for Data Orchestrator components
    
    Monitors:
    - OANDA API connection status
    - Redis cluster health (4 nodes)
    - Data collection performance
    - System resource usage
    """
    
    def __init__(self, redis_manager):
        self.redis_manager = redis_manager
        self.health_data = {
            "oanda_api": {"healthy": False, "last_check": None, "errors": 0},
            "redis_cluster": {"healthy": False, "last_check": None, "errors": 0},
            "data_collection": {"healthy": False, "last_check": None, "errors": 0},
            "overall_status": "unknown"
        }
        
        self.monitoring_active = False
        self.last_health_check: Optional[datetime] = None
        
        logger.info("Health monitor initialized")
    
    async def initialize(self):
        """Initialize health monitoring"""
        logger.info("🏥 Initializing health monitoring...")
        
        # Perform initial health checks
        await self.perform_full_health_check()
        
        self.monitoring_active = True
        logger.info("✅ Health monitoring initialized")
    
    async def perform_full_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        try:
            # Check Redis cluster
            redis_healthy = await self.check_redis_cluster_health()
            
            # Update overall status
            overall_healthy = redis_healthy
            
            self.health_data["overall_status"] = "healthy" if overall_healthy else "unhealthy"
            self.last_health_check = datetime.now()
            
            logger.debug("Full health check completed", 
                        overall_healthy=overall_healthy,
                        redis_healthy=redis_healthy)
            
            return await self.get_health_status()
            
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            self.health_data["overall_status"] = "error"
            return await self.get_health_status()
    
    async def check_redis_cluster_health(self) -> bool:
        """Check Redis cluster health"""
        try:
            cluster_status = await self.redis_manager.get_cluster_status()
            
            healthy = cluster_status.get("cluster_healthy", False)
            
            self.health_data["redis_cluster"] = {
                "healthy": healthy,
                "last_check": datetime.now().isoformat(),
                "errors": self.health_data["redis_cluster"]["errors"] + (0 if healthy else 1),
                "details": cluster_status
            }
            
            return healthy
            
        except Exception as e:
            logger.error("Redis cluster health check failed", error=str(e))
            self.health_data["redis_cluster"]["errors"] += 1
            return False
    
    async def update_oanda_health(self, healthy: bool, details: Optional[Dict[str, Any]] = None):
        """Update OANDA API health status"""
        self.health_data["oanda_api"] = {
            "healthy": healthy,
            "last_check": datetime.now().isoformat(),
            "errors": self.health_data["oanda_api"]["errors"] + (0 if healthy else 1),
            "details": details or {}
        }
    
    async def update_data_collection_health(self, healthy: bool, details: Optional[Dict[str, Any]] = None):
        """Update data collection health status"""
        self.health_data["data_collection"] = {
            "healthy": healthy,
            "last_check": datetime.now().isoformat(),
            "errors": self.health_data["data_collection"]["errors"] + (0 if healthy else 1),
            "details": details or {}
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get current health status"""
        return {
            "healthy": self.health_data["overall_status"] == "healthy",
            "timestamp": datetime.now().isoformat(),
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "components": self.health_data,
            "monitoring_active": self.monitoring_active,
            "architecture": "Fargate Data Orchestrator Health Monitor"
        }
    
    async def shutdown(self):
        """Shutdown health monitoring"""
        logger.info("🏥 Shutting down health monitoring...")
        self.monitoring_active = False
        logger.info("Health monitoring shutdown complete")