"""
OANDA API Client - Single connection point for entire system
ARCHITECTURE COMPLIANCE:
- Maintains single OANDA API connection
- Handles all market data requests for 100+ Lambda strategies
- Implements rate limiting and error handling
- Provides connection health monitoring
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
import structlog
import httpx

from .config import Settings

logger = structlog.get_logger()


class OandaClient:
    """
    Single OANDA API client for entire LumiSignals system
    
    Key Features:
    - Single persistent connection
    - Rate limiting compliance
    - Automatic retry logic
    - Health monitoring
    - Error handling
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.get_oanda_base_url()
        
        # HTTP client with connection pooling
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {settings.parsed_oanda_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=60.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        
        # Connection state
        self.is_connected = False
        self.last_successful_request: Optional[datetime] = None
        self.connection_errors = 0
        self.total_requests = 0
        self.successful_requests = 0
        
        logger.info("OANDA client initialized", 
                   base_url=self.base_url,
                   environment=settings.oanda_environment)
    
    async def test_connection(self) -> bool:
        """Test OANDA API connection"""
        try:
            logger.info("🔗 Testing OANDA API connection...")
            
            # Simple account info request
            response = await self.client.get(f"/v3/accounts/{self.settings.oanda_account_id}")
            
            if response.status_code == 200:
                self.is_connected = True
                self.last_successful_request = datetime.now()
                logger.info("✅ OANDA API connection test successful")
                return True
            else:
                logger.error("❌ OANDA API connection test failed", 
                           status_code=response.status_code,
                           response=response.text)
                return False
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("❌ OANDA API connection test failed", error=str(e))
            return False
    
    async def get_candlesticks(self, instrument: str, granularity: str = "M2", count: int = None, from_time: str = None, to_time: str = None) -> Optional[Dict[str, Any]]:
        """
        Get candlestick data for a currency pair
        
        Args:
            instrument: Currency pair (e.g., 'EUR_USD')
            granularity: Timeframe (M2 for 2-minute candles)
            count: Number of candles to retrieve (default: 100 if no time range specified)
            from_time: ISO 8601 formatted start time (e.g., '2025-01-01T00:00:00.000000000Z')
            to_time: ISO 8601 formatted end time (optional, defaults to now)
        """
        try:
            self.total_requests += 1
            
            # Build request parameters
            params = {
                "granularity": granularity,
                "price": "M"  # Midpoint prices
            }
            
            # Use either count or time range (time range takes priority)
            if from_time:
                params["from"] = from_time
                if to_time:
                    params["to"] = to_time
                logger.info(f"📅 H1 API Request: {instrument} {granularity} from {from_time} to {to_time or 'now'}")
            else:
                # Default to count-based if no time range specified
                params["count"] = count if count is not None else 100
                logger.debug(f"Using count-based: {params['count']} candles")
            
            # Make API request with retry logic
            for attempt in range(self.settings.retry_attempts):
                try:
                    response = await self.client.get(
                        f"/v3/instruments/{instrument}/candles",
                        params=params
                    )
                    
                    if response.status_code == 200:
                        self.successful_requests += 1
                        self.last_successful_request = datetime.now()
                        data = response.json()
                        
                        candle_count = len(data.get('candles', []))
                        if granularity == "H1":
                            logger.info(f"✅ H1 API Response: {instrument} returned {candle_count} candles")
                        else:
                            logger.debug(f"Candlestick data retrieved for {instrument}",
                                       candles=candle_count,
                                       granularity=granularity)
                        
                        return data
                    
                    elif response.status_code == 429:  # Rate limited
                        logger.warning(f"Rate limited on attempt {attempt + 1} for {instrument}")
                        await asyncio.sleep(self.settings.retry_delay_seconds * (attempt + 1))
                        continue
                    
                    else:
                        logger.error(f"OANDA API error for {instrument}",
                                   status_code=response.status_code,
                                   response=response.text[:200])
                        break
                        
                except httpx.TimeoutException:
                    logger.warning(f"Timeout on attempt {attempt + 1} for {instrument}")
                    if attempt < self.settings.retry_attempts - 1:
                        await asyncio.sleep(self.settings.retry_delay_seconds)
                        continue
                    else:
                        raise
                
                except httpx.NetworkError as e:
                    logger.warning(f"Network error on attempt {attempt + 1} for {instrument}", error=str(e))
                    if attempt < self.settings.retry_attempts - 1:
                        await asyncio.sleep(self.settings.retry_delay_seconds * (attempt + 1))
                        continue
                    else:
                        raise
            
            # All attempts failed
            self.connection_errors += 1
            logger.error(f"All retry attempts failed for {instrument}")
            return None
            
        except Exception as e:
            self.connection_errors += 1
            logger.error(f"Candlestick data collection failed for {instrument}", error=str(e))
            return None
    
    async def get_current_prices(self, instruments: List[str]) -> Optional[Dict[str, Any]]:
        """Get current bid/ask prices for multiple instruments"""
        logger.info(f"🌐 Requesting current prices from OANDA for {len(instruments)} instruments")
        print(f"DEBUG: OANDA API call - get_current_prices for {len(instruments)} pairs")
        
        try:
            self.total_requests += 1
            
            # Build instruments parameter
            instruments_param = ",".join(instruments)
            logger.info(f"📡 OANDA API: GET /v3/accounts/{self.settings.oanda_account_id}/pricing")
            
            response = await self.client.get(
                f"/v3/accounts/{self.settings.oanda_account_id}/pricing",
                params={"instruments": instruments_param}
            )
            
            logger.info(f"📬 OANDA API Response: {response.status_code}")
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                data = response.json()
                
                prices_received = len(data.get('prices', []))
                logger.info(f"✅ OANDA: Retrieved pricing for {prices_received} instruments")
                
                # Log sample of what we received
                if data.get('prices'):
                    sample_price = data['prices'][0]
                    instrument = sample_price.get('instrument', 'unknown')
                    tradeable = sample_price.get('tradeable', False)
                    logger.info(f"📊 Sample: {instrument} tradeable={tradeable}")
                    if not tradeable:
                        logger.warning("⚠️ Markets appear to be closed - instruments marked as non-tradeable")
                        print("DEBUG: Markets are closed - OANDA returned non-tradeable instruments")
                
                return data
            else:
                logger.error(f"❌ OANDA API request failed: {response.status_code}")
                logger.error(f"Response: {response.text[:200]}")
                print(f"DEBUG: OANDA API error {response.status_code}: {response.text[:100]}")
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error(f"❌ OANDA connection failed: {str(e)}")
            print(f"DEBUG: OANDA exception: {str(e)}")
            return None
    
    async def get_account_summary(self) -> Optional[Dict[str, Any]]:
        """Get account summary for health monitoring"""
        try:
            response = await self.client.get(f"/v3/accounts/{self.settings.oanda_account_id}/summary")
            
            if response.status_code == 200:
                self.last_successful_request = datetime.now()
                return response.json()
            else:
                logger.error("Account summary request failed",
                           status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Account summary collection failed", error=str(e))
            return None
    
    async def get_connection_status(self) -> Dict[str, Any]:
        """Get connection status and health metrics"""
        success_rate = 0.0
        if self.total_requests > 0:
            success_rate = (self.successful_requests / self.total_requests) * 100
        
        return {
            "connected": self.is_connected,
            "base_url": self.base_url,
            "environment": self.settings.oanda_environment,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "connection_errors": self.connection_errors,
            "success_rate_percent": round(success_rate, 2),
            "last_successful_request": self.last_successful_request.isoformat() if self.last_successful_request else None,
            "account_id": self.settings.oanda_account_id,
            "architecture_role": "SINGLE_CONNECTION_POINT"
        }
    
    async def health_check(self) -> bool:
        """Perform health check"""
        try:
            # Simple ping with account summary
            account_data = await self.get_account_summary()
            
            if account_data and 'account' in account_data:
                self.is_connected = True
                return True
            else:
                self.is_connected = False
                return False
                
        except Exception as e:
            logger.error("OANDA health check failed", error=str(e))
            self.is_connected = False
            return False
    
    # =============================================================================
    # ACCOUNT DATA COLLECTION METHODS (for trade logging infrastructure)
    # =============================================================================
    
    async def get_open_trades(self) -> Optional[Dict[str, Any]]:
        """
        Get all open trades from OANDA with comprehensive data including:
        - takeProfitOrder and stopLossOrder details
        - Current market prices for pip calculations
        - Enhanced trade analysis
        """
        try:
            self.total_requests += 1
            logger.info("📊 Fetching comprehensive open trades data from OANDA...")
            
            # Get open trades
            response = await self.client.get(f"/v3/accounts/{self.settings.oanda_account_id}/openTrades")
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                trades_data = response.json()
                
                trades_count = len(trades_data.get('trades', []))
                logger.info(f"✅ Retrieved {trades_count} open trades from OANDA")
                
                # Enhance trades with current pricing and calculations
                if trades_count > 0:
                    enhanced_trades = await self._enhance_trades_with_calculations(trades_data)
                    return enhanced_trades
                else:
                    return trades_data
                    
            else:
                logger.error("Open trades request failed", status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Open trades collection failed", error=str(e))
            return None
    
    async def _enhance_trades_with_calculations(self, trades_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance trade data with current prices and comprehensive calculations
        """
        from .trade_calculations import enhance_trade_with_calculations, calculate_trade_duration
        
        trades = trades_data.get('trades', [])
        if not trades:
            return trades_data
        
        # Get all unique instruments for current pricing
        instruments = list(set(trade['instrument'] for trade in trades))
        logger.info(f"🔄 Getting current prices for {len(instruments)} instruments...")
        
        # Fetch current pricing data
        current_pricing = await self.get_account_pricing(instruments)
        
        # Build price lookup dictionary
        price_lookup = {}
        if current_pricing and current_pricing.get('prices'):
            for price_data in current_pricing['prices']:
                instrument = price_data['instrument']
                # Use mid price for calculations
                bid = float(price_data['bids'][0]['price'])
                ask = float(price_data['asks'][0]['price'])
                mid_price = (bid + ask) / 2
                price_lookup[instrument] = mid_price
        
        # Enhance each trade with calculations
        enhanced_trades = []
        for trade in trades:
            instrument = trade['instrument']
            current_price = price_lookup.get(instrument)
            
            if current_price:
                # Add comprehensive calculations
                enhanced_trade = enhance_trade_with_calculations(trade, current_price)
                
                # Add trade duration
                if trade.get('openTime'):
                    duration_data = calculate_trade_duration(trade['openTime'])
                    enhanced_trade.update({
                        'trade_duration': duration_data['duration_string'],
                        'duration_seconds': duration_data['duration_seconds']
                    })
                
                enhanced_trades.append(enhanced_trade)
                
                # Log enhanced trade details
                logger.info(f"📈 Enhanced Trade: {instrument} "
                          f"Entry: {trade.get('price')} → Current: {current_price:.5f} "
                          f"Pips: {enhanced_trade.get('pips_moved', 0):.1f} "
                          f"R:R: {enhanced_trade.get('risk_reward_ratio') or 'N/A'}")
            else:
                # Add trade without pricing enhancement
                logger.warning(f"⚠️ No current price available for {instrument}")
                enhanced_trades.append(trade)
        
        # Return enhanced data
        enhanced_data = trades_data.copy()
        enhanced_data['trades'] = enhanced_trades
        enhanced_data['enhancement_timestamp'] = datetime.now().isoformat()
        enhanced_data['enhanced_count'] = len([t for t in enhanced_trades if 'pips_moved' in t])
        
        logger.info(f"✅ Enhanced {enhanced_data['enhanced_count']}/{len(enhanced_trades)} trades with calculations")
        
        return enhanced_data
    
    async def get_closed_trades(self, from_time: Optional[str] = None, count: int = 500) -> Optional[Dict[str, Any]]:
        """Get closed trades from OANDA - matches Airtable Closed Trades table"""
        try:
            self.total_requests += 1
            logger.info("📊 Fetching closed trades from OANDA...")
            
            params = {
                "state": "CLOSED",
                "count": count
            }
            
            if from_time:
                params["fromTime"] = from_time
            
            response = await self.client.get(
                f"/v3/accounts/{self.settings.oanda_account_id}/trades",
                params=params
            )
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                data = response.json()
                
                trades_count = len(data.get('trades', []))
                logger.info(f"✅ Retrieved {trades_count} closed trades from OANDA")
                
                return data
            else:
                logger.error("Closed trades request failed", status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Closed trades collection failed", error=str(e))
            return None
    
    async def get_pending_orders(self) -> Optional[Dict[str, Any]]:
        """Get pending orders from OANDA - matches Airtable Pending Orders table"""
        try:
            self.total_requests += 1
            logger.info("📊 Fetching pending orders from OANDA...")
            
            response = await self.client.get(f"/v3/accounts/{self.settings.oanda_account_id}/pendingOrders")
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                data = response.json()
                
                orders_count = len(data.get('orders', []))
                logger.info(f"✅ Retrieved {orders_count} pending orders from OANDA")
                
                return data
            else:
                logger.error("Pending orders request failed", status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Pending orders collection failed", error=str(e))
            return None
    
    async def get_open_positions(self) -> Optional[Dict[str, Any]]:
        """Get open positions from OANDA - matches Airtable Currency Pair Positions table"""
        try:
            self.total_requests += 1
            logger.info("📊 Fetching open positions from OANDA...")
            
            response = await self.client.get(f"/v3/accounts/{self.settings.oanda_account_id}/openPositions")
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                data = response.json()
                
                positions_count = len(data.get('positions', []))
                logger.info(f"✅ Retrieved {positions_count} open positions from OANDA")
                
                return data
            else:
                logger.error("Open positions request failed", status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Open positions collection failed", error=str(e))
            return None
    
    async def get_transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Get specific transaction details - used for determining trade close reasons"""
        try:
            self.total_requests += 1
            
            response = await self.client.get(
                f"/v3/accounts/{self.settings.oanda_account_id}/transactions/{transaction_id}"
            )
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                return response.json()
            else:
                logger.error(f"Transaction {transaction_id} request failed", 
                           status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error(f"Transaction {transaction_id} collection failed", error=str(e))
            return None
    
    async def get_account_pricing(self, instruments: List[str]) -> Optional[Dict[str, Any]]:
        """Get current pricing for specific instruments - used for live P&L calculations"""
        try:
            self.total_requests += 1
            
            instruments_param = ",".join(instruments)
            response = await self.client.get(
                f"/v3/accounts/{self.settings.oanda_account_id}/pricing",
                params={"instruments": instruments_param}
            )
            
            if response.status_code == 200:
                self.successful_requests += 1
                self.last_successful_request = datetime.now()
                return response.json()
            else:
                logger.error("Account pricing request failed", status_code=response.status_code)
                return None
                
        except Exception as e:
            self.connection_errors += 1
            logger.error("Account pricing collection failed", error=str(e))
            return None
    
    async def get_all_account_data(self) -> Dict[str, Any]:
        """
        Collect all account data in one batch - comprehensive data collection
        This matches the complete Airtable data infrastructure
        """
        logger.info("🔄 Starting comprehensive account data collection...")
        
        # Collect all data concurrently for efficiency
        results = await asyncio.gather(
            self.get_account_summary(),
            self.get_open_trades(),
            self.get_pending_orders(), 
            self.get_open_positions(),
            return_exceptions=True
        )
        
        # Parse results
        account_summary, open_trades, pending_orders, open_positions = results
        
        # Get closed trades (separate call due to different parameters)
        closed_trades = await self.get_closed_trades(from_time="2025-06-01T00:00:00Z")
        
        # Get current pricing for all instruments with open trades/positions
        instruments = set()
        if isinstance(open_trades, dict) and open_trades.get('trades'):
            instruments.update(trade['instrument'] for trade in open_trades['trades'])
        if isinstance(open_positions, dict) and open_positions.get('positions'):
            instruments.update(pos['instrument'] for pos in open_positions['positions'])
        
        current_pricing = None
        if instruments:
            current_pricing = await self.get_account_pricing(list(instruments))
        
        # Compile comprehensive account data
        account_data = {
            "timestamp": datetime.now().isoformat(),
            "account_summary": account_summary if not isinstance(account_summary, Exception) else None,
            "open_trades": open_trades if not isinstance(open_trades, Exception) else None,
            "closed_trades": closed_trades,
            "pending_orders": pending_orders if not isinstance(pending_orders, Exception) else None,
            "open_positions": open_positions if not isinstance(open_positions, Exception) else None,
            "current_pricing": current_pricing,
            "collection_stats": {
                "open_trades_count": len(open_trades.get('trades', [])) if isinstance(open_trades, dict) else 0,
                "closed_trades_count": len(closed_trades.get('trades', [])) if isinstance(closed_trades, dict) else 0,
                "pending_orders_count": len(pending_orders.get('orders', [])) if isinstance(pending_orders, dict) else 0,
                "open_positions_count": len(open_positions.get('positions', [])) if isinstance(open_positions, dict) else 0,
                "pricing_instruments_count": len(current_pricing.get('prices', [])) if isinstance(current_pricing, dict) else 0
            }
        }
        
        total_items = sum(account_data["collection_stats"].values())
        logger.info(f"✅ Account data collection complete: {total_items} total items")
        
        return account_data

    async def close(self):
        """Close the OANDA client connection"""
        logger.info("Closing OANDA client connection")
        await self.client.aclose()
        self.is_connected = False
        logger.info("OANDA client connection closed")