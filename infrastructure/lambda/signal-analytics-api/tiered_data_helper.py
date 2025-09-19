#!/usr/bin/env python3
"""
Tiered Data Helper - Standard pattern for Lambda functions to retrieve data from all tiers
"""

import json
import redis
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

def get_tiered_price_data(
    redis_conn, 
    currency_pair: str, 
    timeframe: str = 'H1', 
    max_candles: int = 500
) -> Dict[str, Any]:
    """
    Standard function for Lambda functions to retrieve data from all Redis tiers.
    
    Args:
        redis_conn: Redis connection object
        currency_pair: e.g., 'EUR_USD', 'GBP_CAD'
        timeframe: e.g., 'M5', 'H1', 'H4'
        max_candles: Maximum number of candles to return
        
    Returns:
        Dictionary with combined candle data from all tiers
    """
    
    try:
        # Redis key patterns (matches Fargate data orchestrator)
        tiered_keys = {
            'hot': f"market_data:{currency_pair}:{timeframe}:hot",
            'warm': f"market_data:{currency_pair}:{timeframe}:warm", 
            'cold': f"market_data:{currency_pair}:{timeframe}:cold"
        }
        
        candles = []
        sources_used = []
        tier_stats = {}
        
        # Step 1: Get hot tier (most recent candles)
        try:
            hot_data = redis_conn.lrange(tiered_keys['hot'], 0, -1)
            hot_candles = []
            for item in hot_data:
                try:
                    candle = json.loads(item.decode('utf-8') if isinstance(item, bytes) else item)
                    hot_candles.append(candle)
                except json.JSONDecodeError:
                    continue
            
            if hot_candles:
                candles.extend(hot_candles)
                sources_used.append(f"hot({len(hot_candles)})")
                tier_stats['hot'] = len(hot_candles)
                logger.info(f"Retrieved {len(hot_candles)} candles from hot tier")
            
        except Exception as e:
            logger.warning(f"Failed to retrieve hot tier data: {e}")
            tier_stats['hot'] = 0
        
        # Step 2: Get warm tier (older candles)
        if len(candles) < max_candles:
            try:
                warm_data = redis_conn.lrange(tiered_keys['warm'], 0, -1)
                warm_candles = []
                for item in warm_data:
                    try:
                        candle = json.loads(item.decode('utf-8') if isinstance(item, bytes) else item)
                        warm_candles.append(candle)
                    except json.JSONDecodeError:
                        continue
                
                if warm_candles:
                    candles.extend(warm_candles)
                    sources_used.append(f"warm({len(warm_candles)})")
                    tier_stats['warm'] = len(warm_candles)
                    logger.info(f"Retrieved {len(warm_candles)} candles from warm tier")
                
            except Exception as e:
                logger.warning(f"Failed to retrieve warm tier data: {e}")
                tier_stats['warm'] = 0
        
        # Step 3: Get cold tier (oldest candles)
        if len(candles) < max_candles:
            try:
                cold_data = redis_conn.get(tiered_keys['cold'])
                if cold_data:
                    cold_parsed = json.loads(cold_data.decode('utf-8') if isinstance(cold_data, bytes) else cold_data)
                    if isinstance(cold_parsed, dict) and 'candles' in cold_parsed:
                        cold_candles = cold_parsed['candles']
                    elif isinstance(cold_parsed, list):
                        cold_candles = cold_parsed
                    else:
                        cold_candles = []
                    
                    if cold_candles:
                        candles.extend(cold_candles)
                        sources_used.append(f"cold({len(cold_candles)})")
                        tier_stats['cold'] = len(cold_candles)
                        logger.info(f"Retrieved {len(cold_candles)} candles from cold tier")
                
            except Exception as e:
                logger.warning(f"Failed to retrieve cold tier data: {e}")
                tier_stats['cold'] = 0
        
        # Step 4: Sort chronologically and limit to requested count
        if candles:
            pre_sort_count = len(candles)
            candles = sorted(candles, key=lambda x: x.get('time', ''))
            
            # Limit to requested count (take most recent)
            if len(candles) > max_candles:
                candles = candles[-max_candles:]
            
            logger.info(f"Tiered data retrieval: {pre_sort_count} total → {len(candles)} final candles")
        
        # Step 5: Check for duplicates (should be zero with fixed tier logic)
        if candles:
            timestamps = [c.get('time', c.get('timestamp', '')) for c in candles]
            unique_timestamps = len(set(timestamps))
            duplicates = len(timestamps) - unique_timestamps
            
            if duplicates > 0:
                logger.warning(f"🚨 DUPLICATES DETECTED: {duplicates} duplicate timestamps in {currency_pair} {timeframe}")
                # Remove duplicates by keeping last occurrence
                seen_times = set()
                unique_candles = []
                for candle in reversed(candles):
                    timestamp = candle.get('time', candle.get('timestamp', ''))
                    if timestamp not in seen_times:
                        seen_times.add(timestamp)
                        unique_candles.insert(0, candle)
                candles = unique_candles
                logger.info(f"🔧 DEDUPLICATION: Removed {duplicates} duplicates")
            else:
                logger.info(f"✅ NO DUPLICATES: Clean data from tiered storage")
        
        return {
            'success': True,
            'candles': candles,
            'metadata': {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'sources_used': sources_used,
                'tier_stats': tier_stats,
                'total_candles': len(candles),
                'max_requested': max_candles,
                'duplicates_found': duplicates if 'duplicates' in locals() else 0
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to retrieve tiered data for {currency_pair} {timeframe}: {e}")
        return {
            'success': False,
            'error': str(e),
            'candles': [],
            'metadata': {}
        }

def get_redis_connection_for_pair(currency_pair: str, redis_nodes: List[str]) -> Optional[redis.Redis]:
    """
    Get the correct Redis connection for a currency pair based on sharding.
    
    Args:
        currency_pair: e.g., 'EUR_USD'
        redis_nodes: List of Redis node endpoints
        
    Returns:
        Redis connection object for the appropriate shard
    """
    
    # Currency pair to shard mapping (matches Fargate configuration)
    shard_mapping = {
        # Shard 0: Major USD pairs
        "EUR_USD": 0, "GBP_USD": 0, "USD_JPY": 0, "USD_CAD": 0, 
        "AUD_USD": 0, "NZD_USD": 0, "USD_CHF": 0,
        
        # Shard 1: EUR cross pairs + GBP_JPY
        "EUR_GBP": 1, "EUR_JPY": 1, "EUR_CAD": 1, "EUR_AUD": 1, 
        "EUR_NZD": 1, "EUR_CHF": 1, "GBP_JPY": 1,
        
        # Shard 2: GBP and AUD cross pairs
        "GBP_CAD": 2, "GBP_AUD": 2, "GBP_NZD": 2, "GBP_CHF": 2,
        "AUD_JPY": 2, "AUD_CAD": 2, "AUD_NZD": 2,
        
        # Shard 3: Remaining cross pairs
        "AUD_CHF": 3, "NZD_JPY": 3, "NZD_CAD": 3, "NZD_CHF": 3,
        "CAD_JPY": 3, "CAD_CHF": 3, "CHF_JPY": 3
    }
    
    shard_index = shard_mapping.get(currency_pair, 0)
    
    if shard_index < len(redis_nodes):
        try:
            host, port = redis_nodes[shard_index].split(':')
            return redis.Redis(
                host=host,
                port=int(port),
                decode_responses=False,
                socket_connect_timeout=30,
                socket_timeout=30,
                retry_on_timeout=True,
                health_check_interval=30
            )
        except Exception as e:
            logger.error(f"Failed to connect to Redis shard {shard_index}: {e}")
            return None
    
    return None

# Example usage for Lambda functions:
"""
# In your Lambda function:
import tiered_data_helper

# Get Redis connection
redis_nodes = ["shard1:6379", "shard2:6379", "shard3:6379", "shard4:6379"] 
redis_conn = tiered_data_helper.get_redis_connection_for_pair("EUR_USD", redis_nodes)

# Get tiered data (standard pattern)
data_result = tiered_data_helper.get_tiered_price_data(
    redis_conn=redis_conn,
    currency_pair="EUR_USD", 
    timeframe="H1",
    max_candles=500
)

if data_result['success']:
    candles = data_result['candles']  # Use this for your analytics
    metadata = data_result['metadata']  # Tier stats and diagnostics
else:
    # Handle error
    error = data_result['error']
"""