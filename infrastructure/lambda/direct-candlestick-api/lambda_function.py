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
        if len(sorted_candles) > 0 and len(h1_candles) == 0:
            # Debug: log the first few M5 candles to understand the format
            logger.info(f"DEBUG: First M5 candle structure: {sorted_candles[0] if sorted_candles else 'None'}")
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
            
            # Try multiple Redis key patterns (matches working dashboard API)
            possible_keys = [
                (f"market_data:{currency_pair}:{timeframe}:historical", f"market_data:{currency_pair}:{timeframe}:current"),
                (f"market_data:{currency_pair}:M5:historical", f"market_data:{currency_pair}:M5:current"),  # Fallback to M5
                (f"candlestick:{currency_pair}:{timeframe}", None),
                (f"ohlc:{currency_pair}:{timeframe}", None),
            ]
            
            # Test connection
            redis_conn.ping()
            
            current_data = None
            historical_data = None
            used_keys = None
            
            # Try each key pattern until we find data
            for historical_key, current_key in possible_keys:
                historical_data = redis_conn.get(historical_key)
                if current_key:
                    current_data = redis_conn.get(current_key)
                
                if historical_data or current_data:
                    used_keys = (historical_key, current_key)
                    logger.info(f"Found data for {currency_pair} using keys: {historical_key}, {current_key}")
                    break
            
            if not used_keys:
                logger.info(f"No data found for {currency_pair} in any key pattern")
            
            candles = []
            
            # Parse historical data
            if historical_data:
                try:
                    parsed_historical = json.loads(historical_data.decode('utf-8'))
                    if isinstance(parsed_historical, dict) and 'candles' in parsed_historical:
                        candles.extend(parsed_historical['candles'])
                    elif isinstance(parsed_historical, list):
                        candles.extend(parsed_historical)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse historical data for {currency_pair}: {e}")
            
            # Parse current data
            if current_data:
                try:
                    parsed_current = json.loads(current_data.decode('utf-8'))
                    if isinstance(parsed_current, dict):
                        # Extract current candle info
                        current_candle = {
                            "time": parsed_current.get('timestamp'),
                            "open": parsed_current.get('open'),
                            "high": parsed_current.get('high'), 
                            "low": parsed_current.get('low'),
                            "close": parsed_current.get('close'),
                            "volume": parsed_current.get('volume', 0)
                        }
                        if current_candle["time"]:
                            candles.append(current_candle)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse current data for {currency_pair}: {e}")
            
            # If we got M5 data but requested H1, aggregate it
            if candles and used_keys and 'M5' in used_keys[0] and timeframe == 'H1':
                candles = self.aggregate_m5_to_h1(candles)
                logger.info(f"Aggregated M5 data to H1 for {currency_pair}")
            
            # Sort by time and limit to requested count
            if candles:
                candles = sorted(candles, key=lambda x: x.get('time', ''))[-count:]
            
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
            
            return {
                "success": True,
                "data": formatted_candles,
                "metadata": {
                    "currency_pair": currency_pair,
                    "timeframe": timeframe,
                    "count_requested": count,
                    "count_returned": len(formatted_candles),
                    "shard_index": shard_index,
                    "data_source": "DIRECT_REDIS_FARGATE",
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
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type,x-api-key',
                    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
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
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,x-api-key',
                'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
            },
            'body': json.dumps(result)
        }
        
    except Exception as e:
        logger.error(f"Lambda handler error: {e}")
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,x-api-key',
                'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
            },
            'body': json.dumps({
                'success': False,
                'error': 'Internal server error'
            })
        }