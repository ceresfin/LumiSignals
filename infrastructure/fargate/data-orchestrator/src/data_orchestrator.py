"""
Data Orchestrator - Core logic for single OANDA API connection and data distribution
ARCHITECTURE COMPLIANCE:
- Maintains single OANDA API connection for entire system
- Collects 2-minute candlestick data for 100+ strategies
- Distributes data across 4-node Redis cluster with currency pair sharding
- Sub-second data distribution to Lambda strategies
"""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import structlog
import httpx

from .config import Settings
from .redis_manager import RedisManager
from .health_monitor import HealthMonitor
from .oanda_client import OandaClient
from .rate_limiter import RateLimiter
from .database_manager import DatabaseManager
from .enhanced_database_manager import EnhancedDatabaseManager
from .enhanced_oanda_data_collection import EnhancedOandaDataCollector
from .integrate_comprehensive_data_collection import ComprehensiveDataOrchestrator
# from .closed_trade_enhancer import ClosedTradeEnhancer  # DISABLED: causes 403 errors from OANDA transaction API

logger = structlog.get_logger()


class DataOrchestrator:
    """
    Core orchestrator for centralized data collection and distribution
    
    Key Responsibilities:
    - Single OANDA API connection management
    - Multi-timeframe candlestick data collection (M5, M15, M30, H1, H4, D, W)
    - Currency pair sharding across Redis nodes
    - Rate limiting and error handling
    - Performance monitoring
    - Support for both current pricing and OHLC candlestick data
    """
    
    def __init__(self, settings: Settings, redis_manager: RedisManager, 
                 health_monitor: HealthMonitor, database_manager: DatabaseManager = None):
        self.settings = settings
        self.redis_manager = redis_manager
        self.health_monitor = health_monitor
        self.database_manager = database_manager
        
        # Initialize OANDA client (SINGLE CONNECTION POINT)
        self.oanda_client = OandaClient(settings)
        
        # Initialize comprehensive data orchestrator with cleanup capabilities
        # This replaces the basic enhanced_data_collector with full cleanup logic
        if self.database_manager:
            # Use the database config from main.py (already parsed from AWS Secrets Manager)
            # This ensures consistency between main.py and data_orchestrator.py database connections
            database_config = {
                'host': settings.parsed_database_host,
                'port': settings.parsed_database_port or 5432,
                'username': settings.parsed_database_username,
                'password': settings.parsed_database_password,
                'dbname': settings.parsed_database_name,
                'ssl': True
            }
            logger.info(f"🎯 Creating comprehensive orchestrator with database: {database_config['host']}")
            self.comprehensive_orchestrator = ComprehensiveDataOrchestrator(
                self.oanda_client, database_config, self.redis_manager
            )
            self.enhanced_data_collector = None  # Don't use fallback when comprehensive exists
            self._comprehensive_initialized = False  # Track initialization state
            logger.info("🎯 Comprehensive orchestrator created - initialization pending")
        else:
            # Fallback to basic collector if no database
            self.enhanced_data_collector = EnhancedOandaDataCollector(self.oanda_client)
            self.comprehensive_orchestrator = None
            self._comprehensive_initialized = False
            logger.info("⚠️ No database manager - using enhanced collector without cleanup")
        
        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            max_requests_per_second=settings.max_requests_per_second,
            burst_limit=settings.burst_limit
        )
        
        # State tracking
        self.is_running = False
        self.last_collection_time: Optional[datetime] = None
        self.collection_count = 0
        self.error_count = 0
        
        # Multi-timeframe tracking
        self.last_timeframe_collection: Dict[str, datetime] = {}
        self.timeframe_collection_counts: Dict[str, int] = {tf: 0 for tf in settings.timeframes}
        
        # Account data tracking (trade logging infrastructure)
        self.last_account_collection: Optional[datetime] = None
        self.account_collection_count = 0
        self.account_collection_interval = 60  # 1 minute for account data (more frequent than market data)
        
        # Performance metrics
        self.metrics = {
            "collections_completed": 0,
            "collections_failed": 0,
            "total_pairs_processed": 0,
            "timeframes_collected": dict(self.timeframe_collection_counts),
            "average_collection_time": 0.0,
            "redis_writes_successful": 0,
            "redis_writes_failed": 0,
            "oanda_api_calls": 0,
            "rate_limit_hits": 0,
            "last_successful_collection": None,
            "uptime_start": datetime.now(),
            "architecture_compliance": True,
            # Account data metrics
            "account_collections_completed": 0,
            "account_collections_failed": 0,
            "open_trades_collected": 0,
            "closed_trades_collected": 0,
            "closed_trades_enhanced": 0,
            "pending_orders_collected": 0,
            "positions_collected": 0,
            "last_account_collection": None,
            # Trade ID linking metrics
            "trade_id_linking_active": 0,
            "trade_id_linking_pending": 0,
            "trade_id_linking_rrr": 0,
            "trade_id_linking_errors": 0,
            "last_trade_id_linking": None
        }
        
        # Initialize closed trade enhancer - DISABLED due to 403 errors
        # self.closed_trade_enhancer = ClosedTradeEnhancer(self.oanda_client)
        self.closed_trade_enhancer = None  # Disabled to prevent 403 errors from transaction API
        
        # Track trade IDs to detect closures
        self.previous_trade_ids = set()
        
        logger.info("Data orchestrator initialized", 
                   currency_pairs=len(settings.currency_pairs),
                   collection_interval=settings.collection_interval_seconds,
                   timeframes=settings.timeframes,
                   redis_nodes=len(settings.redis_cluster_nodes))
    
    async def initialize(self):
        """Initialize the data orchestrator"""
        try:
            # Test OANDA connection
            logger.info("🔗 Testing OANDA API connection...")
            await self.oanda_client.test_connection()
            logger.info("✅ OANDA API connection successful")
            
            # Test Redis connections
            logger.info("🔗 Testing Redis cluster connections...")
            await self.redis_manager.test_all_connections()
            logger.info("✅ All Redis cluster connections successful")
            
            # Initialize database connection if available (non-blocking for market data collection)
            if self.database_manager:
                try:
                    logger.info("🔗 Initializing PostgreSQL database connection...")
                    await self.database_manager.initialize()
                    logger.info("✅ PostgreSQL database connection successful")
                except Exception as db_error:
                    logger.warning("⚠️ Database connection failed - continuing without database", error=str(db_error))
                    logger.info("📊 Market data collection will still work via Redis")
                    self.database_manager = None  # Disable database functionality
                    self.comprehensive_orchestrator = None  # Disable integrated collector
            
            # Initialize comprehensive orchestrator if available
            if self.comprehensive_orchestrator:
                logger.info("🚀 Initializing comprehensive data orchestrator with cleanup...")
                await self.comprehensive_orchestrator.initialize()
                logger.info("✅ Comprehensive data orchestrator with cleanup initialized successfully")
            
            # Initialize health monitoring
            await self.health_monitor.initialize()
            
            logger.info("🎼 Data orchestrator initialization complete")
            
        except Exception as e:
            logger.error("❌ Data orchestrator initialization failed", error=str(e))
            raise
    
    async def backfill_historical_h1_data(self):
        """One-time backfill of historical H1 data for dashboard charts"""
        print("DEBUG: Entered backfill_historical_h1_data() function")
        logger.info("🕐 Starting historical H1 data backfill for dashboard charts")
        print("DEBUG: H1 backfill log message sent")
        
        try:
            print("DEBUG: Starting individual pair H1 data assessment")
            logger.info(f"🔍 Checking H1 data availability for {len(self.settings.currency_pairs)} currency pairs")
            
            # Check each pair individually and collect pairs that need backfill
            pairs_needing_backfill = []
            
            for pair in self.settings.currency_pairs:
                try:
                    print(f"DEBUG: Checking H1 data for {pair}")
                    shard_index = self.settings.get_redis_node_for_pair(pair)
                    redis_conn = await self.redis_manager.get_connection(shard_index)
                    
                    historical_key = f"market_data:{pair}:H1:historical"
                    existing_data = await redis_conn.get(historical_key)
                    existing_count = 0
                    
                    if existing_data:
                        try:
                            parsed_data = json.loads(existing_data)
                            if isinstance(parsed_data, dict) and 'candles' in parsed_data:
                                existing_count = len(parsed_data['candles'])
                            elif isinstance(parsed_data, list):
                                existing_count = len(parsed_data)
                        except Exception as e:
                            print(f"DEBUG: Error parsing H1 data for {pair}: {e}")
                            existing_count = 0
                    
                    print(f"DEBUG: {pair} has {existing_count} H1 candles")
                    
                    # Only backfill pairs with insufficient data (less than 90 H1 candles)
                    if existing_count < 90:
                        pairs_needing_backfill.append(pair)
                        logger.info(f"⏳ {pair}: {existing_count} H1 candles (needs backfill)")
                    else:
                        logger.info(f"✅ {pair}: {existing_count} H1 candles (sufficient)")
                
                except Exception as e:
                    print(f"DEBUG: Error checking {pair}: {e}")
                    pairs_needing_backfill.append(pair)  # Include pair if we can't check
            
            if not pairs_needing_backfill:
                print("DEBUG: No pairs need H1 backfill")
                logger.info("✅ All currency pairs have sufficient H1 data, skipping backfill")
                return
            
            print(f"DEBUG: {len(pairs_needing_backfill)} pairs need backfill: {pairs_needing_backfill}")
            logger.info(f"📥 Backfilling H1 data for {len(pairs_needing_backfill)} currency pairs: {', '.join(pairs_needing_backfill)}")
            
            # Backfill H1 data for pairs that need it
            backfill_tasks = []
            for pair in pairs_needing_backfill:
                task = asyncio.create_task(
                    self._backfill_pair_h1_data(pair),
                    name=f"backfill_h1_{pair}"
                )
                backfill_tasks.append(task)
            
            # Process in smaller batches to avoid overwhelming OANDA API
            batch_size = 5
            for i in range(0, len(backfill_tasks), batch_size):
                batch = backfill_tasks[i:i + batch_size]
                logger.info(f"Processing backfill batch {i//batch_size + 1}/{(len(backfill_tasks) + batch_size - 1)//batch_size}")
                
                results = await asyncio.gather(*batch, return_exceptions=True)
                
                # Log results
                for j, result in enumerate(results):
                    pair = pairs_needing_backfill[i + j]
                    if isinstance(result, Exception):
                        logger.warning(f"Backfill failed for {pair}: {result}")
                    else:
                        logger.info(f"✅ Backfilled {result} H1 candles for {pair}")
                
                # Small delay between batches
                if i + batch_size < len(backfill_tasks):
                    await asyncio.sleep(2)
            
            logger.info("🎉 Historical H1 data backfill completed")
            
        except Exception as e:
            print(f"DEBUG: Exception in H1 backfill: {e}")
            logger.error(f"❌ Historical H1 data backfill failed: {e}")
            import traceback
            print(f"DEBUG: Traceback: {traceback.format_exc()}")

    async def _backfill_pair_h1_data(self, currency_pair: str) -> int:
        """Backfill H1 data for a specific currency pair using count-based approach (matches M5 success pattern)"""
        try:
            # Use the same successful count-based approach as M5 instead of date-range
            # This ensures consistent 500 candles like M5's proven bootstrap method
            candle_count = self.settings.get_candle_count_for_collection("H1", is_bootstrap=True)  # Returns 500
            
            logger.info(f"🕐 Requesting H1 historical data for {currency_pair} using count-based approach ({candle_count} candles)")
            
            # Fetch H1 candles using count-based request (matches M5 bootstrap success pattern)
            data = await self.oanda_client.get_candlesticks(
                instrument=currency_pair,
                granularity="H1", 
                count=candle_count  # Use count parameter like M5, not date range
            )
            
            if not data or 'candles' not in data:
                logger.warning(f"No H1 data received for {currency_pair}")
                return 0
            
            # Use the same simple processing as M5 bootstrap - no complex filtering
            # Process data using the same method as M5 for consistency
            processed_data = self._process_candlestick_data(data, currency_pair, "H1", is_bootstrap=True)
            
            if not processed_data or 'historical_candles' not in processed_data:
                logger.warning(f"Failed to process H1 data for {currency_pair}")
                return 0
            
            formatted_candles = processed_data['historical_candles']
            logger.info(f"📊 Processed {len(formatted_candles)} H1 candles for {currency_pair} using M5-style processing")
            
            # Store in Redis under H1 timeframe
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            redis_conn = await self.redis_manager.get_connection(shard_index)
            
            historical_key = f"market_data:{currency_pair}:H1:historical"
            historical_data = {
                'candles': formatted_candles,
                'timestamp': datetime.now().isoformat(),
                'source': 'FARGATE_H1_BACKFILL',
                'count': len(formatted_candles)
            }
            
            # Store with TTL
            await redis_conn.setex(
                historical_key,
                self.settings.redis_ttl_seconds,
                json.dumps(historical_data)
            )
            
            logger.info(f"✅ Backfilled {len(formatted_candles)} H1 candles for {currency_pair} (30-day range for rich scrollback)")
            
            # Log the time range for verification
            if formatted_candles:
                first_candle = formatted_candles[0]['time']
                last_candle = formatted_candles[-1]['time']
                logger.info(f"📅 H1 data range: {first_candle} → {last_candle} ({len(formatted_candles)} candles)")
            return len(formatted_candles)
            
        except Exception as e:
            logger.error(f"❌ Failed to backfill H1 data for {currency_pair}: {e}")
            return 0
    
    async def perform_bootstrap_collection(self):
        """Perform bootstrap collection of 500 candles for all pairs/timeframes on startup"""
        print("DEBUG: perform_bootstrap_collection() method called")
        logger.info("🚀 Starting bootstrap collection of 500 candles for all currency pairs")
        print(f"DEBUG: Timeframes configured: {self.settings.timeframes}")
        print(f"DEBUG: All supported timeframes: {self.settings.get_all_supported_timeframes()}")
        
        try:
            # Group currency pairs by Redis shard for efficient processing
            shard_groups = self._group_pairs_by_shard()
            
            # Process each timeframe separately to ensure all pairs get bootstrap data
            bootstrap_tasks = []
            total_tasks = 0
            
            for timeframe in self.settings.get_all_supported_timeframes():
                # Skip aggregated timeframes during bootstrap - they'll be computed from M5
                if timeframe in self.settings.aggregated_timeframes:
                    logger.info(f"⚠️ Skipping aggregated timeframe {timeframe} during bootstrap (will be computed from M5)")
                    continue
                
                logger.info(f"🔄 Bootstrapping {timeframe} data for all currency pairs")
                
                for shard_index, pairs in shard_groups.items():
                    task = asyncio.create_task(
                        self._bootstrap_shard_timeframe(shard_index, pairs, timeframe),
                        name=f"bootstrap_shard_{shard_index}_{timeframe}"
                    )
                    bootstrap_tasks.append(task)
                    total_tasks += 1
            
            logger.info(f"🚀 Starting {total_tasks} bootstrap collection tasks")
            
            # Execute bootstrap collection in batches to avoid overwhelming OANDA
            batch_size = 6  # Conservative batch size for bootstrap
            for i in range(0, len(bootstrap_tasks), batch_size):
                batch = bootstrap_tasks[i:i + batch_size]
                batch_number = (i // batch_size) + 1
                total_batches = (len(bootstrap_tasks) + batch_size - 1) // batch_size
                
                logger.info(f"📦 Processing bootstrap batch {batch_number}/{total_batches} ({len(batch)} tasks)")
                
                # Wait for batch completion
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                
                # Check for batch errors
                for j, result in enumerate(batch_results):
                    task_name = batch[j].get_name()
                    if isinstance(result, Exception):
                        logger.error(f"Bootstrap task {task_name} failed: {result}")
                    else:
                        logger.debug(f"Bootstrap task {task_name} completed successfully")
                
                # Rate limiting between batches to be respectful to OANDA
                if i + batch_size < len(bootstrap_tasks):
                    logger.info("⏳ Waiting 3 seconds between bootstrap batches...")
                    await asyncio.sleep(3)
            
            logger.info("✅ Bootstrap collection completed successfully")
            
            # After bootstrap, process aggregated timeframes once
            logger.info("🔄 Computing aggregated timeframes from bootstrap M5 data")
            current_time = int(time.time())
            await self._process_aggregated_timeframes(current_time)
            
        except Exception as e:
            logger.error(f"❌ Bootstrap collection failed: {e}")
            raise
    
    async def _bootstrap_shard_timeframe(self, shard_index: int, currency_pairs: List[str], timeframe: str):
        """Bootstrap a specific timeframe for all pairs in a shard"""
        logger.debug(f"Bootstrapping shard {shard_index} for {timeframe}", pairs=currency_pairs)
        
        bootstrap_data = {}
        
        # Process pairs in smaller batches during bootstrap for stability
        batch_size = min(3, self.settings.batch_size)  # Use smaller batches for bootstrap
        
        for i in range(0, len(currency_pairs), batch_size):
            batch = currency_pairs[i:i + batch_size]
            
            # Rate limiting
            await self.rate_limiter.acquire()
            
            # Collect bootstrap data for batch
            batch_tasks = []
            for pair in batch:
                task = asyncio.create_task(
                    self._collect_pair_timeframe_data(pair, timeframe, is_bootstrap=True),
                    name=f"bootstrap_{pair}_{timeframe}"
                )
                batch_tasks.append(task)
            
            # Wait for batch completion
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Process batch results
            for j, result in enumerate(batch_results):
                pair = batch[j]
                if isinstance(result, Exception):
                    logger.error(f"Bootstrap failed for {pair} {timeframe}", error=str(result))
                    continue
                
                if result:
                    bootstrap_data[pair] = result
                    logger.debug(f"Bootstrap completed for {pair} {timeframe}")
            
            # Add delay between batches to avoid overwhelming OANDA API
            batch_delay = float(os.getenv('BOOTSTRAP_BATCH_DELAY_SECONDS', '10.0'))  # Default 10 seconds between batches
            if i + batch_size < len(currency_pairs):  # Don't delay after last batch
                logger.info(f"⏳ Waiting {batch_delay}s before next batch to avoid OANDA API overload")
                await asyncio.sleep(batch_delay)
        
        # Write bootstrap data to Redis using the same storage pattern
        if bootstrap_data:
            await self._write_bootstrap_data_to_redis(shard_index, bootstrap_data, timeframe)
        
        logger.debug(f"Bootstrap shard {shard_index} {timeframe} completed", 
                    pairs_processed=len(bootstrap_data))
    
    async def _write_bootstrap_data_to_redis(self, shard_index: int, bootstrap_data: Dict[str, Any], timeframe: str):
        """Write bootstrap data to Redis using tiered storage (hot, warm, cold tiers)"""
        try:
            # Get Redis connection for this shard
            redis_conn = await self.redis_manager.get_connection(shard_index)
            
            # Prepare batch operations
            pipe = redis_conn.pipeline()
            
            for currency_pair, data in bootstrap_data.items():
                # Get all Redis keys for this pair/timeframe
                keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
                
                # Extract candles from processed data
                historical_candles = data.get('historical_candles', [])
                
                if historical_candles and len(historical_candles) > 0:
                    # Sort candles by time (oldest to newest) for proper tier distribution
                    sorted_candles = sorted(historical_candles, 
                                          key=lambda x: x.get('time', ''))
                    
                    # Distribute candles across tiers
                    total_candles = len(sorted_candles)
                    
                    # FIXED: Split into chronologically separated tiers (no overlap)
                    if total_candles >= self.settings.hot_tier_candles + self.settings.warm_tier_candles:
                        # Complete 3-tier distribution with chronological separation
                        hot_candles = sorted_candles[-self.settings.hot_tier_candles:]  # Most recent 50
                        warm_candles = sorted_candles[-(self.settings.hot_tier_candles + self.settings.warm_tier_candles):-self.settings.hot_tier_candles]  # Previous 450
                        cold_candles = sorted_candles[:-(self.settings.hot_tier_candles + self.settings.warm_tier_candles)]  # Oldest remaining
                    elif total_candles >= self.settings.hot_tier_candles:
                        # 2-tier distribution: hot + warm (no cold tier needed)
                        hot_candles = sorted_candles[-self.settings.hot_tier_candles:]  # Most recent
                        warm_candles = sorted_candles[:-self.settings.hot_tier_candles]  # Older candles
                        cold_candles = []
                    else:
                        # Single tier: everything in hot tier
                        hot_candles = sorted_candles
                        warm_candles = []
                        cold_candles = []
                    
                    # Store in hot tier (Redis list for ordered access)
                    if hot_candles:
                        hot_candles_json = [json.dumps(candle) for candle in hot_candles]
                        # Use LPUSH to maintain order, then LTRIM for capacity
                        pipe.delete(keys['hot'])  # Clear existing data first
                        pipe.lpush(keys['hot'], *hot_candles_json)
                        pipe.ltrim(keys['hot'], 0, self.settings.hot_tier_candles - 1)
                        pipe.expire(keys['hot'], self.settings.hot_tier_ttl)
                        
                        logger.debug(f"Stored {len(hot_candles)} candles in hot tier for {currency_pair} {timeframe}")
                    
                    # Store in warm tier (Redis list for ordered access)  
                    if warm_candles:
                        warm_candles_json = [json.dumps(candle) for candle in warm_candles]
                        pipe.delete(keys['warm'])  # Clear existing data first
                        pipe.lpush(keys['warm'], *warm_candles_json)
                        pipe.ltrim(keys['warm'], 0, self.settings.warm_tier_candles - 1)
                        pipe.expire(keys['warm'], self.settings.warm_tier_ttl)
                        
                        logger.debug(f"Stored {len(warm_candles)} candles in warm tier for {currency_pair} {timeframe}")
                    
                    # FIXED: Store only chronologically separated data in cold tier
                    if cold_candles:
                        # Cold tier gets only the oldest candles (no overlap)
                        bootstrap_data_formatted = {
                            'candles': cold_candles,
                            'timestamp': datetime.now().isoformat(),
                            'source': f'FARGATE_BOOTSTRAP_{timeframe}',
                            'count': len(cold_candles),
                            'is_bootstrap': True,
                            'tier_distribution': {
                                'hot_count': len(hot_candles),
                                'warm_count': len(warm_candles),
                                'cold_count': len(cold_candles),
                                'total_count': total_candles,
                                'no_overlap': True
                            }
                        }
                    else:
                        # No cold tier data needed for smaller datasets
                        bootstrap_data_formatted = {
                            'candles': [],
                            'timestamp': datetime.now().isoformat(),
                            'source': f'FARGATE_BOOTSTRAP_{timeframe}',
                            'count': 0,
                            'is_bootstrap': True,
                            'tier_distribution': {
                                'hot_count': len(hot_candles),
                                'warm_count': len(warm_candles),
                                'cold_count': 0,
                                'total_count': total_candles,
                                'no_overlap': True
                            }
                        }
                    
                    pipe.setex(
                        keys['cold'],
                        self.settings.cold_tier_ttl,
                        self.redis_manager.serialize_data(bootstrap_data_formatted)
                    )
                    
                    # Store current candle for regular operations
                    pipe.setex(
                        keys['current'],
                        self.settings.redis_ttl_seconds,
                        self.redis_manager.serialize_data(data)
                    )
                    
                    # Update last update timestamp
                    pipe.setex(
                        keys['last_update'],
                        self.settings.redis_ttl_seconds,
                        datetime.now().isoformat()
                    )
                    
                    logger.debug(f"Prepared tiered bootstrap data for {currency_pair} {timeframe}", 
                                hot_candles=len(hot_candles),
                                warm_candles=len(warm_candles), 
                                total_candles=total_candles)
            
            # Execute all bootstrap Redis operations
            await pipe.execute()
            
            self.metrics["redis_writes_successful"] += len(bootstrap_data)
            
            logger.debug(f"Bootstrap shard {shard_index} {timeframe} data written to tiered Redis storage", 
                        pairs=list(bootstrap_data.keys()))
            
        except Exception as e:
            self.metrics["redis_writes_failed"] += len(bootstrap_data)
            logger.error(f"Failed to write bootstrap shard {shard_index} {timeframe} to tiered Redis", error=str(e))
            raise

    async def start(self):
        """Start the data collection loop"""
        print("DEBUG: DataOrchestrator.start() method called")
        self.is_running = True
        logger.info("🚀 Starting data collection loop")
        logger.info("📡 Now serving as SINGLE OANDA API connection point")
        logger.info(f"⏰ Collection interval: {self.settings.collection_interval_seconds} seconds")
        logger.info(f"💱 Currency pairs to monitor: {len(self.settings.currency_pairs)}")
        logger.info(f"🎯 Target timeframes: {self.settings.timeframes}")
        print("DEBUG: Data collection loop starting, is_running =", self.is_running)
        
        # One-time historical H1 data backfill for dashboard charts
        # Only run if environment variable is set (for gradual rollout)
        h1_backfill_env = os.getenv('ENABLE_H1_BACKFILL', 'false').lower()
        print(f"DEBUG: ENABLE_H1_BACKFILL environment variable = '{h1_backfill_env}'")
        logger.info(f"DEBUG: ENABLE_H1_BACKFILL environment variable = '{h1_backfill_env}'")
        
        if h1_backfill_env == 'true':
            print("DEBUG: H1 backfill condition met, about to start backfill")
            logger.info("🕐 H1 backfill enabled via environment variable")
            try:
                await self.backfill_historical_h1_data()
                print("DEBUG: H1 backfill completed successfully")
                logger.info("✅ H1 backfill completed successfully")
            except Exception as e:
                print(f"DEBUG: H1 backfill failed with error: {e}")
                logger.error(f"❌ H1 backfill failed: {e}")
        else:
            print("DEBUG: H1 backfill disabled, skipping")
            logger.info("🕐 H1 backfill disabled (set ENABLE_H1_BACKFILL=true to enable)")
        
        # Smart Bootstrap: Only run once, then remember completion
        bootstrap_env = os.getenv('ENABLE_BOOTSTRAP', 'false').lower()
        print(f"DEBUG: ENABLE_BOOTSTRAP environment variable = '{bootstrap_env}'")
        logger.info(f"DEBUG: ENABLE_BOOTSTRAP environment variable = '{bootstrap_env}'")
        
        if bootstrap_env == 'true':
            # Check if we've already completed bootstrap
            try:
                # Use first shard to check bootstrap completion marker
                redis_conn = await self.redis_manager.get_connection(0)
                bootstrap_marker_key = "lumisignals:system:bootstrap:completed"
                has_bootstrapped = await redis_conn.get(bootstrap_marker_key)
                
                if has_bootstrapped:
                    print("DEBUG: Bootstrap already completed previously, skipping")
                    logger.info("✅ Bootstrap already completed - skipping to avoid data corruption")
                else:
                    print("DEBUG: First time bootstrap - starting collection")
                    logger.info("🚀 First-time bootstrap - collecting 500 candles for all pairs/timeframes")
                    try:
                        await self.perform_bootstrap_collection()
                        
                        # Mark bootstrap as completed (remember for 30 days)
                        await redis_conn.setex(bootstrap_marker_key, 30*24*60*60, "completed")
                        print("DEBUG: Bootstrap collection completed and marked as done")
                        logger.info("✅ Bootstrap collection completed successfully - marked as done")
                    except Exception as e:
                        print(f"DEBUG: Bootstrap collection failed with error: {e}")
                        logger.error(f"❌ Bootstrap collection failed: {e}")
                        
            except Exception as e:
                logger.warning(f"Could not check bootstrap status, skipping bootstrap: {e}")
                print(f"DEBUG: Could not check bootstrap status: {e}")
        else:
            print("DEBUG: Bootstrap collection disabled, skipping")
            logger.info("🚀 Bootstrap collection disabled (set ENABLE_BOOTSTRAP=true to enable)")
        
        try:
            while self.is_running:
                collection_start = time.time()
                cycle_number = self.metrics["collections_completed"] + 1
                
                logger.info(f"🔄 Starting collection cycle #{cycle_number}")
                print(f"DEBUG: Collection cycle #{cycle_number} starting at {datetime.now().isoformat()}")
                
                try:
                    # Collect and distribute market data
                    await self.collect_and_distribute_data()
                    
                    # Collect account data (trades, positions, orders) - less frequent than market data
                    logger.info("🔍 DEBUGGING: About to call collect_and_distribute_account_data()")
                    print("DEBUG: About to call collect_and_distribute_account_data()")
                    await self.collect_and_distribute_account_data()
                    logger.info("🔍 DEBUGGING: collect_and_distribute_account_data() completed successfully")
                    print("DEBUG: collect_and_distribute_account_data() completed successfully")
                    
                    # Update metrics
                    collection_time = time.time() - collection_start
                    self.metrics["collections_completed"] += 1
                    self.metrics["average_collection_time"] = (
                        (self.metrics["average_collection_time"] * (self.metrics["collections_completed"] - 1) + collection_time) /
                        self.metrics["collections_completed"]
                    )
                    self.metrics["last_successful_collection"] = datetime.now().isoformat()
                    
                    logger.info("✅ Data collection cycle completed",
                               collection_time=f"{collection_time:.2f}s",
                               pairs_processed=len(self.settings.currency_pairs),
                               cycle_count=self.metrics["collections_completed"],
                               redis_writes=self.metrics["redis_writes_successful"],
                               oanda_calls=self.metrics["oanda_api_calls"])
                
                except Exception as e:
                    self.metrics["collections_failed"] += 1
                    self.error_count += 1
                    logger.error("❌ Data collection cycle failed", error=str(e), exc_info=True)
                    print(f"DEBUG: Collection cycle #{cycle_number} failed: {str(e)}")
                
                # Wait for next collection interval
                logger.info(f"⏳ Waiting {self.settings.collection_interval_seconds}s until next collection cycle")
                print(f"DEBUG: Sleeping for {self.settings.collection_interval_seconds} seconds")
                await asyncio.sleep(self.settings.collection_interval_seconds)
                
        except asyncio.CancelledError:
            logger.info("Data collection loop cancelled")
        except Exception as e:
            logger.error("❌ Fatal error in data collection loop", error=str(e))
            raise
        finally:
            self.is_running = False
    
    async def collect_and_distribute_data(self):
        """Collect data from OANDA and distribute to Redis cluster"""
        logger.info("📊 Starting data collection and distribution cycle")
        
        # Determine which timeframes to collect based on current time
        current_time = int(time.time())
        timeframes_to_collect = self.settings.get_timeframes_to_collect(current_time)
        
        logger.info(f"🎯 Collecting timeframes: {timeframes_to_collect}")
        print(f"DEBUG: Timeframes to collect: {timeframes_to_collect}")
        
        # Group currency pairs by Redis shard for efficient processing
        shard_groups = self._group_pairs_by_shard()
        logger.info(f"🗂️ Grouped pairs into {len(shard_groups)} shards")
        for shard_index, pairs in shard_groups.items():
            logger.info(f"   Shard {shard_index}: {len(pairs)} pairs {pairs[:3]}{'...' if len(pairs) > 3 else ''}")
        
        # Process each shard concurrently for each timeframe
        tasks = []
        total_tasks = 0
        for timeframe in timeframes_to_collect:
            for shard_index, pairs in shard_groups.items():
                task = asyncio.create_task(
                    self._process_shard_timeframe(shard_index, pairs, timeframe),
                    name=f"shard_{shard_index}_{timeframe}"
                )
                tasks.append(task)
                total_tasks += 1
        
        logger.info(f"🚀 Starting {total_tasks} concurrent shard processing tasks")
        
        # Wait for all shards and timeframes to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check for errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Shard processing failed", task_index=i, error=str(result))
                # Don't raise individual shard errors, continue with others
        
        # Update collection timestamps
        self.last_collection_time = datetime.now()
        for timeframe in timeframes_to_collect:
            self.last_timeframe_collection[timeframe] = self.last_collection_time
            self.timeframe_collection_counts[timeframe] += 1
        
        # Also collect current pricing data for all pairs
        await self._collect_current_pricing()
        
        # Process aggregated timeframes (M15, M30)
        await self._process_aggregated_timeframes(current_time)
        
        logger.debug("Data collection and distribution cycle completed", 
                    timeframes_collected=timeframes_to_collect)
    
    async def _process_shard_timeframe(self, shard_index: int, currency_pairs: List[str], timeframe: str):
        """Process a single Redis shard with its currency pairs for a specific timeframe"""
        logger.debug(f"Processing shard {shard_index} for {timeframe}", pairs=currency_pairs)
        
        # Collect data for all pairs in this shard for this timeframe
        shard_data = {}
        
        # Process pairs in batches to respect rate limits
        for i in range(0, len(currency_pairs), self.settings.batch_size):
            batch = currency_pairs[i:i + self.settings.batch_size]
            
            # Rate limiting
            await self.rate_limiter.acquire()
            
            # Collect candlestick data for batch
            batch_tasks = []
            for pair in batch:
                task = asyncio.create_task(
                    self._collect_pair_timeframe_data(pair, timeframe, is_bootstrap=False),
                    name=f"collect_{pair}_{timeframe}"
                )
                batch_tasks.append(task)
            
            # Wait for batch completion
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Process batch results
            for j, result in enumerate(batch_results):
                pair = batch[j]
                if isinstance(result, Exception):
                    logger.error(f"Data collection failed for {pair} {timeframe}", error=str(result))
                    continue
                
                if result:
                    shard_data[pair] = result
                    self.metrics["total_pairs_processed"] += 1
        
        # Write shard data to Redis
        if shard_data:
            await self._write_shard_timeframe_to_redis(shard_index, shard_data, timeframe)
        
        logger.debug(f"Shard {shard_index} {timeframe} processing completed", 
                    pairs_processed=len(shard_data))
    
    async def _collect_pair_timeframe_data(self, currency_pair: str, timeframe: str, is_bootstrap: bool = False) -> Optional[Dict[str, Any]]:
        """Collect candlestick data for a single currency pair and timeframe"""
        try:
            # Determine how many candles to collect
            candle_count = self.settings.get_candle_count_for_collection(timeframe, is_bootstrap)
            
            # Make OANDA API call
            candlestick_data = await self.oanda_client.get_candlesticks(
                instrument=currency_pair,
                granularity=timeframe,
                count=candle_count
            )
            
            self.metrics["oanda_api_calls"] += 1
            
            if not candlestick_data:
                logger.warning(f"No candlestick data received for {currency_pair} {timeframe}")
                return None
            
            # Process and format data - pass is_bootstrap flag to handle 500 candles properly
            processed_data = self._process_candlestick_data(candlestick_data, currency_pair, timeframe, is_bootstrap)
            
            logger.debug(f"Collected {timeframe} data for {currency_pair}", 
                        candles=len(candlestick_data.get('candles', [])),
                        is_bootstrap=is_bootstrap)
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Data collection failed for {currency_pair} {timeframe}", error=str(e))
            return None
    
    async def _collect_current_pricing(self):
        """Collect current bid/ask pricing for all currency pairs"""
        logger.info("💰 Collecting current pricing data for all currency pairs")
        print(f"DEBUG: Requesting pricing for {len(self.settings.currency_pairs)} pairs")
        
        try:
            # Get current pricing for all pairs
            pricing_data = await self.oanda_client.get_current_prices(
                instruments=self.settings.currency_pairs
            )
            
            if not pricing_data or 'prices' not in pricing_data:
                logger.warning("⚠️ No current pricing data received from OANDA")
                print("DEBUG: OANDA returned no pricing data - likely markets are closed")
                return
            
            prices_count = len(pricing_data.get('prices', []))
            logger.info(f"📈 Received pricing data for {prices_count} instruments")
            
            # Process and store pricing data
            current_time = datetime.now()
            pricing_by_shard = {}
            
            for price_data in pricing_data['prices']:
                instrument = price_data.get('instrument')
                if not instrument:
                    continue
                
                shard_index = self.settings.get_redis_node_for_pair(instrument)
                
                if shard_index not in pricing_by_shard:
                    pricing_by_shard[shard_index] = {}
                
                # Format pricing data
                pricing_by_shard[shard_index][instrument] = {
                    'instrument': instrument,
                    'timestamp': current_time.isoformat(),
                    'bid': float(price_data.get('bids', [{}])[0].get('price', 0)),
                    'ask': float(price_data.get('asks', [{}])[0].get('price', 0)),
                    'spread': float(price_data.get('asks', [{}])[0].get('price', 0)) - float(price_data.get('bids', [{}])[0].get('price', 0)),
                    'tradeable': price_data.get('tradeable', False),
                    'data_source': 'OANDA_API_VIA_FARGATE',
                    'data_type': 'current_pricing'
                }
            
            # Write pricing data to Redis shards
            for shard_index, shard_pricing in pricing_by_shard.items():
                await self._write_pricing_to_redis(shard_index, shard_pricing)
            
            logger.debug("Current pricing data collected and stored", 
                        pairs_count=len(pricing_data['prices']))
            
        except Exception as e:
            logger.error("Failed to collect current pricing", error=str(e))
    
    def _process_candlestick_data(self, raw_data: Dict[str, Any], currency_pair: str, timeframe: str, is_bootstrap: bool = False) -> Dict[str, Any]:
        """Process raw OANDA candlestick data into Redis format with proper time handling"""
        try:
            candles = raw_data.get('candles', [])
            if not candles:
                return {}
            
            # Extract latest candle
            latest_candle = candles[-1]
            mid_prices = latest_candle.get('mid', {})
            
            # Parse timestamp with nanosecond precision handling
            raw_timestamp = latest_candle.get('time')
            formatted_timestamp = self._parse_oanda_timestamp(raw_timestamp)
            
            # Format for Redis storage
            processed_data = {
                'instrument': currency_pair,
                'timeframe': timeframe,
                'timestamp': formatted_timestamp,
                'open': float(mid_prices.get('o', 0)),
                'high': float(mid_prices.get('h', 0)),
                'low': float(mid_prices.get('l', 0)),
                'close': float(mid_prices.get('c', 0)),
                'volume': int(latest_candle.get('volume', 0)),
                'collection_time': datetime.now().isoformat(),
                'data_source': 'OANDA_API_VIA_FARGATE',
                'data_type': 'candlestick',
                'shard_assignment': self.settings.get_redis_node_for_pair(currency_pair)
            }
            
            # Add historical candles for strategies that need them
            historical_candles = []
            
            # During bootstrap, use ALL candles (500 for bootstrap)
            # During regular collection, use limited history based on timeframe
            if is_bootstrap:
                history_count = len(candles)  # Use all candles during bootstrap
                logger.debug(f"Bootstrap mode: processing all {history_count} candles for {currency_pair} {timeframe}")
            else:
                # For different timeframes, store different amounts of history
                history_count = {
                    'M5': 50,   # 50 * 5min = 4+ hours
                    'M15': 32,  # 32 * 15min = 8 hours
                    'M30': 24,  # 24 * 30min = 12 hours
                    'H1': 24,   # 24 * 1hour = 1 day
                    'H4': 30,   # 30 * 4hour = 5 days
                    'D': 30,    # 30 * 1day = 1 month
                    'W': 52     # 52 * 1week = 1 year
                }.get(timeframe, 20)
            
            for candle in candles[-history_count:]:  # Last N candles based on timeframe
                mid = candle.get('mid', {})
                # Parse each historical candle timestamp properly
                raw_candle_time = candle.get('time')
                formatted_candle_time = self._parse_oanda_timestamp(raw_candle_time)
                
                historical_candles.append({
                    'time': formatted_candle_time,
                    'open': float(mid.get('o', 0)),
                    'high': float(mid.get('h', 0)),
                    'low': float(mid.get('l', 0)),
                    'close': float(mid.get('c', 0)),
                    'volume': int(candle.get('volume', 0))
                })
            
            processed_data['historical_candles'] = historical_candles
            processed_data['history_count'] = len(historical_candles)
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Data processing failed for {currency_pair} {timeframe}", error=str(e))
            return {}
    
    def _parse_oanda_timestamp(self, raw_timestamp: str) -> str:
        """Parse OANDA timestamp with nanosecond precision handling"""
        if not raw_timestamp:
            return raw_timestamp
        
        try:
            # Handle OANDA's nanosecond precision format: 2025-01-01T12:34:56.000000000Z
            if raw_timestamp.endswith('.000000000Z'):
                # Remove nanoseconds for compatibility
                cleaned_timestamp = raw_timestamp.replace('.000000000Z', 'Z')
            else:
                cleaned_timestamp = raw_timestamp
            
            # Parse to datetime object for validation and consistent formatting
            dt = datetime.fromisoformat(cleaned_timestamp.replace('Z', '+00:00'))
            # Return as ISO string with Z suffix for TradingView compatibility
            return dt.isoformat().replace('+00:00', 'Z')
            
        except Exception as e:
            logger.warning(f"Failed to parse OANDA timestamp {raw_timestamp}: {e}, using raw value")
            return raw_timestamp
    
    async def _write_shard_timeframe_to_redis(self, shard_index: int, shard_data: Dict[str, Any], timeframe: str):
        """Write shard data for specific timeframe using tiered Redis storage"""
        try:
            # Get Redis connection for this shard
            redis_conn = await self.redis_manager.get_connection(shard_index)
            
            # Prepare batch operations
            pipe = redis_conn.pipeline()
            
            for currency_pair, data in shard_data.items():
                # Get all Redis keys for this pair/timeframe
                keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
                
                # Store current data (single latest candle)
                pipe.setex(
                    keys['current'],
                    self.settings.redis_ttl_seconds,
                    self.redis_manager.serialize_data(data)
                )
                
                # Add latest candle to hot tier (using Redis list for ordered storage)
                latest_candle = self._extract_latest_candle_from_data(data)
                if latest_candle:
                    # Add to end of hot tier list
                    pipe.rpush(keys['hot'], json.dumps(latest_candle))
                    
                    # FIXED: Don't execute pipeline early - get count directly
                    # Execute rpush to add the candle first
                    await pipe.execute()
                    pipe = redis_conn.pipeline()  # Reset pipeline for remaining operations
                    
                    # Check if hot tier exceeds capacity and rotate BEFORE trimming
                    hot_count = await redis_conn.llen(keys['hot'])
                    if hot_count > self.settings.hot_tier_candles:
                        logger.debug(f"Hot tier has {hot_count} candles, rotating excess to warm tier for {currency_pair} {timeframe}")
                        await self._rotate_hot_to_warm_tier(currency_pair, timeframe, redis_conn)
                    
                    # FIXED: Removed redundant ltrim - rotation already handles hot tier trimming
                    
                    # Set TTL for hot tier
                    pipe.expire(keys['hot'], self.settings.hot_tier_ttl)
                    
                    logger.debug(f"Added candle to hot tier for {currency_pair} {timeframe}")
                
                # Update last update timestamp
                pipe.setex(
                    keys['last_update'],
                    self.settings.redis_ttl_seconds,
                    datetime.now().isoformat()
                )
            
            # Execute all batch operations
            await pipe.execute()
            
            self.metrics["redis_writes_successful"] += len(shard_data)
            
            logger.debug(f"Shard {shard_index} {timeframe} written to tiered Redis storage", 
                        pairs=list(shard_data.keys()))
            
        except Exception as e:
            self.metrics["redis_writes_failed"] += len(shard_data)
            logger.error(f"Failed to write shard {shard_index} {timeframe} to tiered Redis", error=str(e))
            raise
    
    def _extract_latest_candle_from_data(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract the latest candle from processed data for hot tier storage"""
        try:
            # Create a standardized candle object for hot tier
            candle = {
                'time': data.get('timestamp'),
                'open': data.get('open'),
                'high': data.get('high'),
                'low': data.get('low'),
                'close': data.get('close'),
                'volume': data.get('volume', 0),
                'instrument': data.get('instrument'),
                'timeframe': data.get('timeframe'),
                'tier': 'hot',
                'stored_at': datetime.now().isoformat()
            }
            
            # Validate required fields
            if all(candle[field] is not None for field in ['time', 'open', 'high', 'low', 'close']):
                return candle
            else:
                logger.warning("Incomplete candle data for hot tier storage", data=data)
                return None
                
        except Exception as e:
            logger.error(f"Failed to extract latest candle: {e}")
            return None
    
    async def _rotate_hot_to_warm_tier(self, currency_pair: str, timeframe: str, redis_conn):
        """FIXED: Rotate older candles from hot tier to warm tier maintaining chronological order"""
        try:
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            # Check current hot tier size
            hot_count = await redis_conn.llen(keys['hot'])
            
            # Only rotate if hot tier exceeds capacity
            if hot_count > self.settings.hot_tier_candles:
                # Calculate how many candles to move to warm tier
                excess_candles = hot_count - self.settings.hot_tier_candles
                
                # Get oldest candles from hot tier (left side of list)
                candles_to_move = await redis_conn.lrange(keys['hot'], 0, excess_candles - 1)
                
                if candles_to_move:
                    pipe = redis_conn.pipeline()
                    
                    # FIXED: Add to end of warm tier to maintain chronological order
                    # Old hot candles (older than current hot) go to end of warm tier
                    pipe.rpush(keys['warm'], *candles_to_move)
                    
                    # Remove from hot tier (left side)
                    pipe.ltrim(keys['hot'], excess_candles, -1)
                    
                    # FIXED: Maintain warm tier capacity by removing oldest data (right side)
                    # This pushes oldest warm data toward cold tier
                    warm_count_after = await redis_conn.llen(keys['warm']) + len(candles_to_move)
                    if warm_count_after > self.settings.warm_tier_candles:
                        # Before trimming warm tier, check if we need to move data to cold tier
                        await self._rotate_warm_to_cold_tier(currency_pair, timeframe, redis_conn, pipe)
                    
                    # Trim warm tier to capacity (remove from right side - oldest)
                    pipe.ltrim(keys['warm'], 0, self.settings.warm_tier_candles - 1)
                    
                    # Update TTLs
                    pipe.expire(keys['hot'], self.settings.hot_tier_ttl)
                    pipe.expire(keys['warm'], self.settings.warm_tier_ttl)
                    
                    # Store rotation metadata
                    rotation_metadata = {
                        'timestamp': datetime.now().isoformat(),
                        'moved_candles': len(candles_to_move),
                        'hot_count_before': hot_count,
                        'hot_count_after': self.settings.hot_tier_candles,
                        'timeframe': timeframe,
                        'currency_pair': currency_pair,
                        'rotation_type': 'hot_to_warm_chronological'
                    }
                    
                    pipe.setex(
                        keys['rotation_meta'],
                        300,  # 5 minutes TTL for rotation metadata
                        json.dumps(rotation_metadata)
                    )
                    
                    await pipe.execute()
                    
                    logger.info(f"✅ FIXED ROTATION: Moved {len(candles_to_move)} candles from hot to warm tier (chronological)", 
                                currency_pair=currency_pair, timeframe=timeframe)
                    
        except Exception as e:
            logger.error(f"Failed to rotate hot to warm tier for {currency_pair} {timeframe}: {e}")
    
    async def _rotate_warm_to_cold_tier(self, currency_pair: str, timeframe: str, redis_conn, pipe=None):
        """NEW: Rotate oldest candles from warm tier to cold tier to maintain lifecycle"""
        try:
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            # Check current warm tier size
            warm_count = await redis_conn.llen(keys['warm'])
            
            # Only rotate if warm tier will exceed capacity after new additions
            if warm_count >= self.settings.warm_tier_candles:
                # Calculate how many candles to move to cold tier
                excess_candles = warm_count - self.settings.warm_tier_candles + 1
                
                # Get oldest candles from warm tier (right side of list - oldest data)
                candles_to_move = await redis_conn.lrange(keys['warm'], -excess_candles, -1)
                
                if candles_to_move and len(candles_to_move) > 0:
                    # Use existing pipeline if provided, otherwise create new one
                    if pipe is None:
                        pipe = redis_conn.pipeline()
                        execute_pipe = True
                    else:
                        execute_pipe = False
                    
                    # Get existing cold tier data
                    existing_cold_data = await redis_conn.get(keys['cold'])
                    if existing_cold_data:
                        try:
                            existing_cold = json.loads(existing_cold_data.decode('utf-8'))
                            existing_candles = existing_cold.get('candles', [])
                        except:
                            existing_candles = []
                    else:
                        existing_candles = []
                    
                    # Parse candles to move
                    new_cold_candles = []
                    for candle_json in candles_to_move:
                        try:
                            candle = json.loads(candle_json.decode('utf-8') if isinstance(candle_json, bytes) else candle_json)
                            new_cold_candles.append(candle)
                        except:
                            continue
                    
                    # Combine and sort all cold tier candles chronologically
                    all_cold_candles = existing_candles + new_cold_candles
                    all_cold_candles.sort(key=lambda x: x.get('time', ''))
                    
                    # Update cold tier with combined data
                    cold_tier_data = {
                        'candles': all_cold_candles,
                        'timestamp': datetime.now().isoformat(),
                        'source': f'FARGATE_ROTATION_{timeframe}',
                        'count': len(all_cold_candles),
                        'is_bootstrap': False,
                        'last_rotation': datetime.now().isoformat()
                    }
                    
                    pipe.setex(
                        keys['cold'],
                        self.settings.cold_tier_ttl,
                        json.dumps(cold_tier_data)
                    )
                    
                    if execute_pipe:
                        await pipe.execute()
                    
                    logger.info(f"✅ LIFECYCLE: Moved {len(new_cold_candles)} candles from warm to cold tier", 
                                currency_pair=currency_pair, timeframe=timeframe)
                    
        except Exception as e:
            logger.error(f"Failed to rotate warm to cold tier for {currency_pair} {timeframe}: {e}")
    
    async def get_tiered_candlestick_data(self, currency_pair: str, timeframe: str, 
                                        requested_count: int = 500) -> Dict[str, Any]:
        """
        Retrieve candlestick data from tiered storage (hot + warm + cold tiers)
        Optimized for chart loading with 500 candlestick lazy loading
        """
        try:
            # Get Redis connection for this currency pair's shard
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            redis_conn = await self.redis_manager.get_connection(shard_index)
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            candles = []
            sources_used = []
            
            # Step 1: Try to get data from hot tier (most recent 50 candles)
            try:
                hot_data = await redis_conn.lrange(keys['hot'], 0, -1)
                if hot_data:
                    hot_candles = [json.loads(candle_json) if isinstance(candle_json, (bytes, str)) 
                                 else candle_json for candle_json in hot_data]
                    candles.extend(hot_candles)
                    sources_used.append(f"hot({len(hot_candles)})")
                    logger.debug(f"Retrieved {len(hot_candles)} candles from hot tier")
            except Exception as e:
                logger.warning(f"Failed to retrieve hot tier data: {e}")
            
            # Step 2: Get additional data from warm tier if needed
            remaining_needed = requested_count - len(candles)
            if remaining_needed > 0:
                try:
                    warm_data = await redis_conn.lrange(keys['warm'], 0, remaining_needed - 1)
                    if warm_data:
                        warm_candles = [json.loads(candle_json) if isinstance(candle_json, (bytes, str))
                                      else candle_json for candle_json in warm_data]
                        candles.extend(warm_candles)
                        sources_used.append(f"warm({len(warm_candles)})")
                        logger.debug(f"Retrieved {len(warm_candles)} candles from warm tier")
                except Exception as e:
                    logger.warning(f"Failed to retrieve warm tier data: {e}")
            
            # Step 3: Fallback to cold tier (bootstrap data) if still not enough
            remaining_needed = requested_count - len(candles)
            if remaining_needed > 0:
                try:
                    cold_data_raw = await redis_conn.get(keys['cold'])
                    if cold_data_raw:
                        cold_data = self.redis_manager.deserialize_data(cold_data_raw)
                        if cold_data and 'candles' in cold_data:
                            cold_candles = cold_data['candles'][-remaining_needed:]  # Most recent from cold
                            candles.extend(cold_candles)
                            sources_used.append(f"cold({len(cold_candles)})")
                            logger.debug(f"Retrieved {len(cold_candles)} candles from cold tier")
                except Exception as e:
                    logger.warning(f"Failed to retrieve cold tier data: {e}")
            
            # Sort all candles by time (oldest to newest) for proper chart display
            if candles:
                candles.sort(key=lambda x: x.get('time', ''))
            
            # Prepare response with metadata
            response = {
                'candles': candles[-requested_count:],  # Limit to requested count
                'metadata': {
                    'currency_pair': currency_pair,
                    'timeframe': timeframe,
                    'requested_count': requested_count,
                    'actual_count': len(candles),
                    'sources_used': sources_used,
                    'retrieval_timestamp': datetime.now().isoformat(),
                    'tier_architecture': 'hot+warm+cold',
                    'is_complete': len(candles) >= requested_count
                }
            }
            
            logger.info(f"Retrieved {len(candles)} candles for {currency_pair} {timeframe} "
                       f"from tiers: {', '.join(sources_used)}")
            
            return response
            
        except Exception as e:
            logger.error(f"Failed to retrieve tiered data for {currency_pair} {timeframe}: {e}")
            return {
                'candles': [],
                'metadata': {
                    'error': str(e),
                    'currency_pair': currency_pair,
                    'timeframe': timeframe,
                    'retrieval_timestamp': datetime.now().isoformat()
                }
            }
    
    async def get_hot_tier_data_only(self, currency_pair: str, timeframe: str) -> List[Dict[str, Any]]:
        """Get only hot tier data (most recent candles) for real-time updates"""
        try:
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            redis_conn = await self.redis_manager.get_connection(shard_index)
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            hot_data = await redis_conn.lrange(keys['hot'], 0, -1)
            if hot_data:
                candles = [json.loads(candle_json) if isinstance(candle_json, (bytes, str))
                          else candle_json for candle_json in hot_data]
                return sorted(candles, key=lambda x: x.get('time', ''))
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to retrieve hot tier data for {currency_pair} {timeframe}: {e}")
            return []
    
    async def get_tier_stats(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Get statistics about tier storage for monitoring and debugging"""
        try:
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            redis_conn = await self.redis_manager.get_connection(shard_index)
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            # Get counts for each tier
            hot_count = await redis_conn.llen(keys['hot'])
            warm_count = await redis_conn.llen(keys['warm'])
            
            # Check cold tier
            cold_exists = await redis_conn.exists(keys['cold'])
            cold_count = 0
            if cold_exists:
                cold_data_raw = await redis_conn.get(keys['cold'])
                if cold_data_raw:
                    cold_data = self.redis_manager.deserialize_data(cold_data_raw)
                    cold_count = len(cold_data.get('candles', []))
            
            # Get TTLs
            hot_ttl = await redis_conn.ttl(keys['hot'])
            warm_ttl = await redis_conn.ttl(keys['warm'])
            cold_ttl = await redis_conn.ttl(keys['cold'])
            
            # Get rotation metadata if available
            rotation_meta = None
            try:
                rotation_meta_raw = await redis_conn.get(keys['rotation_meta'])
                if rotation_meta_raw:
                    rotation_meta = json.loads(rotation_meta_raw)
            except:
                pass
            
            return {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'tiers': {
                    'hot': {
                        'count': hot_count,
                        'capacity': self.settings.hot_tier_candles,
                        'ttl_seconds': hot_ttl,
                        'utilization': hot_count / self.settings.hot_tier_candles if self.settings.hot_tier_candles > 0 else 0
                    },
                    'warm': {
                        'count': warm_count,
                        'capacity': self.settings.warm_tier_candles,
                        'ttl_seconds': warm_ttl,
                        'utilization': warm_count / self.settings.warm_tier_candles if self.settings.warm_tier_candles > 0 else 0
                    },
                    'cold': {
                        'count': cold_count,
                        'ttl_seconds': cold_ttl,
                        'exists': cold_exists
                    }
                },
                'total_candles': hot_count + warm_count + cold_count,
                'last_rotation': rotation_meta,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to get tier stats for {currency_pair} {timeframe}: {e}")
            return {'error': str(e)}
    
    async def _write_pricing_to_redis(self, shard_index: int, pricing_data: Dict[str, Any]):
        """Write current pricing data to Redis"""
        try:
            # Get Redis connection for this shard
            redis_conn = await self.redis_manager.get_connection(shard_index)
            
            # Prepare batch operations
            pipe = redis_conn.pipeline()
            
            for currency_pair, data in pricing_data.items():
                # Current pricing key
                pricing_key = f"market_data:{currency_pair}:pricing:current"
                
                # Store current pricing
                pipe.setex(
                    pricing_key,
                    300,  # 5 minute TTL for current pricing
                    self.redis_manager.serialize_data(data)
                )
                
                # Update last pricing timestamp
                timestamp_key = f"market_data:{currency_pair}:pricing:last_update"
                pipe.setex(
                    timestamp_key,
                    300,
                    datetime.now().isoformat()
                )
            
            # Execute batch operations
            await pipe.execute()
            
            logger.debug(f"Shard {shard_index} pricing data written to Redis", 
                        pairs=list(pricing_data.keys()))
            
        except Exception as e:
            logger.error(f"Failed to write shard {shard_index} pricing to Redis", error=str(e))
            raise
    
    def _group_pairs_by_shard(self) -> Dict[int, List[str]]:
        """Group currency pairs by their Redis shard assignment"""
        shard_groups = {}
        
        for pair in self.settings.currency_pairs:
            shard_index = self.settings.get_redis_node_for_pair(pair)
            
            if shard_index not in shard_groups:
                shard_groups[shard_index] = []
            
            shard_groups[shard_index].append(pair)
        
        return shard_groups
    
    async def collect_and_distribute_account_data(self):
        """
        Collect account data (trades, positions, orders) and store in Redis
        This implements the robust trade logging infrastructure matching Airtable's capabilities
        """
        current_time = datetime.now()
        
        # Check if it's time to collect account data (every 60 seconds) 
        # TEMPORARILY DISABLED FOR DEBUGGING - always collect account data
        # if (self.last_account_collection and 
        #     (current_time - self.last_account_collection).total_seconds() < self.account_collection_interval):
        #     return
        
        logger.info("💼 Starting account data collection (trade logging infrastructure)")
        print("DEBUG: Starting account data collection")
        
        try:
            # Use comprehensive orchestrator if available (includes cleanup), otherwise fallback
            if self.comprehensive_orchestrator:
                logger.info("🚀 Using comprehensive data orchestrator with built-in cleanup")
                
                # Initialize if not already done
                if not self._comprehensive_initialized:
                    print("DEBUG: Initializing comprehensive orchestrator")
                    init_success = await self.comprehensive_orchestrator.initialize()
                    self._comprehensive_initialized = init_success
                    if not init_success:
                        logger.error("Failed to initialize comprehensive orchestrator")
                        return
                    logger.info("✅ Comprehensive orchestrator initialized successfully")
                
                print("DEBUG: About to call comprehensive_orchestrator.collect_and_store_comprehensive_data()")
                success = await self.comprehensive_orchestrator.collect_and_store_comprehensive_data()
                if success:
                    logger.info("✅ Comprehensive data collection and cleanup completed successfully")
                    print("DEBUG: Comprehensive orchestrator completed successfully")
                    return  # Exit early since comprehensive orchestrator handles everything
                else:
                    logger.warning("⚠️ Comprehensive orchestrator failed, no fallback available")
                    print("DEBUG: Comprehensive orchestrator failed, no fallback available")
                    return
            
            # Only use enhanced data collector if comprehensive orchestrator doesn't exist
            if self.enhanced_data_collector is not None:
                logger.info("🚀 Using enhanced OANDA data collection with Distance to Entry (fallback)")
                print("DEBUG: About to call enhanced_data_collector.collect_comprehensive_trade_data()")
                comprehensive_data = await self.enhanced_data_collector.collect_comprehensive_trade_data()
            else:
                logger.error("❌ No data collector available")
                print("DEBUG: No data collector available")
                return
            print(f"DEBUG: Enhanced data result type: {type(comprehensive_data)}, content: {comprehensive_data}")
            
            print(f"DEBUG: Checking if comprehensive_data is truthy: {bool(comprehensive_data)}")
            print(f"DEBUG: comprehensive_data keys: {list(comprehensive_data.keys()) if isinstance(comprehensive_data, dict) else 'Not a dict'}")
            
            if not comprehensive_data:
                logger.warning("No comprehensive data received from enhanced OANDA collector")
                print("DEBUG: Enhanced data was empty, falling back to basic collection")
                # Fallback to basic collection
                logger.info("📊 Falling back to basic account data collection")
                account_data = await self.oanda_client.get_all_account_data()
                print(f"DEBUG: Basic account data result: {type(account_data)}, keys: {account_data.keys() if account_data else 'None'}")
                if not account_data:
                    logger.warning("No account data received from OANDA")
                    print("DEBUG: Basic account data was also empty, returning early")
                    return
            else:
                print("DEBUG: Enhanced data was not empty, entering enhanced path")
                logger.info(f"✅ Enhanced data collected: {len(comprehensive_data.get('trades', []))} trades with full OANDA data")
                
                # Still need to collect pending orders, closed trades, and positions
                logger.info("📊 Collecting additional account data (pending orders, closed trades, positions)...")
                
                # Collect pending orders separately
                pending_orders = await self.oanda_client.get_pending_orders()
                logger.info(f"🔍 DEBUG: Pending orders collected: {len(pending_orders.get('orders', [])) if pending_orders else 0} orders")
                print(f"DEBUG: Pending orders result: {pending_orders}")
                
                # Get last sync time to enable incremental collection
                last_sync_time = None
                if self.database_manager and hasattr(self.database_manager, 'get_last_closed_trades_sync_time'):
                    try:
                        last_sync_time = await self.database_manager.get_last_closed_trades_sync_time()
                    except:
                        pass
                
                # Determine from_time for closed trades collection
                from_time = "2025-06-01T00:00:00Z"  # Default: last 2 months
                if last_sync_time:
                    # Incremental: only get trades since last sync
                    from_time = last_sync_time
                    logger.info(f"📅 Incremental closed trades sync from: {last_sync_time}")
                else:
                    logger.info(f"📅 Full closed trades sync from: {from_time}")
                
                closed_trades_raw = await self.oanda_client.get_closed_trades(from_time=from_time)
                
                # Enhance closed trades with stop_loss and take_profit using proven Airtable logic
                if closed_trades_raw and self.enhanced_data_collector:
                    logger.info("🔍 Enhancing closed trades with stop_loss/take_profit extraction")
                    closed_trades = await self.enhanced_data_collector.enhance_closed_trades(closed_trades_raw)
                    logger.info("✅ Closed trades enhanced with SL/TP data using Airtable-proven logic")
                else:
                    closed_trades = closed_trades_raw
                    logger.warning("⚠️ Using raw closed trades data (no enhancement)")
                
                open_positions = await self.oanda_client.get_open_positions()
                account_summary = await self.oanda_client.get_account_summary()
                
                # Get current pricing for pending order instruments
                pending_order_instruments = []
                if pending_orders and pending_orders.get('orders'):
                    for order in pending_orders['orders']:
                        instrument = order.get('instrument')
                        if instrument and instrument not in pending_order_instruments:
                            pending_order_instruments.append(instrument)
                
                current_pricing = None
                if pending_order_instruments:
                    logger.info(f"📈 Getting current pricing for {len(pending_order_instruments)} pending order instruments")
                    current_pricing = await self.oanda_client.get_account_pricing(pending_order_instruments)
                    logger.info(f"💰 Current pricing collected for {len(current_pricing.get('prices', [])) if current_pricing else 0} instruments")
                
                # Merge enhanced trades with other account data
                account_data = {
                    "open_trades": comprehensive_data,
                    "pending_orders": pending_orders,
                    "closed_trades": closed_trades,
                    "open_positions": open_positions,
                    "account_summary": account_summary,
                    "current_pricing": current_pricing,
                    "collection_stats": {
                        "open_trades_count": len(comprehensive_data.get('trades', [])),
                        "pending_orders_count": len(pending_orders.get('orders', [])) if pending_orders else 0,
                        "closed_trades_count": len(closed_trades.get('trades', [])) if closed_trades else 0,
                        "open_positions_count": len(open_positions.get('positions', [])) if open_positions else 0,
                        "pricing_instruments_count": len(current_pricing.get('prices', [])) if current_pricing else 0,
                        **comprehensive_data.get('enhancement_metadata', {})
                    }
                }
            
            # Store account data in Redis with appropriate keys
            await self._store_account_data_in_redis(account_data)
            
            # Run trade_id linking enhancement every 5 minutes (300 seconds)
            last_linking = self.metrics.get("last_trade_id_linking")
            if (not last_linking or 
                (current_time - last_linking).total_seconds() > 300):
                logger.info("🔗 Running scheduled trade_id linking enhancement...")
                await self.enhance_closed_trades_with_trade_id_linking()
            
            # Update metrics
            self.account_collection_count += 1
            self.last_account_collection = current_time
            self.metrics["account_collections_completed"] += 1
            self.metrics["last_account_collection"] = current_time.isoformat()
            
            # Update collection counts
            stats = account_data.get("collection_stats", {})
            self.metrics["open_trades_collected"] += stats.get("open_trades_count", 0)
            self.metrics["closed_trades_collected"] += stats.get("closed_trades_count", 0)
            self.metrics["pending_orders_collected"] += stats.get("pending_orders_count", 0)
            self.metrics["positions_collected"] += stats.get("open_positions_count", 0)
            
            logger.info("✅ Account data collection completed",
                       open_trades=stats.get("open_trades_count", 0),
                       closed_trades=stats.get("closed_trades_count", 0),
                       pending_orders=stats.get("pending_orders_count", 0),
                       positions=stats.get("open_positions_count", 0))
            
        except Exception as e:
            self.metrics["account_collections_failed"] += 1
            logger.error("❌ Account data collection failed", error=str(e))
            # Don't raise - continue with market data collection
    
    async def _store_account_data_in_redis(self, account_data: Dict[str, Any]):
        """
        Store account data in Redis using proper keys for the trade logging infrastructure
        Keys follow pattern: account_data:{data_type}:{identifier}
        """
        try:
            # Use Redis node 0 for all account data (centralized)
            redis_conn = await self.redis_manager.get_connection(0)
            pipe = redis_conn.pipeline()
            
            current_time = datetime.now().isoformat()
            ttl = 3600  # 1 hour TTL for account data
            
            # Detect newly closed trades for future enhancement
            current_trade_ids = set()
            if account_data.get("open_trades") and account_data["open_trades"].get("trades"):
                for trade in account_data["open_trades"]["trades"]:
                    if trade.get("id"):
                        current_trade_ids.add(trade["id"])
            
            # Check for trades that were open but are now closed
            if self.previous_trade_ids:
                newly_closed_ids = self.previous_trade_ids - current_trade_ids
                if newly_closed_ids:
                    logger.info(f"🔄 Detected {len(newly_closed_ids)} newly closed trades: {newly_closed_ids}")
                    # These will be picked up in the next closed trades collection cycle
            
            # Update previous trade IDs for next iteration
            self.previous_trade_ids = current_trade_ids
            
            # Store enhanced open trades with comprehensive data
            if account_data.get("open_trades") and account_data["open_trades"].get("trades"):
                trades_data = {}
                enhanced_trades = account_data["open_trades"]["trades"]
                
                for trade in enhanced_trades:
                    trade_id = trade.get("id")
                    if trade_id:
                        # Use new strategy mapping method to enhance trade data
                        await self.redis_manager.write_trade_data_with_strategy_mapping(trade)
                        trades_data[trade_id] = trade
                
                # Store enhanced trades in Redis for Lambda access (legacy format)
                pipe.setex(
                    "account_data:trades:open",
                    ttl,
                    self.redis_manager.serialize_data(trades_data)
                )
                
                # Store in RDS using enhanced database manager for comprehensive data
                if self.database_manager:
                    # Check if we have enhanced data with distance_to_entry
                    if hasattr(self.database_manager, 'store_comprehensive_active_trades'):
                        logger.info("🗄️ Using enhanced database manager for comprehensive OANDA data storage")
                        success = await self.database_manager.store_comprehensive_active_trades(enhanced_trades)
                        if success:
                            logger.info(f"✅ Stored {len(enhanced_trades)} trades with Distance to Entry in RDS")
                        else:
                            logger.warning("❌ Enhanced RDS storage failed, trying basic storage")
                            await self.database_manager.store_active_trades(enhanced_trades)
                    else:
                        logger.info("📊 Using basic database manager for RDS storage")
                        await self.database_manager.store_active_trades(enhanced_trades)
                
                logger.info(f"✅ Stored {len(trades_data)} enhanced trades (Redis + RDS) with Target/Stop/R&R data")
                
                # Log sample enhanced data for verification
                if enhanced_trades:
                    sample_trade = enhanced_trades[0]
                    logger.info(f"📊 Sample Enhanced Trade: {sample_trade.get('instrument')} "
                              f"T:{sample_trade.get('take_profit_price')} "
                              f"S:{sample_trade.get('stop_loss_price')} "
                              f"R:R:{sample_trade.get('risk_reward_ratio')} "
                              f"Pips:{sample_trade.get('pips_moved')}")
            
            # Store closed trades (recent ones in Redis, all in RDS for historical data)
            if account_data.get("closed_trades") and account_data["closed_trades"].get("trades"):
                closed_trades = account_data["closed_trades"]["trades"]
                
                # Enhance closed trades with SL/TP data
                logger.info(f"🔍 Enhancing {len(closed_trades)} closed trades with SL/TP data")
                enhanced_closed_trades = []
                for trade in closed_trades:
                    try:
                        # Check if trade needs enhancement (missing SL/TP) - DISABLED due to 403 errors
                        # if not trade.get('stop_loss') or not trade.get('take_profit'):
                        #     enhanced_trade = await self.closed_trade_enhancer.enhance_closed_trade(trade)
                        #     enhanced_closed_trades.append(enhanced_trade)
                        #     if enhanced_trade.get('stop_loss') or enhanced_trade.get('take_profit'):
                        #         self.metrics["closed_trades_enhanced"] += 1
                        #         logger.info(f"✅ Enhanced trade {trade.get('id')} with SL:{enhanced_trade.get('stop_loss')} TP:{enhanced_trade.get('take_profit')}")
                        # else:
                        #     enhanced_closed_trades.append(trade)
                        
                        # Use trade as-is - SL/TP extraction handled by enhanced_database_manager.py
                        enhanced_closed_trades.append(trade)
                    except Exception as e:
                        logger.error(f"Failed to enhance trade {trade.get('id')}: {str(e)}")
                        enhanced_closed_trades.append(trade)  # Use original if enhancement fails
                
                closed_trades = enhanced_closed_trades
                logger.info(f"✅ Enhanced {self.metrics['closed_trades_enhanced']} trades with SL/TP data")
                
                # Store recent closed trades in Redis (24 hours for Lambda access)
                recent_ttl = 86400  # 24 hours
                pipe.setex(
                    "account_data:trades:closed",
                    recent_ttl,
                    self.redis_manager.serialize_data(closed_trades)
                )
                
                logger.debug(f"Storing {len(closed_trades)} closed trades in Redis (24h TTL)")
                
                # Store ALL closed trades in RDS for permanent historical record
                if self.database_manager and hasattr(self.database_manager, 'bulk_upsert_closed_trades'):
                    try:
                        # Get last sync time for incremental updates
                        last_sync_time = await self.database_manager.get_last_closed_trades_sync_time()
                        
                        # Store closed trades in RDS
                        success = await self.database_manager.bulk_upsert_closed_trades(
                            closed_trades, 
                            current_time
                        )
                        
                        if success:
                            logger.info(f"✅ Stored {len(closed_trades)} closed trades in RDS (permanent historical record)")
                            
                            # Automatically fix any 'Unknown Strategy' trades
                            if hasattr(self.database_manager, 'fix_unknown_strategies'):
                                try:
                                    await self.database_manager.fix_unknown_strategies()
                                except Exception as fix_error:
                                    logger.error(f"⚠️ Strategy fix failed: {str(fix_error)}")
                        else:
                            logger.warning("❌ Failed to store closed trades in RDS")
                            
                    except Exception as e:
                        logger.error(f"❌ Failed to store closed trades in RDS: {str(e)}")
                else:
                    logger.info("📝 RDS closed trades storage not available (using enhanced database manager)")
            
            # Initialize sync metadata table on first run
            if self.database_manager and hasattr(self.database_manager, 'create_sync_metadata_table_if_not_exists'):
                try:
                    await self.database_manager.create_sync_metadata_table_if_not_exists()
                except Exception as e:
                    logger.warning(f"Could not create sync metadata table: {str(e)}")
            
            # Store pending orders
            if account_data.get("pending_orders") and account_data["pending_orders"].get("orders"):
                orders_data = {}
                for order in account_data["pending_orders"]["orders"]:
                    order_id = order.get("id")
                    if order_id:
                        orders_data[order_id] = order
                
                pipe.setex(
                    "account_data:orders:pending",
                    ttl,
                    self.redis_manager.serialize_data(orders_data)
                )
                
                logger.debug(f"Storing {len(orders_data)} pending orders in Redis")
                
                # Store pending orders in RDS
                if self.database_manager:
                    try:
                        # Transform OANDA orders to RDS format - only standalone orders (not attached to trades)
                        orders_for_rds = []
                        standalone_orders = []
                        
                        # Get current pricing for pending order instruments
                        pricing_data = account_data.get("current_pricing", {})
                        
                        for order in account_data["pending_orders"]["orders"]:
                            # Only include standalone pending orders (no tradeID means it's not attached to an active trade)
                            if not order.get("tradeID"):
                                standalone_orders.append(order)
                                order_data = self._transform_order_for_rds(order, pricing_data)
                                if order_data:
                                    orders_for_rds.append(order_data)
                        
                        logger.info(f"📋 Found {len(standalone_orders)} standalone pending orders (filtered out {len(account_data['pending_orders']['orders']) - len(standalone_orders)} trade-attached orders)")
                        
                        if orders_for_rds:
                            await self.database_manager.bulk_upsert_pending_orders(orders_for_rds)
                            logger.info(f"✅ Stored {len(orders_for_rds)} pending orders in RDS")
                    except Exception as e:
                        logger.error(f"❌ Failed to store pending orders in RDS: {str(e)}")
            
            # Store open positions
            if account_data.get("open_positions") and account_data["open_positions"].get("positions"):
                positions_data = {}
                for position in account_data["open_positions"]["positions"]:
                    instrument = position.get("instrument")
                    if instrument:
                        positions_data[instrument] = position
                
                pipe.setex(
                    "account_data:positions:current",
                    ttl,
                    self.redis_manager.serialize_data(positions_data)
                )
                
                logger.debug(f"Storing {len(positions_data)} open positions in Redis")
                
                # Store positions in RDS as well (matching Airtable sync)
                if self.database_manager and hasattr(self.database_manager, 'store_positions'):
                    try:
                        positions_list = list(account_data["open_positions"]["positions"])
                        success = await self.database_manager.store_positions(positions_list)
                        if success:
                            logger.info(f"✅ Stored {len(positions_list)} positions in RDS")
                        else:
                            logger.warning("Failed to store positions in RDS")
                    except Exception as e:
                        logger.error(f"❌ Failed to store positions in RDS: {str(e)}")
                
                # Calculate and store exposures in RDS (matching Airtable sync)
                if self.database_manager and hasattr(self.database_manager, 'store_exposures'):
                    try:
                        positions_list = list(account_data["open_positions"]["positions"])
                        # Get account balance from account summary if available
                        account_balance = 100000.0  # Default fallback
                        if account_data.get("account_summary") and account_data["account_summary"].get("balance"):
                            account_balance = float(account_data["account_summary"]["balance"])
                        
                        success = await self.database_manager.store_exposures(positions_list, account_balance)
                        if success:
                            logger.info(f"✅ Calculated and stored currency exposures in RDS")
                        else:
                            logger.warning("Failed to store exposures in RDS")
                    except Exception as e:
                        logger.error(f"❌ Failed to store exposures in RDS: {str(e)}")
            
            # Store account summary
            if account_data.get("account_summary"):
                pipe.setex(
                    "account_data:summary:current",
                    ttl,
                    self.redis_manager.serialize_data(account_data["account_summary"])
                )
            
            # Store current pricing (for trade P&L calculations)
            if account_data.get("current_pricing"):
                pipe.setex(
                    "account_data:pricing:current",
                    300,  # 5 minutes TTL for pricing
                    self.redis_manager.serialize_data(account_data["current_pricing"])
                )
            
            # Store collection metadata
            metadata = {
                "collection_timestamp": current_time,
                "collection_stats": account_data.get("collection_stats", {}),
                "data_source": "OANDA_VIA_FARGATE",
                "infrastructure_type": "trade_logging"
            }
            
            pipe.setex(
                "account_data:meta:last_collection",
                ttl,
                self.redis_manager.serialize_data(metadata)
            )
            
            # Execute all Redis operations
            await pipe.execute()
            
            logger.debug("Account data stored in Redis successfully")
            
        except Exception as e:
            logger.error("Failed to store account data in Redis", error=str(e))
            raise

    async def backfill_historical_closed_trades(self, days_back: int = 90):
        """
        Backfill historical closed trades for specified number of days
        This handles the 60+ days scenario that Redis can't store
        """
        logger.info(f"🏛️ Starting historical closed trades backfill for {days_back} days")
        
        if not self.database_manager or not hasattr(self.database_manager, 'bulk_upsert_closed_trades'):
            logger.error("Enhanced database manager required for historical backfill")
            return False
        
        try:
            # Calculate from_time for historical collection
            from datetime import timedelta
            from_date = datetime.now() - timedelta(days=days_back)
            from_time = from_date.isoformat() + "Z"
            
            logger.info(f"📅 Collecting closed trades from: {from_time}")
            
            # Get historical closed trades from OANDA
            historical_trades = await self.oanda_client.get_closed_trades(
                from_time=from_time, 
                count=1000  # Maximum batch size
            )
            
            if not historical_trades or not historical_trades.get('trades'):
                logger.info("No historical closed trades found")
                return True
            
            trades_list = historical_trades['trades']
            logger.info(f"📊 Retrieved {len(trades_list)} historical closed trades")
            
            # Store in RDS
            success = await self.database_manager.bulk_upsert_closed_trades(
                trades_list, 
                datetime.now().isoformat()
            )
            
            if success:
                logger.info(f"✅ Historical backfill completed: {len(trades_list)} trades stored")
                
                # Automatically fix any 'Unknown Strategy' trades after backfill
                if hasattr(self.database_manager, 'fix_unknown_strategies'):
                    try:
                        await self.database_manager.fix_unknown_strategies()
                    except Exception as fix_error:
                        logger.error(f"⚠️ Strategy fix after backfill failed: {str(fix_error)}")
                
                return True
            else:
                logger.error("❌ Historical backfill failed during RDS storage")
                return False
                
        except Exception as e:
            logger.error(f"❌ Historical closed trades backfill failed: {str(e)}", exc_info=True)
            return False

    async def enhance_closed_trades_with_trade_id_linking(self):
        """
        Enhance closed trades by linking real SL/TP data from active_trades and pending_orders
        This runs as part of the regular data collection cycle and scales to any number of strategies
        
        This approach uses actual trade_id relationships instead of strategy-based estimates
        """
        if not self.database_manager:
            logger.warning("⚠️ Database manager not available for trade_id linking")
            return
        
        try:
            logger.info("🔗 Starting trade_id linking enhancement...")
            
            # Get database connection - fix for EnhancedDatabaseManager
            if hasattr(self.database_manager, 'connection_pool') and self.database_manager.connection_pool:
                conn = await self.database_manager.connection_pool.acquire()
            elif hasattr(self.database_manager, 'get_connection'):
                conn = await self.database_manager.get_connection()
            elif hasattr(self.database_manager, 'pool') and self.database_manager.pool:
                conn = await self.database_manager.pool.acquire()
            else:
                logger.error("Cannot get database connection for trade_id linking")
                logger.error(f"Available attributes: {[attr for attr in dir(self.database_manager) if not attr.startswith('_')]}")
                return
            
            try:
                # Step 1: Link from active_trades
                logger.info("🔗 Linking SL/TP data from active_trades...")
                active_result = await conn.execute("""
                    UPDATE closed_trades 
                    SET 
                        stop_loss = at.stop_loss_price,
                        take_profit = at.take_profit_price,
                        return_risk_ratio = at.risk_reward_ratio
                    FROM active_trades at
                    WHERE closed_trades.trade_id = at.trade_id
                      AND at.stop_loss_price > 0 
                      AND (closed_trades.stop_loss IS NULL OR closed_trades.stop_loss = 0)
                """)
                active_count = int(active_result.split()[-1]) if 'UPDATE' in str(active_result) else 0
                logger.info(f"✅ Updated {active_count} trades from active_trades")
                
                # Step 2: Link from pending_orders  
                logger.info("🔗 Linking SL/TP data from pending_orders...")
                pending_result = await conn.execute("""
                    WITH sl_tp_from_pending AS (
                        SELECT 
                            order_id,
                            MAX(CASE WHEN order_type IN ('STOP_LOSS', 'STOP') THEN order_price END) as sl_price,
                            MAX(CASE WHEN order_type IN ('TAKE_PROFIT', 'LIMIT') THEN order_price END) as tp_price
                        FROM pending_orders
                        WHERE order_id IS NOT NULL 
                          AND order_type IN ('STOP_LOSS', 'TAKE_PROFIT', 'STOP', 'LIMIT')
                        GROUP BY order_id
                    )
                    UPDATE closed_trades 
                    SET 
                        stop_loss = COALESCE(closed_trades.stop_loss, stp.sl_price),
                        take_profit = COALESCE(closed_trades.take_profit, stp.tp_price)
                    FROM sl_tp_from_pending stp
                    WHERE closed_trades.trade_id = stp.order_id
                      AND (stp.sl_price > 0 OR stp.tp_price > 0)
                      AND (closed_trades.stop_loss IS NULL OR closed_trades.stop_loss = 0 OR 
                           closed_trades.take_profit IS NULL OR closed_trades.take_profit = 0)
                """)
                pending_count = int(pending_result.split()[-1]) if 'UPDATE' in str(pending_result) else 0
                logger.info(f"✅ Updated {pending_count} trades from pending_orders")
                
                # Step 3: Calculate RRR for newly enhanced trades
                logger.info("📊 Calculating risk-reward ratios...")
                rrr_result = await conn.execute("""
                    UPDATE closed_trades 
                    SET return_risk_ratio = CASE 
                        WHEN stop_loss > 0 AND take_profit > 0 THEN
                            CASE 
                                WHEN units > 0 THEN  -- Long position
                                    (take_profit - entry_price) / NULLIF(entry_price - stop_loss, 0)
                                ELSE  -- Short position
                                    (entry_price - take_profit) / NULLIF(stop_loss - entry_price, 0)
                            END
                        ELSE return_risk_ratio
                    END
                    WHERE stop_loss > 0 AND take_profit > 0 
                      AND (return_risk_ratio IS NULL OR return_risk_ratio = 0)
                """)
                rrr_count = int(rrr_result.split()[-1]) if 'UPDATE' in str(rrr_result) else 0
                logger.info(f"✅ Calculated RRR for {rrr_count} trades")
                
                # Update metrics
                self.metrics["trade_id_linking_active"] += active_count
                self.metrics["trade_id_linking_pending"] += pending_count
                self.metrics["trade_id_linking_rrr"] += rrr_count
                self.metrics["last_trade_id_linking"] = datetime.now()
                
                total_enhanced = active_count + pending_count
                logger.info(f"✅ Trade ID linking completed: {total_enhanced} trades enhanced with real SL/TP data")
                
                if total_enhanced > 0:
                    # Log sample of enhanced trades for verification
                    sample_result = await conn.fetch("""
                        SELECT trade_id, instrument, entry_price, stop_loss, take_profit, return_risk_ratio
                        FROM closed_trades
                        WHERE stop_loss > 0 AND take_profit > 0
                        ORDER BY last_updated DESC
                        LIMIT 3
                    """)
                    
                    if sample_result:
                        logger.info("📋 Sample enhanced trades:")
                        for trade in sample_result:
                            logger.info(f"  {trade['trade_id']} ({trade['instrument']}): "
                                      f"Entry={trade['entry_price']}, SL={trade['stop_loss']}, "
                                      f"TP={trade['take_profit']}, RRR={trade['return_risk_ratio']:.2f}")
                
            finally:
                # Release connection - fix for EnhancedDatabaseManager  
                if hasattr(self.database_manager, 'connection_pool') and hasattr(conn, 'close'):
                    await self.database_manager.connection_pool.release(conn)
                elif hasattr(self.database_manager, 'pool') and hasattr(conn, 'close'):
                    await self.database_manager.pool.release(conn)
                elif hasattr(conn, 'close'):
                    await conn.close()
        
        except Exception as e:
            self.metrics["trade_id_linking_errors"] += 1
            logger.error(f"❌ Trade ID linking failed: {str(e)}", exc_info=True)

    def _transform_order_for_rds(self, order: Dict[str, Any], pricing_data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Transform OANDA order data to RDS pending_orders table format with current pricing"""
        try:
            # Required fields
            order_id = order.get("id")
            instrument = order.get("instrument")
            if not order_id or not instrument:
                return None
            
            # Parse units and determine direction
            units = int(order.get("units", 0))
            direction = "Long" if units > 0 else "Short"
            absolute_units = abs(units)
            
            # Get prices
            order_price = float(order.get("price", 0))
            current_price = self._get_current_price_for_instrument(instrument, pricing_data)
            
            # Calculate distance to market in pips
            distance_to_market = self._calculate_distance_to_market(order_price, current_price, instrument, direction)
            
            # Order metadata
            order_type = order.get("type", "LIMIT")
            time_in_force = order.get("timeInForce", "GTC")
            gtd_time = None
            if order.get("gtdTime"):
                try:
                    from datetime import datetime
                    gtd_time = datetime.fromisoformat(order.get("gtdTime").replace('Z', '+00:00'))
                except:
                    gtd_time = None
            
            position_fill = order.get("positionFill", "DEFAULT")
            trigger_condition = order.get("triggerCondition", "DEFAULT")
            
            # Risk management
            stop_loss = None
            take_profit = None
            if order.get("stopLossOnFill", {}).get("price"):
                stop_loss = float(order.get("stopLossOnFill", {}).get("price"))
            if order.get("takeProfitOnFill", {}).get("price"):
                take_profit = float(order.get("takeProfitOnFill", {}).get("price"))
            
            # Timing - convert to Eastern Time for consistent display
            created_time = None
            if order.get("createTime"):
                try:
                    import pytz
                    from datetime import datetime
                    # Parse OANDA time (UTC) and convert to Eastern
                    utc_time = datetime.fromisoformat(order.get("createTime").replace('Z', '+00:00'))
                    eastern_tz = pytz.timezone('US/Eastern')
                    created_time = utc_time.astimezone(eastern_tz).replace(tzinfo=None)  # Make naive Eastern
                except:
                    created_time = None
            
            # Current time in Eastern for last_updated
            import pytz
            eastern_tz = pytz.timezone('US/Eastern')
            last_updated_eastern = datetime.now(eastern_tz).replace(tzinfo=None)  # Make naive Eastern
            
            return {
                'order_id': order_id,
                'instrument': instrument,
                'direction': direction,
                'units': absolute_units,
                'order_price': order_price,
                'current_price': current_price,
                'distance_to_market': distance_to_market,
                'order_type': order_type,
                'time_in_force': time_in_force,
                'gtd_time': gtd_time,
                'position_fill': position_fill,
                'trigger_condition': trigger_condition,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'created_time': created_time,
                'last_updated': last_updated_eastern
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to transform order {order.get('id', 'unknown')}: {str(e)}")
            return None

    def _get_current_price_for_instrument(self, instrument: str, pricing_data: Dict[str, Any] = None) -> Optional[float]:
        """Extract current mid price for an instrument from pricing data"""
        if not pricing_data or not pricing_data.get('prices'):
            return None
            
        for price_info in pricing_data['prices']:
            if price_info.get('instrument') == instrument:
                try:
                    # Get bid and ask prices
                    bids = price_info.get('bids', [])
                    asks = price_info.get('asks', [])
                    
                    if bids and asks:
                        bid_price = float(bids[0]['price'])
                        ask_price = float(asks[0]['price'])
                        # Use mid price for calculations
                        mid_price = (bid_price + ask_price) / 2
                        return mid_price
                except (ValueError, TypeError, KeyError, IndexError):
                    continue
        
        return None

    def _calculate_distance_to_market(self, order_price: float, current_price: Optional[float], 
                                    instrument: str, direction: str) -> Optional[float]:
        """Calculate distance from order price to current market price in pips"""
        if not current_price or not order_price:
            return None
            
        # Import pip calculation from trade_calculations
        from .trade_calculations import calculate_pips_moved
        
        # For pending orders, we want to know how far the market needs to move to hit the order
        # This is different from trades - we calculate absolute distance regardless of direction
        try:
            # Calculate pip difference between order price and current market price
            # For pending orders, direction doesn't matter for distance calculation
            pip_values = {
                # Major pairs (4 decimal places)
                'EUR_USD': 0.0001, 'GBP_USD': 0.0001, 'USD_CHF': 0.0001, 'USD_CAD': 0.0001,
                'AUD_USD': 0.0001, 'NZD_USD': 0.0001, 'EUR_GBP': 0.0001, 'EUR_CHF': 0.0001,
                'GBP_CHF': 0.0001, 'EUR_CAD': 0.0001, 'GBP_CAD': 0.0001, 'AUD_CAD': 0.0001,
                'EUR_AUD': 0.0001, 'GBP_AUD': 0.0001, 'EUR_NZD': 0.0001, 'GBP_NZD': 0.0001,
                'AUD_NZD': 0.0001, 'CAD_CHF': 0.0001, 'AUD_CHF': 0.0001, 'NZD_CHF': 0.0001,
                
                # Yen pairs (2 decimal places)
                'USD_JPY': 0.01, 'EUR_JPY': 0.01, 'GBP_JPY': 0.01, 'CHF_JPY': 0.01,
                'CAD_JPY': 0.01, 'AUD_JPY': 0.01, 'NZD_JPY': 0.01
            }
            
            pip_value = pip_values.get(instrument, 0.0001)  # Default to 4 decimal places
            price_difference = abs(order_price - current_price)  # Always positive distance
            distance_pips = price_difference / pip_value
            
            return round(distance_pips, 1)
            
        except Exception as e:
            logger.error(f"Failed to calculate distance to market for {instrument}: {str(e)}")
            return None

    async def get_metrics(self) -> Dict[str, Any]:
        """Get orchestrator performance metrics"""
        current_time = datetime.now()
        uptime = current_time - self.metrics["uptime_start"]
        
        return {
            **self.metrics,
            "uptime_seconds": uptime.total_seconds(),
            "uptime_formatted": str(uptime),
            "current_time": current_time.isoformat(),
            "is_running": self.is_running,
            "last_collection_time": self.last_collection_time.isoformat() if self.last_collection_time else None,
            "last_account_collection": self.last_account_collection.isoformat() if self.last_account_collection else None,
            "last_trade_id_linking": self.metrics["last_trade_id_linking"].isoformat() if self.metrics["last_trade_id_linking"] else None,
            "last_timeframe_collections": {tf: dt.isoformat() if dt else None for tf, dt in self.last_timeframe_collection.items()},
            "timeframe_collection_counts": dict(self.timeframe_collection_counts),
            "trade_id_linking_status": {
                "active_trades_linked": self.metrics["trade_id_linking_active"],
                "pending_orders_linked": self.metrics["trade_id_linking_pending"],
                "rrr_calculated": self.metrics["trade_id_linking_rrr"],
                "errors": self.metrics["trade_id_linking_errors"],
                "last_run": self.metrics["last_trade_id_linking"].isoformat() if self.metrics["last_trade_id_linking"] else None
            },
            "redis_cluster_status": await self.redis_manager.get_cluster_status(),
            "oanda_connection_status": await self.oanda_client.get_connection_status(),
            "architecture_info": self.settings.get_architecture_info()
        }
    
    async def _process_aggregated_timeframes(self, current_time: int):
        """Process aggregated timeframes (M15, M30) from M5 data"""
        for timeframe in self.settings.aggregated_timeframes:
            if self.settings.should_aggregate_timeframe(timeframe, current_time):
                logger.info(f"🔄 Aggregating {timeframe} candles from M5 data")
                await self._aggregate_timeframe_for_all_pairs(timeframe)
    
    async def _aggregate_timeframe_for_all_pairs(self, timeframe: str):
        """Aggregate a specific timeframe for all currency pairs"""
        aggregation_ratio = self.settings.get_aggregation_ratio(timeframe)
        
        # Group currency pairs by Redis shard for efficient processing
        shard_groups = self._group_pairs_by_shard()
        
        # Process each shard concurrently
        tasks = []
        for shard_index, pairs in shard_groups.items():
            task = asyncio.create_task(
                self._aggregate_shard_timeframe(shard_index, pairs, timeframe, aggregation_ratio),
                name=f"aggregate_shard_{shard_index}_{timeframe}"
            )
            tasks.append(task)
        
        # Wait for all shards to complete aggregation
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log any aggregation errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Aggregation failed for shard {i} {timeframe}", error=str(result))
    
    async def _aggregate_shard_timeframe(self, shard_index: int, currency_pairs: List[str], timeframe: str, aggregation_ratio: int):
        """Aggregate a specific timeframe for all pairs in a shard"""
        logger.debug(f"Aggregating shard {shard_index} for {timeframe}", pairs=currency_pairs)
        
        aggregated_data = {}
        
        for pair in currency_pairs:
            try:
                # Get the required number of M5 candles for aggregation
                m5_candles = await self._get_recent_m5_candles(pair, aggregation_ratio)
                
                if len(m5_candles) == aggregation_ratio:
                    # Aggregate the M5 candles into one larger timeframe candle
                    aggregated_candle = self._aggregate_candles(m5_candles, timeframe)
                    aggregated_data[pair] = aggregated_candle
                    
                    logger.debug(f"Aggregated {timeframe} candle for {pair}", 
                                candles_used=len(m5_candles))
                else:
                    logger.warning(f"Insufficient M5 data for {pair} {timeframe} aggregation",
                                  required=aggregation_ratio, available=len(m5_candles))
                    
            except Exception as e:
                logger.error(f"Aggregation failed for {pair} {timeframe}", error=str(e))
        
        # Store aggregated data to Redis
        if aggregated_data:
            await self._write_aggregated_data_to_redis(shard_index, aggregated_data, timeframe)
    
    async def _get_recent_m5_candles(self, currency_pair: str, count: int) -> List[Dict[str, Any]]:
        """Get the most recent M5 candles for a currency pair from Redis"""
        try:
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            redis_client = self.redis_manager.get_client(shard_index)
            
            # Get M5 data from Redis hot tier
            key = f"market_data:{currency_pair}:M5:hot"
            candles_data = await redis_client.lrange(key, -count, -1)  # Get last N candles
            
            # Parse Redis data into candle objects
            candles = []
            for candle_json in candles_data:
                if isinstance(candle_json, bytes):
                    candle_json = candle_json.decode('utf-8')
                candle = json.loads(candle_json)
                candles.append(candle)
            
            return candles
            
        except Exception as e:
            logger.error(f"Failed to get recent M5 candles for {currency_pair}", error=str(e))
            return []
    
    def _aggregate_candles(self, candles: List[Dict[str, Any]], timeframe: str) -> Dict[str, Any]:
        """Aggregate multiple candles into a single larger timeframe candle"""
        if not candles:
            return {}
        
        # OHLCV aggregation logic
        aggregated = {
            'time': candles[-1]['time'],  # Use the timestamp of the last candle
            'open': candles[0]['open'],   # Open from first candle
            'high': max(candle['high'] for candle in candles),  # Highest high
            'low': min(candle['low'] for candle in candles),    # Lowest low
            'close': candles[-1]['close'], # Close from last candle
            'volume': sum(candle.get('volume', 0) for candle in candles),  # Total volume
            'timeframe': timeframe,
            'source': 'aggregated',
            'source_candles': len(candles)
        }
        
        return aggregated
    
    async def _write_aggregated_data_to_redis(self, shard_index: int, aggregated_data: Dict[str, Any], timeframe: str):
        """Write aggregated candle data to Redis"""
        try:
            redis_client = self.redis_manager.get_client(shard_index)
            
            for currency_pair, candle_data in aggregated_data.items():
                # Store in hot tier for immediate access
                hot_key = f"market_data:{currency_pair}:{timeframe}:hot"
                
                # Add to the end of the list (newest data)
                await redis_client.rpush(hot_key, json.dumps(candle_data))
                
                # Maintain sliding window of 100 candles in hot tier
                await redis_client.ltrim(hot_key, -100, -1)
                
                # Set TTL
                await redis_client.expire(hot_key, self.settings.redis_ttl_seconds)
                
                logger.debug(f"Stored aggregated {timeframe} candle for {currency_pair}")
                
        except Exception as e:
            logger.error(f"Failed to write aggregated data to Redis shard {shard_index}", 
                        error=str(e), timeframe=timeframe)
    
    async def shutdown(self):
        """Gracefully shutdown the data orchestrator"""
        logger.info("🛑 Shutting down data orchestrator...")
        
        self.is_running = False
        
        # Close OANDA client
        if hasattr(self.oanda_client, 'close'):
            await self.oanda_client.close()
        
        # Close Redis connections
        await self.redis_manager.close_all_connections()
        
        # Shutdown health monitor
        if hasattr(self.health_monitor, 'shutdown'):
            await self.health_monitor.shutdown()
        
        logger.info("✅ Data orchestrator shutdown complete")