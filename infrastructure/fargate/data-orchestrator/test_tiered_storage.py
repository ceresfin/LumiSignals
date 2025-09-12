#!/usr/bin/env python3
"""
Test script for tiered Redis storage system
Run this locally to verify tiered storage before deployment
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from config import Settings
from redis_manager import RedisManager
from data_orchestrator import DataOrchestrator
from health_monitor import HealthMonitor
import structlog

# Setup logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


async def test_tiered_storage():
    """Test tiered storage implementation before deployment"""
    
    # 1. Initialize components
    logger.info("🚀 Starting tiered storage test")
    
    # Override settings for testing
    os.environ['HOT_TIER_CANDLES'] = '10'  # Small for testing
    os.environ['WARM_TIER_CANDLES'] = '20'  # Small for testing
    os.environ['BOOTSTRAP_CANDLES'] = '30'  # Small for testing
    
    settings = Settings()
    redis_manager = RedisManager(settings)
    health_monitor = HealthMonitor(settings, redis_manager)
    orchestrator = DataOrchestrator(settings, redis_manager, health_monitor)
    
    test_pair = "EUR_USD"
    test_timeframe = "M5"
    
    try:
        # 2. Test Bootstrap Data Distribution
        logger.info("\n📊 TEST 1: Bootstrap Data Distribution")
        
        # Create mock bootstrap data
        mock_candles = []
        base_time = datetime.now() - timedelta(hours=10)
        
        for i in range(30):  # 30 test candles
            candle_time = base_time + timedelta(minutes=5 * i)
            mock_candles.append({
                'time': candle_time.isoformat() + 'Z',
                'open': 1.1000 + (i * 0.0001),
                'high': 1.1000 + (i * 0.0001) + 0.0002,
                'low': 1.1000 + (i * 0.0001) - 0.0001,
                'close': 1.1000 + (i * 0.0001) + 0.0001,
                'volume': 1000 + i
            })
        
        # Create bootstrap data structure
        bootstrap_data = {
            test_pair: {
                'historical_candles': mock_candles,
                'instrument': test_pair,
                'timeframe': test_timeframe,
                'timestamp': datetime.now().isoformat(),
                'open': mock_candles[-1]['open'],
                'high': mock_candles[-1]['high'],
                'low': mock_candles[-1]['low'],
                'close': mock_candles[-1]['close'],
                'volume': mock_candles[-1]['volume']
            }
        }
        
        # Write bootstrap data using tiered storage
        shard_index = settings.get_redis_node_for_pair(test_pair)
        await orchestrator._write_bootstrap_data_to_redis(shard_index, bootstrap_data, test_timeframe)
        
        logger.info("✅ Bootstrap data written to tiered storage")
        
        # 3. Check Tier Distribution
        logger.info("\n📊 TEST 2: Verify Tier Distribution")
        
        tier_stats = await orchestrator.get_tier_stats(test_pair, test_timeframe)
        
        logger.info(f"Hot Tier: {tier_stats['tiers']['hot']['count']}/{tier_stats['tiers']['hot']['capacity']} "
                   f"(utilization: {tier_stats['tiers']['hot']['utilization']:.1%})")
        logger.info(f"Warm Tier: {tier_stats['tiers']['warm']['count']}/{tier_stats['tiers']['warm']['capacity']} "
                   f"(utilization: {tier_stats['tiers']['warm']['utilization']:.1%})")
        logger.info(f"Cold Tier: {tier_stats['tiers']['cold']['count']} candles "
                   f"(exists: {tier_stats['tiers']['cold']['exists']})")
        
        # Verify correct distribution
        assert tier_stats['tiers']['hot']['count'] == 10, "Hot tier should have 10 candles"
        assert tier_stats['tiers']['warm']['count'] == 20, "Warm tier should have 20 candles"
        assert tier_stats['tiers']['cold']['count'] == 30, "Cold tier should have all 30 candles"
        
        logger.info("✅ Tier distribution verified correctly")
        
        # 4. Test Data Retrieval
        logger.info("\n📊 TEST 3: Test Tiered Data Retrieval")
        
        result = await orchestrator.get_tiered_candlestick_data(test_pair, test_timeframe, requested_count=25)
        
        logger.info(f"Requested: {result['metadata']['requested_count']} candles")
        logger.info(f"Retrieved: {result['metadata']['actual_count']} candles")
        logger.info(f"Sources used: {result['metadata']['sources_used']}")
        logger.info(f"Data complete: {result['metadata']['is_complete']}")
        
        assert len(result['candles']) == 25, f"Should retrieve 25 candles, got {len(result['candles'])}"
        assert 'hot' in str(result['metadata']['sources_used']), "Should use hot tier"
        assert 'warm' in str(result['metadata']['sources_used']), "Should use warm tier"
        
        logger.info("✅ Tiered retrieval working correctly")
        
        # 5. Test Hot Tier Updates
        logger.info("\n📊 TEST 4: Test Hot Tier Updates")
        
        # Add a new candle to hot tier
        new_candle_data = {
            test_pair: {
                'instrument': test_pair,
                'timeframe': test_timeframe,
                'timestamp': datetime.now().isoformat() + 'Z',
                'open': 1.1100,
                'high': 1.1105,
                'low': 1.1095,
                'close': 1.1102,
                'volume': 2000
            }
        }
        
        await orchestrator._write_shard_timeframe_to_redis(shard_index, new_candle_data, test_timeframe)
        
        # Check hot tier only
        hot_data = await orchestrator.get_hot_tier_data_only(test_pair, test_timeframe)
        logger.info(f"Hot tier after update: {len(hot_data)} candles")
        
        # The newest candle should be in hot tier
        assert len(hot_data) > 0, "Hot tier should have data"
        
        logger.info("✅ Hot tier updates working correctly")
        
        # 6. Test Rotation Logic
        logger.info("\n📊 TEST 5: Test Hot to Warm Rotation")
        
        # Force rotation by adding many candles
        redis_conn = await redis_manager.get_connection(shard_index)
        keys = settings.get_redis_keys_for_pair_timeframe(test_pair, test_timeframe)
        
        # Add extra candles to hot tier to trigger rotation
        for i in range(5):
            await redis_conn.rpush(keys['hot'], '{"time":"2024-01-01T00:00:00Z","open":1.1,"high":1.1,"low":1.1,"close":1.1}')
        
        # Now trigger rotation
        await orchestrator._rotate_hot_to_warm_tier(test_pair, test_timeframe, redis_conn)
        
        # Check tier stats after rotation
        tier_stats_after = await orchestrator.get_tier_stats(test_pair, test_timeframe)
        
        logger.info(f"Hot tier after rotation: {tier_stats_after['tiers']['hot']['count']} "
                   f"(should be <= {settings.hot_tier_candles})")
        
        assert tier_stats_after['tiers']['hot']['count'] <= settings.hot_tier_candles, \
            "Hot tier should be at or below capacity after rotation"
        
        logger.info("✅ Rotation logic working correctly")
        
        # 7. Clean up test data
        logger.info("\n🧹 Cleaning up test data")
        
        await redis_conn.delete(keys['hot'])
        await redis_conn.delete(keys['warm'])
        await redis_conn.delete(keys['cold'])
        await redis_conn.delete(keys['current'])
        await redis_conn.delete(keys['last_update'])
        await redis_conn.delete(keys['rotation_meta'])
        
        logger.info("✅ Test data cleaned up")
        
        logger.info("\n🎉 ALL TESTS PASSED! Tiered storage is ready for deployment")
        
    except AssertionError as e:
        logger.error(f"❌ Test assertion failed: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        raise
    finally:
        # Cleanup connections
        await redis_manager.close_all_connections()


if __name__ == "__main__":
    asyncio.run(test_tiered_storage())