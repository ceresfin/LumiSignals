#!/usr/bin/env python3
"""
BACKUP DATE: 2025-09-15
API ENDPOINT: https://4kctdba5vc.execute-api.us-east-1.amazonaws.com/prod

Direct Candlestick API - Bypasses Lambda strategies for pure data serving
Provides direct access to Fargate-collected candlestick data from Redis

Data Flow: OANDA → Fargate → Redis → This API → Dashboard
No session filtering, no trading logic - just pure candlestick data serving
"""

import json
import redis
import os
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class DirectCandlestickAPI:
    """Direct Redis access for candlestick data"""
    
    def __init__(self):
        # Redis cluster configuration (matches Fargate configuration)
        self.redis_nodes = [
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ]
        
        # Currency pair to shard mapping (matches Fargate sharding)
        self.shard_mapping = {
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
        
        # Initialize Redis connections
        self.redis_connections = {}
        self._connect_to_redis()
    
    def _connect_to_redis(self):
        """Initialize Redis connections to all shards"""
        for i, node in enumerate(self.redis_nodes):
            try:
                host, port = node.split(':')
                self.redis_connections[i] = redis.Redis(
                    host=host,
                    port=int(port),
                    decode_responses=False,  # Keep as bytes for JSON parsing
                    socket_connect_timeout=30,  # Increased timeout
                    socket_timeout=30,  # Increased timeout
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                logger.info(f"Connected to Redis shard {i}: {node}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis shard {i}: {e}")
    
    def get_shard_for_pair(self, currency_pair: str) -> int:
        """Get Redis shard index for currency pair"""
        return self.shard_mapping.get(currency_pair, 0)
    
    def aggregate_m5_to_h1(self, m5_candles):
        """Convert M5 candlesticks to H1 candlesticks"""
        if not m5_candles:
            return []
        
        h1_candles = []
        current_hour_group = []
        current_hour_boundary = None
        
        # Sort candles by timestamp
        sorted_candles = sorted(m5_candles, key=lambda x: x.get('time', x.get('timestamp', '')))
        
        for candle in sorted_candles:
            try:
                # Parse timestamp and get hour boundary
                candle_time_str = candle.get('time') or candle.get('timestamp')
                if candle_time_str:
                    # Handle different timestamp formats
                    if candle_time_str.endswith('Z'):
                        # Remove nanoseconds if present (e.g., .000000000Z)
                        if '.000000000Z' in candle_time_str:
                            candle_time_str = candle_time_str.replace('.000000000Z', 'Z')
                        candle_time = datetime.fromisoformat(candle_time_str.replace('Z', '+00:00'))
                    else:
                        candle_time = datetime.fromisoformat(candle_time_str)
                    
                    # Get hour boundary
                    hour_boundary = candle_time.replace(minute=0, second=0, microsecond=0)
                    
                    # Check if we're still in the same hour
                    if current_hour_boundary is None:
                        current_hour_boundary = hour_boundary
                    
                    if hour_boundary == current_hour_boundary:
                        current_hour_group.append(candle)
                    else:
                        # Process completed hour group
                        if current_hour_group:
                            h1_candle = self._merge_candles_to_h1(current_hour_group, current_hour_boundary)
                            if h1_candle:
                                h1_candles.append(h1_candle)
                        
                        # Start new hour group
                        current_hour_boundary = hour_boundary
                        current_hour_group = [candle]
                
            except Exception as e:
                logger.warning(f"Failed to process candle during aggregation: {e}")
                continue
        
        # Don't forget the last group
        if current_hour_group and current_hour_boundary:
            h1_candle = self._merge_candles_to_h1(current_hour_group, current_hour_boundary)
            if h1_candle:
                h1_candles.append(h1_candle)
        
        return h1_candles
    
    def _merge_candles_to_h1(self, candles, hour_boundary):
        """Merge multiple candles into a single H1 candle"""
        if not candles:
            return None
        
        try:
            # Sort to ensure correct order
            sorted_candles = sorted(candles, key=lambda x: x.get('time', x.get('timestamp', '')))
            
            first_candle = sorted_candles[0]
            last_candle = sorted_candles[-1]
            
            # Calculate OHLC
            open_price = float(first_candle.get('open', 0))
            close_price = float(last_candle.get('close', 0))
            high_price = max(float(c.get('high', 0)) for c in sorted_candles)
            low_price = min(float(c.get('low', float('inf'))) for c in sorted_candles if float(c.get('low', 0)) > 0)
            
            # Sum volume
            total_volume = sum(int(c.get('volume', 0)) for c in sorted_candles)
            
            # Use hour boundary as timestamp
            timestamp = hour_boundary.isoformat() + 'Z'
            
            return {
                'time': timestamp,
                'timestamp': timestamp,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': total_volume
            }
            
        except Exception as e:
            logger.warning(f"Failed to merge candles to H1: {e}")
            return None
    
    def get_candlestick_data(self, currency_pair: str, timeframe: str = 'H1', count: int = 50) -> Dict[str, Any]:
        """
        Get candlestick data from Redis
        
        Args:
            currency_pair: Currency pair (e.g., 'EUR_USD')
            timeframe: Timeframe (M5, H1, etc.)
            count: Number of candles to retrieve
            
        Returns:
            Dict with success status and candlestick data
        """
        try:
            # Get Redis shard for this currency pair
            shard_index = self.get_shard_for_pair(currency_pair)
            redis_conn = self.redis_connections.get(shard_index)
            
            if not redis_conn:
                logger.error(f"No Redis connection for shard {shard_index}")
                return {
                    "success": False,
                    "error": f"No Redis connection for currency pair {currency_pair}",
                    "data": []
                }
            
            # Debug: List all keys for this currency pair to see what's available
            try:
                all_keys = redis_conn.keys(f"market_data:{currency_pair}:*")
                logger.info(f"Available Redis keys for {currency_pair}: {[key.decode() if isinstance(key, bytes) else key for key in all_keys]}")
            except Exception as e:
                logger.warning(f"Could not list Redis keys for {currency_pair}: {e}")
            
            # Use tiered storage system - hot/warm/cold tiers for 500 candlestick support
            tiered_keys = {
                'hot': f"market_data:{currency_pair}:{timeframe}:hot",
                'warm': f"market_data:{currency_pair}:{timeframe}:warm", 
                'cold': f"market_data:{currency_pair}:{timeframe}:cold"
            }
            
            logger.info(f"Using tiered storage for {currency_pair} {timeframe} - targeting {count} candles")
            
            # Test connection
            redis_conn.ping()
            
            candles = []
            sources_used = []
            
            # Smart tiered retrieval - collect from hot, warm, cold as needed
            try:
                # Step 1: Try hot tier (most recent 50 candles)
                hot_data = redis_conn.lrange(tiered_keys['hot'], 0, -1)
                if hot_data:
                    hot_candles = []
                    for item in hot_data:
                        try:
                            candle = json.loads(item.decode('utf-8'))
                            hot_candles.append(candle)
                        except json.JSONDecodeError:
                            continue
                    candles.extend(hot_candles)
                    sources_used.append(f"hot({len(hot_candles)})")
                    logger.info(f"Retrieved {len(hot_candles)} candles from hot tier")
                
                # Step 2: Try warm tier if we need more candles
                if len(candles) < count:
                    needed = count - len(candles)
                    warm_data = redis_conn.lrange(tiered_keys['warm'], 0, needed - 1)
                    if warm_data:
                        warm_candles = []
                        for item in warm_data:
                            try:
                                candle = json.loads(item.decode('utf-8'))
                                warm_candles.append(candle)
                            except json.JSONDecodeError:
                                continue
                        candles.extend(warm_candles)
                        sources_used.append(f"warm({len(warm_candles)})")
                        logger.info(f"Retrieved {len(warm_candles)} candles from warm tier")
                
                # Step 3: Try cold tier if still need more candles
                if len(candles) < count:
                    cold_data = redis_conn.get(tiered_keys['cold'])
                    if cold_data:
                        try:
                            cold_parsed = json.loads(cold_data.decode('utf-8'))
                            if isinstance(cold_parsed, dict) and 'candles' in cold_parsed:
                                cold_candles = cold_parsed['candles']
                                # Take only what we need from cold tier
                                needed = count - len(candles)
                                candles.extend(cold_candles[-needed:])
                                sources_used.append(f"cold({min(len(cold_candles), needed)})")
                                logger.info(f"Retrieved {min(len(cold_candles), needed)} candles from cold tier")
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse cold tier data: {e}")
                
                logger.info(f"Tiered retrieval for {currency_pair}: {', '.join(sources_used)}")
                
            except Exception as e:
                logger.warning(f"Tiered storage retrieval failed, trying fallback: {e}")
                
                # Fallback to old key patterns if tiered storage fails
                fallback_keys = [
                    (f"market_data:{currency_pair}:{timeframe}:historical", f"market_data:{currency_pair}:{timeframe}:current"),
                ]
                
                for historical_key, current_key in fallback_keys:
                    historical_data = redis_conn.get(historical_key)
                    if historical_data:
                        try:
                            parsed = json.loads(historical_data.decode('utf-8'))
                            if isinstance(parsed, dict) and 'candles' in parsed:
                                candles.extend(parsed['candles'])
                            elif isinstance(parsed, list):
                                candles.extend(parsed)
                            sources_used.append("fallback_historical")
                            break
                        except json.JSONDecodeError:
                            continue
            
            # Determine data source based on what tiers were used
            if sources_used:
                data_source = f"REDIS_FARGATE_TIERED_{timeframe}"
            else:
                data_source = f"REDIS_FARGATE_{timeframe}"
            
            # Handle aggregation for non-native timeframes
            if timeframe in ['M15', 'M30'] and not candles:
                logger.info(f"No {timeframe} data, attempting to aggregate from M5")
                # Try to get M5 data and aggregate
                m5_result = self.get_candlestick_data(currency_pair, 'M5', count * 12)  # Get more M5 for aggregation
                if m5_result['success'] and m5_result['data']:
                    # For now, return M5 data as-is (aggregation can be added later)
                    candles = m5_result['data'][:count]
                    data_source = "REDIS_FARGATE_M5_AS_FALLBACK"
            
            # Sort by timestamp (newest first) and limit to requested count
            if candles:
                # Remove duplicates based on timestamp
                unique_candles = {}
                for candle in candles:
                    timestamp = candle.get('time') or candle.get('timestamp')
                    if timestamp:
                        unique_candles[timestamp] = candle
                
                # Sort and limit
                sorted_candles = sorted(
                    unique_candles.values(), 
                    key=lambda x: x.get('time', x.get('timestamp', '')), 
                    reverse=True
                )[:count]
                
                logger.info(f"Returning {len(sorted_candles)} unique candles for {currency_pair} {timeframe}")
                
                return {
                    "success": True,
                    "data": sorted_candles,
                    "metadata": {
                        "currency_pair": currency_pair,
                        "timeframe": timeframe,
                        "count": len(sorted_candles),
                        "requested_count": count,
                        "timestamp": datetime.utcnow().isoformat() + 'Z',
                        "data_source": data_source,
                        "sources_used": sources_used
                    }
                }
            else:
                logger.warning(f"No candlestick data found for {currency_pair} {timeframe}")
                return {
                    "success": False,
                    "error": f"No data available for {currency_pair} {timeframe}",
                    "data": [],
                    "metadata": {
                        "currency_pair": currency_pair,
                        "timeframe": timeframe,
                        "timestamp": datetime.utcnow().isoformat() + 'Z'
                    }
                }
                
        except Exception as e:
            logger.error(f"Error retrieving candlestick data: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": []
            }

# Global API instance
api = DirectCandlestickAPI()

def lambda_handler(event, context):
    """
    Lambda handler for direct candlestick API
    
    Expected path parameters:
    - currency_pair: EUR_USD, GBP_CAD, etc.
    - timeframe: M5, M15, H1, H4, etc.
    
    Query parameters:
    - count: number of candles (default 50)
    """
    
    # CORS headers for all responses - Allow multiple pipstop.org variants
    origin = event.get('headers', {}).get('origin', '') or event.get('headers', {}).get('Origin', '')
    allowed_origins = [
        'https://pipstop.org',
        'https://www.pipstop.org', 
        'http://pipstop.org',
        'http://www.pipstop.org',
        'https://pipstop.org/',
        'https://www.pipstop.org/'
    ]
    
    # Default to first allowed origin if origin not in list or empty
    cors_origin = origin if origin in allowed_origins else 'https://pipstop.org'
    
    cors_headers = {
        'Access-Control-Allow-Origin': cors_origin,
        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,x-api-key',
        'Access-Control-Allow-Methods': 'GET,OPTIONS,POST',
        'Access-Control-Allow-Credentials': 'false',
        'Access-Control-Max-Age': '86400'
    }
    
    # Handle OPTIONS preflight request
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': ''
        }
    
    try:
        # Extract path parameters
        path_params = event.get('pathParameters', {}) or {}
        query_params = event.get('queryStringParameters', {}) or {}
        
        currency_pair = path_params.get('currency_pair')
        timeframe = path_params.get('timeframe', 'H1')
        count = int(query_params.get('count', 50))
        
        if not currency_pair:
            return {
                'statusCode': 400,
                'headers': {
                    'Content-Type': 'application/json',
                    **cors_headers
                },
                'body': json.dumps({
                    'success': False,
                    'error': 'currency_pair path parameter is required'
                })
            }
        
        # Get candlestick data directly from Redis
        result = api.get_candlestick_data(currency_pair, timeframe, count)
        
        logger.info(f"Direct candlestick API: {currency_pair} {timeframe} - "
                   f"returned {len(result.get('data', []))} candles")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                **cors_headers
            },
            'body': json.dumps(result)
        }
        
    except Exception as e:
        logger.error(f"Lambda handler error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                **cors_headers
            },
            'body': json.dumps({
                'success': False,
                'error': 'Internal server error'
            })
        }