#!/usr/bin/env python3
"""
OANDA API Utilities
Handles OANDA v20 API interactions
"""

import json
import urllib.request
import urllib.parse
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class OandaClient:
    """OANDA API client for v20 REST API"""
    
    def __init__(self, api_key: str, account_id: str, environment: str = 'practice'):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = "https://api-fxpractice.oanda.com" if environment == 'practice' else "https://api-fxtrade.oanda.com"
        self.headers = {'Authorization': f'Bearer {api_key}'}
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to OANDA API"""
        
        url = f"{self.base_url}{endpoint}"
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {self.api_key}')
        
        try:
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
        except Exception as e:
            logger.error(f"OANDA API request failed: {str(e)}")
            raise
    
    def get_account_summary(self) -> Dict[str, Any]:
        """Get account summary"""
        endpoint = f"/v3/accounts/{self.account_id}/summary"
        return self._make_request(endpoint)
    
    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Get all open trades"""
        endpoint = f"/v3/accounts/{self.account_id}/openTrades"
        data = self._make_request(endpoint)
        return data.get('trades', [])
    
    def get_closed_trades(self, from_time: datetime, to_time: datetime, count: int = 500) -> List[Dict[str, Any]]:
        """Get closed trades within a time range"""
        endpoint = f"/v3/accounts/{self.account_id}/trades"
        params = {
            'state': 'CLOSED',
            'fromTime': from_time.strftime('%Y-%m-%dT%H:%M:%S.000000000Z'),
            'toTime': to_time.strftime('%Y-%m-%dT%H:%M:%S.000000000Z'),
            'count': count
        }
        data = self._make_request(endpoint, params)
        return data.get('trades', [])
    
    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get all pending orders"""
        endpoint = f"/v3/accounts/{self.account_id}/pendingOrders"
        data = self._make_request(endpoint)
        return data.get('orders', [])
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions (aggregated by instrument)"""
        endpoint = f"/v3/accounts/{self.account_id}/openPositions"
        data = self._make_request(endpoint)
        return data.get('positions', [])
    
    def get_pricing(self, instruments: List[str]) -> Dict[str, float]:
        """Get current pricing for instruments"""
        endpoint = f"/v3/accounts/{self.account_id}/pricing"
        params = {'instruments': ','.join(instruments)}
        data = self._make_request(endpoint, params)
        
        prices = {}
        for price_data in data.get('prices', []):
            instrument = price_data.get('instrument')
            # Use mid price (average of bid and ask)
            bids = price_data.get('bids', [])
            asks = price_data.get('asks', [])
            if bids and asks:
                bid = float(bids[0]['price'])
                ask = float(asks[0]['price'])
                prices[instrument] = (bid + ask) / 2
        
        return prices
    
    def get_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """Get details of a specific transaction"""
        endpoint = f"/v3/accounts/{self.account_id}/transactions/{transaction_id}"
        data = self._make_request(endpoint)
        return data.get('transaction', {})
    
    def get_candles(self, instrument: str, granularity: str = 'M5', count: int = 100) -> List[Dict[str, Any]]:
        """Get historical candles for an instrument"""
        endpoint = f"/v3/instruments/{instrument}/candles"
        params = {
            'granularity': granularity,
            'count': count,
            'price': 'MBA'  # Mid, Bid, Ask
        }
        data = self._make_request(endpoint, params)
        return data.get('candles', [])

def fetch_all_oanda_data(api_key: str, account_id: str, environment: str = 'practice') -> Dict[str, Any]:
    """Fetch all relevant data from OANDA for sync"""
    
    client = OandaClient(api_key, account_id, environment)
    
    logger.info("🔄 Fetching all OANDA data...")
    
    # Get account summary
    account = client.get_account_summary()
    logger.info(f"💰 Account balance: {account.get('account', {}).get('balance', 'N/A')}")
    
    # Get all open trades
    trades = client.get_open_trades()
    logger.info(f"📊 Open trades: {len(trades)}")
    
    # Get pending orders
    orders = client.get_pending_orders()
    logger.info(f"⏳ Pending orders: {len(orders)}")
    
    # Get open positions
    positions = client.get_positions()
    logger.info(f"💱 Open positions: {len(positions)}")
    
    # Get current prices for all instruments
    all_instruments = set()
    
    # Collect instruments from trades
    for trade in trades:
        instrument = trade.get('instrument', '')
        if instrument:
            all_instruments.add(instrument)
    
    # Collect instruments from orders
    for order in orders:
        instrument = order.get('instrument', '')
        if instrument:
            all_instruments.add(instrument)
    
    # Collect instruments from positions
    for position in positions:
        instrument = position.get('instrument', '')
        if instrument:
            all_instruments.add(instrument)
    
    # Get current prices
    prices = {}
    if all_instruments:
        prices = client.get_pricing(list(all_instruments))
        logger.info(f"💹 Retrieved prices for {len(prices)} instruments")
    
    return {
        'account': account,
        'trades': trades,
        'orders': orders,
        'positions': positions,
        'prices': prices
    }

def get_instrument_precision(instrument: str) -> int:
    """Get the precision (decimal places) for an instrument"""
    
    if 'JPY' in instrument:
        return 3  # JPY pairs use 3 decimal places
    else:
        return 5  # Most other pairs use 5 decimal places

def format_units(units: float) -> int:
    """Format units for display (remove decimals)"""
    return int(abs(units))

def parse_oanda_timestamp(timestamp: str) -> datetime:
    """Parse OANDA timestamp to datetime object"""
    
    try:
        # OANDA uses RFC3339 format
        from dateutil import parser
        return parser.parse(timestamp)
    except Exception as e:
        logger.error(f"Failed to parse timestamp {timestamp}: {e}")
        return datetime.now(timezone.utc)