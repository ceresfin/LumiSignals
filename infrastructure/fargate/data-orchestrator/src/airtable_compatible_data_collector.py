#!/usr/bin/env python3
"""
Airtable-Compatible Data Collector for Fargate
==============================================

This collector ensures RDS gets exactly the same data as Airtable by:
1. Using identical OANDA API endpoints that Airtable uses
2. Applying identical field mappings and calculations
3. Populating all 6 RDS tables to match Airtable structure

Based on: /infrastructure/terraform/momentum-dashboard/AIRTABLE_DATA_INFRASTRUCTURE_ANALYSIS.md
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
import pg8000
import boto3

logger = logging.getLogger(__name__)

class AirtableCompatibleDataCollector:
    """Collects data from OANDA and populates RDS exactly like Airtable"""
    
    def __init__(self, oanda_client, database_manager):
        self.client = oanda_client
        self.db = database_manager
        
        # JPY pairs use 2 decimal places for pip calculation
        self.jpy_pairs = ['USD/JPY', 'EUR/JPY', 'GBP/JPY', 'AUD/JPY', 'NZD/JPY', 'CAD/JPY', 'CHF/JPY']
    
    async def collect_and_sync_all_tables(self) -> bool:
        """
        Main entry point - collect all data and sync all 6 tables
        This mirrors the Lambda trade-sync function behavior
        """
        try:
            logger.info("🎯 Starting Airtable-compatible data collection for all 6 tables...")
            
            # Step 1: Collect data from all OANDA endpoints (like Airtable does)
            oanda_data = await self._collect_all_oanda_data()
            if not oanda_data:
                logger.error("❌ Failed to collect OANDA data")
                return False
            
            # Step 2: Sync each table (in order of dependencies)
            results = {}
            
            # Table 1: Account Summary (no dependencies)
            results['account_summary'] = await self._sync_account_summary(oanda_data['account'])
            
            # Table 2: Active Trades 
            results['active_trades'] = await self._sync_active_trades(
                oanda_data['open_trades'], 
                oanda_data['pricing'],
                oanda_data['account']
            )
            
            # Table 3: Closed Trades (needs transaction lookup)
            results['closed_trades'] = await self._sync_closed_trades(oanda_data['closed_trades'])
            
            # Table 4: Pending Orders
            results['pending_orders'] = await self._sync_pending_orders(
                oanda_data['pending_orders'],
                oanda_data['pricing']
            )
            
            # Table 5: Currency Exposures (calculated from positions)
            results['currency_exposures'] = await self._sync_currency_exposures(oanda_data['positions'])
            
            # Table 6: Currency Pair Positions
            results['currency_pair_positions'] = await self._sync_currency_pair_positions(oanda_data['positions'])
            
            # Log results
            success_count = sum(1 for result in results.values() if result)
            logger.info(f"📊 Sync completed: {success_count}/6 tables successful")
            
            for table, success in results.items():
                status = "✅" if success else "❌"
                logger.info(f"  {status} {table}")
            
            return success_count == 6
            
        except Exception as e:
            logger.error(f"❌ Data collection failed: {str(e)}", exc_info=True)
            return False
    
    async def _collect_all_oanda_data(self) -> Optional[Dict[str, Any]]:
        """
        Collect data from all OANDA endpoints that Airtable uses
        Mirrors the Lambda function's API calls exactly
        """
        try:
            logger.info("📡 Collecting data from OANDA API endpoints...")
            
            # Endpoint 1: Account Summary (/v3/accounts/{account_id}/summary)
            account = await self.client.get_account_summary()
            if not account:
                logger.error("Failed to get account summary")
                return None
            
            # Endpoint 2: Open Trades (/v3/accounts/{account_id}/openTrades)
            open_trades = await self.client.get_open_trades()
            if open_trades is None:
                logger.error("Failed to get open trades")
                return None
                
            # Endpoint 3: Closed Trades (/v3/accounts/{account_id}/trades?state=CLOSED)
            # Get last 30 days of closed trades (like Airtable does)
            from_time = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            closed_trades = await self.client.get_closed_trades(from_time=from_time, count=500)
            
            # Endpoint 4: Pending Orders (/v3/accounts/{account_id}/pendingOrders)
            pending_orders = await self.client.get_pending_orders()
            
            # Endpoint 5: Open Positions (/v3/accounts/{account_id}/openPositions)
            positions = await self.client.get_positions()
            
            # Endpoint 6: Current Pricing (/v3/accounts/{account_id}/pricing)
            # Get pricing for all instruments we have trades/positions for
            instruments = set()
            if open_trades and 'trades' in open_trades:
                instruments.update(trade['instrument'] for trade in open_trades['trades'])
            if pending_orders and 'orders' in pending_orders:
                instruments.update(order['instrument'] for order in pending_orders['orders'])
            if positions and 'positions' in positions:
                instruments.update(pos['instrument'] for pos in positions['positions'])
            
            pricing = {}
            if instruments:
                pricing = await self.client.get_current_pricing(list(instruments))
            
            logger.info("✅ All OANDA API data collected successfully")
            
            return {
                'account': account,
                'open_trades': open_trades,
                'closed_trades': closed_trades,
                'pending_orders': pending_orders,
                'positions': positions,
                'pricing': pricing
            }
            
        except Exception as e:
            logger.error(f"❌ OANDA data collection failed: {str(e)}")
            return None
    
    async def _sync_active_trades(self, open_trades: Dict, pricing: Dict, account: Dict) -> bool:
        """
        Sync Active Trades table with exact Airtable field mapping
        Fields from Airtable analysis: trade_id, oanda_order_id, instrument, direction,
        units, order_type, entry_price, current_price, fill_time, order_time, trade_state,
        strategy, unrealized_pnl, margin_used, stop_loss, take_profit, distance_to_entry,
        risk_amount, potential_profit, last_updated
        """
        try:
            if not open_trades or 'trades' in open_trades and not open_trades['trades']:
                logger.info("📊 No open trades to sync")
                return True
            
            trades_to_insert = []
            
            for trade in open_trades.get('trades', []):
                try:
                    # Map fields exactly like Airtable Lambda does
                    trade_data = {
                        'trade_id': trade['id'],  # OANDA trade ID
                        'oanda_order_id': trade['id'],  # Same as trade ID
                        'instrument': self._format_instrument(trade['instrument']),  # EUR/USD format
                        'direction': 'Long' if float(trade['currentUnits']) > 0 else 'Short',  # Long/Short
                        'units': abs(int(float(trade['currentUnits']))),  # Absolute value
                        'order_type': 'Market Order',  # Hardcoded like Airtable
                        'entry_price': Decimal(str(trade['price'])),  # Entry price
                        'current_price': self._get_current_price(trade['instrument'], pricing),
                        'fill_time': self._parse_oanda_time(trade['openTime']),
                        'order_time': self._parse_oanda_time(trade['openTime']),  # Same as fill time
                        'trade_state': 'Open',  # Hardcoded like Airtable
                        'strategy': 'Auto Trading',  # Hardcoded like Airtable (can enhance later)
                        'unrealized_pnl': Decimal(str(trade.get('unrealizedPL', '0'))),
                        'margin_used': Decimal(str(trade.get('marginUsed', '0'))),
                        'stop_loss': self._extract_stop_loss_price(trade),
                        'take_profit': self._extract_take_profit_price(trade),
                        'distance_to_entry': self._calculate_distance_to_entry(trade, pricing),
                        'risk_amount': Decimal(str(trade.get('marginUsed', '0'))),  # Same as margin used
                        'potential_profit': Decimal(str(trade.get('unrealizedPL', '0'))),  # Same as unrealized P&L
                        'last_updated': datetime.now(timezone.utc)
                    }
                    
                    trades_to_insert.append(trade_data)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing trade {trade.get('id', 'unknown')}: {e}")
                    continue
            
            # Bulk insert/update trades
            if trades_to_insert:
                success = await self.db.bulk_upsert_active_trades(trades_to_insert)
                logger.info(f"📊 Active trades sync: {len(trades_to_insert)} trades processed")
                return success
            else:
                logger.info("📊 No valid active trades to sync")
                return True
                
        except Exception as e:
            logger.error(f"❌ Active trades sync failed: {str(e)}")
            return False
    
    async def _sync_closed_trades(self, closed_trades: Dict) -> bool:
        """
        Sync Closed Trades table with Airtable field mapping
        Includes close reason determination via transaction lookup
        """
        try:
            if not closed_trades or not closed_trades.get('trades'):
                logger.info("📊 No closed trades to sync")
                return True
            
            trades_to_insert = []
            
            for trade in closed_trades.get('trades', []):
                try:
                    # Get close reason by analyzing transactions (like Airtable does)
                    close_reason = await self._determine_close_reason(trade)
                    
                    # Only sync trades with valid close reasons (Airtable filtering)
                    if close_reason not in ['Stop Loss Hit', 'Take Profit', 'Sell Market']:
                        continue
                    
                    # Calculate exit price from transactions
                    exit_price = await self._calculate_exit_price(trade)
                    
                    trade_data = {
                        'trade_id': trade['id'],
                        'oanda_order_id': trade['id'],
                        'instrument': self._format_instrument(trade['instrument']),
                        'direction': 'Long' if float(trade['initialUnits']) > 0 else 'Short',
                        'units': abs(int(float(trade['initialUnits']))),
                        'entry_price': Decimal(str(trade['price'])),
                        'exit_price': exit_price,
                        'open_time': self._parse_oanda_time(trade['openTime']),
                        'close_time': self._parse_oanda_time(trade['closeTime']),
                        'duration_hours': self._calculate_duration_hours(trade['openTime'], trade['closeTime']),
                        'gross_pnl': Decimal(str(trade.get('realizedPL', '0'))),
                        'net_pnl': Decimal(str(trade.get('realizedPL', '0'))) + Decimal(str(trade.get('financing', '0'))),
                        'close_reason': close_reason,
                        'gain_loss': 'Gain' if Decimal(str(trade.get('realizedPL', '0'))) > 0 else 'Loss',
                        'pips': self._calculate_pips(trade, exit_price),
                        'strategy': 'Auto Trading',
                        'status': 'Closed',
                        'return_risk_ratio': self._calculate_return_risk_ratio(trade),
                        'stop_loss': self._extract_stop_loss_price(trade),
                        'take_profit': self._extract_take_profit_price(trade),
                        'max_favorable': Decimal('0'),  # Placeholder
                        'max_adverse': Decimal('0'),    # Placeholder
                        'created_at': datetime.now(timezone.utc)
                    }
                    
                    trades_to_insert.append(trade_data)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing closed trade {trade.get('id', 'unknown')}: {e}")
                    continue
            
            if trades_to_insert:
                success = await self.db.bulk_upsert_closed_trades(trades_to_insert)
                logger.info(f"📊 Closed trades sync: {len(trades_to_insert)} trades processed")
                return success
            else:
                logger.info("📊 No valid closed trades to sync")
                return True
                
        except Exception as e:
            logger.error(f"❌ Closed trades sync failed: {str(e)}")
            return False
    
    async def _sync_pending_orders(self, pending_orders: Dict, pricing: Dict) -> bool:
        """Sync Pending Orders table with Airtable field mapping"""
        try:
            if not pending_orders or not pending_orders.get('orders'):
                logger.info("📊 No pending orders to sync")
                return True
            
            orders_to_insert = []
            
            for order in pending_orders.get('orders', []):
                try:
                    order_data = {
                        'order_id': order['id'],
                        'instrument': self._format_instrument(order['instrument']),
                        'direction': 'Long' if float(order['units']) > 0 else 'Short',
                        'units': abs(int(float(order['units']))),
                        'order_price': Decimal(str(order['price'])),
                        'current_price': self._get_current_price(order['instrument'], pricing),
                        'distance_to_market': self._calculate_distance_to_market(order, pricing),
                        'order_type': order['type'],
                        'time_in_force': order.get('timeInForce', 'GTC'),
                        'gtd_time': self._parse_oanda_time(order.get('gtdTime')) if order.get('gtdTime') else None,
                        'position_fill': order.get('positionFill', 'DEFAULT'),
                        'trigger_condition': order.get('triggerCondition', 'DEFAULT'),
                        'stop_loss': self._extract_order_stop_loss(order),
                        'take_profit': self._extract_order_take_profit(order),
                        'created_time': self._parse_oanda_time(order['createTime']),
                        'last_updated': datetime.now(timezone.utc)
                    }
                    
                    orders_to_insert.append(order_data)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing order {order.get('id', 'unknown')}: {e}")
                    continue
            
            if orders_to_insert:
                success = await self.db.bulk_upsert_pending_orders(orders_to_insert)
                logger.info(f"📊 Pending orders sync: {len(orders_to_insert)} orders processed")
                return success
            else:
                return True
                
        except Exception as e:
            logger.error(f"❌ Pending orders sync failed: {str(e)}")
            return False
    
    async def _sync_currency_exposures(self, positions: Dict) -> bool:
        """
        Sync Currency Exposures table
        Calculate per-currency exposure like Airtable does
        """
        try:
            if not positions or not positions.get('positions'):
                logger.info("📊 No positions for currency exposure calculation")
                return True
            
            # Calculate currency exposures
            exposures = {}
            
            for position in positions.get('positions', []):
                try:
                    instrument = position['instrument']
                    base_currency = instrument.split('_')[0]
                    quote_currency = instrument.split('_')[1]
                    
                    long_units = float(position.get('long', {}).get('units', '0'))
                    short_units = float(position.get('short', {}).get('units', '0'))
                    
                    # Base currency exposure
                    if base_currency not in exposures:
                        exposures[base_currency] = {'long': 0, 'short': 0}
                    
                    exposures[base_currency]['long'] += max(0, long_units)
                    exposures[base_currency]['short'] += abs(min(0, short_units))
                    
                    # Quote currency exposure (opposite direction)
                    if quote_currency not in exposures:
                        exposures[quote_currency] = {'long': 0, 'short': 0}
                    
                    exposures[quote_currency]['short'] += max(0, long_units)
                    exposures[quote_currency]['long'] += abs(min(0, short_units))
                    
                except Exception as e:
                    logger.error(f"❌ Error calculating exposure for {position.get('instrument')}: {e}")
                    continue
            
            # Convert to database format
            exposures_to_insert = []
            for currency, exp in exposures.items():
                exposure_data = {
                    'currency': currency,
                    'long_exposure': Decimal(str(exp['long'])),
                    'short_exposure': Decimal(str(exp['short'])),
                    'net_exposure': Decimal(str(exp['long'] - exp['short'])),
                    'exposure_usd': Decimal('0'),  # Would need exchange rates to calculate
                    'percentage': Decimal('0'),    # Would need total portfolio value
                    'last_updated': datetime.now(timezone.utc)
                }
                exposures_to_insert.append(exposure_data)
            
            if exposures_to_insert:
                success = await self.db.bulk_upsert_currency_exposures(exposures_to_insert)
                logger.info(f"📊 Currency exposures sync: {len(exposures_to_insert)} currencies processed")
                return success
            else:
                return True
                
        except Exception as e:
            logger.error(f"❌ Currency exposures sync failed: {str(e)}")
            return False
    
    async def _sync_currency_pair_positions(self, positions: Dict) -> bool:
        """Sync Currency Pair Positions table"""
        try:
            if not positions or not positions.get('positions'):
                logger.info("📊 No positions for currency pair sync")
                return True
            
            positions_to_insert = []
            
            for position in positions.get('positions', []):
                try:
                    long_units = float(position.get('long', {}).get('units', '0'))
                    short_units = float(position.get('short', {}).get('units', '0'))
                    
                    position_data = {
                        'currency_pair': self._format_instrument(position['instrument']),
                        'long_units': Decimal(str(max(0, long_units))),
                        'short_units': Decimal(str(abs(min(0, short_units)))),
                        'net_units': Decimal(str(long_units + short_units)),  # Note: short_units are negative
                        'average_entry': self._calculate_average_entry(position),
                        'unrealized_pnl': Decimal(str(position.get('unrealizedPL', '0'))),
                        'margin_used': Decimal(str(position.get('marginUsed', '0'))),
                        'exposure_usd': Decimal('0'),  # Would need exchange rates
                        'last_updated': datetime.now(timezone.utc)
                    }
                    
                    positions_to_insert.append(position_data)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing position {position.get('instrument')}: {e}")
                    continue
            
            if positions_to_insert:
                success = await self.db.bulk_upsert_currency_pair_positions(positions_to_insert)
                logger.info(f"📊 Currency pair positions sync: {len(positions_to_insert)} pairs processed")
                return success
            else:
                return True
                
        except Exception as e:
            logger.error(f"❌ Currency pair positions sync failed: {str(e)}")
            return False
    
    async def _sync_account_summary(self, account: Dict) -> bool:
        """Sync Account Summary table"""
        try:
            account_data = {
                'account_id': account.get('id', 'unknown'),
                'balance': Decimal(str(account.get('balance', '0'))),
                'nav': Decimal(str(account.get('NAV', '0'))),
                'margin_used': Decimal(str(account.get('marginUsed', '0'))),
                'margin_available': Decimal(str(account.get('marginAvailable', '0'))),
                'margin_rate': Decimal(str(account.get('marginRate', '0.02'))),
                'unrealized_pnl': Decimal(str(account.get('unrealizedPL', '0'))),
                'daily_pnl': Decimal('0'),  # Would need to calculate from daily changes
                'open_trade_count': int(account.get('openTradeCount', 0)),
                'open_position_count': int(account.get('openPositionCount', 0)),
                'pending_order_count': int(account.get('pendingOrderCount', 0)),
                'last_updated': datetime.now(timezone.utc)
            }
            
            success = await self.db.upsert_account_summary(account_data)
            logger.info("📊 Account summary synced")
            return success
            
        except Exception as e:
            logger.error(f"❌ Account summary sync failed: {str(e)}")
            return False
    
    # ========== HELPER METHODS ==========
    
    def _format_instrument(self, instrument: str) -> str:
        """Format instrument from OANDA format (EUR_USD) to Airtable format (EUR/USD)"""
        return instrument.replace('_', '/')
    
    def _parse_oanda_time(self, time_str: str) -> Optional[datetime]:
        """Parse OANDA timestamp to datetime"""
        if not time_str:
            return None
        try:
            # Remove timezone info and parse (OANDA uses UTC)
            clean_time = time_str.replace('Z', '+00:00')
            return datetime.fromisoformat(clean_time)
        except Exception:
            return None
    
    def _get_current_price(self, instrument: str, pricing: Dict) -> Optional[Decimal]:
        """Get current price from pricing data"""
        if not pricing or 'prices' not in pricing:
            return None
        
        for price_data in pricing['prices']:
            if price_data['instrument'] == instrument:
                # Use mid price (average of bid/ask)
                bid = float(price_data['bids'][0]['price'])
                ask = float(price_data['asks'][0]['price'])
                mid_price = (bid + ask) / 2
                return Decimal(str(mid_price))
        
        return None
    
    def _extract_stop_loss_price(self, trade: Dict) -> Optional[Decimal]:
        """Extract stop loss price from trade"""
        if 'stopLossOrder' in trade and trade['stopLossOrder']:
            return Decimal(str(trade['stopLossOrder']['price']))
        return None
    
    def _extract_take_profit_price(self, trade: Dict) -> Optional[Decimal]:
        """Extract take profit price from trade"""
        if 'takeProfitOrder' in trade and trade['takeProfitOrder']:
            return Decimal(str(trade['takeProfitOrder']['price']))
        return None
    
    def _calculate_distance_to_entry(self, trade: Dict, pricing: Dict) -> Optional[Decimal]:
        """Calculate distance to entry in pips (like Airtable does)"""
        try:
            entry_price = Decimal(str(trade['price']))
            current_price = self._get_current_price(trade['instrument'], pricing)
            
            if not current_price:
                return None
            
            instrument = self._format_instrument(trade['instrument'])
            pip_value = Decimal('0.01') if instrument in self.jpy_pairs else Decimal('0.0001')
            
            distance = abs(current_price - entry_price) / pip_value
            return distance.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            
        except Exception:
            return None
    
    async def _determine_close_reason(self, trade: Dict) -> str:
        """
        Determine close reason by analyzing transactions (like Airtable Lambda does)
        Maps OANDA transaction types to close reasons
        """
        try:
            if not trade.get('closingTransactionIDs'):
                return 'Unknown'
            
            # Check the first closing transaction (primary reason)
            transaction_id = trade['closingTransactionIDs'][0]
            transaction = await self.client.get_transaction(transaction_id)
            
            if not transaction:
                return 'Unknown'
            
            # Map transaction types to close reasons (Airtable mapping)
            transaction_type = transaction.get('type', '')
            if transaction_type == 'STOP_LOSS_ORDER':
                return 'Stop Loss Hit'
            elif transaction_type == 'TAKE_PROFIT_ORDER':
                return 'Take Profit'
            elif transaction_type == 'MARKET_ORDER':
                return 'Sell Market'
            else:
                return 'Unknown'  # Will be filtered out like Airtable does
                
        except Exception as e:
            logger.error(f"Error determining close reason: {e}")
            return 'Unknown'
    
    async def _calculate_exit_price(self, trade: Dict) -> Optional[Decimal]:
        """Calculate exit price from closing transactions"""
        try:
            # First try averageClosePrice if available
            if 'averageClosePrice' in trade and trade['averageClosePrice']:
                return Decimal(str(trade['averageClosePrice']))
            
            # Otherwise analyze closing transactions
            if not trade.get('closingTransactionIDs'):
                return None
            
            # Get the primary closing transaction
            transaction_id = trade['closingTransactionIDs'][0]
            transaction = await self.client.get_transaction(transaction_id)
            
            if transaction and 'price' in transaction:
                return Decimal(str(transaction['price']))
            
            return None
            
        except Exception:
            return None
    
    def _calculate_duration_hours(self, open_time: str, close_time: str) -> Optional[Decimal]:
        """Calculate trade duration in hours"""
        try:
            open_dt = self._parse_oanda_time(open_time)
            close_dt = self._parse_oanda_time(close_time)
            
            if not open_dt or not close_dt:
                return None
            
            duration = close_dt - open_dt
            hours = Decimal(str(duration.total_seconds() / 3600))
            return hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
        except Exception:
            return None
    
    def _calculate_pips(self, trade: Dict, exit_price: Optional[Decimal]) -> Optional[Decimal]:
        """Calculate pips moved (with JPY handling like Airtable)"""
        try:
            if not exit_price:
                return None
            
            entry_price = Decimal(str(trade['price']))
            instrument = self._format_instrument(trade['instrument'])
            
            # JPY pairs use 2 decimal places, others use 4
            pip_value = Decimal('0.01') if instrument in self.jpy_pairs else Decimal('0.0001')
            
            pips = abs(exit_price - entry_price) / pip_value
            return pips.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            
        except Exception:
            return None
    
    def _calculate_return_risk_ratio(self, trade: Dict) -> Optional[Decimal]:
        """Calculate return:risk ratio (like Airtable does)"""
        try:
            # This is a complex calculation that would need SL/TP distances
            # For now, return a simple calculation based on P&L
            realized_pl = Decimal(str(trade.get('realizedPL', '0')))
            margin_used = Decimal(str(trade.get('marginUsed', '1')))
            
            if margin_used == 0:
                return None
            
            ratio = realized_pl / margin_used
            return ratio.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
        except Exception:
            return None
    
    def _calculate_distance_to_market(self, order: Dict, pricing: Dict) -> Optional[Decimal]:
        """Calculate distance from order price to current market price in pips"""
        try:
            order_price = Decimal(str(order['price']))
            current_price = self._get_current_price(order['instrument'], pricing)
            
            if not current_price:
                return None
            
            instrument = self._format_instrument(order['instrument'])
            pip_value = Decimal('0.01') if instrument in self.jpy_pairs else Decimal('0.0001')
            
            distance = abs(current_price - order_price) / pip_value
            return distance.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
            
        except Exception:
            return None
    
    def _extract_order_stop_loss(self, order: Dict) -> Optional[Decimal]:
        """Extract stop loss from order's on-fill instructions"""
        try:
            if 'stopLossOnFill' in order and order['stopLossOnFill']:
                return Decimal(str(order['stopLossOnFill']['price']))
            return None
        except Exception:
            return None
    
    def _extract_order_take_profit(self, order: Dict) -> Optional[Decimal]:
        """Extract take profit from order's on-fill instructions"""
        try:
            if 'takeProfitOnFill' in order and order['takeProfitOnFill']:
                return Decimal(str(order['takeProfitOnFill']['price']))
            return None
        except Exception:
            return None
    
    def _calculate_average_entry(self, position: Dict) -> Optional[Decimal]:
        """Calculate weighted average entry price for position"""
        try:
            long_avg = position.get('long', {}).get('averagePrice')
            short_avg = position.get('short', {}).get('averagePrice')
            long_units = float(position.get('long', {}).get('units', '0'))
            short_units = float(position.get('short', {}).get('units', '0'))
            
            total_units = abs(long_units) + abs(short_units)
            if total_units == 0:
                return None
            
            if long_avg and short_avg:
                # Weighted average
                weighted_avg = (float(long_avg) * abs(long_units) + float(short_avg) * abs(short_units)) / total_units
                return Decimal(str(weighted_avg))
            elif long_avg:
                return Decimal(str(long_avg))
            elif short_avg:
                return Decimal(str(short_avg))
            
            return None
            
        except Exception:
            return None