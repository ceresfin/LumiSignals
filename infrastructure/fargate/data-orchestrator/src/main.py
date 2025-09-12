#!/usr/bin/env python3
"""
Fargate Data Orchestrator - Single OANDA API Connection Point

ARCHITECTURE COMPLIANCE:
- Single OANDA API connection for entire system
- Distributes market data to 4-node Redis cluster
- Serves 100+ Lambda strategies with 2-minute candlestick data
- Follows data flow: OANDA → Fargate → Redis → Lambda Strategies

Key Features:
- Always-on persistent service (not event-driven)
- Rate limit management for OANDA API
- Currency pair sharding across Redis nodes
- Sub-second data distribution
- Cost: $21/month ($0.21/strategy at 100+ scale)
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

import structlog
import uvicorn
from fastapi import FastAPI

from .config import Settings
from .data_orchestrator import DataOrchestrator
from .health_monitor import HealthMonitor
from .database_manager import DatabaseManager
from .enhanced_database_manager import EnhancedDatabaseManager
from .redis_factory import create_redis_manager


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Global variables for graceful shutdown
orchestrator: Optional[DataOrchestrator] = None
app = FastAPI(title="LumiSignals Data Orchestrator", version="1.0.0")


@app.get("/version")
async def get_version():
    """Return build version and deployment info"""
    import hashlib
    import os
    
    version_info = {
        "version": os.getenv("VERSION", "unknown"),
        "build_date": os.getenv("BUILD_DATE", "unknown"),
        "commit_sha": os.getenv("COMMIT_SHA", "unknown"),
        "deployment_time": datetime.now().isoformat(),
    }
    
    # Add file checksums for verification
    try:
        critical_files = {
            "config.py": "/app/src/config.py",
            "main.py": "/app/src/main.py",
            "enhanced_database_manager.py": "/app/src/enhanced_database_manager.py",
            "oanda_client.py": "/app/src/oanda_client.py"
        }
        
        checksums = {}
        for name, filepath in critical_files.items():
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    checksums[name] = hashlib.sha256(f.read()).hexdigest()[:8]
        
        version_info["file_checksums"] = checksums
    except Exception as e:
        version_info["checksum_error"] = str(e)
    
    # Add version file content if available
    try:
        if os.path.exists("/app/version.txt"):
            with open("/app/version.txt", 'r') as f:
                version_info["version_file"] = f.read().strip()
    except Exception:
        pass
    
    return version_info


@app.get("/health")
async def health_check():
    """Health check endpoint for Fargate health monitoring"""
    try:
        if orchestrator and orchestrator.health_monitor:
            health_status = await orchestrator.health_monitor.get_health_status()
            return {
                "status": "healthy" if health_status["healthy"] else "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "details": health_status,
                "architecture": "Fargate Data Orchestrator - Single OANDA Connection"
            }
        else:
            return {
                "status": "starting",
                "timestamp": datetime.now().isoformat(),
                "message": "Data orchestrator initializing"
            }
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }


@app.get("/metrics")
async def get_metrics():
    """Get orchestrator metrics for monitoring"""
    try:
        if orchestrator:
            return await orchestrator.get_metrics()
        else:
            return {"status": "initializing"}
    except Exception as e:
        logger.error("Metrics collection failed", error=str(e))
        return {"error": str(e)}


@app.get("/redis-status")
async def get_redis_status():
    """Get Redis cluster status"""
    try:
        if orchestrator and orchestrator.redis_manager:
            return await orchestrator.redis_manager.get_cluster_status()
        else:
            return {"status": "initializing"}
    except Exception as e:
        logger.error("Redis status check failed", error=str(e))
        return {"error": str(e)}


@app.get("/data-status")
async def get_data_status():
    """Get data collection status and sample data"""
    try:
        if not orchestrator:
            return {"status": "initializing", "message": "Orchestrator not ready"}
        
        # Get orchestrator metrics
        metrics = await orchestrator.get_metrics()
        
        # Get sample data from Redis
        sample_data = {}
        try:
            # Try to get data for a few currency pairs
            test_pairs = ["EUR_USD", "GBP_USD", "USD_JPY"]
            for pair in test_pairs:
                data = await orchestrator.redis_manager.read_market_data(pair)
                if data:
                    sample_data[pair] = {
                        "instrument": data.get("instrument"),
                        "timestamp": data.get("timestamp"),
                        "has_data": True,
                        "data_type": data.get("data_type")
                    }
                else:
                    sample_data[pair] = {"has_data": False}
        except Exception as e:
            sample_data = {"error": f"Could not read sample data: {str(e)}"}
        
        return {
            "status": "running" if orchestrator.is_running else "stopped",
            "collection_metrics": {
                "collections_completed": metrics.get("collections_completed", 0),
                "collections_failed": metrics.get("collections_failed", 0),
                "last_successful_collection": metrics.get("last_successful_collection"),
                "uptime_formatted": metrics.get("uptime_formatted"),
                "is_running": metrics.get("is_running", False)
            },
            "redis_status": {
                "total_writes": orchestrator.redis_manager.metrics.get("total_writes", 0),
                "successful_writes": orchestrator.redis_manager.metrics.get("successful_writes", 0),
                "failed_writes": orchestrator.redis_manager.metrics.get("failed_writes", 0)
            },
            "sample_data": sample_data,
            "architecture": "Single OANDA API → 4-Node Redis → Lambda Strategies",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error("Data status check failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.get("/trade-id-linking-status")
async def get_trade_id_linking_status():
    """Get trade_id linking enhancement status and metrics"""
    try:
        if not orchestrator:
            return {"status": "initializing", "message": "Orchestrator not ready"}
        
        metrics = await orchestrator.get_metrics()
        linking_status = metrics.get("trade_id_linking_status", {})
        
        return {
            "status": "active" if linking_status.get("last_run") else "pending",
            "metrics": {
                "active_trades_linked": linking_status.get("active_trades_linked", 0),
                "pending_orders_linked": linking_status.get("pending_orders_linked", 0),
                "rrr_calculated": linking_status.get("rrr_calculated", 0),
                "errors": linking_status.get("errors", 0),
                "last_run": linking_status.get("last_run"),
                "total_enhancements": (linking_status.get("active_trades_linked", 0) + 
                                    linking_status.get("pending_orders_linked", 0))
            },
            "info": {
                "description": "Links closed trades with real SL/TP data from active_trades and pending_orders",
                "method": "trade_id relationships (scales to any number of strategies)",
                "schedule": "Every 5 minutes during account data collection",
                "target": "146 historical closed trades + ongoing enhancements"
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error("Trade ID linking status check failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.post("/execute-trade-id-linking")
async def execute_trade_id_linking():
    """Manually trigger trade_id linking enhancement"""
    try:
        if not orchestrator:
            return {"error": "Orchestrator not ready", "status": "initializing"}
        
        logger.info("🔗 Manual trade_id linking requested via API")
        await orchestrator.enhance_closed_trades_with_trade_id_linking()
        
        # Get updated metrics
        metrics = await orchestrator.get_metrics()
        linking_status = metrics.get("trade_id_linking_status", {})
        
        return {
            "status": "completed",
            "message": "Trade ID linking executed successfully",
            "results": {
                "active_trades_linked": linking_status.get("active_trades_linked", 0),
                "pending_orders_linked": linking_status.get("pending_orders_linked", 0),
                "rrr_calculated": linking_status.get("rrr_calculated", 0),
                "total_enhancements": (linking_status.get("active_trades_linked", 0) + 
                                    linking_status.get("pending_orders_linked", 0))
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error("Manual trade ID linking failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.get("/preview-cleanup")
async def preview_cleanup():
    """Preview what trades would be moved from active_trades to closed_trades"""
    try:
        if not orchestrator:
            return {"error": "Orchestrator not ready", "status": "initializing"}
        
        # Check if we have enhanced database manager
        if not hasattr(orchestrator, 'database_manager') or not orchestrator.database_manager:
            return {"error": "Database manager not available", "status": "no_database"}
        
        # Check if it's the enhanced version with preview method
        if not hasattr(orchestrator.database_manager, 'preview_cleanup_inactive_trades'):
            return {"error": "Preview method not available", "status": "no_preview_method"}
        
        logger.info("🔍 Preview cleanup requested via API")
        preview_result = await orchestrator.database_manager.preview_cleanup_inactive_trades()
        
        return {
            "status": "completed",
            "message": "Cleanup preview generated successfully",
            "preview": preview_result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error("Preview cleanup failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.post("/execute-cleanup")
async def execute_cleanup():
    """Actually execute the cleanup to move stale trades to closed_trades"""
    try:
        if not orchestrator:
            return {"error": "Orchestrator not ready", "status": "initializing"}
        
        # Check if we have enhanced database manager
        if not hasattr(orchestrator, 'database_manager') or not orchestrator.database_manager:
            return {"error": "Database manager not available", "status": "no_database"}
        
        # Check if it's the enhanced version with cleanup method
        if not hasattr(orchestrator.database_manager, 'cleanup_inactive_trades'):
            return {"error": "Cleanup method not available", "status": "no_cleanup_method"}
        
        logger.info("🧹 Manual cleanup requested via API")
        
        # Execute the actual cleanup
        await orchestrator.database_manager.cleanup_inactive_trades()
        
        return {
            "status": "completed",
            "message": "Cleanup executed successfully",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error("Manual cleanup failed", error=str(e))
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.get("/historical-data/{currency_pair}")
async def get_historical_data(currency_pair: str, timeframe: str = "H1", limit: int = 200):
    """Get historical candlestick data for pipstop.org charts
    
    Args:
        currency_pair: Currency pair (e.g., EUR_USD)
        timeframe: Timeframe (M5, M15, M30, H1, H4, D, W) - default H1
        limit: Number of candles to return (max 500) - default 200
    
    Returns:
        Historical candlestick data in format suitable for TradingView charts
    """
    try:
        if not orchestrator:
            return {"error": "Orchestrator not ready", "status": "initializing"}
        
        # Validate timeframe
        valid_timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D', 'W']
        if timeframe not in valid_timeframes:
            return {"error": f"Invalid timeframe. Valid options: {valid_timeframes}"}
        
        # Validate limit
        limit = min(max(1, limit), 500)  # Clamp between 1 and 500
        
        # Get Redis connection for this currency pair
        shard_index = orchestrator.settings.get_redis_node_for_pair(currency_pair)
        redis_conn = await orchestrator.redis_manager.get_connection(shard_index)
        
        # Try to get historical data from Redis
        historical_key = f"market_data:{currency_pair}:{timeframe}:historical"
        current_key = f"market_data:{currency_pair}:{timeframe}:current"
        
        logger.info(f"📊 Fetching historical data for {currency_pair} {timeframe} (limit: {limit})")
        
        # Get historical candles
        historical_data_raw = await redis_conn.get(historical_key)
        current_data_raw = await redis_conn.get(current_key)
        
        candles = []
        
        if historical_data_raw:
            try:
                historical_data = orchestrator.redis_manager.deserialize_data(historical_data_raw)
                if isinstance(historical_data, list):
                    candles.extend(historical_data)
                    logger.info(f"📈 Found {len(historical_data)} historical candles")
            except Exception as e:
                logger.error(f"Failed to parse historical data: {str(e)}")
        
        # Also add current candle if available
        if current_data_raw:
            try:
                current_data = orchestrator.redis_manager.deserialize_data(current_data_raw)
                if current_data and isinstance(current_data, dict):
                    # Convert current data to candle format
                    current_candle = {
                        'time': current_data.get('timestamp'),
                        'open': current_data.get('open', 0),
                        'high': current_data.get('high', 0),
                        'low': current_data.get('low', 0),
                        'close': current_data.get('close', 0),
                        'volume': current_data.get('volume', 0)
                    }
                    candles.append(current_candle)
                    logger.info(f"📊 Added current candle")
            except Exception as e:
                logger.error(f"Failed to parse current data: {str(e)}")
        
        # If no data in Redis, try to fetch fresh data from OANDA
        if not candles:
            logger.info(f"🔄 No Redis data found, fetching fresh data from OANDA")
            oanda_data = await orchestrator.oanda_client.get_candlesticks(
                instrument=currency_pair,
                granularity=timeframe,
                count=limit
            )
            
            if oanda_data and 'candles' in oanda_data:
                for candle in oanda_data['candles']:
                    mid = candle.get('mid', {})
                    candles.append({
                        'time': candle.get('time'),
                        'open': float(mid.get('o', 0)),
                        'high': float(mid.get('h', 0)),
                        'low': float(mid.get('l', 0)),
                        'close': float(mid.get('c', 0)),
                        'volume': int(candle.get('volume', 0))
                    })
                logger.info(f"🌐 Fetched {len(candles)} fresh candles from OANDA")
        
        # Sort by time and limit results
        candles.sort(key=lambda x: x.get('time', ''))
        candles = candles[-limit:] if len(candles) > limit else candles
        
        # Format response for pipstop.org
        response = {
            "status": "success",
            "currency_pair": currency_pair,
            "timeframe": timeframe,
            "count": len(candles),
            "limit_requested": limit,
            "data_source": "Redis" if historical_data_raw or current_data_raw else "OANDA_Direct",
            "shard_index": shard_index,
            "candles": candles,
            "timestamp": datetime.now().isoformat(),
            "api_info": {
                "usage": "This endpoint provides historical candlestick data for pipstop.org charts",
                "formats": "Data is formatted for TradingView/Chart.js compatibility",
                "update_frequency": "Data updates every 5 minutes during market hours"
            }
        }
        
        logger.info(f"✅ Successfully returned {len(candles)} candles for {currency_pair} {timeframe}")
        return response
        
    except Exception as e:
        logger.error(f"Historical data endpoint failed for {currency_pair}", error=str(e))
        return {
            "error": str(e),
            "currency_pair": currency_pair,
            "timeframe": timeframe,
            "timestamp": datetime.now().isoformat(),
            "status": "error"
        }


async def graceful_shutdown(signum: int, frame) -> None:
    """Handle graceful shutdown"""
    logger.info("Received shutdown signal", signal=signum)
    
    if orchestrator:
        logger.info("Shutting down data orchestrator...")
        await orchestrator.shutdown()
    
    logger.info("Fargate Data Orchestrator shutdown complete")
    sys.exit(0)


def log_deployment_info():
    """Log deployment and build information for verification"""
    import os
    import hashlib
    
    version = os.getenv("VERSION", "unknown")
    build_date = os.getenv("BUILD_DATE", "unknown")
    commit_sha = os.getenv("COMMIT_SHA", "unknown")
    
    logger.info("🚀 LumiSignals Data Orchestrator Deployment Info",
               version=version,
               build_date=build_date,
               commit_sha=commit_sha[:8] if commit_sha != "unknown" else "unknown")
    
    # Log critical file checksums for deployment verification
    try:
        config_checksum = hashlib.sha256(
            open("/app/src/config.py", "rb").read()
        ).hexdigest()[:8]
        logger.info("📁 Config checksum for deployment verification", 
                   config_checksum=config_checksum)
    except Exception:
        pass


async def main():
    """Main entry point for Fargate Data Orchestrator"""
    global orchestrator
    
    # Log deployment information first
    log_deployment_info()
    
    logger.info("🚀 Starting LumiSignals Fargate Data Orchestrator")
    logger.info("📡 Architecture: Single OANDA API → Redis Cluster → 100+ Lambda Strategies")
    
    try:
        # Load configuration
        settings = Settings()
        
        logger.info("Configuration loaded", 
                   redis_nodes=len(settings.redis_cluster_nodes),
                   oanda_environment=settings.oanda_environment)
        
        # Initialize Redis manager (auto-detects cluster vs manual mode)
        logger.info("🔗 Initializing Redis connection...")
        redis_manager = create_redis_manager(settings)
        await redis_manager.initialize()
        
        # Initialize enhanced database manager if credentials are available
        database_manager = None
        if settings.parsed_database_host:
            logger.info("📊 Initializing Enhanced PostgreSQL database connection with Distance to Entry support...")
            
            # Create enhanced database manager for comprehensive OANDA data
            database_config = {
                'host': settings.parsed_database_host,
                'port': settings.parsed_database_port or 5432,
                'username': settings.parsed_database_username,
                'password': settings.parsed_database_password,
                'dbname': settings.parsed_database_name,
                'ssl': True
            }
            
            enhanced_db_manager = EnhancedDatabaseManager(database_config, redis_manager)
            await enhanced_db_manager.initialize_connection_pool()
            
            # Use enhanced database manager which has comprehensive methods
            database_manager = enhanced_db_manager
            logger.info(f"✅ Enhanced database manager initialized for host: {settings.parsed_database_host}")
            logger.info("🎯 Ready to store OANDA Distance to Entry and all 31 Airtable fields")
            
            # Run cleanup on startup to move inactive trades to closed_trades
            logger.info("🧹 Running startup cleanup to move inactive trades to closed_trades...")
            try:
                await enhanced_db_manager.cleanup_inactive_trades()
                logger.info("✅ Startup cleanup complete")
            except Exception as e:
                logger.error(f"❌ Startup cleanup failed: {str(e)}")
                import traceback
                logger.error(f"Cleanup traceback: {traceback.format_exc()}")
        else:
            pass
            logger.warning("⚠️ No database credentials found - running without PostgreSQL storage")
        
        # Initialize health monitor
        logger.info("💊 Initializing health monitoring...")
        health_monitor = HealthMonitor(redis_manager)
        
        # Initialize data orchestrator
        logger.info("🎼 Initializing data orchestrator...")
        orchestrator = DataOrchestrator(settings, redis_manager, health_monitor, database_manager)
        await orchestrator.initialize()
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, graceful_shutdown)
        signal.signal(signal.SIGINT, graceful_shutdown)
        
        logger.info("✅ Fargate Data Orchestrator fully initialized")
        logger.info("📊 Now serving as single OANDA API connection point")
        logger.info("⚡ Distributing 2-minute candlestick data to Redis cluster")
        
        # Start the orchestrator
        orchestrator_task = asyncio.create_task(orchestrator.start())
        
        # Start FastAPI health server
        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=8080,
            log_level="info",
            access_log=False
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())
        
        # Wait for either task to complete
        done, pending = await asyncio.wait(
            [orchestrator_task, server_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Check if orchestrator failed
        for task in done:
            if task.exception():
                logger.error("Task failed", task=task, error=task.exception())
                raise task.exception()
        
    except Exception as e:
        logger.error("❌ Fatal error in data orchestrator", error=str(e), exc_info=True)
        if orchestrator:
            await orchestrator.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    # Check if running in Fargate
    if len(sys.argv) > 1 and sys.argv[1] == "--health-only":
        # Start only health server for testing
        uvicorn.run(app, host="0.0.0.0", port=8080)
    else:
        try:
            # Start full orchestrator
            asyncio.run(main())
        except Exception as e:
            logger.error(f"Failed to start main orchestrator: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Fallback to health-only mode
            logger.info("Falling back to health-only mode")
            uvicorn.run(app, host="0.0.0.0", port=8080)