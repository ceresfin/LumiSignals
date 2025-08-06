#!/usr/bin/env python3
"""
Enhanced OANDA Data Collection for Fargate Data Orchestrator
Collects ALL 31 Airtable fields directly from OANDA API to populate RDS

This enhanced version grabs everything possible from OANDA instead of calculating it ourselves:
- All trade fields from /v3/accounts/{account_id}/openTrades
- Current pricing from /v3/accounts/{account_id}/pricing  
- Account info from /v3/accounts/{account_id}
- Position details from /v3/accounts/{account_id}/openPositions
- Transaction history for strategy identification
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import pytz

from .strategy_mapper import StrategyMapper

logger = logging.getLogger(__name__)

class EnhancedOandaDataCollector:
    """Enhanced OANDA data collection for complete trade information"""
    
    def __init__(self, oanda_client):
        self.client = oanda_client
        self.strategy_mapper = StrategyMapper()  # Initialize strategy mapper
        self.redis_manager = None  # Will be injected if available
        self._data_came_from_redis = False  # Track if current data came from Redis
        
        # Eastern timezone
        self.eastern_tz = pytz.timezone('US/Eastern')
        
        # Market sessions in UTC (forex market hours)
        self.market_sessions = {
            'SYDNEY': {'start': 22, 'end': 7},     # 22:00 - 07:00 UTC (5pm-2am ET)
            'TOKYO': {'start': 0, 'end': 9},       # 00:00 - 09:00 UTC (7pm-4am ET)  
            'LONDON': {'start': 8, 'end': 17},     # 08:00 - 17:00 UTC (3am-12pm ET)
            'NEW_YORK': {'start': 13, 'end': 21}   # 13:00 - 21:00 UTC (8am-5pm ET)
        }
    
    def _determine_data_source(self) -> str:
        """Determine the appropriate data_source value based on data origin"""
        if self._data_came_from_redis:
            return 'REDIS_FARGATE_RDS'
        else:
            return 'OANDA_FARGATE_RDS'
    
    def _convert_to_eastern(self, utc_dt: datetime) -> datetime:
        """Convert UTC datetime to Eastern Time"""
        if utc_dt.tzinfo is None:
            # Make timezone aware if naive
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        return utc_dt.astimezone(self.eastern_tz)
    
    def _format_eastern_time(self, utc_dt: datetime) -> str:
        """Format datetime in Eastern Time with timezone abbreviation"""
        eastern_dt = self._convert_to_eastern(utc_dt)
        # Get timezone abbreviation (EST/EDT)
        tz_abbr = eastern_dt.strftime('%Z')
        return f"{eastern_dt.strftime('%Y-%m-%d %H:%M:%S')} {tz_abbr}"
    
    def _format_eastern_timestamp(self, eastern_dt: datetime) -> str:
        """Format Eastern datetime for database storage - show as Eastern Time"""
        # Return timezone-naive string - PostgreSQL will display without conversion
        # This shows the actual Eastern time without UTC conversion
        return eastern_dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    
    async def collect_comprehensive_trade_data(self) -> Optional[Dict[str, Any]]:
        """
        Collect ALL trade data needed for 31 Airtable fields
        
        Returns complete trade data including:
        - All OANDA trade fields
        - Current pricing and calculations  
        - Market session information
        - Strategy identification
        - Enhanced metadata
        """
        try:
            logger.info("🚀 Starting comprehensive OANDA data collection...")
            
            # Step 1: Get all open trades with full details
            trades_response = await self._get_detailed_open_trades()
            if not trades_response:
                return None
            
            # Step 2: Get current account information
            account_info = await self._get_account_info()
            
            # Step 3: Get current pricing for all instruments
            instruments = self._extract_instruments_from_trades(trades_response.get('trades', []))
            current_pricing = await self._get_current_pricing(instruments)
            
            # Step 4: Get position information
            positions_info = await self._get_positions_info()
            
            # Step 5: Enhance each trade with comprehensive data
            enhanced_trades = await self._enhance_trades_comprehensively(
                trades_response, account_info, current_pricing, positions_info
            )
            
            logger.info(f"✅ Comprehensive data collection completed for {len(enhanced_trades.get('trades', []))} trades")
            return enhanced_trades
            
        except Exception as e:
            logger.error(f"❌ Comprehensive data collection failed: {str(e)}", exc_info=True)
            return None
    
    async def _get_detailed_open_trades(self) -> Optional[Dict[str, Any]]:
        """Get all open trades with complete OANDA details"""
        try:
            data = await self.client.get_open_trades()
            if data:
                logger.info(f"📊 Retrieved {len(data.get('trades', []))} open trades from OANDA")
                return data
            else:
                logger.error("Failed to get open trades")
                return None
                
        except Exception as e:
            logger.error(f"Error getting detailed open trades: {str(e)}")
            return None
    
    async def _get_account_info(self) -> Optional[Dict[str, Any]]:
        """Get current account information including balance"""
        try:
            data = await self.client.get_account_summary()
            if data:
                logger.info("📊 Retrieved account information")
                return data
            else:
                logger.error("Failed to get account info")
                return None
                
        except Exception as e:
            logger.error(f"Error getting account info: {str(e)}")
            return None
    
    async def _get_current_pricing(self, instruments: List[str]) -> Optional[Dict[str, Any]]:
        """Get current pricing for all trade instruments"""
        if not instruments:
            return None
            
        try:
            pricing_data = await self.client.get_account_pricing(instruments)
            if pricing_data:
                logger.info(f"📊 Retrieved pricing for {len(instruments)} instruments")
                return pricing_data
            else:
                logger.error("Failed to get pricing")
                return None
                
        except Exception as e:
            logger.error(f"Error getting current pricing: {str(e)}")
            return None
    
    async def _get_positions_info(self) -> Optional[Dict[str, Any]]:
        """Get open positions information"""
        try:
            positions_data = await self.client.get_open_positions()
            if positions_data:
                logger.info(f"📊 Retrieved {len(positions_data.get('positions', []))} positions")
                return positions_data
            else:
                logger.error("Failed to get positions")
                return None
                
        except Exception as e:
            logger.error(f"Error getting positions info: {str(e)}")
            return None
    
    def _extract_instruments_from_trades(self, trades: List[Dict[str, Any]]) -> List[str]:
        """Extract unique instruments from trades"""
        return list(set(trade.get('instrument', '') for trade in trades if trade.get('instrument')))
    
    async def _enhance_trades_comprehensively(self, trades_response: Dict[str, Any], 
                                            account_info: Optional[Dict[str, Any]],
                                            current_pricing: Optional[Dict[str, Any]],
                                            positions_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Enhance trades with ALL 31 Airtable fields using OANDA data
        
        Maps to Airtable columns:
        1. OANDA Order ID → trade['id'] 
        2. Trade ID → trade['id']
        3. Order Time → trade['openTime'] 
        4. Fill Time → trade['openTime']
        5. Pending Duration → 0 (immediate fills)
        6. Active Trade Duration → calculated from openTime
        7. Instrument → trade['instrument']
        8. Direction → based on trade['currentUnits'] 
        9. Strategy → inferred from trade metadata/tags
        10. Margin Used → trade['marginUsed']
        11. Order Type → 'Market Order' (post-fill data)
        12. Units → trade['currentUnits']
        13. Entry Price → trade['price']
        14. Current Price → from pricing API
        15. Exit Price → null (for open trades)
        16. Unrealized PnL → trade['unrealizedPL']
        17. Stop Loss → trade['stopLossOrder']['price']
        18. Take Profit → trade['takeProfitOrder']['price'] 
        19. Potential Risk Amount → calculated from SL
        20. Potential Profit ($) → calculated from TP
        21. Return over Risk Ratio → Profit/Risk ratio
        22. Exit Time → null (for open trades)
        23. Realized PnL → null (for open trades)  
        24. Trade State → 'OPEN'
        25. Spread → from pricing data (ask - bid)
        26. Account Balance Before → account['balance']
        27. Market Session → calculated from time
        28. Momentum Strength → from strategy logic
        29. Analysis Type → from strategy logic
        30. Current Time → real-time timestamp
        31. Distance to Entry → calculated pips moved
        """
        
        trades = trades_response.get('trades', [])
        if not trades:
            return trades_response
        
        # Create pricing lookup
        pricing_lookup = self._create_pricing_lookup(current_pricing)
        
        # DEBUG: Print OANDA account info structure to see all available fields
        if account_info:
            logger.info(f"🔍 OANDA Account Info Structure: {json.dumps(account_info, indent=2)}")
        
        # Current account balance from OANDA account summary
        account_balance = 0.0
        if account_info and 'account' in account_info:
            # OANDA returns account data nested under 'account' key
            account_data = account_info['account']
            balance_str = account_data.get('balance', '0')
            try:
                account_balance = float(balance_str)
                logger.info(f"✅ Retrieved account balance: ${account_balance:,.2f}")
            except (ValueError, TypeError):
                logger.warning(f"⚠️  Could not parse account balance: {balance_str}")
                account_balance = 0.0
        elif account_info:
            # Try direct access if not nested
            balance_str = account_info.get('balance', '0')
            try:
                account_balance = float(balance_str)
                logger.info(f"✅ Retrieved account balance (direct): ${account_balance:,.2f}")
            except (ValueError, TypeError):
                logger.warning(f"⚠️  Could not parse account balance (direct): {balance_str}")
                account_balance = 0.0
        else:
            logger.warning("⚠️  No account info available for balance")
        
        # Current timestamp in Eastern Time
        current_time_utc = datetime.now(timezone.utc)
        current_time = self._convert_to_eastern(current_time_utc)
        
        enhanced_trades = []
        
        for trade in trades:
            try:
                # Extract basic OANDA fields
                trade_id = trade.get('id', '')
                instrument = trade.get('instrument', '')
                current_units = float(trade.get('currentUnits', 0))
                entry_price = float(trade.get('price', 0))
                unrealized_pl = float(trade.get('unrealizedPL', 0))
                margin_used = float(trade.get('marginUsed', 0))
                open_time_str = trade.get('openTime', '')
                
                # Parse open time and convert to Eastern
                open_time_utc = self._parse_oanda_time(open_time_str) if open_time_str else current_time
                open_time = self._convert_to_eastern(open_time_utc)
                
                # Direction based on units
                direction = 'Long' if current_units > 0 else 'Short'
                
                # Get current price
                current_price = pricing_lookup.get(instrument, {}).get('mid', entry_price)
                
                # Get spread
                pricing_data = pricing_lookup.get(instrument, {})
                spread = pricing_data.get('spread', 0.0)
                
                # Extract stop loss and take profit
                stop_loss_price = None
                take_profit_price = None
                
                if 'stopLossOrder' in trade and trade['stopLossOrder']:
                    stop_loss_price = float(trade['stopLossOrder'].get('price', 0))
                
                if 'takeProfitOrder' in trade and trade['takeProfitOrder']:
                    take_profit_price = float(trade['takeProfitOrder'].get('price', 0))
                
                # Calculate durations (both times now in Eastern)
                active_duration = self._calculate_duration(open_time, current_time)
                
                # DEBUG: Print OANDA trade structure to see all available fields
                logger.info(f"🔍 OANDA Trade Structure for {trade_id}: {json.dumps(trade, indent=2)}")
                
                # Get Distance to Entry from OANDA's unrealizedPL (more accurate than calculation)
                # OANDA calculates P&L based on actual pip movement including spread
                
                # Try to get OANDA's direct distance field first
                distance_to_entry = None
                for field_name in ['distanceToEntry', 'distance_to_entry', 'pipsFromEntry', 'pips_from_entry']:
                    if field_name in trade:
                        distance_to_entry = trade.get(field_name)
                        logger.info(f"✅ Found OANDA Distance Field '{field_name}': {distance_to_entry}")
                        break
                
                if distance_to_entry is not None:
                    # OANDA provides direct distance field
                    pips_moved = float(distance_to_entry)
                    logger.info(f"✅ Using OANDA Distance to Entry: {pips_moved} pips for trade {trade_id}")
                elif unrealized_pl != 0:
                    # Use OANDA's P&L to reverse-calculate pips (more accurate)
                    # This accounts for OANDA's exact pip calculations and spread
                    pip_value = self._get_pip_value_for_instrument(instrument, abs(current_units))
                    if pip_value > 0:
                        # Calculate pips from P&L (accounts for position direction)
                        pips_moved = unrealized_pl / pip_value
                        if direction.lower() in ['short', 'sell']:
                            pips_moved = -pips_moved  # Flip for short positions
                        pips_moved = round(pips_moved, 1)
                        logger.info(f"💰 Using OANDA P&L to calculate pips: {pips_moved} pips (P&L: ${unrealized_pl}) for trade {trade_id}")
                    else:
                        # Fallback to price calculation
                        pips_moved = self._calculate_pips_moved(entry_price, current_price, instrument, direction)
                        logger.info(f"📊 Fallback calculated pips: {pips_moved} pips for trade {trade_id}")
                else:
                    # Fallback to calculation if no P&L available
                    pips_moved = self._calculate_pips_moved(entry_price, current_price, instrument, direction)
                    logger.info(f"📊 Calculated pips moved: {pips_moved} pips for trade {trade_id}")
                
                # Calculate risk/reward amounts
                risk_amount, profit_amount, rr_ratio = self._calculate_risk_reward(
                    entry_price, stop_loss_price, take_profit_price, abs(current_units), direction, instrument
                )
                
                # Determine market session based on when the trade was opened (use UTC for session logic)
                market_session = self._get_market_session(open_time_utc)
                
                # Strategy identification (enhanced logic)
                strategy_name = self._identify_strategy(trade, current_units, instrument)
                
                # Create comprehensive enhanced trade
                enhanced_trade = {
                    # Basic OANDA fields (1-16)
                    'trade_id': trade_id,
                    'instrument': instrument,
                    'units': int(current_units),
                    'current_units': int(current_units),
                    'price': entry_price,  # Entry price
                    'current_price': current_price,
                    'entry_price': entry_price,
                    'unrealized_pl': unrealized_pl,
                    'margin_used': margin_used,
                    'open_time': self._format_eastern_timestamp(open_time),
                    'state': 'OPEN',
                    'direction': direction,
                    
                    # Stop Loss & Take Profit (17-18)
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    
                    # Calculated fields (19-31)
                    'potential_risk_amount': risk_amount,
                    'potential_profit_amount': profit_amount,
                    'risk_reward_ratio': rr_ratio,
                    'realized_pnl': None,  # Open trades don't have realized P&L
                    'exit_price': None,    # Open trades don't have exit price
                    'exit_time': None,     # Open trades don't have exit time
                    'spread': spread,
                    'account_balance_before': account_balance,
                    'market_session': market_session,
                    'strategy': strategy_name,
                    'order_type': self._determine_order_type(trade, strategy_name),
                    'pips_moved': pips_moved,
                    'distance_to_entry': pips_moved,  # OANDA's Distance to Entry field
                    'oanda_distance_to_entry': distance_to_entry,  # Raw OANDA value if available
                    
                    # Duration calculations
                    'active_trade_duration': active_duration,
                    'pending_duration': 0,  # Immediate market fills
                    
                    # Analysis fields (strategy-dependent)
                    'momentum_strength': self._calculate_momentum_strength(pips_moved, unrealized_pl),
                    'analysis_type': self._determine_analysis_type(strategy_name),
                    
                    # Timestamps (all in Eastern Time)
                    'order_time': self._format_eastern_timestamp(open_time),
                    'fill_time': self._format_eastern_timestamp(open_time),
                    'current_time': self._format_eastern_timestamp(current_time),
                    
                    # Additional OANDA metadata
                    'financing': float(trade.get('financing', 0)),
                    'commission': float(trade.get('commission', 0)),
                    'initial_units': int(trade.get('initialUnits', current_units)),
                    
                    # Enhancement metadata
                    'data_source': self._determine_data_source(),
                    'enhancement_timestamp': self._format_eastern_timestamp(current_time),
                    'oanda_raw_data': trade  # Keep original for debugging
                }
                
                enhanced_trades.append(enhanced_trade)
                
            except Exception as e:
                logger.error(f"Error enhancing trade {trade.get('id', 'unknown')}: {str(e)}")
                # Add basic trade data even if enhancement fails
                enhanced_trades.append({
                    'trade_id': trade.get('id', ''),
                    'instrument': trade.get('instrument', ''),
                    'units': int(trade.get('currentUnits', 0)),
                    'price': float(trade.get('price', 0)),
                    'unrealized_pl': float(trade.get('unrealizedPL', 0)),
                    'state': 'OPEN',
                    'error': f'Enhancement failed: {str(e)}'
                })
        
        # Return enhanced response
        enhanced_response = trades_response.copy()
        enhanced_response['trades'] = enhanced_trades
        enhanced_response['enhancement_metadata'] = {
            'enhanced_at': self._format_eastern_timestamp(current_time),
            'account_balance': account_balance,
            'total_trades_enhanced': len(enhanced_trades),
            'pricing_instruments': len(pricing_lookup),
            'market_session': self._get_market_session(current_time_utc)
        }
        
        return enhanced_response
    
    def _create_pricing_lookup(self, current_pricing: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """Create instrument → pricing data lookup"""
        pricing_lookup = {}
        
        if not current_pricing or 'prices' not in current_pricing:
            return pricing_lookup
        
        for price_data in current_pricing['prices']:
            instrument = price_data.get('instrument', '')
            if not instrument:
                continue
                
            try:
                bid = float(price_data['bids'][0]['price'])
                ask = float(price_data['asks'][0]['price'])
                mid = (bid + ask) / 2
                spread = ask - bid
                
                pricing_lookup[instrument] = {
                    'bid': bid,
                    'ask': ask,
                    'mid': mid,
                    'spread': spread
                }
                
            except (KeyError, IndexError, ValueError) as e:
                logger.warning(f"Failed to parse pricing for {instrument}: {str(e)}")
        
        return pricing_lookup
    
    def _parse_oanda_time(self, time_str: str) -> datetime:
        """Parse OANDA timestamp format"""
        try:
            # OANDA format: 2023-07-28T19:30:45.123456789Z
            if time_str.endswith('Z'):
                time_str = time_str[:-1] + '+00:00'
            return datetime.fromisoformat(time_str)
        except Exception:
            return datetime.now(timezone.utc)
    
    def _calculate_duration(self, start_time: datetime, end_time: datetime) -> int:
        """Calculate duration in minutes"""
        return int((end_time - start_time).total_seconds() / 60)
    
    def _calculate_pips_moved(self, entry_price: float, current_price: float, instrument: str, direction: str) -> float:
        """Calculate pips moved using existing logic"""
        if not current_price or not entry_price:
            return 0.0
            
        # Pip values for different instrument types
        pip_values = {
            # Major pairs (4 decimal places)
            'EUR_USD': 0.0001, 'GBP_USD': 0.0001, 'USD_CHF': 0.0001, 'USD_CAD': 0.0001,
            'AUD_USD': 0.0001, 'NZD_USD': 0.0001, 'EUR_GBP': 0.0001, 'EUR_CHF': 0.0001,
            'GBP_CHF': 0.0001, 'EUR_CAD': 0.0001, 'GBP_CAD': 0.0001, 'AUD_CAD': 0.0001,
            'EUR_AUD': 0.0001, 'GBP_AUD': 0.0001, 'EUR_NZD': 0.0001, 'GBP_NZD': 0.0001,
            'AUD_NZD': 0.0001, 'CAD_CHF': 0.0001, 'AUD_CHF': 0.0001, 'NZD_CHF': 0.0001,
            # Yen pairs (2 decimal places)
            'USD_JPY': 0.01, 'EUR_JPY': 0.01, 'GBP_JPY': 0.01, 'CHF_JPY': 0.01,
            'CAD_JPY': 0.01, 'AUD_JPY': 0.01, 'NZD_JPY': 0.01
        }
        
        pip_value = pip_values.get(instrument, 0.0001)
        price_difference = current_price - entry_price
        
        # For short positions, flip the sign
        if direction.lower() in ['short', 'sell']:
            price_difference = -price_difference
        
        return round(price_difference / pip_value, 1)
    
    def _get_pip_value_for_instrument(self, instrument: str, units: float) -> float:
        """Get pip value in account currency (USD) for calculating pips from P&L"""
        # Pip values in USD for different instrument types
        # These are approximate - OANDA's actual calculations may vary slightly
        
        if '_JPY' in instrument:
            # JPY pairs: 1 pip = 0.01, value varies by base currency
            if instrument.startswith('USD'):
                return units * 0.01  # USD/JPY
            else:
                # For other XXX/JPY pairs, convert via current rate (simplified)
                return units * 0.01 * 0.007  # Approximate USD equivalent
        else:
            # Major pairs: 1 pip = 0.0001
            if instrument.endswith('_USD'):
                return units * 0.0001  # XXX/USD pairs
            elif instrument.startswith('USD'):
                return units * 0.0001 * 0.85  # USD/XXX pairs (approximate)
            else:
                # Cross pairs: approximate USD value
                return units * 0.0001 * 1.1  # Approximate cross rate
    
    def _calculate_risk_reward(self, entry_price: float, stop_loss_price: Optional[float], 
                              take_profit_price: Optional[float], units: float, 
                              direction: str, instrument: str) -> tuple:
        """Calculate risk amount, profit amount, and R:R ratio"""
        risk_amount = 0.0
        profit_amount = 0.0
        rr_ratio = None
        
        if not stop_loss_price and not take_profit_price:
            return risk_amount, profit_amount, rr_ratio
        
        # Calculate risk (if stop loss exists)
        if stop_loss_price:
            risk_pips = abs(entry_price - stop_loss_price)
            # Simplified USD calculation (should use proper conversion)
            risk_amount = risk_pips * units
            
        # Calculate profit potential (if take profit exists)  
        if take_profit_price:
            profit_pips = abs(take_profit_price - entry_price)
            profit_amount = profit_pips * units
            
        # Calculate R:R ratio
        if risk_amount > 0 and profit_amount > 0:
            rr_ratio = round(profit_amount / risk_amount, 2)
            
        return round(risk_amount, 2), round(profit_amount, 2), rr_ratio
    
    def _get_market_session(self, trade_time: datetime) -> str:
        """Determine market session based on trade open time"""
        # Ensure we have timezone-aware datetime
        if trade_time.tzinfo is None:
            trade_time = trade_time.replace(tzinfo=timezone.utc)
        
        utc_hour = trade_time.hour
        utc_day = trade_time.strftime('%A')  # Day of week
        
        # Convert to Eastern for logging
        eastern_time = self._convert_to_eastern(trade_time)
        
        # Log for debugging
        logger.debug(f"🕐 Market Session Check - Trade opened at: {trade_time.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                    f"({eastern_time.strftime('%Y-%m-%d %H:%M:%S %Z')}), UTC Hour: {utc_hour}")
        
        # Forex market is closed from Friday 5pm ET to Sunday 5pm ET
        # In UTC: Friday 22:00 to Sunday 22:00
        if utc_day == 'Saturday' or (utc_day == 'Friday' and utc_hour >= 22) or (utc_day == 'Sunday' and utc_hour < 22):
            return 'WEEKEND'
        
        # Check overlapping sessions (multiple sessions can be active)
        active_sessions = []
        
        for session, hours in self.market_sessions.items():
            start, end = hours['start'], hours['end']
            
            if start <= end:  # Normal range (like London, Tokyo)
                if start <= utc_hour < end:
                    active_sessions.append(session)
            else:  # Overnight range (like Sydney)
                if utc_hour >= start or utc_hour < end:
                    active_sessions.append(session)
        
        # Return the most relevant session based on priority
        if 'NEW_YORK' in active_sessions and 'LONDON' in active_sessions:
            return 'LONDON_NY_OVERLAP'  # Most liquid time
        elif 'LONDON' in active_sessions and 'TOKYO' in active_sessions:
            return 'LONDON_TOKYO_OVERLAP'
        elif 'NEW_YORK' in active_sessions:
            return 'NEW_YORK'
        elif 'LONDON' in active_sessions:
            return 'LONDON'
        elif 'TOKYO' in active_sessions:
            return 'TOKYO'
        elif 'SYDNEY' in active_sessions:
            return 'SYDNEY'
        else:
            return 'OFF_HOURS'
    
    def _identify_strategy(self, trade: Dict[str, Any], units: float, instrument: str) -> str:
        """
        Identify strategy using StrategyMapper for real strategy names
        """
        
        # Use StrategyMapper to get real strategy name
        strategy_name = self.strategy_mapper.get_strategy_name(trade)
        
        logger.info(f"🎯 Identified strategy for trade {trade.get('id', 'unknown')}: {strategy_name}")
        
        return strategy_name
    
    def _calculate_momentum_strength(self, pips_moved: float, unrealized_pl: float) -> str:
        """Calculate momentum strength based on trade performance"""
        if pips_moved > 50 or unrealized_pl > 100:
            return "STRONG_BULLISH" if pips_moved > 0 else "STRONG_BEARISH"
        elif pips_moved > 20 or unrealized_pl > 50:
            return "WEAK_BULLISH" if pips_moved > 0 else "WEAK_BEARISH"
        else:
            return "NEUTRAL"
    
    def _determine_analysis_type(self, strategy_name: str) -> str:
        """Determine analysis type based on analytical methodology"""
        # Institutional Numbers for all current strategies using Dime/Quarter/Penny levels
        if ("Dime Curve" in strategy_name or "DC H1" in strategy_name or 
            "Quarter Curve" in strategy_name or "QC H1" in strategy_name or
            "Penny Curve" in strategy_name or "PC H1" in strategy_name):
            return "INSTITUTIONAL_NUMBERS"
        # Future: Sentiment Analysis for sentiment-based strategies
        elif "Sentiment" in strategy_name or "Market_Sentiment" in strategy_name:
            return "SENTIMENT_ANALYSIS"
        # Future: Technical Analysis for RSI, technicals, quadrant chart strategies
        elif ("RSI" in strategy_name or "Technical" in strategy_name or 
              "Quadrant" in strategy_name or "Chart" in strategy_name or
              "Momentum" in strategy_name or "Breakout" in strategy_name):
            return "TECHNICAL_ANALYSIS"
        # Future: Fundamental Analysis for Fed day, economic event strategies
        elif ("Fed" in strategy_name or "Economic" in strategy_name or 
              "Fundamental" in strategy_name or "News" in strategy_name):
            return "FUNDAMENTAL_ANALYSIS"
        # Future: Hybrid Analysis for combined approach strategies
        elif "Hybrid" in strategy_name or "Combined" in strategy_name:
            return "HYBRID_ANALYSIS"
        # Return None for unrecognized strategies (no dummy data)
        else:
            return None
    
    def _determine_order_type(self, trade: Dict[str, Any], strategy_name: str) -> str:
        """Determine order type based on OANDA trade data and strategy"""
        
        # Check if OANDA provides order type information
        if 'orderType' in trade:
            order_type = trade.get('orderType', '').upper()
            if 'LIMIT' in order_type:
                return 'Limit Order'
            elif 'MARKET' in order_type:
                return 'Market Order'
            elif 'STOP' in order_type:
                return 'Stop Order'
        
        # Check clientExtensions for order type hints
        client_ext = trade.get('clientExtensions', {})
        if isinstance(client_ext, dict):
            comment = client_ext.get('comment', '').lower()
            ext_id = client_ext.get('id', '').lower()
            
            if 'limit' in comment or 'limit' in ext_id:
                return 'Limit Order'
            elif 'market' in comment or 'market' in ext_id:
                return 'Market Order'
        
        # Infer from strategy name (most strategies use dual limit orders)
        if strategy_name and 'Dual Limit' in strategy_name:
            return 'Limit Order'
        
        # Check if trade has both stop loss and take profit (typical for limit order strategies)
        has_sl = 'stopLossOrder' in trade and trade['stopLossOrder']
        has_tp = 'takeProfitOrder' in trade and trade['takeProfitOrder']
        
        if has_sl and has_tp:
            # Trades with both SL and TP are typically from limit order strategies
            return 'Limit Order'
        
        # Default to Market Order if we can't determine
        logger.debug(f"Could not determine order type for trade {trade.get('id', 'unknown')}, defaulting to Market Order")
        return 'Market Order'
    
    def get_stop_loss_price(self, trade: Dict[str, Any]) -> Optional[float]:
        """
        Extract stop loss price from trade data using the same logic that works in Airtable
        """
        trade_id = trade.get('id', 'unknown')
        
        # Check if trade has stop loss order info
        stop_loss_order = trade.get('stopLossOrder', {})
        if stop_loss_order and stop_loss_order.get('price'):
            price = float(stop_loss_order.get('price', 0))
            logger.info(f"📊 Trade {trade_id}: Found SL price {price} from stopLossOrder")
            return price
        
        # Check trade fills for stop loss info
        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
        if trade_fills:
            stop_loss = trade_fills.get('stopLossOnFill', {})
            if stop_loss and stop_loss.get('price'):
                price = float(stop_loss.get('price', 0))
                logger.info(f"📊 Trade {trade_id}: Found SL price {price} from stopLossOnFill")
                return price
        
        # Check alternative locations in trade data
        client_extensions = trade.get('clientExtensions', {})
        if client_extensions:
            logger.debug(f"📊 Trade {trade_id}: clientExtensions found: {client_extensions}")
        
        logger.debug(f"📊 Trade {trade_id}: No stop loss price found")
        return None

    def get_take_profit_price(self, trade: Dict[str, Any]) -> Optional[float]:
        """
        Extract take profit price from trade data using the same logic that works in Airtable
        """
        trade_id = trade.get('id', 'unknown')
        
        # Check if trade has take profit order info
        take_profit_order = trade.get('takeProfitOrder', {})
        if take_profit_order and take_profit_order.get('price'):
            price = float(take_profit_order.get('price', 0))
            logger.info(f"📊 Trade {trade_id}: Found TP price {price} from takeProfitOrder")
            return price
        
        # Check trade fills for take profit info
        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
        if trade_fills:
            take_profit = trade_fills.get('takeProfitOnFill', {})
            if take_profit and take_profit.get('price'):
                price = float(take_profit.get('price', 0))
                logger.info(f"📊 Trade {trade_id}: Found TP price {price} from takeProfitOnFill")
                return price
        
        logger.debug(f"📊 Trade {trade_id}: No take profit price found")
        return None
    
    async def enhance_closed_trades(self, closed_trades_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enhance closed trades with stop_loss and take_profit data using Airtable-proven logic
        """
        if not closed_trades_data or 'trades' not in closed_trades_data:
            return closed_trades_data
        
        enhanced_trades = []
        
        for trade in closed_trades_data['trades']:
            trade_id = trade.get('id', 'unknown')
            logger.info(f"🔍 Enhancing closed trade {trade_id} with SL/TP extraction")
            
            # Extract stop loss and take profit using proven Airtable logic
            stop_loss_price = self.get_stop_loss_price(trade)
            take_profit_price = self.get_take_profit_price(trade)
            
            # Add the extracted prices to the trade data
            enhanced_trade = trade.copy()
            if stop_loss_price is not None:
                enhanced_trade['stop_loss_price'] = stop_loss_price
                enhanced_trade['stop_loss'] = stop_loss_price  # For backward compatibility
                logger.info(f"✅ Trade {trade_id}: Enhanced with stop_loss_price = {stop_loss_price}")
            else:
                enhanced_trade['stop_loss_price'] = 0.0
                enhanced_trade['stop_loss'] = 0.0
                logger.warning(f"⚠️ Trade {trade_id}: No stop loss price found")
            
            if take_profit_price is not None:
                enhanced_trade['take_profit_price'] = take_profit_price
                enhanced_trade['take_profit'] = take_profit_price  # For backward compatibility
                logger.info(f"✅ Trade {trade_id}: Enhanced with take_profit_price = {take_profit_price}")
            else:
                enhanced_trade['take_profit_price'] = 0.0
                enhanced_trade['take_profit'] = 0.0
                logger.warning(f"⚠️ Trade {trade_id}: No take profit price found")
            
            enhanced_trades.append(enhanced_trade)
        
        # Return enhanced data
        enhanced_data = closed_trades_data.copy()
        enhanced_data['trades'] = enhanced_trades
        
        logger.info(f"🎯 Enhanced {len(enhanced_trades)} closed trades with SL/TP data")
        return enhanced_data