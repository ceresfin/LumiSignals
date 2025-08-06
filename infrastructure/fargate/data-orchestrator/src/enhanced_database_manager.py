#!/usr/bin/env python3
"""
Enhanced Database Manager for Fargate Data Orchestrator
Handles storage of comprehensive OANDA trade data with all 31 Airtable fields
"""

import logging
import asyncpg
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dateutil import parser
import json

logger = logging.getLogger(__name__)

class EnhancedDatabaseManager:
    """Enhanced database manager for comprehensive trade data storage"""
    
    def __init__(self, database_config: Dict[str, Any], redis_manager=None):
        self.config = database_config
        self.connection_pool = None
        self.redis_manager = redis_manager  # Store Redis manager for SL/TP lookup
    
    async def initialize_connection_pool(self):
        """Initialize PostgreSQL connection pool with Eastern timezone"""
        try:
            # Custom init function to set timezone for each connection
            async def init_connection(conn):
                """Set connection timezone to Eastern for proper timestamp display"""
                await conn.execute("SET timezone = 'America/New_York'")
                logger.debug("🕐 Connection timezone set to America/New_York (Eastern)")
            
            self.connection_pool = await asyncpg.create_pool(
                host=self.config['host'],
                port=self.config.get('port', 5432),
                user=self.config['username'],
                password=self.config['password'],
                database=self.config['dbname'],
                min_size=2,
                max_size=10,
                ssl='require' if self.config.get('ssl', True) else 'disable',
                init=init_connection  # Set timezone on each connection
            )
            logger.info("✅ Database connection pool initialized with Eastern timezone")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize database pool: {str(e)}")
            return False
    
    async def initialize(self):
        """Compatibility method for basic database manager interface"""
        return await self.initialize_connection_pool()
    
    async def store_active_trades(self, trades_data: List[Dict[str, Any]]) -> None:
        """Compatibility method - redirects to comprehensive storage"""
        success = await self.store_comprehensive_active_trades(trades_data)
        if not success:
            logger.warning("Enhanced active trades storage failed")
    
    async def store_comprehensive_active_trades(self, trades_data: List[Dict[str, Any]]) -> bool:
        """
        Store comprehensive active trades with all 31 Airtable fields
        
        Uses UPSERT to handle updates efficiently
        """
        if not trades_data:
            logger.info("No trades to store")
            return True
        
        if not self.connection_pool:
            logger.error("Database connection pool not initialized")
            return False
        
        async with self.connection_pool.acquire() as conn:
            try:
                # Use a transaction for consistency
                async with conn.transaction():
                    upsert_query = """
                    INSERT INTO active_trades (
                        -- Match exact RDS column order (45 total columns)
                        trade_id, oanda_order_id, instrument, direction, units, order_type,
                        entry_price, current_price, fill_time, order_time, trade_state, strategy,
                        unrealized_pnl, margin_used, stop_loss, take_profit, distance_to_entry,
                        risk_amount, potential_profit, last_updated, stop_loss_price, take_profit_price,
                        risk_reward_ratio, pips_moved, exit_price, potential_risk_amount, potential_profit_amount,
                        realized_pnl, spread, account_balance_before, market_session, momentum_strength,
                        analysis_type, current_units, state, data_source, sync_timestamp,
                        enhancement_timestamp, open_time, active_trade_duration, pending_duration,
                        financing, commission, initial_units, exit_time
                    ) 
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,           -- 1-10
                        $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,   -- 11-20  
                        $21, $22, $23, $24, $25, $26, $27, $28, $29, $30,   -- 21-30
                        $31, $32, $33, $34, $35, $36, $37, $38, $39, $40,   -- 31-40
                        $41, $42, $43, $44, $45                            -- 41-45
                    )
                    ON CONFLICT (trade_id) DO UPDATE SET
                        -- Update all fields except trade_id (using RDS column names)
                        oanda_order_id = EXCLUDED.oanda_order_id,
                        instrument = EXCLUDED.instrument,
                        direction = EXCLUDED.direction,
                        units = EXCLUDED.units,
                        order_type = EXCLUDED.order_type,
                        entry_price = EXCLUDED.entry_price,
                        current_price = EXCLUDED.current_price,
                        fill_time = EXCLUDED.fill_time,
                        order_time = EXCLUDED.order_time,
                        trade_state = EXCLUDED.trade_state,
                        strategy = EXCLUDED.strategy,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        margin_used = EXCLUDED.margin_used,
                        stop_loss = EXCLUDED.stop_loss,
                        take_profit = EXCLUDED.take_profit,
                        distance_to_entry = EXCLUDED.distance_to_entry,
                        risk_amount = EXCLUDED.risk_amount,
                        potential_profit = EXCLUDED.potential_profit,
                        last_updated = EXCLUDED.last_updated,
                        stop_loss_price = EXCLUDED.stop_loss_price,
                        take_profit_price = EXCLUDED.take_profit_price,
                        risk_reward_ratio = EXCLUDED.risk_reward_ratio,
                        pips_moved = EXCLUDED.pips_moved,
                        exit_price = EXCLUDED.exit_price,
                        potential_risk_amount = EXCLUDED.potential_risk_amount,
                        potential_profit_amount = EXCLUDED.potential_profit_amount,
                        realized_pnl = EXCLUDED.realized_pnl,
                        spread = EXCLUDED.spread,
                        account_balance_before = EXCLUDED.account_balance_before,
                        market_session = EXCLUDED.market_session,
                        momentum_strength = EXCLUDED.momentum_strength,
                        analysis_type = EXCLUDED.analysis_type,
                        current_units = EXCLUDED.current_units,
                        state = EXCLUDED.state,
                        data_source = EXCLUDED.data_source,
                        sync_timestamp = EXCLUDED.sync_timestamp,
                        enhancement_timestamp = EXCLUDED.enhancement_timestamp,
                        open_time = EXCLUDED.open_time,
                        active_trade_duration = EXCLUDED.active_trade_duration,
                        pending_duration = EXCLUDED.pending_duration,
                        financing = EXCLUDED.financing,
                        commission = EXCLUDED.commission,
                        initial_units = EXCLUDED.initial_units,
                        exit_time = EXCLUDED.exit_time
                    """
                    
                    # Prepare batch insert data
                    batch_data = []
                    for trade in trades_data:
                        try:
                            # PROCESS ALL TRADES - NO DATE FILTERING
                            fill_time_raw = trade.get('fill_time')
                            
                            if fill_time_raw:
                                trade_date = None
                                if isinstance(fill_time_raw, datetime):
                                    trade_date = fill_time_raw.date()
                                elif isinstance(fill_time_raw, str):
                                    try:
                                        if fill_time_raw.endswith('Z'):
                                            fill_time_raw = fill_time_raw[:-1] + '+00:00'
                                        parsed_dt = datetime.fromisoformat(fill_time_raw)
                                        trade_date = parsed_dt.date()
                                    except ValueError:
                                        trade_date = "unparseable"
                                
                                logger.info(f"✅ PROCESSING trade from {trade_date}: {trade.get('trade_id', 'unknown')}")
                            
                            # Extract all fields matching RDS column order exactly (45 values)
                            
                            # DEFINITIVE TIMEZONE SOLUTION - MAKE EVERYTHING CONSISTENTLY TIMEZONE-AWARE
                            # The golden rule: Every datetime must be timezone-aware UTC before database storage
                            import datetime as dt
                            
                            def force_naive_eastern(dt_obj):
                                """
                                For timestamp WITHOUT time zone columns - force to naive Eastern.
                                Takes any datetime and returns timezone-naive Eastern datetime.
                                """
                                if not dt_obj:
                                    return None
                                    
                                try:
                                    import pytz
                                    eastern_tz = pytz.timezone('US/Eastern')
                                    
                                    if isinstance(dt_obj, dt.datetime):
                                        if dt_obj.tzinfo is None:
                                            # Naive - assume UTC and convert to Eastern
                                            utc_dt = dt_obj.replace(tzinfo=timezone.utc)
                                            eastern_dt = utc_dt.astimezone(eastern_tz)
                                            return eastern_dt.replace(tzinfo=None)  # Make naive
                                        else:
                                            # Convert to Eastern and strip timezone
                                            eastern_dt = dt_obj.astimezone(eastern_tz)
                                            return eastern_dt.replace(tzinfo=None)
                                    
                                    if isinstance(dt_obj, str):
                                        # Clean OANDA 'Z' suffix
                                        if dt_obj.endswith('Z'):
                                            dt_obj = dt_obj[:-1] + '+00:00'
                                        
                                        try:
                                            parsed = dt.datetime.fromisoformat(dt_obj)
                                            # Apply same logic recursively
                                            return force_naive_eastern(parsed)
                                        except ValueError:
                                            return None
                                    
                                    return None
                                except Exception:
                                    return None
                            
                            def force_aware_eastern(dt_obj):
                                """
                                For timestamp WITH time zone columns - force to timezone-aware Eastern.
                                Takes any datetime and returns timezone-aware Eastern datetime.
                                """
                                if not dt_obj:
                                    return None
                                    
                                try:
                                    import pytz
                                    eastern_tz = pytz.timezone('US/Eastern')
                                    
                                    if isinstance(dt_obj, dt.datetime):
                                        if dt_obj.tzinfo is None:
                                            # Naive - assume UTC and convert to Eastern
                                            utc_dt = dt_obj.replace(tzinfo=timezone.utc)
                                            return utc_dt.astimezone(eastern_tz)
                                        else:
                                            # Convert to Eastern
                                            return dt_obj.astimezone(eastern_tz)
                                    
                                    if isinstance(dt_obj, str):
                                        # Clean OANDA 'Z' suffix
                                        if dt_obj.endswith('Z'):
                                            dt_obj = dt_obj[:-1] + '+00:00'
                                        
                                        try:
                                            parsed = dt.datetime.fromisoformat(dt_obj)
                                            # Apply same logic recursively
                                            return force_aware_eastern(parsed)
                                        except ValueError:
                                            return None
                                    
                                    return None
                                except Exception:
                                    return None
                            
                            def force_naive_utc(dt_obj):
                                """
                                For timestamp WITHOUT time zone columns - don't convert, preserve as-is.
                                These fields are already in Eastern Time from enhanced_oanda_data_collection.py
                                """
                                if not dt_obj:
                                    return None
                                    
                                try:
                                    if isinstance(dt_obj, dt.datetime):
                                        if dt_obj.tzinfo is None:
                                            # Already naive - keep as-is (already Eastern)
                                            return dt_obj
                                        else:
                                            # Strip timezone but keep the time (already Eastern)
                                            return dt_obj.replace(tzinfo=None)
                                    
                                    if isinstance(dt_obj, str):
                                        # Clean OANDA 'Z' suffix
                                        if dt_obj.endswith('Z'):
                                            dt_obj = dt_obj[:-1] + '+00:00'
                                        
                                        try:
                                            parsed = dt.datetime.fromisoformat(dt_obj)
                                            # Apply same logic recursively
                                            return force_naive_utc(parsed)
                                        except ValueError:
                                            return None
                                    
                                    return None
                                except Exception:
                                    return None
                            
                            def force_aware_utc(dt_obj):
                                """
                                For timestamp WITH time zone columns - don't convert, preserve as-is.
                                These fields are already in Eastern Time from enhanced_oanda_data_collection.py
                                """
                                if not dt_obj:
                                    return None
                                    
                                try:
                                    if isinstance(dt_obj, dt.datetime):
                                        if dt_obj.tzinfo is None:
                                            # Naive - assume it's already Eastern, add Eastern timezone
                                            import pytz
                                            eastern_tz = pytz.timezone('US/Eastern')
                                            return eastern_tz.localize(dt_obj)
                                        else:
                                            # Already timezone-aware - keep as-is (already Eastern)
                                            return dt_obj
                                    
                                    if isinstance(dt_obj, str):
                                        # Clean OANDA 'Z' suffix
                                        if dt_obj.endswith('Z'):
                                            dt_obj = dt_obj[:-1] + '+00:00'
                                        
                                        try:
                                            parsed = dt.datetime.fromisoformat(dt_obj)
                                            # Apply same logic recursively
                                            return force_aware_utc(parsed)
                                        except ValueError:
                                            return None
                                    
                                    return None
                                except Exception:
                                    return None
                            
                            def get_current_aware_eastern():
                                """Returns current time as timezone-aware Eastern datetime."""
                                import pytz
                                eastern_tz = pytz.timezone('US/Eastern')
                                return dt.datetime.now(eastern_tz)
                                
                            def get_current_naive_eastern():
                                """Returns current time as timezone-naive Eastern datetime."""
                                import pytz
                                eastern_tz = pytz.timezone('US/Eastern')
                                eastern_time = dt.datetime.now(eastern_tz)
                                return eastern_time.replace(tzinfo=None)  # Remove timezone info
                            
                            # Generate current time for both naive and aware columns (Eastern Time)
                            now_eastern_naive = get_current_naive_eastern()  # For timestamp without time zone
                            now_eastern_aware = get_current_aware_eastern()  # For timestamp with time zone
                            
                            # Apply corrected timezone handling:
                            # - fill_time, order_time, open_time: Already Eastern from enhanced_oanda_data_collection.py (preserve as-is)
                            # - last_updated: Convert current time to Eastern
                            # - sync_timestamp, enhancement_timestamp: Convert current time to Eastern (working correctly)
                            
                            # REVERT: These fields were already Eastern Time, don't double-convert
                            fill_time_processed = force_naive_utc(trade.get('fill_time'))      # WITHOUT timezone (already Eastern)
                            order_time_processed = force_naive_utc(trade.get('order_time'))    # WITHOUT timezone (already Eastern)
                            open_time_processed = force_aware_utc(trade.get('open_time', trade.get('fill_time')))  # WITH timezone (already Eastern)
                            exit_time_processed = force_aware_utc(trade.get('exit_time'))      # WITH timezone (already Eastern)
                            
                            # DEBUG: Verify corrected timezone handling
                            logger.info(f"DEBUG TIMEZONE: now_eastern_naive (for last_updated) type={type(now_eastern_naive)}, tzinfo={getattr(now_eastern_naive, 'tzinfo', None)}")
                            logger.info(f"DEBUG TIMEZONE: now_eastern_aware (for sync/enhancement) type={type(now_eastern_aware)}, tzinfo={getattr(now_eastern_aware, 'tzinfo', None)}")
                            if fill_time_processed:
                                logger.info(f"DEBUG TIMEZONE: fill_time_processed (preserved as-is) type={type(fill_time_processed)}, tzinfo={getattr(fill_time_processed, 'tzinfo', None)}")
                            if order_time_processed:
                                logger.info(f"DEBUG TIMEZONE: order_time_processed (preserved as-is) type={type(order_time_processed)}, tzinfo={getattr(order_time_processed, 'tzinfo', None)}")
                            if open_time_processed:
                                logger.info(f"DEBUG TIMEZONE: open_time_processed (preserved as-is) type={type(open_time_processed)}, tzinfo={getattr(open_time_processed, 'tzinfo', None)}")
                            
                            row_data = (
                                # RDS Column order (1-10)
                                trade.get('trade_id', ''),                                     # 1: trade_id
                                trade.get('trade_id', ''),                                     # 2: oanda_order_id (use trade_id)
                                trade.get('instrument', ''),                                   # 3: instrument
                                trade.get('direction'),                                        # 4: direction
                                trade.get('units', 0),                                        # 5: units
                                trade.get('order_type', 'Market Order'),                      # 6: order_type
                                trade.get('entry_price', 0.0),                               # 7: entry_price
                                trade.get('current_price', 0.0),                             # 8: current_price
                                fill_time_processed,                                         # 9: fill_time (FIXED)
                                order_time_processed,                                        # 10: order_time (FIXED)
                                
                                # RDS Columns (11-20)
                                trade.get('state', 'OPEN'),                                  # 11: trade_state
                                trade.get('strategy'),                                       # 12: strategy
                                trade.get('unrealized_pl', 0.0),                            # 13: unrealized_pnl
                                trade.get('margin_used', 0.0),                               # 14: margin_used
                                trade.get('stop_loss_price'),                                # 15: stop_loss (legacy)
                                trade.get('take_profit_price'),                              # 16: take_profit (legacy)
                                trade.get('distance_to_entry', 0.0),                        # 17: distance_to_entry
                                trade.get('potential_risk_amount', 0.0),                     # 18: risk_amount (legacy)
                                trade.get('potential_profit_amount', 0.0),                   # 19: potential_profit (legacy)
                                now_eastern_naive,                                          # 20: last_updated (Eastern Time, naive)
                                
                                # RDS Columns (21-30)
                                trade.get('stop_loss_price'),                                # 21: stop_loss_price
                                trade.get('take_profit_price'),                              # 22: take_profit_price
                                trade.get('risk_reward_ratio'),                              # 23: risk_reward_ratio
                                trade.get('pips_moved', 0.0),                               # 24: pips_moved
                                trade.get('exit_price'),                                     # 25: exit_price
                                trade.get('potential_risk_amount', 0.0),                     # 26: potential_risk_amount
                                trade.get('potential_profit_amount', 0.0),                   # 27: potential_profit_amount
                                trade.get('realized_pnl'),                                   # 28: realized_pnl
                                trade.get('spread', 0.0),                                    # 29: spread
                                trade.get('account_balance_before', 0.0),                    # 30: account_balance_before
                                
                                # RDS Columns (31-40)
                                trade.get('market_session'),                                 # 31: market_session
                                trade.get('momentum_strength'),                              # 32: momentum_strength
                                trade.get('analysis_type'),                                  # 33: analysis_type
                                trade.get('current_units', trade.get('units', 0)),           # 34: current_units
                                trade.get('state', 'OPEN'),                                  # 35: state
                                trade.get('data_source', 'OANDA_FARGATE_RDS'),     # 36: data_source
                                now_eastern_aware,                                          # 37: sync_timestamp (Eastern Time)
                                now_eastern_aware,                                          # 38: enhancement_timestamp (Eastern Time)
                                open_time_processed,                                         # 39: open_time (FIXED)
                                trade.get('active_trade_duration', 0),                       # 40: active_trade_duration
                                
                                # RDS Columns (41-45)
                                trade.get('pending_duration', 0),                            # 41: pending_duration
                                trade.get('financing', 0.0),                                 # 42: financing
                                trade.get('commission', 0.0),                                # 43: commission
                                trade.get('initial_units', trade.get('units', 0)),           # 44: initial_units
                                exit_time_processed                                          # 45: exit_time (FIXED)
                            )
                            
                            # ULTIMATE FIX: Force ALL datetime parameters to be timezone-naive 
                            # This is a definitive workaround to resolve the PostgreSQL timezone mismatch
                            row_data_list = list(row_data)
                            for i, value in enumerate(row_data_list):
                                if isinstance(value, dt.datetime):
                                    if hasattr(value, 'tzinfo') and value.tzinfo is not None:
                                        # Force all datetimes to be timezone-naive by removing tzinfo
                                        row_data_list[i] = value.replace(tzinfo=None)
                                        logger.info(f"🔧 FIXED: Position {i+1} converted to naive: {row_data_list[i]}")
                                    else:
                                        logger.info(f"✅ Position {i+1} already naive: {value}")
                            row_data = tuple(row_data_list)
                            
                            batch_data.append(row_data)
                        
                        except Exception as e:
                            logger.error(f"Error preparing trade {trade.get('trade_id', 'unknown')}: {str(e)}")
                            continue
                    
                    if batch_data:
                        # Execute batch upsert
                        await conn.executemany(upsert_query, batch_data)
                        logger.info(f"✅ Stored {len(batch_data)} comprehensive active trades")
                        
                        # Log some statistics
                        await self._log_storage_statistics(conn, batch_data)
                        
                        return True
                    else:
                        logger.warning("No valid trade data to store")
                        return False
                        
            except Exception as e:
                logger.error(f"❌ Failed to store comprehensive active trades: {str(e)}", exc_info=True)
                return False
    
    async def _log_storage_statistics(self, conn, batch_data: List[tuple]):
        """Log statistics about stored data"""
        try:
            # Get current counts
            result = await conn.fetchrow("""
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN stop_loss_price IS NOT NULL THEN 1 END) as trades_with_sl,
                    COUNT(CASE WHEN take_profit_price IS NOT NULL THEN 1 END) as trades_with_tp,
                    COUNT(CASE WHEN risk_reward_ratio IS NOT NULL THEN 1 END) as trades_with_rr,
                    AVG(pips_moved) as avg_pips_moved,
                    SUM(unrealized_pnl) as total_unrealized_pnl
                FROM active_trades 
                WHERE enhancement_timestamp >= NOW() - INTERVAL '5 minutes'
            """)
            
            logger.info(f"📊 Storage Statistics:")
            logger.info(f"  - Total active trades: {result['total_trades']}")
            logger.info(f"  - Trades with Stop Loss: {result['trades_with_sl']}")
            logger.info(f"  - Trades with Take Profit: {result['trades_with_tp']}")
            logger.info(f"  - Trades with R:R Ratio: {result['trades_with_rr']}")
            logger.info(f"  - Average pips moved: {result['avg_pips_moved']:.1f}" if result['avg_pips_moved'] else "  - Average pips moved: 0")
            logger.info(f"  - Total unrealized P&L: ${result['total_unrealized_pnl']:.2f}" if result['total_unrealized_pnl'] else "  - Total unrealized P&L: $0.00")
            
        except Exception as e:
            logger.warning(f"Failed to log storage statistics: {str(e)}")
    
    def _parse_timestamp(self, timestamp_value) -> Optional[datetime]:
        """Parse various timestamp formats to datetime with robust timezone handling"""
        if not timestamp_value:
            return None
        
        try:    
            if isinstance(timestamp_value, datetime):
                # Ensure timezone awareness
                if timestamp_value.tzinfo is None:
                    return timestamp_value.replace(tzinfo=timezone.utc)
                return timestamp_value
                
            if isinstance(timestamp_value, str):
                try:
                    # Handle ISO format with timezone
                    if timestamp_value.endswith('Z'):
                        timestamp_value = timestamp_value[:-1] + '+00:00'
                    parsed = datetime.fromisoformat(timestamp_value)
                    # Ensure timezone awareness
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except ValueError:
                    try:
                        # Try without timezone and add UTC
                        parsed = datetime.fromisoformat(timestamp_value)
                        return parsed.replace(tzinfo=timezone.utc)
                    except ValueError:
                        logger.warning(f"Failed to parse timestamp: {timestamp_value}")
                        return None
            
            # For any other type, try to convert to string first
            if hasattr(timestamp_value, '__str__'):
                return self._parse_timestamp(str(timestamp_value))
                
        except Exception as e:
            logger.warning(f"Exception parsing timestamp {timestamp_value}: {str(e)}")
            return None
        
        return None
    
    def _safe_timestamp(self, timestamp_value) -> Optional[datetime]:
        """Ultra-safe timestamp parsing that ALWAYS returns UTC timezone-aware datetime or None"""
        if not timestamp_value:
            return None
        
        try:
            # If it's already a datetime
            if isinstance(timestamp_value, datetime):
                # ALWAYS ensure UTC timezone
                if timestamp_value.tzinfo is None:
                    # Naive datetime - assume UTC
                    return timestamp_value.replace(tzinfo=timezone.utc)
                else:
                    # Has timezone - convert to UTC
                    return timestamp_value.astimezone(timezone.utc)
            
            # If it's a string, parse it
            if isinstance(timestamp_value, str):
                # Clean up common formats
                if timestamp_value.endswith('Z'):
                    timestamp_value = timestamp_value[:-1] + '+00:00'
                
                # Try parsing
                from dateutil import parser
                parsed = parser.parse(timestamp_value)
                
                # Ensure UTC timezone
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                else:
                    return parsed.astimezone(timezone.utc)
            
            # For any other type, log and return None
            logger.warning(f"Unexpected timestamp type: {type(timestamp_value)} - {timestamp_value}")
            return None
            
        except Exception as e:
            logger.warning(f"Failed to parse timestamp {timestamp_value}: {str(e)}")
            return None

    def _timestamp_to_iso(self, timestamp_value) -> Optional[str]:
        """Convert any timestamp to ISO string format for safe database storage"""
        parsed = self._safe_timestamp(timestamp_value)
        if parsed:
            return parsed.isoformat()
        return None

    async def get_active_trades_summary(self) -> Optional[Dict[str, Any]]:
        """Get summary of active trades for monitoring"""
        if not self.connection_pool:
            return None
            
        async with self.connection_pool.acquire() as conn:
            try:
                result = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_active_trades,
                        COUNT(CASE WHEN stop_loss_price IS NOT NULL THEN 1 END) as trades_with_stop_loss,
                        COUNT(CASE WHEN take_profit_price IS NOT NULL THEN 1 END) as trades_with_take_profit,
                        COUNT(CASE WHEN risk_reward_ratio IS NOT NULL THEN 1 END) as trades_with_risk_reward,
                        AVG(pips_moved) as average_pips_moved,
                        SUM(unrealized_pnl) as total_unrealized_pnl,
                        SUM(margin_used) as total_margin_used,
                        COUNT(DISTINCT strategy) as unique_strategies,
                        COUNT(DISTINCT market_session) as active_sessions
                    FROM active_trades 
                    WHERE state = 'OPEN'
                """)
                
                return {
                    'total_active_trades': result['total_active_trades'],
                    'trades_with_stop_loss': result['trades_with_stop_loss'],
                    'trades_with_take_profit': result['trades_with_take_profit'],
                    'trades_with_risk_reward': result['trades_with_risk_reward'],
                    'average_pips_moved': float(result['average_pips_moved']) if result['average_pips_moved'] else 0.0,
                    'total_unrealized_pnl': float(result['total_unrealized_pnl']) if result['total_unrealized_pnl'] else 0.0,
                    'total_margin_used': float(result['total_margin_used']) if result['total_margin_used'] else 0.0,
                    'unique_strategies': result['unique_strategies'],
                    'active_sessions': result['active_sessions']
                }
                
            except Exception as e:
                logger.error(f"Failed to get active trades summary: {str(e)}")
                return None
    
    async def cleanup_stale_trades(self, hours_threshold: int = 24) -> bool:
        """Remove trades that haven't been updated recently (may have been closed)"""
        if not self.connection_pool:
            return False
            
        async with self.connection_pool.acquire() as conn:
            try:
                result = await conn.execute("""
                    DELETE FROM active_trades 
                    WHERE sync_timestamp < NOW() - INTERVAL '%s hours'
                    AND state = 'OPEN'
                """, hours_threshold)
                
                deleted_count = int(result.split()[-1]) if result else 0
                if deleted_count > 0:
                    logger.info(f"🧹 Cleaned up {deleted_count} stale active trades")
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to cleanup stale trades: {str(e)}")
                return False
    
    async def cleanup_inactive_trades(self, current_active_trade_ids: List[str]) -> bool:
        """Remove trades from RDS that are no longer active in OANDA"""
        if not self.connection_pool:
            return False
            
        async with self.connection_pool.acquire() as conn:
            try:
                if not current_active_trade_ids:
                    # If no active trades in OANDA, remove all from RDS
                    result = await conn.execute("DELETE FROM active_trades")
                    deleted_count = int(result.split()[-1]) if result else 0
                    logger.info(f"🧹 No active trades in OANDA - removed all {deleted_count} trades from RDS")
                    return True
                
                # Remove trades that are in RDS but not in current OANDA active trades
                placeholders = ','.join(f'${i+1}' for i in range(len(current_active_trade_ids)))
                result = await conn.execute(f"""
                    DELETE FROM active_trades 
                    WHERE trade_id NOT IN ({placeholders})
                """, *current_active_trade_ids)
                
                deleted_count = int(result.split()[-1]) if result else 0
                if deleted_count > 0:
                    logger.info(f"🧹 Removed {deleted_count} inactive trades from RDS (not in OANDA)")
                    logger.info(f"📊 Keeping {len(current_active_trade_ids)} active trades: {current_active_trade_ids}")
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to cleanup inactive trades: {str(e)}")
                return False
    
    async def bulk_upsert_pending_orders(self, orders: List[Dict[str, Any]]) -> bool:
        """Bulk upsert pending orders to RDS"""
        if not orders:
            logger.info("No pending orders to store")
            return True
            
        try:
            async with self.connection_pool.acquire() as conn:
                # Clear existing orders first (they change frequently)
                await conn.execute("DELETE FROM pending_orders")
                
                # Insert current orders
                insert_query = """
                    INSERT INTO pending_orders (
                        order_id, instrument, direction, units, order_price,
                        current_price, distance_to_market, order_type, time_in_force,
                        gtd_time, position_fill, trigger_condition, stop_loss,
                        take_profit, created_time, last_updated
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                """
                
                for order in orders:
                    await conn.execute(insert_query,
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
                    )
                
                logger.info(f"✅ Stored {len(orders)} pending orders in RDS")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to store pending orders in RDS: {str(e)}")
            return False
    
    async def bulk_upsert_closed_trades(self, closed_trades: List[Dict[str, Any]], last_sync_time: Optional[str] = None) -> bool:
        """
        Bulk upsert closed trades to RDS with incremental sync support
        
        Args:
            closed_trades: List of closed trade data from OANDA
            last_sync_time: Last sync timestamp to avoid duplicates
        """
        if not closed_trades:
            logger.info("No closed trades to store")
            return True
            
        if not self.connection_pool:
            logger.error("Database connection pool not initialized")
            return False
            
        try:
            async with self.connection_pool.acquire() as conn:
                async with conn.transaction():
                    stored_count = 0
                    
                    # Upsert each closed trade using existing table schema
                    upsert_query = """
                        INSERT INTO closed_trades (
                            trade_id, oanda_order_id, instrument, direction, units,
                            entry_price, exit_price, open_time, close_time, duration_hours,
                            gross_pnl, net_pnl, pips, close_reason, gain_loss,
                            strategy, status, return_risk_ratio, stop_loss, take_profit,
                            max_favorable, max_adverse, created_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                            $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
                            $21, $22, $23
                        )
                        ON CONFLICT (trade_id) DO UPDATE SET
                            exit_price = EXCLUDED.exit_price,
                            close_time = EXCLUDED.close_time,
                            gross_pnl = EXCLUDED.gross_pnl,
                            net_pnl = EXCLUDED.net_pnl,
                            pips = EXCLUDED.pips,
                            close_reason = EXCLUDED.close_reason,
                            gain_loss = EXCLUDED.gain_loss,
                            return_risk_ratio = EXCLUDED.return_risk_ratio,
                            created_at = EXCLUDED.created_at
                    """
                    
                    for trade in closed_trades:
                        try:
                            # Transform trade data for RDS storage
                            trade_data = self._transform_closed_trade_for_rds(trade)
                            if not trade_data:
                                continue
                            
                            await conn.execute(upsert_query, *trade_data)
                            stored_count += 1
                            
                        except Exception as e:
                            logger.error(f"Failed to store closed trade {trade.get('id', 'unknown')}: {str(e)}")
                            continue
                    
                    # Update last sync timestamp
                    if last_sync_time:
                        # Parse the ISO string to datetime for database storage
                        sync_time_dt = datetime.fromisoformat(last_sync_time.replace('Z', '+00:00')) if isinstance(last_sync_time, str) else last_sync_time
                        await conn.execute("""
                            INSERT INTO sync_metadata (sync_type, last_sync_time, records_processed)
                            VALUES ('closed_trades', $1, $2)
                            ON CONFLICT (sync_type) DO UPDATE SET
                                last_sync_time = EXCLUDED.last_sync_time,
                                records_processed = EXCLUDED.records_processed,
                                updated_at = NOW()
                        """, sync_time_dt, stored_count)
                    
                    logger.info(f"✅ Stored {stored_count} closed trades in RDS")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Failed to bulk upsert closed trades: {str(e)}", exc_info=True)
            return False
    
    def _transform_closed_trade_for_rds(self, trade: Dict[str, Any]) -> Optional[tuple]:
        """Transform OANDA closed trade data to RDS format"""
        try:
            # Basic trade info
            trade_id = trade.get('id')
            if not trade_id:
                return None
            
            instrument = trade.get('instrument', '')
            units = float(trade.get('initialUnits', 0))
            direction = 'Long' if units > 0 else 'Short'
            units = abs(units)
            
            # Prices and P&L
            entry_price = float(trade.get('price', 0))
            exit_price = float(trade.get('averageClosePrice', 0))
            realized_pnl = float(trade.get('realizedPL', 0))
            financing = float(trade.get('financing', 0))
            commission = float(trade.get('commission', 0))
            
            # Timestamps with Eastern Time conversion
            import pytz
            eastern_tz = pytz.timezone('US/Eastern')
            now_eastern = datetime.now(eastern_tz).replace(tzinfo=None)
            
            open_time = None
            if trade.get('openTime'):
                try:
                    utc_time = datetime.fromisoformat(trade.get('openTime').replace('Z', '+00:00'))
                    open_time = utc_time.astimezone(eastern_tz).replace(tzinfo=None)
                except:
                    pass
            
            close_time = None
            if trade.get('closeTime'):
                try:
                    utc_time = datetime.fromisoformat(trade.get('closeTime').replace('Z', '+00:00'))
                    close_time = utc_time.astimezone(eastern_tz).replace(tzinfo=None)
                except:
                    pass
            
            # Calculate trade duration
            active_duration = 0
            if open_time and close_time:
                duration_delta = close_time - open_time
                active_duration = int(duration_delta.total_seconds() / 60)  # minutes
            
            # Extract stop loss, take profit, account balance, and margin data
            stop_loss_price = None
            take_profit_price = None
            account_balance_before = None
            margin_used = None
            
            # PRIORITY 1: Get from Redis trade mapping (most reliable - direct from order placement)
            import asyncio
            loop = asyncio.get_event_loop()
            try:
                redis_trade_data = loop.run_until_complete(
                    self._get_trade_data_from_redis(trade_id, instrument)
                )
                if redis_trade_data:
                    stop_loss_price = redis_trade_data.get('stop_loss')
                    take_profit_price = redis_trade_data.get('take_profit')
                    account_balance_before = redis_trade_data.get('account_balance_before')
                    margin_used = redis_trade_data.get('margin_used')
                    logger.info(f"✅ Retrieved complete trade data from Redis: SL={stop_loss_price}, TP={take_profit_price}, Bal={account_balance_before}, Margin={margin_used}")
            except Exception as e:
                logger.debug(f"Could not retrieve trade data from Redis: {str(e)}")
            
            # PRIORITY 2: Fallback to OANDA trade data using proven Airtable extraction logic
            if not stop_loss_price or not take_profit_price:
                
                # Extract stop loss using Airtable-proven method
                if not stop_loss_price:
                    # Method 1: Direct stopLossOrder field
                    stop_loss_order = trade.get('stopLossOrder', {})
                    if stop_loss_order and stop_loss_order.get('price'):
                        stop_loss_price = float(stop_loss_order.get('price', 0))
                    else:
                        # Method 2: stopLossOnFill from trade fills
                        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
                        if trade_fills:
                            stop_loss = trade_fills.get('stopLossOnFill', {})
                            if stop_loss and stop_loss.get('price'):
                                stop_loss_price = float(stop_loss.get('price', 0))
                
                # Extract take profit using Airtable-proven method
                if not take_profit_price:
                    # Method 1: Direct takeProfitOrder field
                    take_profit_order = trade.get('takeProfitOrder', {})
                    if take_profit_order and take_profit_order.get('price'):
                        take_profit_price = float(take_profit_order.get('price', 0))
                    else:
                        # Method 2: takeProfitOnFill from trade fills
                        trade_fills = trade.get('tradeOpened', {}).get('tradeOpened', {})
                        if trade_fills:
                            take_profit = trade_fills.get('takeProfitOnFill', {})
                            if take_profit and take_profit.get('price'):
                                take_profit_price = float(take_profit.get('price', 0))
                
                logger.info(f"✅ Extracted using Airtable logic for trade {trade_id}: SL={stop_loss_price}, TP={take_profit_price}")
            
            close_reason = self._determine_close_reason(trade)
            
            # Calculate pips moved
            pips_moved = self._calculate_closed_trade_pips(entry_price, exit_price, instrument, direction)
            
            # Strategy identification - use StrategyMapper (async lookup happens later)
            from .strategy_mapper import StrategyMapper
            strategy_mapper = StrategyMapper()
            
            # Add debug logging to see trade structure
            logger.debug(f"Closed trade data for strategy mapping: {trade}")
            
            strategy = strategy_mapper.get_strategy_name(trade)
            if not strategy:
                    # Enhanced fallback based on closed trades characteristics
                    strategy = self._infer_strategy_from_closed_trade(trade)
            
            logger.debug(f"Final strategy for trade {trade.get('id')}: {strategy}")
            
            # Market session (simplified)
            market_session = 'UNKNOWN'
            if close_time:
                hour = close_time.hour
                if 8 <= hour < 17:
                    market_session = 'LONDON_NY_OVERLAP'
                elif 13 <= hour < 21:
                    market_session = 'NEW_YORK'
            
            # Calculate risk/reward ratio if we have SL and TP
            risk_reward_ratio = None
            if stop_loss_price and take_profit_price and entry_price:
                try:
                    # Calculate potential risk (distance to stop loss)
                    if direction == 'Long':
                        potential_risk = abs(entry_price - stop_loss_price) * units
                        potential_profit = abs(take_profit_price - entry_price) * units
                    else:  # Short
                        potential_risk = abs(stop_loss_price - entry_price) * units
                        potential_profit = abs(entry_price - take_profit_price) * units
                    
                    if potential_risk > 0:
                        risk_reward_ratio = round(potential_profit / potential_risk, 2)
                        logger.debug(f"Calculated RRR for trade {trade_id}: {risk_reward_ratio} (Profit: {potential_profit}, Risk: {potential_risk})")
                except Exception as e:
                    logger.warning(f"Failed to calculate risk/reward ratio for trade {trade_id}: {str(e)}")
                    risk_reward_ratio = None
            
            # Calculate duration in hours
            duration_hours = 0.0
            if active_duration > 0:
                duration_hours = round(active_duration / 60.0, 2)  # Convert minutes to hours
            
            # Calculate gain/loss
            gain_loss = 'Gain' if realized_pnl > 0 else 'Loss' if realized_pnl < 0 else 'Breakeven'
            
            # Map to existing table schema (23 columns)
            return (
                trade_id,                           # 1: trade_id
                trade_id,                           # 2: oanda_order_id  
                instrument,                         # 3: instrument
                direction,                          # 4: direction
                int(units),                         # 5: units
                entry_price,                        # 6: entry_price
                exit_price,                         # 7: exit_price
                open_time,                          # 8: open_time
                close_time,                         # 9: close_time
                duration_hours,                     # 10: duration_hours
                realized_pnl,                       # 11: gross_pnl
                realized_pnl - financing - commission,  # 12: net_pnl (subtract fees)
                pips_moved,                         # 13: pips
                close_reason,                       # 14: close_reason
                gain_loss,                          # 15: gain_loss
                strategy,                           # 16: strategy
                'CLOSED',                           # 17: status
                risk_reward_ratio,                  # 18: return_risk_ratio
                stop_loss_price,                    # 19: stop_loss
                take_profit_price,                  # 20: take_profit
                0.0,                               # 21: max_favorable (not available from OANDA)
                0.0,                               # 22: max_adverse (not available from OANDA)
                now_eastern                         # 23: created_at
            )
            
        except Exception as e:
            logger.error(f"Failed to transform closed trade {trade.get('id', 'unknown')}: {str(e)}")
            return None
    
    def _calculate_closed_trade_pips(self, entry_price: float, exit_price: float, instrument: str, direction: str) -> float:
        """Calculate pips moved for closed trade"""
        if not entry_price or not exit_price:
            return 0.0
        
        # Pip values
        pip_value = 0.01 if '_JPY' in instrument else 0.0001
        price_diff = exit_price - entry_price
        
        # For short positions, flip the sign
        if direction.lower() == 'short':
            price_diff = -price_diff
        
        return round(price_diff / pip_value, 1)
    
    def _determine_close_reason(self, trade: Dict[str, Any]) -> str:
        """Determine the close reason from OANDA trade data"""
        
        # Check closing transaction IDs for patterns
        closing_transactions = trade.get('closingTransactionIDs', [])
        
        # If no closing transactions, assume manual close
        if not closing_transactions:
            return 'MANUAL_CLOSE'
        
        # Try to determine from price action vs original orders
        entry_price = float(trade.get('price', 0))
        exit_price = float(trade.get('averageClosePrice', 0))
        
        # Get original stop loss and take profit if available
        initial_units = float(trade.get('initialUnits', 0))
        direction = 'Long' if initial_units > 0 else 'Short'
        
        # Check if trade had protective orders (common pattern)
        if closing_transactions and len(closing_transactions) == 1:
            # Single transaction close - likely stop or target hit
            price_diff = exit_price - entry_price
            
            if direction == 'Long':
                if price_diff > 0:
                    return 'TAKE_PROFIT'  # Profit target hit
                elif price_diff < -0.0010:  # Significant loss (10+ pips for most pairs)
                    return 'STOP_LOSS'
                else:
                    return 'MANUAL_CLOSE'
            else:  # Short
                if price_diff < 0:
                    return 'TAKE_PROFIT'  # Profit target hit  
                elif price_diff > 0.0010:  # Significant loss
                    return 'STOP_LOSS'
                else:
                    return 'MANUAL_CLOSE'
        
        # Multiple closing transactions - likely partial or manual close
        if len(closing_transactions) > 1:
            return 'PARTIAL_CLOSE'
        
        # Market close during weekends/holidays
        close_time = trade.get('closeTime', '')
        if close_time and ('friday' in close_time.lower() or 'weekend' in close_time.lower()):
            return 'MARKET_CLOSE'
        
        return 'MANUAL_CLOSE'
    
    def _infer_strategy_from_closed_trade(self, trade: Dict[str, Any]) -> str:
        """Infer strategy name from closed trade characteristics"""
        
        # Try to extract from any comments or extensions first
        if 'clientExtensions' in trade:
            client_ext = trade.get('clientExtensions', {})
            comment = str(client_ext.get('comment', '')).lower()
            if 'dime' in comment or 'dc' in comment:
                return 'Dime Curve DC H1 Dual Limit 100SL'
            elif 'penny' in comment or 'pc' in comment:
                return 'Penny Curve PC H1 Dual Limit 20SL'
            elif 'quarter' in comment or 'qc' in comment:
                return 'Quarter Curve QC H1 Dual Limit 50SL'
        
        # Analyze trade characteristics
        try:
            units = abs(float(trade.get('initialUnits', 0)))
            realized_pnl = float(trade.get('realizedPL', 0))
            entry_price = float(trade.get('price', 0))
            
            # Based on units size (common pattern from our system)
            if units > 0:
                # Very small positions (< 100) likely test trades -> Quarter Curve
                if units < 100:
                    return 'Quarter Curve QC H1 Dual Limit 50SL'
                # Small positions (100-1000) -> Penny Curve  
                elif units < 1000:
                    return 'Penny Curve PC H1 Dual Limit 20SL'
                # Larger positions -> Dime Curve (most common)
                else:
                    return 'Dime Curve DC H1 Dual Limit 100SL'
            
        except (ValueError, TypeError):
            pass
        
        # Default to most commonly used strategy based on our system
        return 'Dime Curve DC H1 Dual Limit 100SL'
    
    async def _get_strategy_from_active_trade_data(self, trade_id: str) -> Optional[str]:
        """
        Get strategy name from previously stored active trade data
        This ensures strategy information flows: Lambda → Redis → Fargate → RDS
        """
        if not trade_id or not self.connection_pool:
            return None
            
        try:
            async with self.connection_pool.acquire() as conn:
                # Check if this trade exists in active_trades table with strategy info
                result = await conn.fetchrow("""
                    SELECT strategy FROM active_trades 
                    WHERE trade_id = $1 
                    AND strategy IS NOT NULL 
                    AND strategy != 'Unknown Strategy'
                    ORDER BY last_updated DESC
                    LIMIT 1
                """, trade_id)
                
                if result and result['strategy']:
                    logger.info(f"✅ Found strategy from active trade data: {trade_id} → {result['strategy']}")
                    return result['strategy']
                    
                # Also check if we have historical data in our Redis cache
                # This would require Redis connection - implement if needed
                logger.debug(f"No strategy found in active_trades for trade {trade_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting strategy from active trade data for {trade_id}: {str(e)}")
            return None
    
    async def fix_unknown_strategies(self) -> bool:
        """
        Automatically fix any closed trades with 'Unknown Strategy'
        Uses Lambda → Redis → Fargate → RDS strategy flow
        """
        if not self.connection_pool:
            logger.error("Database connection pool not initialized")
            return False
            
        try:
            async with self.connection_pool.acquire() as conn:
                # Get all trades with Unknown Strategy
                unknown_trades = await conn.fetch("""
                    SELECT trade_id, units, instrument
                    FROM closed_trades 
                    WHERE strategy = 'Unknown Strategy'
                    ORDER BY trade_id
                """)
                
                if not unknown_trades:
                    logger.debug("✅ No trades with 'Unknown Strategy' found")
                    return True
                
                logger.info(f"🔧 Found {len(unknown_trades)} trades with 'Unknown Strategy' - fixing automatically...")
                
                fixed_count = 0
                fallback_count = 0
                
                async with conn.transaction():
                    for trade in unknown_trades:
                        trade_id = trade['trade_id']
                        
                        # First, try to get strategy from active_trades table
                        strategy = await self._get_strategy_from_active_trade_data(trade_id)
                        
                        if not strategy:
                            # Fallback to units-based inference
                            units = abs(int(trade['units']))
                            if units < 100:
                                strategy = 'Quarter Curve QC H1 Dual Limit 50SL'
                            elif units < 1000:
                                strategy = 'Penny Curve PC H1 Dual Limit 20SL'
                            else:
                                strategy = 'Dime Curve DC H1 Dual Limit 100SL'
                            fallback_count += 1
                        else:
                            fixed_count += 1
                        
                        # Update the trade with the correct strategy
                        await conn.execute("""
                            UPDATE closed_trades 
                            SET strategy = $1 
                            WHERE trade_id = $2
                        """, strategy, trade_id)
                
                logger.info(f"✅ Fixed {fixed_count} trades from active trade data, {fallback_count} from fallback logic")
                
                # Show updated distribution
                distribution = await conn.fetch("""
                    SELECT strategy, COUNT(*) as count
                    FROM closed_trades 
                    GROUP BY strategy
                    ORDER BY count DESC
                """)
                
                logger.info("📈 Updated strategy distribution:")
                for row in distribution:
                    logger.info(f"  {row['strategy']}: {row['count']} trades")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to fix unknown strategies: {str(e)}")
            return False
    
    async def get_last_closed_trades_sync_time(self) -> Optional[str]:
        """Get the last sync timestamp for closed trades to enable incremental sync"""
        if not self.connection_pool:
            return None
            
        try:
            async with self.connection_pool.acquire() as conn:
                result = await conn.fetchrow("""
                    SELECT last_sync_time 
                    FROM sync_metadata 
                    WHERE sync_type = 'closed_trades'
                """)
                
                if result:
                    return result['last_sync_time']
                return None
                
        except Exception as e:
            logger.error(f"Failed to get last closed trades sync time: {str(e)}")
            return None
    
    async def create_sync_metadata_table_if_not_exists(self):
        """Create sync metadata table for tracking incremental syncs"""
        if not self.connection_pool:
            return False
            
        try:
            async with self.connection_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sync_metadata (
                        sync_type VARCHAR(50) PRIMARY KEY,
                        last_sync_time TIMESTAMP,
                        records_processed INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                logger.info("✅ Sync metadata table ready")
                return True
                
        except Exception as e:
            logger.error(f"Failed to create sync metadata table: {str(e)}")
            return False

    async def close_connection_pool(self):
        """Close the database connection pool"""
        if self.connection_pool:
            await self.connection_pool.close()
            logger.info("Database connection pool closed")
    
    def _extract_stop_loss_from_trade(self, trade: Dict[str, Any]) -> Optional[float]:
        """Extract stop loss price from various locations in trade data"""
        # Try different possible locations for stop loss data
        try:
            # Method 1: Direct stopLoss field
            if 'stopLoss' in trade and trade['stopLoss']:
                return float(trade['stopLoss'])
            
            # Method 2: In trade extensions or metadata
            if 'clientExtensions' in trade:
                ext = trade.get('clientExtensions', {})
                if 'tag' in ext and 'sl=' in ext['tag'].lower():
                    # Extract from tag like "sl=1.3950"
                    import re
                    match = re.search(r'sl=([0-9.]+)', ext['tag'].lower())
                    if match:
                        return float(match.group(1))
            
            # Method 3: Try to get from Redis strategy signals
            trade_id = trade.get('id')
            if trade_id and hasattr(self, 'redis_manager'):
                try:
                    # Look for stored signals in Redis that match this trade
                    import asyncio
                    loop = asyncio.get_event_loop()
                    stop_loss = loop.run_until_complete(
                        self._get_stop_loss_from_redis(trade_id, trade.get('instrument'))
                    )
                    if stop_loss:
                        logger.info(f"✅ Retrieved stop loss from Redis for trade {trade_id}: {stop_loss}")
                        return stop_loss
                except Exception as e:
                    logger.debug(f"Could not retrieve stop loss from Redis: {str(e)}")
            
            # Method 4: From closing transactions (more complex parsing)
            closing_transactions = trade.get('closingTransactionIDs', [])
            if closing_transactions:
                # This would require additional API calls to get transaction details
                # For now, return None and rely on the primary extraction method
                pass
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting stop loss: {str(e)}")
            return None
    
    def _extract_take_profit_from_trade(self, trade: Dict[str, Any]) -> Optional[float]:
        """Extract take profit price from various locations in trade data"""
        # Try different possible locations for take profit data
        try:
            # Method 1: Direct takeProfit field
            if 'takeProfit' in trade and trade['takeProfit']:
                return float(trade['takeProfit'])
            
            # Method 2: In trade extensions or metadata
            if 'clientExtensions' in trade:
                ext = trade.get('clientExtensions', {})
                if 'tag' in ext and 'tp=' in ext['tag'].lower():
                    # Extract from tag like "tp=1.3650"
                    import re
                    match = re.search(r'tp=([0-9.]+)', ext['tag'].lower())
                    if match:
                        return float(match.group(1))
            
            # Method 3: Try to get from Redis strategy signals
            trade_id = trade.get('id')
            if trade_id and hasattr(self, 'redis_manager'):
                try:
                    # Look for stored signals in Redis that match this trade
                    import asyncio
                    loop = asyncio.get_event_loop()
                    take_profit = loop.run_until_complete(
                        self._get_take_profit_from_redis(trade_id, trade.get('instrument'))
                    )
                    if take_profit:
                        logger.info(f"✅ Retrieved take profit from Redis for trade {trade_id}: {take_profit}")
                        return take_profit
                except Exception as e:
                    logger.debug(f"Could not retrieve take profit from Redis: {str(e)}")
            
            # Method 4: From closing transactions (more complex parsing)
            closing_transactions = trade.get('closingTransactionIDs', [])
            if closing_transactions:
                # This would require additional API calls to get transaction details
                # For now, return None and rely on the primary extraction method
                pass
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting take profit: {str(e)}")
            return None
    
    async def _get_stop_loss_from_redis(self, trade_id: str, instrument: str) -> Optional[float]:
        """Get stop loss from Redis using direct trade ID mapping"""
        try:
            if not hasattr(self, 'redis_manager') or not self.redis_manager:
                return None
            
            # Method 1: Direct trade ID mapping (most reliable)
            trade_mapping_key = f"trade:sl_tp:{trade_id}"
            try:
                # Get connection for this currency pair
                conn = await self.redis_manager.get_connection_for_pair(instrument)
                trade_data = await conn.get(trade_mapping_key)
                
                if trade_data:
                    import json
                    trade_info = json.loads(trade_data)
                    stop_loss = trade_info.get('stop_loss')
                    if stop_loss and float(stop_loss) > 0:
                        logger.info(f"✅ Found stop loss via direct trade mapping {trade_mapping_key}: {stop_loss}")
                        # Store the full trade info for later use
                        self._cached_trade_info = trade_info
                        return float(stop_loss)
            except Exception as e:
                logger.debug(f"Error getting direct trade mapping {trade_mapping_key}: {str(e)}")
            
            # Method 2: Fallback to strategy signals (less reliable)
            strategies = [
                'dime_curve_dc_h1_all_dual_limit_100sl', 
                'quarter_curve_qc_h1_all_dual_limit_75sl',
                'penny_curve_pc_h1_all_dual_limit_20sl'
            ]
            
            for strategy in strategies:
                signal_key = f"signal:latest:{strategy}:{instrument}"
                try:
                    # Get connection for this currency pair
                    conn = await self.redis_manager.get_connection_for_pair(instrument)
                    signal_data = await conn.get(signal_key)
                    
                    if signal_data:
                        import json
                        signal = json.loads(signal_data)
                        stop_loss = signal.get('stop_loss')
                        if stop_loss and float(stop_loss) > 0:
                            logger.info(f"✅ Found stop loss in Redis signal {signal_key}: {stop_loss}")
                            return float(stop_loss)
                except Exception as e:
                    logger.debug(f"Error parsing Redis signal {signal_key}: {str(e)}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error getting stop loss from Redis: {str(e)}")
            return None
    
    async def _get_take_profit_from_redis(self, trade_id: str, instrument: str) -> Optional[float]:
        """Get take profit from Redis using direct trade ID mapping"""
        try:
            if not hasattr(self, 'redis_manager') or not self.redis_manager:
                return None
            
            # Method 1: Direct trade ID mapping (most reliable)
            trade_mapping_key = f"trade:sl_tp:{trade_id}"
            try:
                # Get connection for this currency pair
                conn = await self.redis_manager.get_connection_for_pair(instrument)
                trade_data = await conn.get(trade_mapping_key)
                
                if trade_data:
                    import json
                    trade_info = json.loads(trade_data)
                    take_profit = trade_info.get('take_profit')
                    if take_profit and float(take_profit) > 0:
                        logger.info(f"✅ Found take profit via direct trade mapping {trade_mapping_key}: {take_profit}")
                        return float(take_profit)
            except Exception as e:
                logger.debug(f"Error getting direct trade mapping {trade_mapping_key}: {str(e)}")
            
            # Method 2: Fallback to strategy signals (less reliable)
            strategies = [
                'dime_curve_dc_h1_all_dual_limit_100sl', 
                'quarter_curve_qc_h1_all_dual_limit_75sl',
                'penny_curve_pc_h1_all_dual_limit_20sl'
            ]
            
            for strategy in strategies:
                signal_key = f"signal:latest:{strategy}:{instrument}"
                try:
                    # Get connection for this currency pair
                    conn = await self.redis_manager.get_connection_for_pair(instrument)
                    signal_data = await conn.get(signal_key)
                    
                    if signal_data:
                        import json
                        signal = json.loads(signal_data)
                        take_profit = signal.get('take_profit')
                        if take_profit and float(take_profit) > 0:
                            logger.info(f"✅ Found take profit in Redis signal {signal_key}: {take_profit}")
                            return float(take_profit)
                except Exception as e:
                    logger.debug(f"Error parsing Redis signal {signal_key}: {str(e)}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error getting take profit from Redis: {str(e)}")
            return None
    
    async def _get_trade_data_from_redis(self, trade_id: str, instrument: str) -> Optional[Dict[str, Any]]:
        """Get complete trade data from Redis using direct trade ID mapping"""
        try:
            if not hasattr(self, 'redis_manager') or not self.redis_manager:
                return None
            
            # Direct trade ID mapping (most reliable)
            trade_mapping_key = f"trade:sl_tp:{trade_id}"
            try:
                # Get connection for this currency pair
                conn = await self.redis_manager.get_connection_for_pair(instrument)
                trade_data = await conn.get(trade_mapping_key)
                
                if trade_data:
                    import json
                    trade_info = json.loads(trade_data)
                    logger.info(f"✅ Found complete trade data via direct mapping {trade_mapping_key}")
                    return trade_info
            except Exception as e:
                logger.debug(f"Error getting direct trade mapping {trade_mapping_key}: {str(e)}")
            
            return None
            
        except Exception as e:
            logger.debug(f"Error getting trade data from Redis: {str(e)}")
            return None

    async def cleanup_inactive_trades(self):
        """Move stale trades from active_trades to closed_trades table
        
        This function:
        1. Gets all trades from OANDA API
        2. Compares with trades in RDS active_trades table
        3. Moves any trades that exist in RDS but not in OANDA to closed_trades
        
        This ensures active_trades only contains truly active trades.
        """
        try:
            logger.info("🧹 Starting cleanup of inactive trades from RDS")
            
            # Get active trades from OANDA
            from .oanda_client import OandaClient
            from .config import Settings
            
            settings = Settings()
            oanda_client = OandaClient(settings)
            
            # Get current active trades from OANDA
            oanda_result = await oanda_client.get_open_trades()
            if not oanda_result or 'trades' not in oanda_result:
                logger.warning("Could not fetch active trades from OANDA for cleanup")
                return
            
            oanda_trade_ids = {trade['id'] for trade in oanda_result['trades']}
            logger.info(f"Found {len(oanda_trade_ids)} active trades in OANDA: {oanda_trade_ids}")
            
            async with self.connection_pool.acquire() as conn:
                # Get all trades from RDS active_trades table
                rds_trades = await conn.fetch("SELECT * FROM active_trades")
                rds_trade_ids = {str(row['trade_id']) for row in rds_trades}
                logger.info(f"Found {len(rds_trade_ids)} trades in RDS active_trades: {rds_trade_ids}")
                
                # Find trades that are in RDS but not in OANDA (these have been closed)
                stale_trade_ids = rds_trade_ids - oanda_trade_ids
                
                if stale_trade_ids:
                    logger.info(f"📦 Found {len(stale_trade_ids)} closed trades to move: {stale_trade_ids}")
                    
                    # Move stale trades to closed_trades
                    for trade_id in stale_trade_ids:
                        # Get the full trade data
                        trade_data = await conn.fetchrow(
                            "SELECT * FROM active_trades WHERE trade_id = $1",
                            trade_id
                        )
                        
                        if trade_data:
                            # Prepare data for closed_trades table
                            closed_trade_data = dict(trade_data)
                            
                            # Set exit time to current time and mark as CLOSED
                            from datetime import datetime
                            closed_trade_data['exit_time'] = datetime.utcnow()
                            closed_trade_data['status'] = 'CLOSED'
                            
                            # If we don't have exit_price, use current_price
                            if 'exit_price' not in closed_trade_data or closed_trade_data['exit_price'] is None:
                                closed_trade_data['exit_price'] = closed_trade_data.get('current_price', closed_trade_data.get('entry_price'))
                            
                            # Calculate realized P&L if not set
                            if 'realized_pnl' not in closed_trade_data or closed_trade_data['realized_pnl'] is None:
                                closed_trade_data['realized_pnl'] = closed_trade_data.get('unrealized_pl', 0.0)
                            
                            # Insert into closed_trades - only use columns that exist in both tables
                            try:
                                # Map active_trades columns to closed_trades columns correctly
                                mapped_data = {
                                    'trade_id': closed_trade_data.get('trade_id'),
                                    'oanda_order_id': closed_trade_data.get('oanda_order_id'),
                                    'instrument': closed_trade_data.get('instrument'),
                                    'direction': closed_trade_data.get('direction'),
                                    'units': closed_trade_data.get('units'),
                                    'entry_price': closed_trade_data.get('entry_price'),
                                    'exit_price': closed_trade_data.get('exit_price'),
                                    'open_time': closed_trade_data.get('open_time'),
                                    'close_time': closed_trade_data.get('exit_time'),
                                    'gross_pnl': closed_trade_data.get('unrealized_pnl'),
                                    'net_pnl': closed_trade_data.get('unrealized_pnl'),
                                    'strategy': closed_trade_data.get('strategy'),
                                    'status': 'CLOSED',
                                    'order_type': closed_trade_data.get('order_type'),
                                    'current_price': closed_trade_data.get('current_price'),
                                    'fill_time': closed_trade_data.get('fill_time'),
                                    'order_time': closed_trade_data.get('order_time'),
                                    'trade_state': closed_trade_data.get('trade_state'),
                                    'unrealized_pnl': closed_trade_data.get('unrealized_pnl'),
                                    'margin_used': closed_trade_data.get('margin_used'),
                                    'distance_to_entry': closed_trade_data.get('distance_to_entry'),
                                    'risk_amount': closed_trade_data.get('risk_amount'),
                                    'potential_profit': closed_trade_data.get('potential_profit'),
                                    'last_updated': closed_trade_data.get('last_updated'),
                                    'stop_loss_price': closed_trade_data.get('stop_loss_price'),
                                    'take_profit_price': closed_trade_data.get('take_profit_price'),
                                    'risk_reward_ratio': closed_trade_data.get('risk_reward_ratio'),
                                    'pips_moved': closed_trade_data.get('pips_moved'),
                                    'potential_risk_amount': closed_trade_data.get('potential_risk_amount'),
                                    'potential_profit_amount': closed_trade_data.get('potential_profit_amount'),
                                    'spread': closed_trade_data.get('spread'),
                                    'account_balance_before': closed_trade_data.get('account_balance_before'),
                                    'market_session': closed_trade_data.get('market_session'),
                                    'momentum_strength': closed_trade_data.get('momentum_strength'),
                                    'analysis_type': closed_trade_data.get('analysis_type'),
                                    'current_units': closed_trade_data.get('current_units'),
                                    'state': closed_trade_data.get('state'),
                                    'data_source': closed_trade_data.get('data_source'),
                                    'sync_timestamp': closed_trade_data.get('sync_timestamp'),
                                    'enhancement_timestamp': closed_trade_data.get('enhancement_timestamp'),
                                    'active_trade_duration': closed_trade_data.get('active_trade_duration'),
                                    'pending_duration': closed_trade_data.get('pending_duration'),
                                    'financing': closed_trade_data.get('financing'),
                                    'commission': closed_trade_data.get('commission'),
                                    'initial_units': closed_trade_data.get('initial_units'),
                                    'realized_pnl': closed_trade_data.get('realized_pnl', closed_trade_data.get('unrealized_pnl'))
                                }
                                
                                # Remove None values
                                mapped_data = {k: v for k, v in mapped_data.items() if v is not None}
                                
                                columns = ', '.join(mapped_data.keys())
                                placeholders = ', '.join(f'${i+1}' for i in range(len(mapped_data)))
                                values = list(mapped_data.values())
                                
                                logger.info(f"Inserting {len(mapped_data)} mapped columns into closed_trades for trade {trade_id}")
                                
                                await conn.execute(f"""
                                    INSERT INTO closed_trades ({columns})
                                    VALUES ({placeholders})
                                    ON CONFLICT (trade_id) DO UPDATE SET
                                        status = EXCLUDED.status,
                                        close_time = EXCLUDED.close_time,
                                        exit_price = EXCLUDED.exit_price,
                                        realized_pnl = EXCLUDED.realized_pnl
                                """, *values)
                                
                                logger.info(f"✅ Moved trade {trade_id} to closed_trades with P&L: {closed_trade_data.get('realized_pnl', 0)}")
                            except Exception as e:
                                logger.error(f"Error inserting trade {trade_id} into closed_trades: {str(e)}")
                                continue
                            
                            # Remove from active_trades
                            await conn.execute(
                                "DELETE FROM active_trades WHERE trade_id = $1",
                                trade_id
                            )
                            logger.info(f"Removed trade {trade_id} from active_trades")
                    
                    logger.info(f"✅ Cleanup complete: moved {len(stale_trade_ids)} trades to closed_trades")
                else:
                    logger.info("✅ No stale trades found - active_trades table is clean")
                
                # Log final state
                remaining_trades = await conn.fetch("SELECT trade_id FROM active_trades")
                remaining_ids = {str(row['trade_id']) for row in remaining_trades}
                logger.info(f"📊 Final state: {len(remaining_ids)} active trades in RDS: {remaining_ids}")
                
                # Log closed trades count
                closed_count = await conn.fetchval("SELECT COUNT(*) FROM closed_trades")
                logger.info(f"📊 Total closed trades in database: {closed_count}")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup_inactive_trades: {str(e)}", exc_info=True)
    
    async def preview_cleanup_inactive_trades(self):
        """Preview what trades would be moved from active_trades to closed_trades
        
        This is a dry-run version that shows what the cleanup would do without actually moving anything.
        Returns a dict with preview information.
        """
        try:
            logger.info("🔍 Previewing cleanup of inactive trades (DRY RUN)")
            
            # Get active trades from OANDA
            from .oanda_client import OandaClient
            from .config import Settings
            
            settings = Settings()
            oanda_client = OandaClient(settings)
            
            # Get current active trades from OANDA
            oanda_result = await oanda_client.get_open_trades()
            if not oanda_result or 'trades' not in oanda_result:
                return {
                    "status": "error",
                    "message": "Could not fetch active trades from OANDA for preview"
                }
            
            oanda_trade_ids = {trade['id'] for trade in oanda_result['trades']}
            
            async with self.connection_pool.acquire() as conn:
                # Get all trades from RDS active_trades table
                rds_trades = await conn.fetch("SELECT * FROM active_trades")
                rds_trade_ids = {str(row['trade_id']) for row in rds_trades}
                
                # Find trades that are in RDS but not in OANDA (these have been closed)
                stale_trade_ids = rds_trade_ids - oanda_trade_ids
                
                # Get detailed information about stale trades
                stale_trade_details = []
                for trade_id in stale_trade_ids:
                    trade_data = await conn.fetchrow(
                        "SELECT trade_id, instrument, direction, units, entry_price, unrealized_pnl, strategy, order_time FROM active_trades WHERE trade_id = $1",
                        trade_id
                    )
                    if trade_data:
                        stale_trade_details.append({
                            "trade_id": trade_data['trade_id'],
                            "instrument": trade_data['instrument'],
                            "direction": trade_data['direction'],
                            "units": trade_data['units'],
                            "entry_price": float(trade_data['entry_price']) if trade_data['entry_price'] else None,
                            "unrealized_pnl": float(trade_data['unrealized_pnl']) if trade_data['unrealized_pnl'] else 0.0,
                            "strategy": trade_data['strategy'],
                            "order_time": trade_data['order_time'].isoformat() if trade_data['order_time'] else None
                        })
                
                # Get column compatibility info
                active_trades_columns = await conn.fetch("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'active_trades' AND table_schema = 'public'
                    ORDER BY ordinal_position
                """)
                
                closed_trades_columns = await conn.fetch("""
                    SELECT column_name FROM information_schema.columns 
                    WHERE table_name = 'closed_trades' AND table_schema = 'public'
                    ORDER BY ordinal_position
                """)
                
                active_cols = {row['column_name'] for row in active_trades_columns}
                closed_cols = {row['column_name'] for row in closed_trades_columns}
                
                missing_columns = active_cols - closed_cols
                
                preview_result = {
                    "status": "success",
                    "oanda_active_trades": len(oanda_trade_ids),
                    "oanda_trade_ids": list(oanda_trade_ids),
                    "rds_active_trades": len(rds_trade_ids),
                    "rds_trade_ids": list(rds_trade_ids),
                    "stale_trades_count": len(stale_trade_ids),
                    "stale_trade_ids": list(stale_trade_ids),
                    "stale_trade_details": stale_trade_details,
                    "column_compatibility": {
                        "active_trades_columns": len(active_cols),
                        "closed_trades_columns": len(closed_cols),
                        "missing_columns": list(missing_columns),
                        "compatible": len(missing_columns) == 0
                    },
                    "action_summary": {
                        "trades_to_move": len(stale_trade_ids),
                        "remaining_after_cleanup": len(oanda_trade_ids),
                        "total_unrealized_pnl_affected": sum(trade['unrealized_pnl'] for trade in stale_trade_details)
                    }
                }
                
                return preview_result
                
        except Exception as e:
            logger.error(f"❌ Error during preview_cleanup_inactive_trades: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def store_positions(self, positions_data: List[Dict[str, Any]]) -> bool:
        """
        Store currency pair positions data in RDS positions table
        Based on OANDA positions API data structure matching Airtable schema
        """
        if not positions_data:
            logger.info("No positions data to store")
            return True
        
        if not self.connection_pool:
            logger.error("Database connection pool not initialized")
            return False
        
        async with self.connection_pool.acquire() as conn:
            # Create positions table if it doesn't exist
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS positions (
                        id SERIAL PRIMARY KEY,
                        currency_pair VARCHAR(10) NOT NULL UNIQUE,
                        long_units INTEGER DEFAULT 0,
                        short_units INTEGER DEFAULT 0,
                        net_units INTEGER DEFAULT 0,
                        trade_count INTEGER DEFAULT 0,
                        long_trades INTEGER DEFAULT 0,
                        short_trades INTEGER DEFAULT 0,
                        average_entry DECIMAL(10, 5) DEFAULT 0,
                        current_price DECIMAL(10, 5) DEFAULT 0,
                        distance_pips DECIMAL(10, 1) DEFAULT 0,
                        profit_pips DECIMAL(10, 1) DEFAULT 0,
                        unrealized_pnl DECIMAL(10, 2) DEFAULT 0,
                        margin_used DECIMAL(10, 2) DEFAULT 0,
                        largest_position INTEGER DEFAULT 0,
                        concentration_percent DECIMAL(5, 2) DEFAULT 0,
                        last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)
                logger.info("✅ Positions table created/verified")
            except Exception as e:
                logger.warning(f"Error creating positions table: {str(e)}")
            
            try:
                # Process each position
                for position in positions_data:
                    instrument = position.get('instrument', '').replace('_', '/')  # USD_CHF -> USD/CHF
                    
                    if not instrument:
                        continue
                    
                    # Get long and short positions
                    long_position = position.get('long', {})
                    short_position = position.get('short', {})
                    
                    long_units = int(float(long_position.get('units', 0)))
                    short_units = abs(int(float(short_position.get('units', 0))))  # Make positive
                    net_units = long_units - short_units
                    
                    # Skip if no position
                    if long_units == 0 and short_units == 0:
                        continue
                    
                    # Get unrealized P&L
                    long_pl = float(long_position.get('unrealizedPL', 0))
                    short_pl = float(short_position.get('unrealizedPL', 0))
                    total_pl = long_pl + short_pl
                    
                    # Get average prices
                    avg_short_price = float(short_position.get('averagePrice', 0))
                    avg_long_price = float(long_position.get('averagePrice', 0))
                    
                    # Determine effective average price based on net position
                    if net_units > 0:  # Net long
                        avg_price = avg_long_price
                    elif net_units < 0:  # Net short
                        avg_price = avg_short_price
                    else:  # Flat
                        avg_price = (avg_long_price + avg_short_price) / 2 if avg_long_price and avg_short_price else 0
                    
                    # Get margin info
                    margin_usd = float(position.get('marginUsed', 0))
                    
                    # Calculate additional fields
                    trade_count = 1 if net_units != 0 else 0
                    long_trades = 1 if long_units > 0 else 0
                    short_trades = 1 if short_units > 0 else 0
                    
                    # Calculate profit in pips (simplified)
                    pip_multiplier = 100 if 'JPY' in instrument else 10000
                    profit_pips = (total_pl / abs(net_units)) * pip_multiplier if net_units != 0 else 0
                    
                    # Calculate concentration percentage (simplified)
                    # This would be better with actual account balance
                    concentration_percent = 0  # Placeholder for now
                    
                    # UPSERT position record
                    await conn.execute("""
                        INSERT INTO positions (
                            currency_pair, long_units, short_units, net_units, trade_count,
                            long_trades, short_trades, average_entry, current_price,
                            distance_pips, profit_pips, unrealized_pnl, margin_used,
                            largest_position, concentration_percent, last_updated
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW())
                        ON CONFLICT (currency_pair) DO UPDATE SET
                            long_units = EXCLUDED.long_units,
                            short_units = EXCLUDED.short_units,
                            net_units = EXCLUDED.net_units,
                            trade_count = EXCLUDED.trade_count,
                            long_trades = EXCLUDED.long_trades,
                            short_trades = EXCLUDED.short_trades,
                            average_entry = EXCLUDED.average_entry,
                            current_price = EXCLUDED.current_price,
                            distance_pips = EXCLUDED.distance_pips,
                            profit_pips = EXCLUDED.profit_pips,
                            unrealized_pnl = EXCLUDED.unrealized_pnl,
                            margin_used = EXCLUDED.margin_used,
                            largest_position = EXCLUDED.largest_position,
                            concentration_percent = EXCLUDED.concentration_percent,
                            last_updated = NOW()
                    """, instrument, long_units, short_units, net_units, trade_count,
                         long_trades, short_trades, avg_price, 0,  # current_price will be updated later
                         0, profit_pips, total_pl, margin_usd,  # distance_pips calculated later
                         abs(net_units), concentration_percent)
                
                logger.info(f"✅ Stored {len(positions_data)} positions in RDS")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error storing positions: {str(e)}", exc_info=True)
                return False
    
    async def store_exposures(self, positions_data: List[Dict[str, Any]], account_balance: float = 100000.0) -> bool:
        """
        Store currency exposures data in RDS exposures table
        Calculated from OANDA positions data matching Airtable schema
        """
        if not positions_data:
            logger.info("No positions data to calculate exposures")
            return True
        
        if not self.connection_pool:
            logger.error("Database connection pool not initialized")
            return False
        
        async with self.connection_pool.acquire() as conn:
            # Create exposures table if it doesn't exist
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS exposures (
                        id SERIAL PRIMARY KEY,
                        currency VARCHAR(3) NOT NULL UNIQUE,
                        net_exposure DECIMAL(15, 2) DEFAULT 0,
                        long_exposure DECIMAL(15, 2) DEFAULT 0,
                        short_exposure DECIMAL(15, 2) DEFAULT 0,
                        usd_value DECIMAL(15, 2) DEFAULT 0,
                        risk_percent DECIMAL(5, 2) DEFAULT 0,
                        last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)
                logger.info("✅ Exposures table created/verified")
            except Exception as e:
                logger.warning(f"Error creating exposures table: {str(e)}")
            
            try:
                # Calculate currency exposures from positions data
                currency_data = {}
                
                for position in positions_data:
                    instrument = position.get('instrument', '')
                    if '_' not in instrument:
                        continue
                        
                    base_currency, quote_currency = instrument.split('_')
                    
                    # Get position details
                    long_data = position.get('long', {})
                    short_data = position.get('short', {})
                    
                    long_units = float(long_data.get('units', 0))
                    short_units = float(short_data.get('units', 0))
                    
                    # Skip if no position
                    if long_units == 0 and short_units == 0:
                        continue
                    
                    # Initialize currency data
                    for currency in [base_currency, quote_currency]:
                        if currency not in currency_data:
                            currency_data[currency] = {
                                'net_exposure': 0,
                                'long_exposure': 0,
                                'short_exposure': 0
                            }
                    
                    # Get average prices for conversion
                    long_price = float(long_data.get('averagePrice', 0)) if long_units != 0 else 0
                    short_price = float(short_data.get('averagePrice', 0)) if short_units != 0 else 0
                    avg_price = long_price if long_price > 0 else short_price
                    
                    # Calculate currency exposures
                    if long_units > 0:
                        # Long position: Long base currency, short quote currency
                        base_amount = abs(long_units)
                        quote_amount = abs(long_units) * avg_price if avg_price > 0 else abs(long_units)
                        
                        currency_data[base_currency]['net_exposure'] += base_amount
                        currency_data[base_currency]['long_exposure'] += base_amount
                        currency_data[quote_currency]['net_exposure'] -= quote_amount
                        currency_data[quote_currency]['short_exposure'] += quote_amount
                        
                    if short_units < 0:
                        # Short position: Short base currency, long quote currency
                        base_amount = abs(short_units)
                        quote_amount = abs(short_units) * avg_price if avg_price > 0 else abs(short_units)
                        
                        currency_data[base_currency]['net_exposure'] -= base_amount
                        currency_data[base_currency]['short_exposure'] += base_amount
                        currency_data[quote_currency]['net_exposure'] += quote_amount
                        currency_data[quote_currency]['long_exposure'] += quote_amount
                
                # Store exposures in database
                for currency, data in currency_data.items():
                    if abs(data['net_exposure']) < 0.01:  # Skip negligible exposures
                        continue
                    
                    # Simple USD conversion (approximate rates)
                    usd_rates = {
                        'USD': 1.0, 'EUR': 1.08, 'GBP': 1.25, 'JPY': 0.0067,
                        'CAD': 0.74, 'AUD': 0.65, 'CHF': 1.10, 'NZD': 0.60
                    }
                    usd_value = abs(data['net_exposure']) * usd_rates.get(currency, 1.0)
                    risk_percent = (usd_value / account_balance * 100) if account_balance > 0 else 0.0
                    
                    # UPSERT exposure record
                    await conn.execute("""
                        INSERT INTO exposures (
                            currency, net_exposure, long_exposure, short_exposure,
                            usd_value, risk_percent, last_updated
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, NOW())
                        ON CONFLICT (currency) DO UPDATE SET
                            net_exposure = EXCLUDED.net_exposure,
                            long_exposure = EXCLUDED.long_exposure,
                            short_exposure = EXCLUDED.short_exposure,
                            usd_value = EXCLUDED.usd_value,
                            risk_percent = EXCLUDED.risk_percent,
                            last_updated = NOW()
                    """, currency, data['net_exposure'], data['long_exposure'], 
                         data['short_exposure'], usd_value, risk_percent)
                
                logger.info(f"✅ Stored exposures for {len(currency_data)} currencies in RDS")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error storing exposures: {str(e)}", exc_info=True)
                return False