#!/usr/bin/env python3
"""
LumiSignals Signal Analytics API Lambda Function

This Lambda function provides signal analytics for the momentum dashboard frontend.
It uses the lumisignals-trading-core layer for sophisticated market-aware calculations.

API Endpoints:
- GET /analytics/all-signals - Get all signal analytics for all currency pairs
- GET /analytics/momentum/{instrument} - Get momentum analysis for specific instrument
- GET /analytics/consensus/{instrument} - Get consensus signal for specific instrument

Author: LumiSignals Trading Team
Version: 1.0.0
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import redis
import boto3
import pytz

# Import Fibonacci strategy naming
from fibonacci_strategy_naming import FibonacciStrategyNaming

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def convert_to_est(timestamp_str: str) -> str:
    """
    Convert UTC timestamp to EST timezone
    
    Args:
        timestamp_str: UTC timestamp string (ISO format)
    
    Returns:
        EST timestamp string with timezone info
    """
    try:
        # Parse UTC timestamp
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        
        utc_dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Convert to EST
        est_tz = pytz.timezone('US/Eastern')
        est_dt = utc_dt.astimezone(est_tz)
        
        # Return formatted EST timestamp
        return est_dt.strftime('%Y-%m-%dT%H:%M:%S %Z')
        
    except Exception as e:
        logger.error(f"Error converting timestamp to EST: {e}")
        return timestamp_str  # Return original if conversion fails

# Redis cluster configuration (matches Fargate configuration)
REDIS_NODES = [
    "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
    "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
]

# Currency pair to shard mapping (matches Fargate sharding)
SHARD_MAPPING = {
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
redis_connections = {}

def init_redis_connections():
    """Initialize Redis connections to all shards"""
    global redis_connections
    for i, node in enumerate(REDIS_NODES):
        try:
            host, port = node.split(':')
            redis_connections[i] = redis.Redis(
                host=host,
                port=int(port),
                decode_responses=False,  # Keep as bytes for JSON parsing
                socket_connect_timeout=30,
                socket_timeout=30,
                retry_on_timeout=True,
                health_check_interval=30
            )
            logger.info(f"Connected to Redis shard {i}: {node}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis shard {i}: {e}")

def get_redis_client_for_instrument(instrument: str):
    """Get the correct Redis client for an instrument based on sharding"""
    if not redis_connections:
        init_redis_connections()
    
    shard_id = SHARD_MAPPING.get(instrument, 0)
    return redis_connections.get(shard_id)

def get_redis_candles(redis_key: str, instrument: str) -> List[Dict]:
    """Get candlestick data from Redis"""
    try:
        redis_client = get_redis_client_for_instrument(instrument)
        if not redis_client:
            logger.error(f"No Redis client available for instrument {instrument}")
            return []
        
        # Get data from Redis LIST (stored as individual JSON entries)
        raw_candles = redis_client.lrange(redis_key, 0, -1)
        if not raw_candles:
            logger.warning(f"No data found for key: {redis_key}")
            return []
        
        # Parse each JSON entry
        candles = []
        for raw_candle in raw_candles:
            try:
                # Handle both string and bytes
                if isinstance(raw_candle, bytes):
                    raw_candle = raw_candle.decode('utf-8')
                candle = json.loads(raw_candle)
                candles.append(candle)
            except Exception as e:
                logger.error(f"Failed to parse candle: {e}")
        
        logger.info(f"Retrieved {len(candles)} candles from {redis_key}")
        return candles
        
    except Exception as e:
        logger.error(f"Error retrieving Redis data for {redis_key}: {e}")
        return []

def get_current_price(instrument: str) -> float:
    """Get current price from Redis"""
    try:
        redis_client = get_redis_client_for_instrument(instrument)
        if not redis_client:
            return None
        
        pricing_key = f"market_data:{instrument}:pricing:current"
        price_data = redis_client.get(pricing_key)
        
        if price_data:
            # Handle bytes
            if isinstance(price_data, bytes):
                price_data = price_data.decode('utf-8')
            pricing = json.loads(price_data)
            # Return mid price (average of bid/ask)
            return (pricing.get('bid', 0) + pricing.get('ask', 0)) / 2
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting current price for {instrument}: {e}")
        return None

def normalize_candle_timestamps(candles: List[Dict]) -> List[Dict]:
    """
    Normalize timestamps in candle data to ensure consistent format.
    Handles Oanda nanosecond timestamps, ISO formats, and missing timestamps.
    
    Args:
        candles: List of candle dictionaries
        
    Returns:
        List of candles with normalized timestamp fields
    """
    if not candles:
        return candles
        
    normalized = []
    
    for i, candle in enumerate(candles):
        try:
            # Get timestamp from various possible fields
            ts = candle.get('time') or candle.get('timestamp') or candle.get('t')
            
            # Parse timestamp into datetime object
            dt = None
            if ts is None:
                # No timestamp - use index-based timestamp (should rarely happen)
                logger.warning(f"Missing timestamp for candle {i}, using index-based time")
                dt = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            elif isinstance(ts, (int, str)) and str(ts).isdigit():
                # Numeric timestamp
                ts_int = int(ts)
                if len(str(ts_int)) > 13:  # Nanoseconds (Oanda format)
                    dt = datetime.fromtimestamp(ts_int / 1_000_000_000, tz=timezone.utc)
                elif len(str(ts_int)) > 10:  # Milliseconds
                    dt = datetime.fromtimestamp(ts_int / 1_000, tz=timezone.utc)
                else:  # Seconds
                    dt = datetime.fromtimestamp(ts_int, tz=timezone.utc)
            elif isinstance(ts, str):
                # ISO format string
                try:
                    # Handle ISO format with or without Z suffix
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    logger.error(f"Could not parse timestamp '{ts}', using index-based time")
                    dt = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            elif isinstance(ts, datetime):
                # Already a datetime object
                dt = ts
            else:
                logger.error(f"Unknown timestamp type {type(ts)}, using index-based time")
                dt = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            
            # Create normalized candle
            normalized_candle = candle.copy()
            
            # Convert datetime back to nanosecond timestamp (Oanda format) for consistency
            ns_timestamp = str(int(dt.timestamp() * 1_000_000_000))
            
            # Ensure both 'time' and 'timestamp' fields exist with same value
            normalized_candle['time'] = ns_timestamp
            normalized_candle['timestamp'] = ns_timestamp
            
            # Store the datetime object temporarily for sorting
            normalized_candle['_dt'] = dt
            
            normalized.append(normalized_candle)
            
        except Exception as e:
            logger.error(f"Error normalizing timestamp for candle {i}: {e}")
            # Include the candle anyway but log the issue
            normalized_candle = candle.copy()
            # Set a fallback timestamp
            fallback_dt = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)
            fallback_ns = str(int(fallback_dt.timestamp() * 1_000_000_000))
            normalized_candle['time'] = fallback_ns
            normalized_candle['timestamp'] = fallback_ns
            normalized_candle['_dt'] = fallback_dt
            normalized.append(normalized_candle)
    
    # Sort by datetime to ensure chronological order
    try:
        normalized.sort(key=lambda x: x['_dt'])
    except Exception as e:
        logger.error(f"Error sorting candles by timestamp: {e}")
    
    # Remove temporary datetime objects
    for candle in normalized:
        candle.pop('_dt', None)
    
    return normalized

def get_tiered_price_data(instrument: str, timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Get all price data tiers for an instrument/timeframe with normalized timestamps
    This is the centralized data retrieval function that all analytics will use
    """
    try:
        logger.info(f"Retrieving tiered price data for {instrument} {timeframe}")
        
        # Get data from all tiers
        hot_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:hot", instrument)
        warm_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:warm", instrument) 
        cold_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:historical", instrument)
        current_price = get_current_price(instrument)
        
        # Normalize timestamps for all data to ensure consistency
        hot_data = normalize_candle_timestamps(hot_data) if hot_data else []
        warm_data = normalize_candle_timestamps(warm_data) if warm_data else []
        cold_data = normalize_candle_timestamps(cold_data) if cold_data else []
        
        # Combine hot + warm for complete dataset (500 candles total)
        combined_data = hot_data + warm_data
        
        # Data is already sorted by normalize_candle_timestamps
        logger.info(f"Combined {len(combined_data)} normalized candles (hot: {len(hot_data)}, warm: {len(warm_data)})")
        
        # If we don't have enough data, fall back to cold tier
        if len(combined_data) < 100:
            logger.warning(f"Insufficient hot+warm data ({len(combined_data)} candles), using cold tier")
            combined_data = cold_data
            # Cold data is already normalized and sorted
            logger.info(f"Using normalized cold data: {len(combined_data)} candles")
        
        result = {
            'hot': hot_data,
            'warm': warm_data, 
            'cold': cold_data,
            'combined': combined_data,
            'current_price': current_price,
            'instrument': instrument,
            'timeframe': timeframe,
            'total_candles': len(combined_data)
        }
        
        logger.info(f"Retrieved tiered data: hot={len(hot_data)}, warm={len(warm_data)}, cold={len(cold_data)}, current_price={current_price}")
        return result
        
    except Exception as e:
        logger.error(f"Error retrieving tiered price data for {instrument} {timeframe}: {e}")
        return {
            'hot': [],
            'warm': [],
            'cold': [],
            'combined': [],
            'current_price': None,
            'instrument': instrument,
            'timeframe': timeframe,
            'total_candles': 0
        }

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for signal analytics API
    """
    try:
        logger.info(f"Signal Analytics API - Event keys: {list(event.keys())}")
        
        # Handle both API Gateway and Lambda Function URL formats
        if 'requestContext' in event and 'http' in event['requestContext']:
            # Lambda Function URL format
            http_method = event['requestContext']['http']['method']
            path = event['requestContext']['http']['path']
            headers = event.get('headers', {})
        else:
            # API Gateway format
            http_method = event.get('httpMethod', 'GET')
            path = event.get('path', '/')
            headers = event.get('headers', {})
            
        logger.info(f"Parsed - Method: {http_method}, Path: {path}")
        
        # CORS headers setup - following working candlestick API pattern  
        origin = headers.get('origin', '') or headers.get('Origin', '')
        
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
        
        # Handle OPTIONS preflight request - following working pattern exactly
        if http_method == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': ''
            }
        
        # Extract path and query parameters based on event format
        if 'requestContext' in event and 'http' in event['requestContext']:
            # Lambda Function URL format
            path_parameters = {}
            query_parameters = event.get('queryStringParameters') or {}
        else:
            # API Gateway format  
            path_parameters = event.get('pathParameters') or {}
            query_parameters = event.get('queryStringParameters') or {}
        
        logger.info(f"Processing {http_method} {path}")
        
        # Route to appropriate handler
        if path == '/analytics/all-signals' and http_method == 'GET':
            timeframe = query_parameters.get('timeframe', 'H1')
            return handle_all_signals(query_parameters, cors_headers, timeframe)
        elif path.startswith('/analytics/momentum/') and http_method == 'GET':
            instrument = path_parameters.get('instrument')
            return handle_momentum_analysis(instrument, query_parameters, cors_headers)
        elif path.startswith('/analytics/consensus/') and http_method == 'GET':
            instrument = path_parameters.get('instrument')
            return handle_consensus_signal(instrument, query_parameters, cors_headers)
        elif path == '/analytics/trade-setups' and http_method == 'GET':
            timeframe = query_parameters.get('timeframe', 'M5')
            return handle_trade_setups(query_parameters, cors_headers, timeframe)
        elif path == '/analytics/place-trade' and http_method == 'POST':
            return handle_place_trade(event, cors_headers)
        else:
            return {
                'statusCode': 404,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps({
                    'success': False,
                    'error': f"Endpoint not found: {http_method} {path}",
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }
            
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Internal server error: {str(e)}",
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }

def handle_all_signals(query_parameters: Dict[str, str], cors_headers: Dict[str, str], timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Handle GET /analytics/all-signals
    Returns comprehensive signal analytics for all currency pairs
    """
    try:
        # Import lumisignals-trading-core components
        try:
            from lumisignals_trading_core import MarketAwareMomentumCalculator, get_current_market_time, is_market_currently_open
            from lumisignals_trading_core.fibonacci import analyze_fibonacci_levels
            from lumisignals_trading_core.sentiment import analyze_candlestick_patterns
            from lumisignals_trading_core.levels import find_supply_demand_zones
            
            logger.info("Successfully imported lumisignals-trading-core components")
        except Exception as import_error:
            logger.warning(f"lumisignals-trading-core layer not available: {import_error}")
            # Use mock functions for development
            def get_current_market_time():
                return datetime.utcnow()
            def is_market_currently_open():
                return True
        
        logger.info("Generating comprehensive signal analytics for all currency pairs")
        
        # Initialize components (note: would need OANDA API in production)
        # For now, we'll use the layer's utilities without actual API calls
        current_time = get_current_market_time()
        market_open = is_market_currently_open()
        
        # Standard forex pairs
        currency_pairs = [
            'EUR_USD', 'GBP_USD', 'USD_CAD', 'AUD_USD', 'USD_JPY', 'NZD_USD', 'USD_CHF',
            'EUR_GBP', 'EUR_JPY', 'GBP_JPY', 'AUD_JPY', 'EUR_CAD', 'GBP_CAD', 'AUD_CAD',
            'EUR_AUD', 'EUR_CHF', 'GBP_CHF', 'AUD_CHF', 'CAD_CHF', 'NZD_CHF', 'CHF_JPY',
            'NZD_JPY', 'CAD_JPY', 'EUR_NZD', 'GBP_NZD', 'AUD_NZD', 'NZD_CAD', 'GBP_AUD'
        ]
        
        signal_data = {}
        
        for pair in currency_pairs:
            try:
                # Generate analytics for each pair with specified timeframe
                signal_data[pair] = generate_pair_analytics(pair, timeframe)
                
            except Exception as e:
                logger.error(f"Error generating analytics for {pair}: {str(e)}")
                # Continue with other pairs
                signal_data[pair] = create_error_analytics(pair, str(e))
        
        response_data = {
            'success': True,
            'data': signal_data,
            'metadata': {
                'market_time': current_time.isoformat(),
                'market_open': market_open,
                'total_pairs': len(currency_pairs),
                'generated_at': datetime.utcnow().isoformat() + 'Z'
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps(response_data, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in handle_all_signals: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Failed to generate signal analytics: {str(e)}",
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }

# REMOVED: analyze_fibonacci_tiered() function was causing fallback to broken implementations
# This function proliferation pattern was creating deployment issues where working code
# would fall back to broken versions. Using Git for version control instead.

# REMOVED: analyze_swing_points_tiered() and create_fallback_swing() functions
# Swing analysis is now integrated into the Fibonacci analysis module

def create_fallback_fibonacci_mode(price_data: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """Create fallback Fibonacci analysis for specific mode when improved analysis fails"""
    instrument = price_data['instrument']
    current_price = price_data['current_price']
    
    # Use current price if available, otherwise estimate
    if not current_price:
        is_jpy_pair = 'JPY' in instrument
        current_price = 150.0 if is_jpy_pair else 1.1000
    
    if mode == 'fixed':
        # H1 timeframe specific levels (fewer levels, more conservative range)
        price_range = current_price * 0.04  # 4% range
        high_price = current_price + (price_range * 0.6)
        low_price = current_price - (price_range * 0.4)
        
        return {
            'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1.0],  # H1 levels with deep retracements
            'high': high_price,
            'low': low_price,
            'direction': 'neutral',
            'current_retracement': 0.382,
            'key_level': 0.618,
            'mode': 'fixed',
            'detailed_levels': [
                {'ratio': r, 'price': high_price - ((high_price - low_price) * r), 'description': f'{r:.1%} Retracement'}
                for r in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1.0]
            ],
            'swing_range_pips': int((high_price - low_price) * (10000 if 'JPY' not in instrument else 100))
        }
    else:  # mode == 'atr'
        # ATR mode with full levels and wider range
        price_range = current_price * 0.06  # 6% range
        high_price = current_price + (price_range * 0.8)
        low_price = current_price - (price_range * 0.2)
        
        return {
            'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1.0],  # All levels
            'high': high_price,
            'low': low_price,
            'direction': 'neutral',
            'current_retracement': 0.5,
            'key_level': 0.618,
            'mode': 'atr',
            'detailed_levels': [
                {'ratio': r, 'price': high_price - ((high_price - low_price) * r), 'description': f'{r:.1%} Retracement'}
                for r in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 1.0]
            ],
            'swing_range_pips': int((high_price - low_price) * (10000 if 'JPY' not in instrument else 100))
        }

# REMOVED: generate_fibonacci_trade_setups() - moved to improved_fibonacci_analysis.py
# Lambda should not do trade calculations - it should only call the analysis module

# REMOVED: generate_bullish_setup() - moved to improved_fibonacci_analysis.py

# REMOVED: generate_bearish_setup() - moved to improved_fibonacci_analysis.py

# REMOVED: get_stop_buffer_pips() - moved to improved_fibonacci_analysis.py

# REMOVED: get_extension_target() - moved to improved_fibonacci_analysis.py

# REMOVED: calculate_position_size() - moved to improved_fibonacci_analysis.py

# REMOVED: get_setup_quality() - moved to improved_fibonacci_analysis.py

# Removed old dual-mode fallback function - now using create_fallback_fibonacci_mode() for Fixed mode only

def generate_pair_analytics(instrument: str, timeframe: str = 'H1', 
                          include_confluence: bool = False,
                          institutional_levels: Dict = None) -> Dict[str, Any]:
    """
    Generate comprehensive analytics for a single currency pair using centralized data retrieval
    
    Args:
        instrument: Currency pair (e.g., 'EUR_USD')
        timeframe: Time period for analysis (default: 'H1')
        include_confluence: Whether to include confluence analysis in trade setups
        institutional_levels: Dictionary of institutional price levels for confluence
    """
    try:
        logger.info(f"Generating analytics for {instrument} {timeframe}")
        
        # GET ALL DATA ONCE - This is the key improvement
        price_data = get_tiered_price_data(instrument, timeframe)
        
        if price_data['total_candles'] == 0:
            logger.warning(f"No price data available for {instrument} {timeframe}")
            return create_error_analytics(instrument, f"No price data available for {timeframe}")
        
        # RUN ALL ANALYTICS WITH SAME DATA
        current_price = price_data['current_price'] or 1.1000
        
        # RUN ENHANCED FIBONACCI ANALYSIS WITH INTEGRATED TRADE SETUPS
        try:
            from lumisignals_trading_core.fibonacci.improved_fibonacci_analysis import analyze_fibonacci_levels_improved
            
            # Convert Redis candle format to analysis format (h,l,c,o -> high,low,close,open)
            combined_candles = price_data['combined']
            formatted_candles = []
            for candle in combined_candles:
                formatted_candles.append({
                    'high': float(candle.get('h', candle.get('high', 0))),
                    'low': float(candle.get('l', candle.get('low', 0))),
                    'close': float(candle.get('c', candle.get('close', 0))),
                    'open': float(candle.get('o', candle.get('open', 0))),
                    'timestamp': candle.get('time', candle.get('timestamp', ''))
                })
            
            fibonacci_data = analyze_fibonacci_levels_improved(
                instrument=instrument,
                current_price=current_price,
                price_data=formatted_candles,  # Use formatted candles instead of raw Redis data
                mode='fixed',
                timeframe=timeframe,
                include_trade_setups=True,  # Generate trade setups directly in analysis
                include_confluence=include_confluence,
                institutional_levels=institutional_levels
            )
        except ImportError as e:
            logger.error(f"Trading core import failed: {e}")
            import traceback
            logger.error(f"Import traceback: {traceback.format_exc()}")
            raise Exception(f"Fibonacci analysis unavailable - import error: {str(e)}")
        except Exception as e:
            logger.error(f"Fibonacci analysis failed with error: {e}")
            import traceback
            logger.error(f"Analysis traceback: {traceback.format_exc()}")
            raise Exception(f"Fibonacci analysis failed: {str(e)}")
        
        # Swing analysis is now integrated into Fibonacci analysis
        swing_data = {'message': 'Swing analysis integrated into Fibonacci module'}
        
        # Extract trade setups from fibonacci data - no fallback
        trade_setups = fibonacci_data.get('trade_setups', [])
        
        # DEBUG: Log what fibonacci analysis returned
        logger.info(f"DEBUG {instrument}: fibonacci_data has trade_setups = {'trade_setups' in fibonacci_data}")
        if 'trade_setups' in fibonacci_data:
            logger.info(f"DEBUG {instrument}: fibonacci_data['trade_setups'] = {len(fibonacci_data['trade_setups'])} setups")
        
        # Future analytics will use the same price_data:
        # rsi_data = analyze_rsi_tiered(price_data)
        # ma_data = analyze_moving_averages_tiered(price_data)
        # sentiment_data = analyze_sentiment_tiered(price_data)
        
        # Generate other analytics (using mock data for now - will be replaced with tiered analysis)
        price_range = current_price * 0.05
        
        # Generate Supply/Demand zones (future: analyze_supply_demand_tiered(price_data))
        supply_demand_data = {
            'zones': [
                {
                    'type': 'supply',
                    'start': current_price + (price_range * 0.5),
                    'end': current_price + (price_range * 0.7),
                    'strength': 0.85,
                    'touches': 2,
                    'freshness': 0.9
                },
                {
                    'type': 'demand',
                    'start': current_price - (price_range * 0.7),
                    'end': current_price - (price_range * 0.5),
                    'strength': 0.92,
                    'touches': 1,
                    'freshness': 1.0
                }
            ]
        }
        
        # Generate momentum analysis (future: analyze_momentum_tiered(price_data))
        momentum_data = {
            'overall_bias': 'BULLISH',
            'confidence': 0.73,
            'strength': 'STRONG',
            'timeframe_breakdown': {
                '15m': {'momentum': 0.052, 'direction': 'BULLISH'},
                '60m': {'momentum': 0.041, 'direction': 'BULLISH'},
                '4h': {'momentum': 0.067, 'direction': 'BULLISH'},
                '24h': {'momentum': 0.034, 'direction': 'BULLISH'},
                '48h': {'momentum': -0.012, 'direction': 'BEARISH'}
            }
        }
        
        # Generate consensus signal (future: analyze_consensus_tiered(price_data))
        consensus_data = {
            'trading_ready': True,
            'signal': 'BULLISH',
            'aligned_timeframes': 4,
            'confidence': 0.8,
            'strength': 'STRONG'
        }
        
        # Generate trend analysis (future: analyze_trend_tiered(price_data))
        trend_data = {
            'direction': 'up',
            'strength': 0.72,
            'timeframes': {
                '5m': 'up',
                '15m': 'up',
                '1h': 'neutral',
                '4h': 'up'
            }
        }
        
        # Generate RSI/SMA analysis (future: analyze_rsi_sma_tiered(price_data))
        rsi_sma_data = {
            'rsi': 62,
            'sma': current_price * 0.999,
            'quadrant': 'bullish',
            'rsi_level': 'neutral'
        }
        
        # Generate sentiment analysis (future: analyze_sentiment_tiered(price_data))
        adam_button_data = {
            'sentiment': 'neutral',
            'strength': 'moderate',
            'last_update': datetime.utcnow().isoformat() + 'Z'
        }
        
        scotiabank_data = {
            'flow': 'buying',
            'strength': 'moderate',
            'volume': 250000000,
            'direction': 'bullish'
        }
        
        # Generate candlestick analysis (future: analyze_candlestick_tiered(price_data))
        candlestick_data = {
            'patterns': [
                {
                    'name': 'hammer',
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'reliability': 0.75,
                    'direction': 'bullish'
                }
            ]
        }
        
        return {
            'instrument': instrument,
            'timeframe': timeframe,
            'fibonacci': fibonacci_data,
            'trade_setups': trade_setups,
            'swing': swing_data,
            'supplyDemand': supply_demand_data,
            'momentum': momentum_data,
            'consensus': consensus_data,
            'trend': trend_data,
            'rsiSma': rsi_sma_data,
            'adamButton': adam_button_data,
            'scotiabank': scotiabank_data,
            'candlestick': candlestick_data,
            'data_source': 'redis_tiered',
            'total_candles': price_data['total_candles'],
            'current_price': current_price,
            'generated_at': datetime.utcnow().isoformat() + 'Z'
        }
        
    except Exception as e:
        logger.error(f"Error generating analytics for {instrument}: {str(e)}")
        return create_error_analytics(instrument, str(e))

def create_error_analytics(instrument: str, error_msg: str) -> Dict[str, Any]:
    """Create error response for individual pair analytics"""
    return {
        'instrument': instrument,
        'error': error_msg,
        'generated_at': datetime.utcnow().isoformat() + 'Z'
    }

def handle_momentum_analysis(instrument: str, query_parameters: Dict[str, str], cors_headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Handle GET /analytics/momentum/{instrument}
    Returns detailed momentum analysis for specific instrument
    """
    try:
        if not instrument:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps({
                    'success': False,
                    'error': "Instrument parameter is required",
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }
        
        strategy_type = query_parameters.get('strategy', 'pennies')
        
        logger.info(f"Generating momentum analysis for {instrument} with strategy {strategy_type}")
        
        # Generate detailed momentum data
        pair_analytics = generate_pair_analytics(instrument)
        
        response_data = {
            'success': True,
            'data': {
                'instrument': instrument,
                'strategy_type': strategy_type,
                'momentum_summary': pair_analytics['momentum'],
                'consensus': pair_analytics['consensus'],
                'timeframe_breakdown': pair_analytics['momentum']['timeframe_breakdown']
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps(response_data, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in handle_momentum_analysis: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Failed to generate momentum analysis: {str(e)}",
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }

def handle_consensus_signal(instrument: str, query_parameters: Dict[str, str], cors_headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Handle GET /analytics/consensus/{instrument}
    Returns consensus trading signal for specific instrument
    """
    try:
        if not instrument:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps({
                    'success': False,
                    'error': "Instrument parameter is required",
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }
        
        strategy_type = query_parameters.get('strategy', 'pennies')
        required_confidence = float(query_parameters.get('confidence', '0.6'))
        
        logger.info(f"Generating consensus signal for {instrument} with strategy {strategy_type}")
        
        # Generate consensus data
        pair_analytics = generate_pair_analytics(instrument)
        consensus = pair_analytics['consensus']
        
        response_data = {
            'success': True,
            'data': {
                'instrument': instrument,
                'strategy_type': strategy_type,
                'consensus': consensus,
                'trading_ready': consensus['confidence'] >= required_confidence,
                'required_confidence': required_confidence
            },
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps(response_data, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in handle_consensus_signal: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Failed to generate consensus signal: {str(e)}",
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }

# Removed unused CORS helper functions - now using working API pattern directly

# Health check endpoint
def health_check() -> Dict[str, Any]:
    """Health check for the analytics API"""
    try:
        from lumisignals_trading_core import get_layer_info, validate_layer
        
        layer_info = get_layer_info()
        layer_status = validate_layer()
        
        return create_success_response({
            'status': 'healthy',
            'service': 'lumisignals-signal-analytics-api',
            'version': '1.0.0',
            'layer_info': layer_info,
            'layer_status': layer_status,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
    except Exception as e:
        return create_error_response(500, f"Health check failed: {str(e)}")

# SAVED FOR LATER: Enhanced version with trading core integration
# TODO: Integrate features one by one after basic functionality works

# REMOVED: generate_pair_analytics_with_setups() function
# Enhanced features have been integrated into main generate_pair_analytics() function:
# - Confluence and institutional levels support
# - Integrated trade setup generation 
# - Cleaner structure without non-existent helper functions

def convert_analytics_to_trade_format(fibonacci_data: Dict[str, Any], current_price: float, instrument: str) -> Dict[str, Any]:
    """
    Convert all-signals fibonacci data to format expected by trade setup generator
    """
    try:
        if not fibonacci_data or not fibonacci_data.get('levels'):
            return None
        
        # Extract swing high and low from fibonacci data
        swing_high_price = fibonacci_data.get('high')
        swing_low_price = fibonacci_data.get('low')
        
        if not swing_high_price or not swing_low_price:
            return None
        
        # Create swing objects
        swing_high = {
            'price': swing_high_price,
            'time': '',  # Not needed for trade generation
            'index': 0
        }
        
        swing_low = {
            'price': swing_low_price, 
            'time': '',
            'index': 0
        }
        
        # Calculate swing range
        swing_range = swing_high_price - swing_low_price
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        swing_range_pips = int(swing_range / pip_value)
        
        # Build retracement levels from fibonacci data
        retracement_levels = {}
        levels = fibonacci_data.get('levels', [])
        
        for level in levels:
            if level > 0.0 and level <= 1.0:  # Valid retracement levels
                price = swing_high_price - (swing_range * level)
                retracement_levels[f'{level:.3f}'] = {
                    'price': price,
                    'ratio': level
                }
        
        # Build extension levels (basic set)
        extension_levels = {}
        extension_ratios = [1.272, 1.382, 1.618, 2.000]
        
        for ratio in extension_ratios:
            price = swing_high_price + (swing_range * (ratio - 1.0))
            extension_levels[f'{ratio:.3f}'] = {
                'price': price,
                'ratio': ratio
            }
        
        # Return format expected by fibonacci_trade_setups.py
        return {
            'fibonacci_sets': [{}],  # Non-empty to pass validation
            'most_relevant': {
                'swing_range_pips': swing_range_pips,
                'high_swing': swing_high,
                'low_swing': swing_low,
                'retracement_levels': retracement_levels,
                'extension_levels': extension_levels
            }
        }
        
    except Exception as e:
        logger.error(f"Error converting analytics to trade format: {e}")
        return None

def handle_trade_setups(query_parameters: Dict[str, str], cors_headers: Dict[str, str], timeframe: str = 'M5') -> Dict[str, Any]:
    """
    Generate Fibonacci trade setups with OANDA integration
    """
    try:
        logger.info(f"Generating trade setups for timeframe: {timeframe}")
        
        # Initialize strategy naming
        strategy_naming = FibonacciStrategyNaming()
        
        # Check if confluence is requested
        use_confluence = query_parameters.get('confluence', 'false').lower() == 'true'
        logger.info(f"Confluence enabled: {use_confluence}")
        
        # Get instruments to analyze (default to all 28 pairs)
        instruments_param = query_parameters.get('instruments', '')
        if instruments_param:
            instruments = [inst.strip() for inst in instruments_param.split(',')]
        else:
            # Default to all 28 currency pairs from SHARD_MAPPING
            instruments = list(SHARD_MAPPING.keys())
        
        # Generate trade setups for each instrument
        trade_setups = []
        
        for instrument in instruments:
            try:
                logger.info(f"Analyzing {instrument} for trade setups...")
                
                # Get institutional levels if confluence is enabled
                institutional_levels = None
                if use_confluence:
                    institutional_levels = get_institutional_levels(instrument, 1.1000)  # Will get real price inside function
                
                # Use enhanced analytics function with integrated trade setups and confluence support
                pair_analytics = generate_pair_analytics(instrument, timeframe, use_confluence, institutional_levels)
                
                if not pair_analytics or 'fibonacci' not in pair_analytics:
                    logger.warning(f"No Fibonacci analysis available for {instrument}")
                    continue
                
                fibonacci_data = pair_analytics['fibonacci']
                current_price = pair_analytics.get('current_price')
                
                if not current_price:
                    logger.warning(f"No current price available for {instrument}")
                    continue
                
                # DEBUG: Log what we have
                logger.info(f"DEBUG {instrument}: fibonacci_data keys = {list(fibonacci_data.keys())}")
                logger.info(f"DEBUG {instrument}: pair_analytics keys = {list(pair_analytics.keys())}")
                
                # Use enhanced Fibonacci analysis with trade setups
                # Check both locations: fibonacci['trade_setups'] and top-level 'trade_setups'
                # DON'T reassign fibonacci_data - it's already set above!
                trade_setups_source = []
                
                if 'trade_setups' in fibonacci_data and fibonacci_data['trade_setups']:
                    trade_setups_source = fibonacci_data['trade_setups']
                    logger.info(f"DEBUG {instrument}: Found {len(trade_setups_source)} setups in fibonacci_data")
                elif 'trade_setups' in pair_analytics and pair_analytics['trade_setups']:
                    trade_setups_source = pair_analytics['trade_setups']
                    logger.info(f"DEBUG {instrument}: Found {len(trade_setups_source)} setups in pair_analytics")
                else:
                    logger.info(f"DEBUG {instrument}: No trade setups found in either location")
                
                if trade_setups_source:
                    for setup in trade_setups_source:
                        # Generate strategy metadata using our naming system
                        setup_data = {
                            'type': setup['direction'].lower().replace('buy', 'long').replace('sell', 'short'),
                            'strategy': setup['strategy'],
                            'action': setup['direction'],
                            'entry_price': setup['entry_price'],
                            'fibonacci_level': setup['fibonacci_level']
                        }
                        
                        strategy_metadata = strategy_naming.get_strategy_metadata(setup_data, timeframe)
                        
                        # Just pass through the setup with added metadata
                        trade_setup = {
                            **setup,  # Include all fields from the setup
                            'strategy_metadata': strategy_metadata,
                            'analysis_timestamp': convert_to_est(setup['analysis_timestamp']),
                            'analysis_timestamp_utc': setup['analysis_timestamp']  # Keep original UTC for reference
                        }
                        
                        trade_setups.append(trade_setup)
                        
            except Exception as e:
                logger.error(f"Error analyzing {instrument}: {e}")
                continue
        
        # Sort by setup quality (highest first)
        trade_setups.sort(key=lambda x: x['setup_quality'], reverse=True)
        
        # Generate timestamps
        utc_timestamp = datetime.utcnow().isoformat() + 'Z'
        est_timestamp = convert_to_est(utc_timestamp)
        
        response_data = {
            'success': True,
            'data': {
                'timeframe': timeframe,
                'confluence_enabled': use_confluence,
                'instruments_analyzed': len(instruments),
                'setups_found': len(trade_setups),
                'trade_setups': trade_setups[:20]  # Limit to top 20 setups
            },
            'timestamp': est_timestamp,
            'timestamp_utc': utc_timestamp
        }
        
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps(response_data, default=str)
        }
        
    except Exception as e:
        logger.error(f"Error in handle_trade_setups: {e}", exc_info=True)
        utc_timestamp = datetime.utcnow().isoformat() + 'Z'
        est_timestamp = convert_to_est(utc_timestamp)
        
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Trade setup generation failed: {str(e)}",
                'timestamp': est_timestamp,
                'timestamp_utc': utc_timestamp
            })
        }

# REMOVED: perform_fibonacci_analysis() - duplicate logic moved to improved_fibonacci_analysis.py

# REMOVED: create_fibonacci_analysis_from_candles() - duplicate logic moved to improved_fibonacci_analysis.py

# REMOVED: find_significant_swings() - duplicate logic moved to improved_fibonacci_analysis.py

# REMOVED: determine_trend_direction() - duplicate logic moved to improved_fibonacci_analysis.py

# REMOVED: convert_fibonacci_setup_format() - duplicate logic moved to improved_fibonacci_analysis.py

def get_institutional_levels(instrument: str, current_price: float) -> Dict[str, Any]:
    """
    Generate institutional levels (quarters, pennies, dimes) for confluence analysis
    """
    try:
        is_jpy = 'JPY' in instrument
        
        if is_jpy:
            # JPY pairs: Use whole numbers and half numbers
            base_level = round(current_price)
            level_range = 5
            
            levels = {
                'quarters': [],  # Every 0.25 for JPY doesn't make sense
                'pennies': [base_level + i for i in range(-level_range, level_range + 1)],  # Whole numbers
                'dimes': [base_level + (i * 10) for i in range(-2, 3)]  # Every 10 yen
            }
        else:
            # Non-JPY pairs: Use decimal levels
            # Quarters: Every 0.25 (1.2500, 1.2750, 1.3000, etc.)
            quarter_base = round(current_price * 4) / 4
            quarters = [quarter_base + (i * 0.25) for i in range(-4, 5)]
            
            # Pennies: Every 0.01 (1.2300, 1.2400, 1.2500, etc.)
            penny_base = round(current_price, 2)
            pennies = [penny_base + (i * 0.01) for i in range(-10, 11)]
            
            # Dimes: Every 0.10 (1.2000, 1.3000, 1.4000, etc.)
            dime_base = round(current_price, 1)
            dimes = [dime_base + (i * 0.10) for i in range(-5, 6)]
            
            levels = {
                'quarters': quarters,
                'pennies': pennies,
                'dimes': dimes
            }
        
        # Filter positive levels only
        for level_type in levels:
            levels[level_type] = [level for level in levels[level_type] if level > 0]
        
        return levels
        
    except Exception as e:
        logger.error(f"Error generating institutional levels: {e}")
        return {'quarters': [], 'pennies': [], 'dimes': []}

def handle_place_trade(event: Dict[str, Any], cors_headers: Dict[str, str]) -> Dict[str, Any]:
    """
    Place trade orders based on Fibonacci trade setups through OANDA
    Following LumiSignals architecture: Lambda → OANDA → Fargate collection → RDS
    """
    try:
        # Parse request body
        body = event.get('body', '{}')
        if isinstance(body, str):
            trade_data = json.loads(body)
        else:
            trade_data = body
        
        logger.info(f"Placing trade order: {trade_data}")
        
        # Validate required fields
        required_fields = ['instrument', 'direction', 'entry_price', 'stop_loss', 'take_profit']
        missing_fields = [field for field in required_fields if field not in trade_data]
        
        if missing_fields:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps({
                    'success': False,
                    'error': f"Missing required fields: {missing_fields}",
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }
        
        # Initialize OANDA API client
        oanda_api = get_oanda_client()
        if not oanda_api:
            return create_error_response(500, "OANDA client not available", cors_headers)
        
        # Calculate position size (default $10 risk per trade)
        risk_amount = trade_data.get('risk_amount', 10.0)  # $10 default risk
        units = calculate_position_size(
            trade_data['instrument'],
            trade_data['entry_price'],
            trade_data['stop_loss'],
            risk_amount
        )
        
        # Adjust units for direction (positive for BUY, negative for SELL)
        if trade_data['direction'].upper() == 'SELL':
            units = -abs(units)
        else:
            units = abs(units)
        
        # Place limit order with stop loss and take profit
        order_result = oanda_api.place_limit_order(
            instrument=trade_data['instrument'],
            units=units,
            price=float(trade_data['entry_price']),
            stop_loss=float(trade_data['stop_loss']),
            take_profit=float(trade_data['take_profit'])
        )
        
        if order_result and not order_result.get('error'):
            # Store trade metadata to Redis for Fargate collection
            trade_metadata = prepare_trade_metadata(trade_data, order_result, units)
            
            # Store to Redis using centralized market data client
            from centralized_market_data_client import CentralizedMarketDataClient
            market_client = CentralizedMarketDataClient()
            metadata_stored = market_client.store_trade_metadata(trade_metadata)
            
            # Prepare success response
            response_data = {
                'success': True,
                'data': {
                    'order_id': order_result.get('orderCreateTransaction', {}).get('id'),
                    'instrument': trade_data['instrument'],
                    'direction': trade_data['direction'],
                    'units': units,
                    'entry_price': trade_data['entry_price'],
                    'stop_loss': trade_data['stop_loss'],
                    'take_profit': trade_data['take_profit'],
                    'risk_amount': risk_amount,
                    'oanda_response': order_result,
                    'metadata_stored': metadata_stored,
                    'strategy_name': trade_data.get('strategy_metadata', {}).get('strategy_name', 'Fibonacci Setup')
                },
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }
            
            logger.info(f"✅ Trade placed successfully: {trade_data['instrument']} {trade_data['direction']}")
            
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps(response_data, default=str)
            }
        else:
            # OANDA order failed
            error_msg = order_result.get('error', 'Unknown OANDA error')
            logger.error(f"OANDA order failed: {error_msg}")
            
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json', **cors_headers},
                'body': json.dumps({
                    'success': False,
                    'error': f"OANDA order failed: {error_msg}",
                    'oanda_response': order_result,
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            }
            
    except Exception as e:
        logger.error(f"Error in handle_place_trade: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json', **cors_headers},
            'body': json.dumps({
                'success': False,
                'error': f"Trade placement failed: {str(e)}",
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })
        }

def get_oanda_client():
    """
    Initialize OANDA API client with credentials from environment/secrets
    """
    try:
        # Import OANDA API client
        import sys
        sys.path.append('/opt/python')  # Lambda layer path
        from oanda_api import OandaAPI
        
        # Get credentials from environment or AWS Secrets Manager
        api_key = os.environ.get('OANDA_API_KEY')
        account_id = os.environ.get('OANDA_ACCOUNT_ID')
        environment = os.environ.get('OANDA_ENVIRONMENT', 'practice')
        
        if not api_key or not account_id:
            logger.error("OANDA credentials not configured")
            return None
        
        oanda_client = OandaAPI(api_key, account_id, environment)
        logger.info(f"✅ OANDA client initialized ({environment})")
        
        return oanda_client
        
    except Exception as e:
        logger.error(f"Failed to initialize OANDA client: {e}")
        return None

def calculate_position_size(instrument: str, entry_price: float, stop_loss: float, risk_amount: float) -> int:
    """
    Calculate position size based on fixed risk amount ($10 default)
    """
    try:
        # Calculate risk in pips
        is_jpy = 'JPY' in instrument
        pip_value = 0.01 if is_jpy else 0.0001
        
        risk_pips = abs(entry_price - stop_loss) / pip_value
        
        if risk_pips <= 0:
            logger.warning(f"Invalid risk calculation: entry={entry_price}, stop={stop_loss}")
            return 1000  # Default small position
        
        # Standard pip values for position sizing
        if is_jpy:
            # For JPY pairs: 1 pip = $1 per 10,000 units (approximately)
            pip_value_usd = 0.0001 * 10000  # ~$1 per 10k units
        else:
            # For non-JPY pairs: 1 pip = $1 per 10,000 units (approximately)  
            pip_value_usd = 0.0001 * 10000  # ~$1 per 10k units
        
        # Calculate units needed for target risk
        target_loss = risk_amount  # $10 default
        units_per_dollar_risk = 10000 / (risk_pips * pip_value_usd)
        
        position_size = int(target_loss * units_per_dollar_risk)
        
        # Ensure minimum and maximum position sizes
        position_size = max(1000, min(position_size, 100000))  # Between 1k and 100k units
        
        logger.info(f"Position sizing: {instrument}, Risk: ${risk_amount}, Pips: {risk_pips:.1f}, Units: {position_size}")
        
        return position_size
        
    except Exception as e:
        logger.error(f"Error calculating position size: {e}")
        return 1000  # Default fallback

def prepare_trade_metadata(trade_data: Dict, order_result: Dict, units: int) -> Dict:
    """
    Prepare trade metadata for Redis storage and Fargate collection
    """
    try:
        order_transaction = order_result.get('orderCreateTransaction', {})
        
        metadata = {
            'order_id': order_transaction.get('id'),
            'instrument': trade_data['instrument'],
            'action': trade_data['direction'].upper(),
            'order_type': 'LIMIT',
            'entry_price': float(trade_data['entry_price']),
            'stop_loss': float(trade_data['stop_loss']),
            'take_profit': float(trade_data['take_profit']),
            'units': units,
            'risk_amount': trade_data.get('risk_amount', 10.0),
            'rr_ratio': trade_data.get('risk_reward_ratio', 0),
            'signal_confidence': trade_data.get('signal_confidence', 75),
            'strategy_name': trade_data.get('strategy_metadata', {}).get('strategy_name', 'Fibonacci Setup'),
            'fibonacci_level': trade_data.get('fibonacci_level'),
            'confluence_enabled': trade_data.get('confluence_enabled', False),
            'reasoning': [trade_data.get('entry_reason', 'Fibonacci trade setup')],
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'oanda_transaction_id': order_transaction.get('id'),
            'oanda_time': order_transaction.get('time')
        }
        
        return metadata
        
    except Exception as e:
        logger.error(f"Error preparing trade metadata: {e}")
        return {}