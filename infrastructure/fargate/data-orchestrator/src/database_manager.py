"""
Database Manager - PostgreSQL connection and data storage for Data Orchestrator

Handles real OANDA data storage to PostgreSQL RDS with proper error handling
and connection management optimized for the Fargate environment.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import asyncpg
import structlog

logger = structlog.get_logger()


class DatabaseManager:
    """
    Manages PostgreSQL connections for storing market data from OANDA
    
    Key Features:
    - Connection pooling for high performance
    - Time-series optimized schema for market data
    - Proper SSL handling for RDS connections
    - Error handling and reconnection logic
    """
    
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self.pool = None
        self.is_connected = False
        
    async def initialize(self):
        """Initialize database connection pool"""
        try:
            logger.info("🔗 Initializing PostgreSQL connection pool...")
            
            # Create connection pool with optimized settings
            self.pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=2,
                max_size=10,
                command_timeout=30,
                server_settings={
                    'application_name': 'lumisignals_data_orchestrator',
                    'timezone': 'UTC'
                }
            )
            
            # Test connection and setup schema
            async with self.pool.acquire() as conn:
                await conn.execute('SELECT 1')
                logger.info("✅ PostgreSQL connection test successful")
                
                # Setup schema
                await self._setup_schema(conn)
                
            self.is_connected = True
            logger.info("✅ Database manager initialized successfully")
            
        except Exception as e:
            logger.error("❌ Failed to initialize database manager", error=str(e))
            self.is_connected = False
            raise
    
    async def _setup_schema(self, conn):
        """Setup market data schema if not exists"""
        try:
            # Create market_data table for storing OANDA candlestick data
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    instrument VARCHAR(10) NOT NULL,
                    granularity VARCHAR(10) NOT NULL,
                    open_price DECIMAL(10,5) NOT NULL,
                    high_price DECIMAL(10,5) NOT NULL,
                    low_price DECIMAL(10,5) NOT NULL,
                    close_price DECIMAL(10,5) NOT NULL,
                    volume INTEGER DEFAULT 0,
                    data_source VARCHAR(50) DEFAULT 'OANDA_API_VIA_FARGATE',
                    collection_time TIMESTAMPTZ DEFAULT NOW(),
                    redis_shard INTEGER,
                    metadata JSONB
                );
            """)
            
            # Create indexes for performance
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_data_timestamp_desc 
                ON market_data (timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_market_data_instrument_timestamp 
                ON market_data (instrument, timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_market_data_collection_time 
                ON market_data (collection_time DESC);
            """)
            
            # Create active_trades table for comprehensive trade tracking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS active_trades (
                    id SERIAL PRIMARY KEY,
                    trade_id VARCHAR(50) UNIQUE NOT NULL,
                    instrument VARCHAR(10) NOT NULL,
                    direction VARCHAR(10) NOT NULL,
                    units DECIMAL(12,2) NOT NULL,
                    current_units DECIMAL(12,2) NOT NULL,
                    entry_price DECIMAL(10,5) NOT NULL,
                    current_price DECIMAL(10,5),
                    open_time TIMESTAMPTZ NOT NULL,
                    unrealized_pnl DECIMAL(10,2),
                    unrealized_pl DECIMAL(10,2),
                    margin_used DECIMAL(10,2),
                    
                    -- Enhanced fields from comprehensive OANDA data
                    take_profit_price DECIMAL(10,5),
                    stop_loss_price DECIMAL(10,5),
                    pips_moved DECIMAL(8,1),
                    distance_to_entry DECIMAL(8,1),
                    risk_reward_ratio DECIMAL(6,2),
                    trade_duration VARCHAR(20),
                    duration_seconds INTEGER,
                    
                    -- Metadata and tracking
                    data_source VARCHAR(50) DEFAULT 'FARGATE_OANDA_ENHANCED',
                    last_updated TIMESTAMPTZ DEFAULT NOW(),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    enhancement_timestamp TIMESTAMPTZ,
                    metadata JSONB
                );
                
                CREATE INDEX IF NOT EXISTS idx_active_trades_trade_id 
                ON active_trades (trade_id);
                
                CREATE INDEX IF NOT EXISTS idx_active_trades_instrument 
                ON active_trades (instrument);
                
                CREATE INDEX IF NOT EXISTS idx_active_trades_last_updated 
                ON active_trades (last_updated DESC);
            """)
            
            # Create orchestrator_metrics table for tracking performance
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orchestrator_metrics (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    metric_type VARCHAR(50) NOT NULL,
                    metric_value DECIMAL(10,2),
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_orchestrator_metrics_timestamp 
                ON orchestrator_metrics (timestamp DESC);
            """)
            
            logger.info("✅ Database schema setup completed")
            
        except Exception as e:
            logger.error("❌ Failed to setup database schema", error=str(e))
            raise
    
    async def store_market_data(self, market_data: Dict[str, Any]) -> bool:
        """Store market data from OANDA to PostgreSQL"""
        if not self.is_connected or not self.pool:
            logger.warning("Database not connected, cannot store market data")
            return False
        
        try:
            async with self.pool.acquire() as conn:
                # Extract data from market_data dict
                instrument = market_data.get('instrument', '')
                granularity = market_data.get('granularity', 'M2')
                open_price = float(market_data.get('open', 0))
                high_price = float(market_data.get('high', 0))
                low_price = float(market_data.get('low', 0))
                close_price = float(market_data.get('close', 0))
                volume = int(market_data.get('volume', 0))
                data_source = market_data.get('data_source', 'OANDA_API_VIA_FARGATE')
                redis_shard = market_data.get('shard_assignment', 0)
                
                # Store in database
                await conn.execute("""
                    INSERT INTO market_data (
                        instrument, granularity, open_price, high_price, 
                        low_price, close_price, volume, data_source, 
                        redis_shard, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, 
                    instrument, granularity, open_price, high_price,
                    low_price, close_price, volume, data_source,
                    redis_shard, json.dumps(market_data.get('metadata', {}))
                )
                
                logger.debug("✅ Market data stored to PostgreSQL", 
                           instrument=instrument, 
                           data_source=data_source)
                
                return True
                
        except Exception as e:
            logger.error("❌ Failed to store market data", 
                        instrument=market_data.get('instrument', 'unknown'),
                        error=str(e))
            return False
    
    async def store_active_trades(self, trades_data: List[Dict[str, Any]]) -> bool:
        """Store comprehensive active trades data from enhanced OANDA collection"""
        if not self.is_connected or not self.pool:
            logger.warning("Database not connected, cannot store active trades")
            return False
        
        if not trades_data:
            logger.info("No trades data to store")
            return True
        
        try:
            async with self.pool.acquire() as conn:
                # Use UPSERT to handle trade updates
                for trade in trades_data:
                    # Extract enhanced trade data
                    trade_id = trade.get('id', '')
                    instrument = trade.get('instrument', '')
                    direction = trade.get('direction', '')
                    units = float(trade.get('initialUnits', 0)) if trade.get('initialUnits') else float(trade.get('units', 0))
                    current_units = float(trade.get('currentUnits', 0))
                    entry_price = float(trade.get('price', 0))
                    current_price = trade.get('current_price')
                    open_time = trade.get('openTime', '')
                    unrealized_pnl = float(trade.get('unrealizedPL', 0))
                    margin_used = float(trade.get('marginUsed', 0))
                    
                    # Enhanced fields
                    take_profit_price = trade.get('take_profit_price')
                    stop_loss_price = trade.get('stop_loss_price')
                    pips_moved = trade.get('pips_moved')
                    distance_to_entry = trade.get('distance_to_entry')
                    risk_reward_ratio = trade.get('risk_reward_ratio')
                    trade_duration = trade.get('trade_duration')
                    duration_seconds = trade.get('duration_seconds')
                    enhancement_timestamp = trade.get('enhanced_timestamp')
                    
                    # UPSERT query
                    await conn.execute("""
                        INSERT INTO active_trades (
                            trade_id, instrument, direction, units, current_units,
                            entry_price, current_price, open_time, unrealized_pnl, unrealized_pl,
                            margin_used, take_profit_price, stop_loss_price, pips_moved,
                            distance_to_entry, risk_reward_ratio, trade_duration, duration_seconds,
                            enhancement_timestamp, metadata, last_updated
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18, $19, $20, NOW()
                        ) ON CONFLICT (trade_id) DO UPDATE SET
                            current_units = EXCLUDED.current_units,
                            current_price = EXCLUDED.current_price,
                            unrealized_pnl = EXCLUDED.unrealized_pnl,
                            unrealized_pl = EXCLUDED.unrealized_pl,
                            margin_used = EXCLUDED.margin_used,
                            take_profit_price = EXCLUDED.take_profit_price,
                            stop_loss_price = EXCLUDED.stop_loss_price,
                            pips_moved = EXCLUDED.pips_moved,
                            distance_to_entry = EXCLUDED.distance_to_entry,
                            risk_reward_ratio = EXCLUDED.risk_reward_ratio,
                            trade_duration = EXCLUDED.trade_duration,
                            duration_seconds = EXCLUDED.duration_seconds,
                            enhancement_timestamp = EXCLUDED.enhancement_timestamp,
                            metadata = EXCLUDED.metadata,
                            last_updated = NOW()
                    """, 
                        trade_id, instrument, direction, units, current_units,
                        entry_price, current_price, open_time, unrealized_pnl, unrealized_pnl,
                        margin_used, take_profit_price, stop_loss_price, pips_moved,
                        distance_to_entry, risk_reward_ratio, trade_duration, duration_seconds,
                        enhancement_timestamp, json.dumps(trade), 
                    )
                
                logger.info(f"✅ Stored {len(trades_data)} active trades with enhanced data")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to store active trades: {str(e)}")
            return False

    async def store_metrics(self, metric_type: str, metric_value: float, metadata: Dict = None) -> bool:
        """Store orchestrator performance metrics"""
        if not self.is_connected or not self.pool:
            return False
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO orchestrator_metrics (metric_type, metric_value, metadata)
                    VALUES ($1, $2, $3)
                """, metric_type, metric_value, json.dumps(metadata or {}))
                
                return True
                
        except Exception as e:
            logger.error("❌ Failed to store metrics", 
                        metric_type=metric_type, 
                        error=str(e))
            return False
    
    async def get_latest_market_data(self, instrument: str, limit: int = 10) -> List[Dict]:
        """Retrieve latest market data for an instrument"""
        if not self.is_connected or not self.pool:
            return []
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT timestamp, instrument, granularity, open_price, high_price,
                           low_price, close_price, volume, data_source
                    FROM market_data 
                    WHERE instrument = $1
                    ORDER BY timestamp DESC
                    LIMIT $2
                """, instrument, limit)
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error("❌ Failed to retrieve market data", 
                        instrument=instrument, 
                        error=str(e))
            return []
    
    async def verify_real_data_flow(self) -> Dict[str, Any]:
        """Verify that real OANDA data is flowing through the system"""
        if not self.is_connected or not self.pool:
            return {"status": "disconnected"}
        
        try:
            async with self.pool.acquire() as conn:
                # Check recent data (last 5 minutes)
                recent_data = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_records,
                        COUNT(DISTINCT instrument) as instruments_count,
                        MAX(collection_time) as latest_collection,
                        MIN(collection_time) as earliest_collection
                    FROM market_data 
                    WHERE collection_time > NOW() - INTERVAL '5 minutes'
                    AND data_source = 'OANDA_API_VIA_FARGATE'
                """)
                
                # Check data quality
                data_quality = await conn.fetchrow("""
                    SELECT 
                        AVG(CASE WHEN close_price > 0 THEN 1 ELSE 0 END) as valid_price_ratio,
                        AVG(volume) as avg_volume
                    FROM market_data 
                    WHERE collection_time > NOW() - INTERVAL '5 minutes'
                """)
                
                return {
                    "status": "connected",
                    "recent_records": dict(recent_data) if recent_data else {},
                    "data_quality": dict(data_quality) if data_quality else {},
                    "verification_time": datetime.now(timezone.utc).isoformat()
                }
                
        except Exception as e:
            logger.error("❌ Failed to verify data flow", error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def cleanup_old_data(self, days_to_keep: int = 7):
        """Clean up old market data to manage storage"""
        if not self.is_connected or not self.pool:
            return
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute("""
                    DELETE FROM market_data 
                    WHERE collection_time < NOW() - INTERVAL '%s days'
                """, days_to_keep)
                
                logger.info("🧹 Cleaned up old market data", 
                           days_kept=days_to_keep,
                           records_deleted=result)
                
        except Exception as e:
            logger.error("❌ Failed to cleanup old data", error=str(e))
    
    async def get_connection_status(self) -> Dict[str, Any]:
        """Get database connection status"""
        if not self.pool:
            return {"connected": False, "pool_status": "not_initialized"}
        
        try:
            async with self.pool.acquire() as conn:
                await conn.execute('SELECT 1')
                
                return {
                    "connected": True,
                    "pool_size": self.pool.get_size(),
                    "pool_min_size": self.pool.get_min_size(),
                    "pool_max_size": self.pool.get_max_size(),
                    "test_query_success": True
                }
                
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "test_query_success": False
            }
    
    async def close(self):
        """Close database connections"""
        if self.pool:
            await self.pool.close()
            self.pool = None
            self.is_connected = False
            logger.info("✅ Database connections closed")