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
from datetime import datetime
from typing import Dict, Any, Optional, List
import redis
import boto3

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def get_tiered_price_data(instrument: str, timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Get all price data tiers for an instrument/timeframe
    This is the centralized data retrieval function that all analytics will use
    """
    try:
        logger.info(f"Retrieving tiered price data for {instrument} {timeframe}")
        
        # Get data from all tiers
        hot_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:hot", instrument)
        warm_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:warm", instrument) 
        cold_data = get_redis_candles(f"market_data:{instrument}:{timeframe}:historical", instrument)
        current_price = get_current_price(instrument)
        
        # Combine hot + warm for complete dataset (500 candles total)
        combined_data = hot_data + warm_data
        
        # If we don't have enough data, fall back to cold tier
        if len(combined_data) < 100:
            logger.warning(f"Insufficient hot+warm data ({len(combined_data)} candles), using cold tier")
            combined_data = cold_data
        
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

def analyze_fibonacci_tiered(price_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze Fibonacci levels using tiered price data
    """
    try:
        from lumisignals_trading_core.fibonacci.improved_fibonacci_analysis import analyze_fibonacci_levels_improved
        
        instrument = price_data['instrument']
        current_price = price_data['current_price']
        combined_candles = price_data['combined']
        
        # Convert Redis candle format to analysis format if needed
        formatted_candles = []
        for candle in combined_candles:
            # Redis format uses 'o', 'h', 'l', 'c' keys
            formatted_candles.append({
                'high': float(candle.get('h', candle.get('high', 0))),
                'low': float(candle.get('l', candle.get('low', 0))),
                'close': float(candle.get('c', candle.get('close', 0))),
                'open': float(candle.get('o', candle.get('open', 0))),
                'timestamp': candle.get('time', candle.get('timestamp', ''))
            })
        
        # Use real analysis with actual market data - Fixed mode only
        if current_price and len(formatted_candles) > 10:
            # Get Fixed mode Fibonacci analysis only
            result_fixed = analyze_fibonacci_levels_improved(instrument, current_price, formatted_candles, mode='fixed', timeframe=price_data['timeframe'])
            
            logger.info(f"Fibonacci analysis for {instrument}: Fixed levels={result_fixed.get('levels', [])}")
            
            # Check if Fixed mode encountered errors
            fixed_fallback = 'error' in result_fixed
            
            if fixed_fallback:
                result_fixed = create_fallback_fibonacci_mode(price_data, 'fixed')
                result_fixed['fallback'] = True
                result_fixed['message'] = f'Fixed mode error: {result_fixed.get("error", "Unknown")}'
            
            # Return simplified single-mode result
            return {
                'levels': result_fixed.get('levels', []),
                'high': result_fixed.get('high', 0),
                'low': result_fixed.get('low', 0),
                'direction': result_fixed.get('direction', 'neutral'),
                'current_retracement': result_fixed.get('current_retracement', 0.5),
                'key_level': result_fixed.get('key_level', 0.618),
                'detailed_levels': result_fixed.get('detailed_levels', []),
                'swing_range_pips': result_fixed.get('swing_range_pips', 0),
                'relevance_score': result_fixed.get('relevance_score', 0),
                'mode': 'fixed',
                'mode_info': result_fixed.get('mode_info', {}),
                'swing_analysis': result_fixed.get('swing_analysis', {}),
                'has_fallback': fixed_fallback
            }
        else:
            logger.warning(f"Insufficient data for {instrument}: current_price={current_price}, candles={len(formatted_candles)}")
            raise Exception("Insufficient data for analysis")
            
    except Exception as e:
        logger.error(f"Fibonacci analysis error for {price_data['instrument']}: {str(e)}")
        combined_candles = price_data.get('combined', [])
        logger.error(f"Candle sample: {combined_candles[0] if combined_candles else 'No candles'}")
        # Fallback to basic analysis - Fixed mode only
        fallback_result = create_fallback_fibonacci_mode(price_data, 'fixed')
        return {
            'levels': fallback_result.get('levels', []),
            'high': fallback_result.get('high', 0),
            'low': fallback_result.get('low', 0),
            'direction': fallback_result.get('direction', 'neutral'),
            'current_retracement': fallback_result.get('current_retracement', 0.5),
            'key_level': fallback_result.get('key_level', 0.618),
            'detailed_levels': fallback_result.get('detailed_levels', []),
            'swing_range_pips': fallback_result.get('swing_range_pips', 0),
            'relevance_score': 0.1,  # Low relevance for fallback
            'mode': 'fixed',
            'mode_info': {'mode': 'fixed', 'fallback': True},
            'swing_analysis': {},
            'has_fallback': True,
            'message': 'Using fallback Fixed Fibonacci analysis'
        }

def analyze_swing_points_tiered(price_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze swing points using tiered price data and robust swing detection
    """
    try:
        from lumisignals_trading_core.swing.swing_detection import analyze_swing_structure
        
        instrument = price_data['instrument']
        timeframe = price_data['timeframe']
        combined_candles = price_data['combined']
        
        # Convert Redis candle format to analysis format if needed
        formatted_candles = []
        for candle in combined_candles:
            # Redis format uses 'o', 'h', 'l', 'c' keys
            formatted_candles.append({
                'high': float(candle.get('h', candle.get('high', 0))),
                'low': float(candle.get('l', candle.get('low', 0))),
                'close': float(candle.get('c', candle.get('close', 0))),
                'open': float(candle.get('o', candle.get('open', 0))),
                'timestamp': candle.get('time', candle.get('timestamp', ''))
            })
        
        # Use robust swing detection from trading core
        if len(formatted_candles) > 10:
            current_price = formatted_candles[-1]['close'] if formatted_candles else 0
            swing_analysis = analyze_swing_structure(instrument, formatted_candles, timeframe, current_price)
            
            logger.info(f"Swing analysis for {instrument}: {len(swing_analysis.get('swing_analysis', {}).get('validated_highs', []))} highs, {len(swing_analysis.get('swing_analysis', {}).get('validated_lows', []))} lows")
            
            return {
                'swing_analysis': swing_analysis.get('swing_analysis', {}),
                'fibonacci_swings': swing_analysis.get('fibonacci_swings', []),
                'success': swing_analysis.get('success', False),
                'total_candles': len(formatted_candles),
                'timeframe': timeframe
            }
        else:
            logger.warning(f"Insufficient data for swing analysis: {len(formatted_candles)} candles")
            raise Exception("Insufficient data for swing analysis")
            
    except Exception as e:
        logger.error(f"Swing analysis error for {price_data['instrument']}: {str(e)}")
        # Fallback to basic swing analysis
        return create_fallback_swing(price_data)

def create_fallback_swing(price_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create fallback swing analysis when robust analysis fails"""
    instrument = price_data['instrument']
    current_price = price_data['current_price']
    
    # Use current price if available, otherwise estimate
    if not current_price:
        is_jpy_pair = 'JPY' in instrument
        current_price = 150.0 if is_jpy_pair else 1.1000
    
    # Create reasonable high/low based on current price
    price_range = current_price * 0.03  # 3% range for swings
    
    fallback_swing = {
        'validated_highs': [
            {
                'price': current_price + (price_range * 0.8),
                'index': 30,
                'confidence': 1.0,
                'method': 'fallback'
            }
        ],
        'validated_lows': [
            {
                'price': current_price - (price_range * 0.8),
                'index': 15,
                'confidence': 1.0,
                'method': 'fallback'
            }
        ],
        'total_validated_swings': 2
    }
    
    return {
        'swing_analysis': fallback_swing,
        'fibonacci_swings': [],
        'success': False,
        'fallback': True,
        'message': f'Using fallback swing analysis for {instrument}'
    }

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
            'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 1.0],  # H1 levels (no 0.786)
            'high': high_price,
            'low': low_price,
            'direction': 'neutral',
            'current_retracement': 0.382,
            'key_level': 0.618,
            'mode': 'fixed',
            'detailed_levels': [
                {'ratio': r, 'price': high_price - ((high_price - low_price) * r), 'description': f'{r:.1%} Retracement'}
                for r in [0.0, 0.236, 0.382, 0.5, 0.618, 1.0]
            ],
            'swing_range_pips': int((high_price - low_price) * (10000 if 'JPY' not in instrument else 100))
        }
    else:  # mode == 'atr'
        # ATR mode with full levels and wider range
        price_range = current_price * 0.06  # 6% range
        high_price = current_price + (price_range * 0.8)
        low_price = current_price - (price_range * 0.2)
        
        return {
            'levels': [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0],  # All levels
            'high': high_price,
            'low': low_price,
            'direction': 'neutral',
            'current_retracement': 0.5,
            'key_level': 0.618,
            'mode': 'atr',
            'detailed_levels': [
                {'ratio': r, 'price': high_price - ((high_price - low_price) * r), 'description': f'{r:.1%} Retracement'}
                for r in [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
            ],
            'swing_range_pips': int((high_price - low_price) * (10000 if 'JPY' not in instrument else 100))
        }

# Removed old dual-mode fallback function - now using create_fallback_fibonacci_mode() for Fixed mode only

def generate_pair_analytics(instrument: str, timeframe: str = 'H1') -> Dict[str, Any]:
    """
    Generate comprehensive analytics for a single currency pair using centralized data retrieval
    """
    try:
        logger.info(f"Generating analytics for {instrument} {timeframe}")
        
        # GET ALL DATA ONCE - This is the key improvement
        price_data = get_tiered_price_data(instrument, timeframe)
        
        if price_data['total_candles'] == 0:
            logger.warning(f"No price data available for {instrument} {timeframe}")
            return create_error_analytics(instrument, f"No price data available for {timeframe}")
        
        # RUN ALL ANALYTICS WITH SAME DATA
        fibonacci_data = analyze_fibonacci_tiered(price_data)
        swing_data = analyze_swing_points_tiered(price_data)
        
        # Future analytics will use the same price_data:
        # rsi_data = analyze_rsi_tiered(price_data)
        # ma_data = analyze_moving_averages_tiered(price_data)
        # sentiment_data = analyze_sentiment_tiered(price_data)
        
        # Generate other analytics (using mock data for now - will be replaced with tiered analysis)
        current_price = price_data['current_price'] or 1.1000
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