"""
Data Orchestrator - Core logic for single OANDA API connection and data distribution
ARCHITECTURE COMPLIANCE:
- Maintains single OANDA API connection for entire system
- Collects 2-minute candlestick data for 100+ strategies
- Distributes data across 4-node Redis cluster with currency pair sharding
- Sub-second data distribution to Lambda strategies
"""

import asyncio
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
        
        # Initialize enhanced data collector for comprehensive OANDA data
        self.enhanced_data_collector = EnhancedOandaDataCollector(self.oanda_client)
        
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
            
            # Initialize health monitoring
            await self.health_monitor.initialize()
            
            logger.info("🎼 Data orchestrator initialization complete")
            
        except Exception as e:
            logger.error("❌ Data orchestrator initialization failed", error=str(e))
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
                    self._collect_pair_timeframe_data(pair, timeframe),
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
    
    async def _collect_pair_timeframe_data(self, currency_pair: str, timeframe: str) -> Optional[Dict[str, Any]]:
        """Collect candlestick data for a single currency pair and timeframe"""
        try:
            # Make OANDA API call
            candlestick_data = await self.oanda_client.get_candlesticks(
                instrument=currency_pair,
                granularity=timeframe,
                count=self.settings.historical_data_points
            )
            
            self.metrics["oanda_api_calls"] += 1
            
            if not candlestick_data:
                logger.warning(f"No candlestick data received for {currency_pair} {timeframe}")
                return None
            
            # Process and format data
            processed_data = self._process_candlestick_data(candlestick_data, currency_pair, timeframe)
            
            logger.debug(f"Collected {timeframe} data for {currency_pair}", 
                        candles=len(candlestick_data.get('candles', [])))
            
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
    
    def _process_candlestick_data(self, raw_data: Dict[str, Any], currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Process raw OANDA candlestick data into Redis format"""
        try:
            candles = raw_data.get('candles', [])
            if not candles:
                return {}
            
            # Extract latest candle
            latest_candle = candles[-1]
            mid_prices = latest_candle.get('mid', {})
            
            # Format for Redis storage
            processed_data = {
                'instrument': currency_pair,
                'timeframe': timeframe,
                'timestamp': latest_candle.get('time'),
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
                historical_candles.append({
                    'time': candle.get('time'),
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
    
    async def _write_shard_timeframe_to_redis(self, shard_index: int, shard_data: Dict[str, Any], timeframe: str):
        """Write shard data for specific timeframe to appropriate Redis node"""
        try:
            # Get Redis connection for this shard
            redis_conn = await self.redis_manager.get_connection(shard_index)
            
            # Prepare batch operations
            pipe = redis_conn.pipeline()
            
            for currency_pair, data in shard_data.items():
                # Timeframe-specific keys
                current_key = f"market_data:{currency_pair}:{timeframe}:current"
                historical_key = f"market_data:{currency_pair}:{timeframe}:historical"
                
                # Store current data
                pipe.setex(
                    current_key,
                    self.settings.redis_ttl_seconds,
                    self.redis_manager.serialize_data(data)
                )
                
                # Store historical data
                historical_data = data.get('historical_candles', [])
                if historical_data:
                    pipe.setex(
                        historical_key,
                        self.settings.redis_ttl_seconds,
                        self.redis_manager.serialize_data(historical_data)
                    )
                
                # Update last update timestamp for this timeframe
                timestamp_key = f"market_data:{currency_pair}:{timeframe}:last_update"
                pipe.setex(
                    timestamp_key,
                    self.settings.redis_ttl_seconds,
                    datetime.now().isoformat()
                )
            
            # Execute batch operations
            await pipe.execute()
            
            self.metrics["redis_writes_successful"] += len(shard_data)
            
            logger.debug(f"Shard {shard_index} {timeframe} data written to Redis", 
                        pairs=list(shard_data.keys()))
            
        except Exception as e:
            self.metrics["redis_writes_failed"] += len(shard_data)
            logger.error(f"Failed to write shard {shard_index} {timeframe} to Redis", error=str(e))
            raise
    
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
            # Use enhanced data collector for comprehensive OANDA data including Distance to Entry
            logger.info("🚀 Using enhanced OANDA data collection with Distance to Entry")
            print("DEBUG: About to call enhanced_data_collector.collect_comprehensive_trade_data()")
            comprehensive_data = await self.enhanced_data_collector.collect_comprehensive_trade_data()
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