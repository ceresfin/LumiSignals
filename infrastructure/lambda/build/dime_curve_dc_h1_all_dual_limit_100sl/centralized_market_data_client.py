#!/usr/bin/env python3
"""
LumiSignals Centralized Market Data Client
==========================================

Client library for strategies and dashboard to access centralized market data
from the Phase 3 Central Data Collector with Redis hot storage and PostgreSQL
warm storage fallback.

Features:
- Sub-second access to market data via internal Lambda invocation
- Automatic fallback: Redis → PostgreSQL → OANDA API
- Caching to minimize inter-Lambda calls
- Support for both prices and candlesticks
"""

import json
import boto3
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class CentralizedMarketDataClient:
    """Client for accessing centralized market data from Phase 3 collector"""
    
    def __init__(self, lambda_client=None):
        """Initialize market data client
        
        Args:
            lambda_client: Boto3 Lambda client (will create if not provided)
        """
        self.lambda_client = lambda_client or boto3.client('lambda')
        self.collector_function_name = os.environ.get(
            'CENTRAL_COLLECTOR_FUNCTION',
            'lumisignals-central-data-collector'
        )
        
        # Local cache for reducing Lambda calls
        self._price_cache = {}
        self._candlestick_cache = {}
        self._cache_timestamp = None
        self._cache_ttl_seconds = 60  # 1 minute local cache
        
    def _is_cache_valid(self) -> bool:
        """Check if local cache is still valid"""
        if not self._cache_timestamp:
            return False
        
        age = (datetime.now(timezone.utc) - self._cache_timestamp).total_seconds()
        return age < self._cache_ttl_seconds
    
    def _invoke_collector(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Invoke the central data collector Lambda function
        
        Args:
            path: API path (e.g., '/market-data', '/candlesticks')
            params: Optional query parameters
            
        Returns:
            Response data from collector
        """
        try:
            # Build payload
            payload = {
                'path': path,
                'httpMethod': 'GET',
                'queryStringParameters': params or {}
            }
            
            # Invoke Lambda function
            response = self.lambda_client.invoke(
                FunctionName=self.collector_function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )
            
            # Parse response
            result = json.loads(response['Payload'].read())
            
            if result.get('statusCode') == 200:
                body = json.loads(result.get('body', '{}'))
                return body
            else:
                logger.error(f"Collector returned error: {result}")
                return {}
                
        except Exception as e:
            logger.error(f"Failed to invoke collector: {e}")
            return {}
    
    def get_market_prices(self, use_cache: bool = True) -> Dict[str, Any]:
        """Get current market prices for all forex pairs
        
        Args:
            use_cache: Whether to use local cache (default: True)
            
        Returns:
            Dict with 'prices' containing price data for each pair
        """
        # Check local cache first
        if use_cache and self._is_cache_valid() and self._price_cache:
            logger.info("Using local cache for market prices")
            return {
                'prices': self._price_cache,
                'lastUpdate': self._cache_timestamp.isoformat(),
                'source': 'local_cache',
                'cache_status': 'local_hit'
            }
        
        # Fetch from central collector
        logger.info("Fetching market prices from central collector")
        data = self._invoke_collector('/market-data')
        
        if data and 'prices' in data:
            # Update local cache
            self._price_cache = data['prices']
            self._cache_timestamp = datetime.now(timezone.utc)
            
            # Add cache info to response
            data['local_cache_updated'] = True
            
        return data
    
    def get_candlesticks(self, timeframe: str = 'H1', use_cache: bool = True) -> Dict[str, Any]:
        """Get candlestick data for all forex pairs
        
        Args:
            timeframe: Candlestick timeframe (default: 'H1')
            use_cache: Whether to use local cache (default: True)
            
        Returns:
            Dict with 'data' containing candlestick arrays for each pair
        """
        # Check local cache first
        cache_key = f"candles_{timeframe}"
        if use_cache and self._is_cache_valid() and cache_key in self._candlestick_cache:
            logger.info(f"Using local cache for {timeframe} candlesticks")
            return {
                'data': self._candlestick_cache[cache_key],
                'timeframe': timeframe,
                'lastUpdate': self._cache_timestamp.isoformat(),
                'source': 'local_cache',
                'cache_status': 'local_hit'
            }
        
        # Fetch from central collector
        logger.info(f"Fetching {timeframe} candlesticks from central collector")
        data = self._invoke_collector('/candlesticks', {'timeframe': timeframe})
        
        if data and 'data' in data:
            # Update local cache
            self._candlestick_cache[cache_key] = data['data']
            self._cache_timestamp = datetime.now(timezone.utc)
            
            # Add cache info to response
            data['local_cache_updated'] = True
            
        return data
    
    def get_price_for_pair(self, instrument: str) -> Optional[Dict[str, Any]]:
        """Get price data for a specific instrument
        
        Args:
            instrument: Forex pair (e.g., 'EUR_USD')
            
        Returns:
            Price data dict or None if not found
        """
        data = self.get_market_prices()
        prices = data.get('prices', {})
        
        if instrument in prices:
            return {
                'instrument': instrument,
                **prices[instrument],
                'source': data.get('source', 'unknown'),
                'lastUpdate': data.get('lastUpdate')
            }
        
        return None
    
    def get_candlesticks_for_pair(self, instrument: str, timeframe: str = 'H1') -> Optional[List[Dict]]:
        """Get candlestick data for a specific instrument
        
        Args:
            instrument: Forex pair (e.g., 'EUR_USD')
            timeframe: Candlestick timeframe (default: 'H1')
            
        Returns:
            List of candlestick dicts or None if not found
        """
        data = self.get_candlesticks(timeframe)
        candles = data.get('data', {})
        
        return candles.get(instrument)
    
    def get_collector_health(self) -> Dict[str, Any]:
        """Get health status of the central data collector
        
        Returns:
            Health status including Redis and PostgreSQL connectivity
        """
        return self._invoke_collector('/health')
    
    def store_trade_metadata(self, metadata: Dict[str, Any]) -> bool:
        """Store trade metadata to centralized system
        
        Args:
            metadata: Trade metadata including strategy info
            
        Returns:
            Success status
        """
        try:
            # Import Redis integration for actual storage
            import sys
            sys.path.append('/opt/python')  # Lambda layer path
            from redis_integration import RedisTradeWriter
            
            # Create Redis writer
            redis_writer = RedisTradeWriter()
            
            # Convert metadata to signal format for Redis storage
            signal_data = {
                'signal_id': metadata.get('order_id', ''),
                'instrument': metadata.get('instrument', 'UNKNOWN'),
                'action': metadata.get('action', 'UNKNOWN'),
                'order_type': metadata.get('order_type', 'LIMIT'),
                'entry_price': metadata.get('entry_price', 0.0),
                'stop_loss': metadata.get('stop_loss', 0.0),  # Critical: SL field
                'take_profit': metadata.get('take_profit', 0.0),  # Critical: TP field
                'risk_amount': metadata.get('risk_amount', 0.0),
                'rr_ratio': metadata.get('rr_ratio', 0.0),
                'confidence': metadata.get('signal_confidence', 0),
                'reasoning': metadata.get('reasoning', [])
            }
            
            strategy_name = metadata.get('strategy_name', 'unknown_strategy')
            
            # Store signal to Redis with SL/TP preserved
            success = redis_writer.write_trade_signal(signal_data, strategy_name)
            
            # CRITICAL: Also store direct trade_id mapping for closed trades lookup
            if success and metadata.get('order_id'):
                try:
                    # Store direct mapping: trade_id -> SL/TP + account/margin data
                    trade_mapping_key = f"trade:sl_tp:{metadata.get('order_id')}"
                    trade_sl_tp_data = {
                        'trade_id': metadata.get('order_id'),
                        'stop_loss': signal_data['stop_loss'],
                        'take_profit': signal_data['take_profit'],
                        'instrument': signal_data['instrument'],
                        'strategy': strategy_name,
                        'entry_price': signal_data['entry_price'],
                        'account_balance_before': metadata.get('account_balance_before'),  # Added
                        'margin_used': metadata.get('margin_used'),  # Added
                        'timestamp': metadata.get('timestamp')
                    }
                    
                    # Store with 30-day expiry (longer than Redis TTL for trades)
                    redis_writer.redis_client.setex(
                        trade_mapping_key, 
                        2592000,  # 30 days in seconds
                        json.dumps(trade_sl_tp_data, default=str)
                    )
                    
                    logger.info(f"✅ Trade SL/TP mapping stored: {trade_mapping_key}")
                    
                except Exception as e:
                    logger.error(f"Failed to store trade SL/TP mapping: {str(e)}")
            
            if success:
                logger.info(f"✅ Trade metadata stored to Redis: {strategy_name} - SL: {signal_data['stop_loss']}, TP: {signal_data['take_profit']}")
            else:
                logger.error(f"Failed to store trade metadata to Redis")
            
            redis_writer.close()
            return success
            
        except Exception as e:
            logger.error(f"Failed to store trade metadata: {e}")
            return False


# Convenience functions for strategies
def get_current_price(instrument: str) -> Optional[float]:
    """Quick helper to get current price for an instrument
    
    Args:
        instrument: Forex pair (e.g., 'EUR_USD')
        
    Returns:
        Current price as float or None
    """
    client = CentralizedMarketDataClient()
    price_data = client.get_price_for_pair(instrument)
    
    return price_data['price'] if price_data else None


def get_price_with_spread(instrument: str) -> Optional[Dict[str, float]]:
    """Get bid, ask, and spread for an instrument
    
    Args:
        instrument: Forex pair (e.g., 'EUR_USD')
        
    Returns:
        Dict with 'bid', 'ask', 'spread' or None
    """
    client = CentralizedMarketDataClient()
    price_data = client.get_price_for_pair(instrument)
    
    if price_data:
        return {
            'bid': price_data['bid'],
            'ask': price_data['ask'],
            'spread': price_data['spread']
        }
    
    return None