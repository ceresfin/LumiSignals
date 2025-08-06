#!/usr/bin/env python3
"""
Airtable-Compatible Database Manager
===================================

Database operations for the 6 Airtable-equivalent tables:
1. active_trades
2. closed_trades  
3. pending_orders
4. currency_exposures
5. currency_pair_positions
6. account_summary

Each method handles upserts (insert or update) to match Airtable's behavior
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import pg8000

logger = logging.getLogger(__name__)

class AirtableCompatibleDatabaseManager:
    """Database manager for Airtable-compatible RDS tables"""
    
    def __init__(self, connection_pool):
        self.pool = connection_pool
    
    async def bulk_upsert_active_trades(self, trades: List[Dict[str, Any]]) -> bool:
        """
        Bulk upsert active trades with conflict resolution
        Matches Airtable's incremental update behavior
        """
        if not trades:
            return True
            
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            # Prepare upsert query
            upsert_query = """
                INSERT INTO active_trades (
                    trade_id, oanda_order_id, instrument, direction, units,
                    order_type, entry_price, current_price, fill_time, order_time,
                    trade_state, strategy, unrealized_pnl, margin_used,
                    stop_loss, take_profit, distance_to_entry, risk_amount,
                    potential_profit, last_updated
                ) VALUES %s
                ON CONFLICT (trade_id) DO UPDATE SET
                    current_price = EXCLUDED.current_price,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    distance_to_entry = EXCLUDED.distance_to_entry,
                    potential_profit = EXCLUDED.potential_profit,
                    last_updated = EXCLUDED.last_updated
            """
            
            # Prepare values
            values = []
            for trade in trades:
                values.append((
                    trade['trade_id'],
                    trade['oanda_order_id'],
                    trade['instrument'],
                    trade['direction'],
                    trade['units'],
                    trade['order_type'],
                    trade['entry_price'],
                    trade['current_price'],
                    trade['fill_time'],
                    trade['order_time'],
                    trade['trade_state'],
                    trade['strategy'],
                    trade['unrealized_pnl'],
                    trade['margin_used'],
                    trade['stop_loss'],
                    trade['take_profit'],
                    trade['distance_to_entry'],
                    trade['risk_amount'],
                    trade['potential_profit'],
                    trade['last_updated']
                ))
            
            # Execute batch upsert
            cursor.executemany(upsert_query.replace('%s', '(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'), values)
            conn.commit()
            
            logger.info(f"✅ Active trades bulk upsert: {len(trades)} records")
            return True
            
        except Exception as e:
            logger.error(f"❌ Active trades bulk upsert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def bulk_upsert_closed_trades(self, trades: List[Dict[str, Any]]) -> bool:
        """Bulk upsert closed trades (insert only, no updates needed)"""
        if not trades:
            return True
            
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            # Closed trades are insert-only (historical data)
            insert_query = """
                INSERT INTO closed_trades (
                    trade_id, oanda_order_id, instrument, direction, units,
                    entry_price, exit_price, open_time, close_time, duration_hours,
                    gross_pnl, net_pnl, close_reason, gain_loss, pips,
                    strategy, status, return_risk_ratio, stop_loss, take_profit,
                    max_favorable, max_adverse, created_at
                ) VALUES %s
                ON CONFLICT (trade_id) DO NOTHING
            """
            
            values = []
            for trade in trades:
                values.append((
                    trade['trade_id'],
                    trade['oanda_order_id'],
                    trade['instrument'],
                    trade['direction'],
                    trade['units'],
                    trade['entry_price'],
                    trade['exit_price'],
                    trade['open_time'],
                    trade['close_time'],
                    trade['duration_hours'],
                    trade['gross_pnl'],
                    trade['net_pnl'],
                    trade['close_reason'],
                    trade['gain_loss'],
                    trade['pips'],
                    trade['strategy'],
                    trade['status'],
                    trade['return_risk_ratio'],
                    trade['stop_loss'],
                    trade['take_profit'],
                    trade['max_favorable'],
                    trade['max_adverse'],
                    trade['created_at']
                ))
            
            cursor.executemany(insert_query.replace('%s', '(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'), values)
            conn.commit()
            
            logger.info(f"✅ Closed trades bulk insert: {len(trades)} records")
            return True
            
        except Exception as e:
            logger.error(f"❌ Closed trades bulk insert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def bulk_upsert_pending_orders(self, orders: List[Dict[str, Any]]) -> bool:
        """Bulk upsert pending orders"""
        if not orders:
            return True
            
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            # Clear existing orders first (they change frequently)
            cursor.execute("DELETE FROM pending_orders")
            
            # Insert current orders
            insert_query = """
                INSERT INTO pending_orders (
                    order_id, instrument, direction, units, order_price,
                    current_price, distance_to_market, order_type, time_in_force,
                    gtd_time, position_fill, trigger_condition, stop_loss,
                    take_profit, created_time, last_updated
                ) VALUES %s
            """
            
            values = []
            for order in orders:
                values.append((
                    order['order_id'],
                    order['instrument'],
                    order['direction'],
                    order['units'],
                    order['order_price'],
                    order['current_price'],
                    order['distance_to_market'],
                    order['order_type'],
                    order['time_in_force'],
                    order['gtd_time'],
                    order['position_fill'],
                    order['trigger_condition'],
                    order['stop_loss'],
                    order['take_profit'],
                    order['created_time'],
                    order['last_updated']
                ))
            
            cursor.executemany(insert_query.replace('%s', '(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)'), values)
            conn.commit()
            
            logger.info(f"✅ Pending orders bulk upsert: {len(orders)} records")
            return True
            
        except Exception as e:
            logger.error(f"❌ Pending orders bulk upsert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def bulk_upsert_currency_exposures(self, exposures: List[Dict[str, Any]]) -> bool:
        """Bulk upsert currency exposures"""
        if not exposures:
            return True
            
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            upsert_query = """
                INSERT INTO currency_exposures (
                    currency, long_exposure, short_exposure, net_exposure,
                    exposure_usd, percentage, last_updated
                ) VALUES %s
                ON CONFLICT (currency) DO UPDATE SET
                    long_exposure = EXCLUDED.long_exposure,
                    short_exposure = EXCLUDED.short_exposure,
                    net_exposure = EXCLUDED.net_exposure,
                    exposure_usd = EXCLUDED.exposure_usd,
                    percentage = EXCLUDED.percentage,
                    last_updated = EXCLUDED.last_updated
            """
            
            values = []
            for exposure in exposures:
                values.append((
                    exposure['currency'],
                    exposure['long_exposure'],
                    exposure['short_exposure'],
                    exposure['net_exposure'],
                    exposure['exposure_usd'],
                    exposure['percentage'],
                    exposure['last_updated']
                ))
            
            cursor.executemany(upsert_query.replace('%s', '(%s,%s,%s,%s,%s,%s,%s)'), values)
            conn.commit()
            
            logger.info(f"✅ Currency exposures bulk upsert: {len(exposures)} records")
            return True
            
        except Exception as e:
            logger.error(f"❌ Currency exposures bulk upsert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def bulk_upsert_currency_pair_positions(self, positions: List[Dict[str, Any]]) -> bool:
        """Bulk upsert currency pair positions"""
        if not positions:
            return True
            
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            upsert_query = """
                INSERT INTO currency_pair_positions (
                    currency_pair, long_units, short_units, net_units,
                    average_entry, unrealized_pnl, margin_used, exposure_usd,
                    last_updated
                ) VALUES %s
                ON CONFLICT (currency_pair) DO UPDATE SET
                    long_units = EXCLUDED.long_units,
                    short_units = EXCLUDED.short_units,
                    net_units = EXCLUDED.net_units,
                    average_entry = EXCLUDED.average_entry,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    margin_used = EXCLUDED.margin_used,
                    exposure_usd = EXCLUDED.exposure_usd,
                    last_updated = EXCLUDED.last_updated
            """
            
            values = []
            for position in positions:
                values.append((
                    position['currency_pair'],
                    position['long_units'],
                    position['short_units'],
                    position['net_units'],
                    position['average_entry'],
                    position['unrealized_pnl'],
                    position['margin_used'],
                    position['exposure_usd'],
                    position['last_updated']
                ))
            
            cursor.executemany(upsert_query.replace('%s', '(%s,%s,%s,%s,%s,%s,%s,%s,%s)'), values)
            conn.commit()
            
            logger.info(f"✅ Currency pair positions bulk upsert: {len(positions)} records")
            return True
            
        except Exception as e:
            logger.error(f"❌ Currency pair positions bulk upsert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def upsert_account_summary(self, account_data: Dict[str, Any]) -> bool:
        """Upsert account summary (single record)"""
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            upsert_query = """
                INSERT INTO account_summary (
                    account_id, balance, nav, margin_used, margin_available,
                    margin_rate, unrealized_pnl, daily_pnl, open_trade_count,
                    open_position_count, pending_order_count, last_updated
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (account_id) DO UPDATE SET
                    balance = EXCLUDED.balance,
                    nav = EXCLUDED.nav,
                    margin_used = EXCLUDED.margin_used,
                    margin_available = EXCLUDED.margin_available,
                    margin_rate = EXCLUDED.margin_rate,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    daily_pnl = EXCLUDED.daily_pnl,
                    open_trade_count = EXCLUDED.open_trade_count,
                    open_position_count = EXCLUDED.open_position_count,
                    pending_order_count = EXCLUDED.pending_order_count,
                    last_updated = EXCLUDED.last_updated
            """
            
            cursor.execute(upsert_query, (
                account_data['account_id'],
                account_data['balance'],
                account_data['nav'],
                account_data['margin_used'],
                account_data['margin_available'],
                account_data['margin_rate'],
                account_data['unrealized_pnl'],
                account_data['daily_pnl'],
                account_data['open_trade_count'],
                account_data['open_position_count'],
                account_data['pending_order_count'],
                account_data['last_updated']
            ))
            
            conn.commit()
            logger.info("✅ Account summary upserted")
            return True
            
        except Exception as e:
            logger.error(f"❌ Account summary upsert failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def update_sync_status(self, table_name: str, status: str, records_synced: int = 0, error_message: str = None) -> bool:
        """Update sync status tracking"""
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            update_query = """
                UPDATE sync_status 
                SET last_sync_time = %s,
                    sync_status = %s,
                    records_synced = %s,
                    error_message = %s,
                    updated_at = %s
                WHERE table_name = %s
            """
            
            cursor.execute(update_query, (
                datetime.now(),
                status,
                records_synced,
                error_message,
                datetime.now(),
                table_name
            ))
            
            conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Sync status update failed for {table_name}: {str(e)}")
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def get_data_validation_summary(self) -> Optional[List[Dict[str, Any]]]:
        """Get data validation summary from the view"""
        try:
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM data_validation ORDER BY table_name")
            results = cursor.fetchall()
            
            validation_data = []
            for row in results:
                validation_data.append({
                    'table_name': row[0],
                    'record_count': row[1],
                    'last_update': row[2]
                })
            
            return validation_data
            
        except Exception as e:
            logger.error(f"❌ Data validation query failed: {str(e)}")
            return None
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)
    
    async def cleanup_stale_active_trades(self, current_trade_ids: List[str]) -> bool:
        """Remove active trades that are no longer open"""
        try:
            if not current_trade_ids:
                # If no active trades, clear the table
                conn = await self.pool.getconn()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM active_trades")
                conn.commit()
                logger.info("✅ Cleared all active trades (no open trades)")
                return True
            
            conn = await self.pool.getconn()
            cursor = conn.cursor()
            
            # Delete trades not in current list
            placeholders = ','.join(['%s'] * len(current_trade_ids))
            delete_query = f"DELETE FROM active_trades WHERE trade_id NOT IN ({placeholders})"
            
            cursor.execute(delete_query, current_trade_ids)
            deleted_count = cursor.rowcount
            conn.commit()
            
            if deleted_count > 0:
                logger.info(f"✅ Cleaned up {deleted_count} stale active trades")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Active trades cleanup failed: {str(e)}")
            if 'conn' in locals():
                conn.rollback()
            return False
        finally:
            if 'conn' in locals():
                await self.pool.putconn(conn)