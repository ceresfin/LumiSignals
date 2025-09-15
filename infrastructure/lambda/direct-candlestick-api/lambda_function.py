#!/usr/bin/env python3
"""
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
                    
                    hour_boundary = candle_time.replace(minute=0, second=0, microsecond=0)
                    
                    # Group candles by hour
                    if current_hour_boundary is None or hour_boundary != current_hour_boundary:
                        # Complete the previous hour if exists
                        if current_hour_group:
                            h1_candle = self.create_h1_candle(current_hour_group, current_hour_boundary)
                            h1_candles.append(h1_candle)
                        
                        # Start new hour
                        current_hour_group = [candle]
                        current_hour_boundary = hour_boundary
                    else:
                        current_hour_group.append(candle)
                        
            except Exception as e:
                logger.debug(f"Error processing candle timestamp: {e}")
                continue
        
        # Handle the last group
        if current_hour_group and current_hour_boundary:
            h1_candle = self.create_h1_candle(current_hour_group, current_hour_boundary)
            h1_candles.append(h1_candle)
        
        logger.info(f"Aggregated {len(sorted_candles)} M5 candles → {len(h1_candles)} H1 candles")
        
        # Enhanced debugging
        if len(sorted_candles) > 0 and len(h1_candles) < 10:
            logger.info(f"LOW H1 OUTPUT DEBUG:")
            logger.info(f"- M5 candles: {len(sorted_candles)}")
            logger.info(f"- H1 candles: {len(h1_candles)}")
            logger.info(f"- Expected H1: ~{len(sorted_candles) // 12}")
            logger.info(f"- First M5 candle: {sorted_candles[0] if sorted_candles else 'None'}")
            logger.info(f"- Last M5 candle: {sorted_candles[-1] if sorted_candles else 'None'}")
            
            # Show unique hour boundaries found
            unique_hours = set()
            for candle in sorted_candles[:50]:  # Check first 50
                try:
                    candle_time_str = candle.get('time') or candle.get('timestamp')
                    if candle_time_str:
                        if candle_time_str.endswith('Z'):
                            if '.000000000Z' in candle_time_str:
                                candle_time_str = candle_time_str.replace('.000000000Z', 'Z')
                            candle_time = datetime.fromisoformat(candle_time_str.replace('Z', '+00:00'))
                        else:
                            candle_time = datetime.fromisoformat(candle_time_str)
                        hour_boundary = candle_time.replace(minute=0, second=0, microsecond=0)
                        unique_hours.add(hour_boundary.isoformat())
                except:
                    continue
            logger.info(f"- Unique hour boundaries found: {len(unique_hours)}")
            if unique_hours:
                sorted_hours = sorted(unique_hours)
                logger.info(f"- Hour range: {sorted_hours[0]} to {sorted_hours[-1]}")
        
        return h1_candles
    
    def create_h1_candle(self, m5_group, hour_boundary):
        """Create a single H1 candle from a group of M5 candles"""
        try:
            return {
                'time': hour_boundary.isoformat(),
                'timestamp': int(hour_boundary.timestamp()),
                'datetime': hour_boundary.isoformat(),
                'open': float(m5_group[0].get('open', 0)),
                'high': max(float(c.get('high', 0)) for c in m5_group),
                'low': min(float(c.get('low', 0)) for c in m5_group),
                'close': float(m5_group[-1].get('close', 0)),
                'volume': sum(int(c.get('volume', 0)) for c in m5_group)
            }
        except Exception as e:
            logger.error(f"Error creating H1 candle: {e}")
            return {}
    
    def get_candlestick_data(self, currency_pair: str, timeframe: str = "H1", count: int = 50) -> Dict[str, Any]:
        """
        Get candlestick data directly from Redis
        
        Args:
            currency_pair: e.g., 'EUR_USD', 'GBP_CAD'
            timeframe: e.g., 'M5', 'M15', 'H1', 'H4'
            count: number of candles to return
            
        Returns:
            Dictionary with candlestick data
        """
        try:
            # Get appropriate Redis connection
            shard_index = self.get_shard_for_pair(currency_pair)
            redis_conn = self.redis_connections.get(shard_index)
            
            if not redis_conn:
                return {
                    "success": False,
                    "error": f"No Redis connection for shard {shard_index}",
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
                logger.info(f"✅ Using tiered storage for {currency_pair}: {', '.join(sources_used)}")
            else:
                data_source = f"REDIS_FARGATE_FALLBACK_{timeframe}"
                logger.info(f"⚠️ Used fallback storage for {currency_pair}")
            
            # Sort by time and limit to requested count
            if candles:
                pre_sort_count = len(candles)
                candles = sorted(candles, key=lambda x: x.get('time', ''))[-count:]
                logger.info(f"Limited from {pre_sort_count} to {len(candles)} candles (requested {count})")
            
            # Log if we have insufficient data (Fargate should have backfilled this)
            if len(candles) < count and len(candles) < 50 and timeframe == "H1":
                logger.warning(f"Insufficient H1 data in Redis ({len(candles)} < {count}). Fargate may need to run backfill.")
                logger.info(f"Using {len(candles)} available H1 candles from Redis instead of requested {count}")
            
            # Format response for dashboard compatibility
            formatted_candles = []
            for candle in candles:
                formatted_candles.append({
                    "datetime": candle.get('time'),
                    "open": float(candle.get('open', 0)),
                    "high": float(candle.get('high', 0)),
                    "low": float(candle.get('low', 0)),
                    "close": float(candle.get('close', 0)),
                    "volume": int(candle.get('volume', 0))
                })
            
            # CRITICAL FIX: Deduplicate timestamps using exact frontend logic
            # Copy of frontend deduplication from LightweightTradingViewChartWithTrades.tsx lines 812-825
            time_set = set()
            duplicate_timestamps = []
            for candle in formatted_candles:
                timestamp = candle.get('datetime')
                if timestamp in time_set:
                    duplicate_timestamps.append(timestamp)
                time_set.add(timestamp)
            
            if duplicate_timestamps:
                logger.info(f"🚨 LAMBDA DEDUP: Found {len(duplicate_timestamps)} duplicate timestamps for {currency_pair}")
                # Remove duplicates by keeping only the last occurrence of each timestamp (same as frontend)
                unique_candles = []
                seen_times = set()
                for i in range(len(formatted_candles) - 1, -1, -1):  # Reverse iteration like frontend
                    candle = formatted_candles[i]
                    timestamp = candle.get('datetime')
                    if timestamp not in seen_times:
                        seen_times.add(timestamp)
                        unique_candles.insert(0, candle)  # Insert at beginning to maintain order
                
                duplicates_removed = len(formatted_candles) - len(unique_candles)
                logger.info(f"🔧 LAMBDA DEDUP: Removed {duplicates_removed} duplicate candles for {currency_pair}")
                formatted_candles = unique_candles
            else:
                logger.info(f"✅ LAMBDA DEDUP: No duplicates found for {currency_pair}")
            
            return {
                "success": True,
                "data": formatted_candles,
                "metadata": {
                    "currency_pair": currency_pair,
                    "timeframe": timeframe,
                    "count_requested": count,
                    "count_returned": len(formatted_candles),
                    "shard_index": shard_index,
                    "data_source": data_source,
                    "sources_used": sources_used,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting candlestick data for {currency_pair}: {e}")
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
    
    # CORS headers for all responses - OVERRIDE API Gateway CORS
    # API Gateway may have its own CORS settings that return wildcard (*)
    # We need to ensure our specific origin is returned to fix browser CORS errors
    
    # Log incoming request details for debugging
    logger.info(f"Incoming request - Method: {event.get('httpMethod')}, Path: {event.get('path')}")
    logger.info(f"Headers: {json.dumps(event.get('headers', {}))}")
    
    origin = event.get('headers', {}).get('origin', '') or event.get('headers', {}).get('Origin', '')
    
    # Clean up origin - remove trailing slashes
    if origin.endswith('/'):
        origin = origin.rstrip('/')
    
    logger.info(f"Origin header: '{origin}'")
    
    allowed_origins = [
        'https://pipstop.org',
        'https://www.pipstop.org', 
        'http://pipstop.org',
        'http://www.pipstop.org'
    ]
    
    # CRITICAL: Always return specific origin to override API Gateway wildcard CORS
    if origin and origin in allowed_origins:
        cors_origin = origin
    else:
        cors_origin = 'https://pipstop.org'  # Default to primary domain
    
    # These headers will override API Gateway CORS configuration
    cors_headers = {
        'Access-Control-Allow-Origin': cors_origin,
        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,x-api-key,Accept,Origin',
        'Access-Control-Allow-Methods': 'GET,OPTIONS,POST',
        'Access-Control-Allow-Credentials': 'false',
        'Access-Control-Max-Age': '86400',
        'Vary': 'Origin'  # Important: tells browsers that response varies by origin
    }
    
    logger.info(f"Setting CORS origin to: {cors_origin}")
    
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