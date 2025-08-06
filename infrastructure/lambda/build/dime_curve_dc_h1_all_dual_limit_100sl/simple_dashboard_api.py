#!/usr/bin/env python3
"""
Simple Dashboard API Lambda Function - Focus on getting Momentum Grid working
"""

import json
import logging
import os
import boto3
import redis
import pg8000
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class DashboardDataProvider:
    """Simple data provider focused on active trades"""
    
    def __init__(self):
        self.secrets_client = boto3.client('secretsmanager')
        self.redis_client = self._init_redis()
        self.db_conn = self._init_rds()
    
    def calculate_pips_movement(self, instrument: str, entry_price: float, current_price: float, direction: str) -> float:
        """Calculate pips movement for a trade"""
        if not entry_price or not current_price or entry_price == current_price:
            return 0.0
        
        # Determine pip value based on instrument
        if 'JPY' in instrument:
            pip_factor = 0.01  # JPY pairs: pip = 0.01
        else:
            pip_factor = 0.0001  # Major pairs: pip = 0.0001
        
        price_diff = current_price - entry_price
        
        # Adjust for trade direction
        if direction == 'Short':
            price_diff = -price_diff
        
        pips = price_diff / pip_factor
        return round(pips, 1)
    
    def estimate_current_price_from_pnl(self, instrument: str, entry_price: float, units: int, unrealized_pnl: float, direction: str) -> float:
        """Estimate current price from unrealized P&L when current_price is not available"""
        if not entry_price or not units or unrealized_pnl == 0:
            return entry_price
        
        try:
            # For JPY pairs, 1 pip movement = units * 0.01 / 100 (for most account currencies)
            # For other pairs, 1 pip movement = units * 0.0001
            if 'JPY' in instrument:
                pip_value = abs(units) * 0.01 / 100
                pip_factor = 0.01
            else:
                pip_value = abs(units) * 0.0001
                pip_factor = 0.0001
            
            if pip_value > 0:
                pips_moved = unrealized_pnl / pip_value
                price_change = pips_moved * pip_factor
                
                # Adjust for trade direction
                if direction == 'Long':
                    estimated_current_price = entry_price + price_change
                else:
                    estimated_current_price = entry_price - price_change
                
                return round(estimated_current_price, 5)
        except:
            pass
        
        return entry_price
    
    def aggregate_m5_to_h1(self, m5_candles: List[Dict]) -> List[Dict]:
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
        
        logger.info(f"✅ Aggregated {len(sorted_candles)} M5 candles → {len(h1_candles)} H1 candles")
        return h1_candles
    
    def create_h1_candle(self, m5_group: List[Dict], hour_boundary: datetime) -> Dict:
        """Create a single H1 candle from a group of M5 candles"""
        try:
            return {
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
            return {
                'timestamp': int(hour_boundary.timestamp()),
                'datetime': hour_boundary.isoformat(),
                'open': 0, 'high': 0, 'low': 0, 'close': 0, 'volume': 0
            }
    
    def get_redis_status(self) -> Dict[str, Any]:
        """Get comprehensive Redis status including candlestick data availability"""
        status = {
            'connected': False,
            'total_keys': 0,
            'candlestick_keys': [],
            'market_data_keys': [],
            'sample_data': {},
            'key_patterns': {},
            'redis_info': {}
        }
        
        if not self.redis_client:
            status['error'] = 'No Redis connection'
            return status
        
        try:
            # Test connection
            self.redis_client.ping()
            status['connected'] = True
            
            # Get total keys
            status['total_keys'] = self.redis_client.dbsize()
            
            # Search for different patterns
            patterns = {
                'candlestick': ['candlestick*', '*candlestick*'],
                'market_data': ['market*', '*market*', 'ohlc*'],
                'instruments': ['EUR_USD*', 'GBP_USD*', '*H1*', '*M5*', '*H4*'],
                'all_keys': ['*'] if status['total_keys'] < 100 else []
            }
            
            for category, pattern_list in patterns.items():
                found_keys = set()
                for pattern in pattern_list:
                    keys = self.redis_client.keys(pattern)
                    if keys:
                        found_keys.update(keys[:20])  # Limit to prevent overflow
                
                status['key_patterns'][category] = sorted(list(found_keys))
                
                if category == 'candlestick':
                    status['candlestick_keys'] = sorted(list(found_keys))
                elif category == 'market_data':
                    status['market_data_keys'] = sorted(list(found_keys))
            
            # Get sample data from interesting keys
            sample_keys = (status['candlestick_keys'][:3] + 
                          status['market_data_keys'][:3] + 
                          status['key_patterns'].get('instruments', [])[:3])
            
            for key in sample_keys[:5]:  # Limit samples
                try:
                    key_type = self.redis_client.type(key)
                    sample_info = {'type': key_type}
                    
                    if key_type == 'string':
                        value = self.redis_client.get(key)
                        if value:
                            sample_info['preview'] = str(value)[:200] + ('...' if len(str(value)) > 200 else '')
                    elif key_type == 'zset':
                        size = self.redis_client.zcard(key)
                        sample_info['size'] = size
                        if size > 0:
                            # Get last few entries
                            entries = self.redis_client.zrange(key, -3, -1, withscores=True)
                            sample_info['last_entries'] = entries
                    elif key_type == 'list':
                        size = self.redis_client.llen(key)
                        sample_info['size'] = size
                        if size > 0:
                            entries = self.redis_client.lrange(key, -3, -1)
                            sample_info['last_entries'] = entries
                    elif key_type == 'hash':
                        size = self.redis_client.hlen(key)
                        sample_info['size'] = size
                        if size > 0:
                            # Get a few hash fields
                            fields = self.redis_client.hkeys(key)[:5]
                            sample_values = {}
                            for field in fields:
                                sample_values[field] = self.redis_client.hget(key, field)[:100] if self.redis_client.hget(key, field) else None
                            sample_info['sample_fields'] = sample_values
                    
                    status['sample_data'][key] = sample_info
                    
                except Exception as e:
                    status['sample_data'][key] = {'error': str(e)}
            
            # Get Redis server info
            info = self.redis_client.info()
            status['redis_info'] = {
                'redis_version': info.get('redis_version'),
                'used_memory_human': info.get('used_memory_human'),
                'connected_clients': info.get('connected_clients'),
                'uptime_in_seconds': info.get('uptime_in_seconds')
            }
            
            logger.info(f"✅ Redis status check complete: {status['total_keys']} keys, {len(status['candlestick_keys'])} candlestick keys")
            
        except Exception as e:
            status['error'] = str(e)
            logger.error(f"Failed to get Redis status: {str(e)}")
        
        return status
        
    def _init_redis(self) -> Optional[redis.StrictRedis]:
        """Initialize Redis connection"""
        try:
            secret_response = self.secrets_client.get_secret_value(
                SecretId="lumisignals/redis/prod-pg17/config"
            )
            redis_config = json.loads(secret_response['SecretString'])
            
            shard_endpoint = redis_config['shard_0']
            host, port = shard_endpoint.split(':')
            
            client = redis.StrictRedis(
                host=host,
                port=int(port),
                password=redis_config.get('auth_token'),
                decode_responses=True,
                socket_connect_timeout=5
            )
            
            client.ping()
            logger.info("✅ Connected to Redis shard 0")
            return client
            
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {str(e)}")
            return None
    
    def _init_rds(self) -> Optional[pg8000.Connection]:
        """Initialize RDS connection with SSL"""
        try:
            secret_response = self.secrets_client.get_secret_value(
                SecretId="lumisignals/rds/postgresql/credentials"
            )
            rds_config = json.loads(secret_response['SecretString'])
            
            # Try connection with SSL first, then without SSL if it fails
            try:
                conn = pg8000.connect(
                    host=rds_config['host'],
                    database=rds_config['dbname'],
                    user=rds_config['username'],
                    password=rds_config['password'],
                    port=rds_config.get('port', 5432),
                    ssl_context=True
                )
                logger.info("✅ Connected to RDS with SSL")
                return conn
            except Exception as ssl_error:
                logger.warning(f"SSL connection failed, trying without SSL: {ssl_error}")
                conn = pg8000.connect(
                    host=rds_config['host'],
                    database=rds_config['dbname'],
                    user=rds_config['username'],
                    password=rds_config['password'],
                    port=rds_config.get('port', 5432)
                )
                logger.info("✅ Connected to RDS without SSL")
                return conn
                
        except Exception as e:
            logger.error(f"❌ RDS connection failed: {str(e)}")
            return None
    
    def get_closed_trades_quality_report(self) -> Dict[str, Any]:
        """Generate closed trades data quality report"""
        if not self.db_conn:
            logger.warning("No RDS connection - cannot check closed trades")
            return {'error': 'No database connection'}
        
        try:
            cursor = self.db_conn.cursor()
            results = {}
            
            # First check what columns exist in closed_trades
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'closed_trades'
                ORDER BY ordinal_position
            """)
            columns = [row[0] for row in cursor.fetchall()]
            results['available_columns'] = columns
            logger.info(f"Available columns in closed_trades: {columns}")
            
            # Check if the table even exists and has data
            cursor.execute("SELECT COUNT(*) FROM closed_trades")
            total_count = cursor.fetchone()[0]
            results['total_trades'] = total_count
            
            if total_count == 0:
                return {'message': 'No data in closed_trades table', 'available_columns': columns}
            
            # Only proceed with analysis if we have the essential columns
            has_rrr = 'return_risk_ratio' in columns
            has_close_time = 'close_time' in columns or 'closed_time' in columns
            
            if not has_rrr:
                return {'message': 'return_risk_ratio column not found', 'available_columns': columns, 'total_trades': total_count}
            
            # 1. Check return_risk_ratio values distribution
            close_time_col = 'close_time' if 'close_time' in columns else 'closed_time'
            
            cursor.execute(f'''
                SELECT 
                    return_risk_ratio,
                    COUNT(*) as count
                FROM closed_trades
                WHERE return_risk_ratio IS NOT NULL
                GROUP BY return_risk_ratio
                ORDER BY count DESC
                LIMIT 15
            ''')
            
            rrr_distribution = []
            for row in cursor.fetchall():
                rrr_distribution.append({
                    'value': float(row[0]),
                    'count': row[1]
                })
            
            results['rrr_distribution'] = rrr_distribution
            
            # 2. Check stop_loss and take_profit population
            has_sl = 'stop_loss' in columns
            has_tp = 'take_profit' in columns
            
            if has_sl and has_tp:
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_trades,
                        COUNT(stop_loss) as has_stop_loss,
                        COUNT(take_profit) as has_take_profit,
                        COUNT(CASE WHEN stop_loss IS NOT NULL AND take_profit IS NOT NULL THEN 1 END) as has_both
                    FROM closed_trades
                ''')
                
                row = cursor.fetchone()
                results['sl_tp_stats'] = {
                    'total_trades': row[0],
                    'has_stop_loss': row[1],
                    'has_take_profit': row[2],
                    'has_both': row[3],
                    'sl_percentage': round(row[1] / row[0] * 100, 2) if row[0] > 0 else 0,
                    'tp_percentage': round(row[2] / row[0] * 100, 2) if row[0] > 0 else 0
                }
            else:
                results['sl_tp_stats'] = {'message': 'stop_loss or take_profit columns not found'}
            
            # 3. Recent trades sample - use only available columns
            basic_columns = ['return_risk_ratio']
            if has_close_time:
                basic_columns.append(close_time_col)
            if 'entry_price' in columns:
                basic_columns.append('entry_price')
            if 'exit_price' in columns:
                basic_columns.append('exit_price')
            
            select_clause = ', '.join(basic_columns)
            cursor.execute(f'''
                SELECT {select_clause}
                FROM closed_trades
                WHERE return_risk_ratio IS NOT NULL
                ORDER BY {close_time_col if has_close_time else 'return_risk_ratio'} DESC
                LIMIT 5
            ''')
            
            recent_trades = []
            for row in cursor.fetchall():
                trade_data = {}
                for i, col in enumerate(basic_columns):
                    if row[i] is not None:
                        if col in ['entry_price', 'exit_price', 'return_risk_ratio']:
                            trade_data[col] = float(row[i])
                        elif col in ['close_time', 'closed_time']:
                            trade_data[col] = row[i].isoformat() if hasattr(row[i], 'isoformat') else str(row[i])
                        else:
                            trade_data[col] = row[i]
                recent_trades.append(trade_data)
            
            results['recent_trades'] = recent_trades
            
            # 4. RRR statistics
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT return_risk_ratio) as unique_rrr_count,
                    MIN(return_risk_ratio) as min_rrr,
                    MAX(return_risk_ratio) as max_rrr,
                    AVG(return_risk_ratio) as avg_rrr,
                    STDDEV(return_risk_ratio) as stddev_rrr
                FROM closed_trades
                WHERE return_risk_ratio IS NOT NULL
            ''')
            
            row = cursor.fetchone()
            results['rrr_statistics'] = {
                'unique_count': row[0],
                'min': float(row[1]) if row[1] else None,
                'max': float(row[2]) if row[2] else None,
                'average': float(row[3]) if row[3] else None,
                'std_dev': float(row[4]) if row[4] else None
            }
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get closed trades quality report: {str(e)}")
            return {'error': str(e)}

    def get_active_trades_list(self) -> List[Dict[str, Any]]:
        """Get all active trades from RDS"""
        trades = []
        
        if not self.db_conn:
            logger.warning("No RDS connection - returning empty trades")
            return trades
        
        try:
            cursor = self.db_conn.cursor()
            
            # First check what columns exist
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'active_trades'
                ORDER BY ordinal_position
            """)
            columns = [row[0] for row in cursor.fetchall()]
            logger.info(f"Available columns in active_trades: {columns}")
            
            # Check total row count first
            cursor.execute("SELECT COUNT(*) FROM active_trades")
            total_count = cursor.fetchone()[0]
            logger.info(f"Total rows in active_trades: {total_count}")
            
            # Check rows with open_time
            cursor.execute("SELECT COUNT(*) FROM active_trades WHERE open_time IS NOT NULL")
            open_time_count = cursor.fetchone()[0]
            logger.info(f"Rows with open_time: {open_time_count}")
            
            # Check if enhanced columns exist by testing the schema
            enhanced_columns_available = False
            if 'take_profit_price' in columns and 'stop_loss_price' in columns:
                enhanced_columns_available = True
                logger.info("✅ Enhanced columns detected in schema")
            
            if enhanced_columns_available:
                # Check if we have distance_to_entry field (OANDA's direct pips measurement)
                has_distance_to_entry = 'distance_to_entry' in columns
                
                if has_distance_to_entry:
                    cursor.execute("""
                        SELECT trade_id, instrument, units, entry_price, unrealized_pnl, 
                               open_time, state, take_profit_price, stop_loss_price, 
                               pips_moved, risk_reward_ratio, current_price, distance_to_entry,
                               strategy, active_trade_duration, direction, momentum_strength
                        FROM active_trades
                        WHERE open_time IS NOT NULL
                        ORDER BY open_time DESC
                        LIMIT 100
                    """)
                    logger.info("✅ Using enhanced query with OANDA Distance to Entry field")
                else:
                    cursor.execute("""
                        SELECT trade_id, instrument, units, entry_price, unrealized_pnl, 
                               open_time, state, take_profit_price, stop_loss_price, 
                               pips_moved, risk_reward_ratio, current_price,
                               strategy, active_trade_duration, direction, momentum_strength
                        FROM active_trades
                        WHERE open_time IS NOT NULL
                        ORDER BY open_time DESC
                        LIMIT 100
                    """)
                    logger.info("✅ Using enhanced query without distance_to_entry field")
                logger.info("✅ Using enhanced query with stop loss and take profit columns")
            else:
                logger.info("📊 Using basic query - enhanced Fargate columns not yet available")
                cursor.execute("""
                    SELECT trade_id, instrument, units, entry_price, unrealized_pnl, 
                           open_time, state, strategy, active_trade_duration, direction,
                           momentum_strength, current_price, pips_moved, risk_reward_ratio
                    FROM active_trades
                    WHERE open_time IS NOT NULL
                    ORDER BY open_time DESC
                    LIMIT 100
                """)
            
            for row in cursor.fetchall():
                if enhanced_columns_available:
                    # Determine if we have distance_to_entry field
                    row_has_distance = has_distance_to_entry and len(row) > 12
                    
                    # Enhanced query with all fields
                    trade = {
                        'trade_id': row[0],
                        'instrument': row[1],
                        'units': int(row[2]) if row[2] else 0,
                        'entry_price': float(row[3]) if row[3] else 0.0,
                        'unrealized_pnl': float(row[4]) if row[4] else 0.0,
                        'open_time': row[5].isoformat() if row[5] else '',
                        'state': row[6] or 'UNKNOWN',
                        'take_profit_price': float(row[7]) if row[7] else None,
                        'stop_loss_price': float(row[8]) if row[8] else None,
                        'pips_moved': float(row[9]) if row[9] else 0.0,
                        'risk_reward_ratio': float(row[10]) if row[10] else None,
                        'current_price': float(row[11]) if row[11] else float(row[3]) if row[3] else 0.0,
                        'strategy_name': row[13] if row[13] else 'Unknown',
                        'duration': int(row[14]) if row[14] else 0,
                        'direction': row[15] if row[15] else ('Long' if (row[2] and int(row[2]) > 0) else 'Short'),
                        'momentum_strength': row[16] if row[16] else 'NEUTRAL',
                        'financing': 0.0,
                        'margin_used': 0.0
                    }
                    
                    # Use OANDA's Distance to Entry if available (most accurate)
                    if row_has_distance and row[12] is not None:
                        oanda_distance = float(row[12])
                        trade['pips_moved'] = oanda_distance  # Override with OANDA's accurate measurement
                        trade['distance_to_entry_source'] = 'OANDA_DIRECT'
                        logger.info(f"🎯 Using OANDA Distance to Entry: {oanda_distance} pips for trade {trade['trade_id']}")
                    else:
                        trade['distance_to_entry_source'] = 'CALCULATED'
                    
                    # Calculate duration in minutes from open_time to now
                    if row[5]:  # if open_time exists
                        try:
                            open_time = row[5] if hasattr(row[5], 'replace') else datetime.fromisoformat(str(row[5]).replace('Z', '+00:00'))
                            if open_time.tzinfo is None:
                                open_time = open_time.replace(tzinfo=timezone.utc)
                            current_time = datetime.now(timezone.utc)
                            duration_delta = current_time - open_time
                            duration_minutes = int(duration_delta.total_seconds() / 60)
                            trade['duration'] = duration_minutes
                        except Exception as e:
                            logger.warning(f"Failed to calculate duration for trade {row[0]}: {e}")
                            trade['duration'] = 0
                    else:
                        trade['duration'] = 0
                    
                    # Fix pips calculation if current_price equals entry_price (indicating stale data)
                    if trade['current_price'] == trade['entry_price'] and trade['unrealized_pnl'] != 0:
                        # Estimate current price from P&L
                        estimated_price = self.estimate_current_price_from_pnl(
                            trade['instrument'], 
                            trade['entry_price'], 
                            trade['units'], 
                            trade['unrealized_pnl'], 
                            trade['direction']
                        )
                        trade['current_price'] = estimated_price
                        
                        # Recalculate pips with estimated price
                        trade['pips_moved'] = self.calculate_pips_movement(
                            trade['instrument'],
                            trade['entry_price'],
                            trade['current_price'],
                            trade['direction']
                        )
                else:
                    # Basic query fallback with all available columns
                    trade = {
                        'trade_id': row[0],
                        'instrument': row[1],
                        'units': int(row[2]) if row[2] else 0,
                        'entry_price': float(row[3]) if row[3] else 0.0,
                        'unrealized_pnl': float(row[4]) if row[4] else 0.0,
                        'open_time': row[5].isoformat() if row[5] else '',
                        'state': row[6] or 'UNKNOWN',
                        'strategy_name': row[7] if row[7] else 'Unknown',
                        'duration': int(row[8]) if row[8] else 0,
                        'direction': row[9] if row[9] else ('Long' if (row[2] and int(row[2]) > 0) else 'Short'),
                        'momentum_strength': row[10] if row[10] else 'NEUTRAL',
                        'current_price': float(row[11]) if row[11] else float(row[3]) if row[3] else 0.0,
                        'pips_moved': float(row[12]) if row[12] else 0.0,
                        'risk_reward_ratio': float(row[13]) if row[13] else None,
                        'take_profit_price': None,  # Not available in basic query
                        'stop_loss_price': None,    # Not available in basic query
                        'financing': 0.0,
                        'margin_used': 0.0
                    }
                    
                    # Calculate duration in minutes from open_time to now
                    if row[5]:  # if open_time exists
                        try:
                            open_time = row[5] if hasattr(row[5], 'replace') else datetime.fromisoformat(str(row[5]).replace('Z', '+00:00'))
                            if open_time.tzinfo is None:
                                open_time = open_time.replace(tzinfo=timezone.utc)
                            current_time = datetime.now(timezone.utc)
                            duration_delta = current_time - open_time
                            duration_minutes = int(duration_delta.total_seconds() / 60)
                            trade['duration'] = duration_minutes
                        except Exception as e:
                            logger.warning(f"Failed to calculate duration for trade {row[0]}: {e}")
                            trade['duration'] = 0
                    else:
                        trade['duration'] = 0
                    
                    # Calculate pips movement from unrealized P&L
                    if trade['unrealized_pnl'] != 0:
                        # Estimate current price from P&L
                        estimated_price = self.estimate_current_price_from_pnl(
                            trade['instrument'], 
                            trade['entry_price'], 
                            trade['units'], 
                            trade['unrealized_pnl'], 
                            trade['direction']
                        )
                        trade['current_price'] = estimated_price
                        
                        # Calculate pips with estimated price
                        trade['pips_moved'] = self.calculate_pips_movement(
                            trade['instrument'],
                            trade['entry_price'],
                            trade['current_price'],
                            trade['direction']
                        )
                trades.append(trade)
            
            logger.info(f"Retrieved {len(trades)} active trades from RDS")
            
        except Exception as e:
            logger.error(f"Failed to get active trades: {str(e)}")
        
        return trades

    def get_positions_list(self) -> List[Dict[str, Any]]:
        """Get all currency pair positions from RDS"""
        positions = []
        
        if not self.db_conn:
            logger.warning("No RDS connection - returning empty positions")
            return positions
        
        try:
            cursor = self.db_conn.cursor()
            
            # Check if positions table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'positions'
                )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logger.warning("Positions table does not exist in RDS")
                return positions
            
            # Get all positions with current data
            cursor.execute("""
                SELECT currency_pair, long_units, short_units, net_units, 
                       trade_count, long_trades, short_trades, average_entry, 
                       current_price, distance_pips, profit_pips, unrealized_pnl, 
                       margin_used, largest_position, concentration_percent, 
                       last_updated
                FROM positions 
                ORDER BY ABS(unrealized_pnl) DESC
            """)
            
            for row in cursor.fetchall():
                position = {
                    'currency_pair': row[0],
                    'long_units': int(row[1]) if row[1] else 0,
                    'short_units': int(row[2]) if row[2] else 0,
                    'net_units': int(row[3]) if row[3] else 0,
                    'trade_count': int(row[4]) if row[4] else 0,
                    'long_trades': int(row[5]) if row[5] else 0,
                    'short_trades': int(row[6]) if row[6] else 0,
                    'average_entry': float(row[7]) if row[7] else 0.0,
                    'current_price': float(row[8]) if row[8] else 0.0,
                    'distance_pips': float(row[9]) if row[9] else 0.0,
                    'profit_pips': float(row[10]) if row[10] else 0.0,
                    'unrealized_pnl': float(row[11]) if row[11] else 0.0,
                    'margin_used': float(row[12]) if row[12] else 0.0,
                    'largest_position': int(row[13]) if row[13] else 0,
                    'concentration_percent': float(row[14]) if row[14] else 0.0,
                    'last_updated': row[15].isoformat() if row[15] else '',
                    'direction': 'Long' if int(row[3]) > 0 else 'Short' if int(row[3]) < 0 else 'Neutral'
                }
                positions.append(position)
            
            logger.info(f"Retrieved {len(positions)} positions from RDS")
            
        except Exception as e:
            logger.error(f"Failed to get positions: {str(e)}")
        
        return positions

    def get_exposures_list(self) -> List[Dict[str, Any]]:
        """Get all currency exposures from RDS"""
        exposures = []
        
        if not self.db_conn:
            logger.warning("No RDS connection - returning empty exposures")
            return exposures
        
        try:
            cursor = self.db_conn.cursor()
            
            # Check if exposures table exists
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'exposures'
                )
            """)
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logger.warning("Exposures table does not exist in RDS")
                return exposures
            
            # Get all exposures with current data
            cursor.execute("""
                SELECT currency, net_exposure, long_exposure, short_exposure, 
                       usd_value, risk_percent, last_updated
                FROM exposures 
                ORDER BY ABS(risk_percent) DESC
            """)
            
            for row in cursor.fetchall():
                exposure = {
                    'currency': row[0],
                    'net_exposure': float(row[1]) if row[1] else 0.0,
                    'long_exposure': float(row[2]) if row[2] else 0.0,
                    'short_exposure': float(row[3]) if row[3] else 0.0,
                    'usd_value': float(row[4]) if row[4] else 0.0,
                    'risk_percent': float(row[5]) if row[5] else 0.0,
                    'last_updated': row[6].isoformat() if row[6] else '',
                    'exposure_direction': 'Long' if float(row[1]) > 0 else 'Short' if float(row[1]) < 0 else 'Neutral'
                }
                exposures.append(exposure)
            
            logger.info(f"Retrieved {len(exposures)} currency exposures from RDS")
            
        except Exception as e:
            logger.error(f"Failed to get exposures: {str(e)}")
        
        return exposures

    def get_candlestick_data(self, currency_pair: str, timeframe: str = 'H1', count: int = 50) -> List[Dict[str, Any]]:
        """Get candlestick data from Redis for a specific currency pair"""
        candlesticks = []
        
        if not self.redis_client:
            logger.warning("No Redis connection - returning empty candlesticks")
            return candlesticks
        
        try:
            # Check available Redis keys for debugging
            try:
                # Look for candlestick-related keys
                pattern_keys = self.redis_client.keys("*candlestick*")
                market_keys = self.redis_client.keys(f"*{currency_pair}*")
                logger.info(f"Available candlestick keys: {pattern_keys}")
                logger.info(f"Available {currency_pair} keys: {market_keys}")
            except Exception as e:
                logger.warning(f"Could not scan Redis keys: {e}")
            
            # Try multiple possible Redis key formats
            # Based on actual Redis data found: market_data:USD_JPY:M5:current and market_data:USD_JPY:M5:historical
            possible_keys = [
                f"market_data:{currency_pair}:{timeframe}:historical",
                f"market_data:{currency_pair}:{timeframe}:current",
                f"market_data:{currency_pair}:M5:historical",  # Fallback to M5 data for any timeframe
                f"market_data:{currency_pair}:M5:current",
                f"candlesticks:{currency_pair}:{timeframe}",
                f"candlestick:{currency_pair}:{timeframe}",
                f"market_data:{currency_pair}:{timeframe}",
                f"ohlc:{currency_pair}:{timeframe}",
                f"{currency_pair}:candlesticks:{timeframe}",
                f"{currency_pair}:{timeframe}:candlesticks"
            ]
            
            candlestick_data = None
            used_key = None
            
            for redis_key in possible_keys:
                logger.info(f"Trying Redis key: {redis_key}")
                try:
                    # Try as string first (current Redis format)
                    string_data = self.redis_client.get(redis_key)
                    if string_data:
                        try:
                            # Parse JSON data 
                            if redis_key.endswith(':current'):
                                # Current data format: single candlestick object
                                current_candle = json.loads(string_data)
                                candlestick_data = [current_candle]
                                used_key = redis_key
                                logger.info(f"Found current candlestick data with key: {redis_key} (JSON string)")
                                break
                            elif redis_key.endswith(':historical'):
                                # Historical data format: array of candlesticks
                                historical_candles = json.loads(string_data)
                                if isinstance(historical_candles, list):
                                    candlestick_data = historical_candles[-count:]  # Get last N candles
                                    used_key = redis_key
                                    logger.info(f"Found historical candlestick data with key: {redis_key} (JSON array, {len(candlestick_data)} candles)")
                                    break
                        except json.JSONDecodeError as je:
                            logger.debug(f"JSON decode error for key {redis_key}: {je}")
                    
                    # Try as sorted set (legacy format)
                    data = self.redis_client.zrevrange(redis_key, 0, count - 1, withscores=True)
                    if data:
                        candlestick_data = data
                        used_key = redis_key
                        logger.info(f"Found candlestick data with key: {redis_key} (sorted set)")
                        break
                    
                    # Try as regular list (legacy format)
                    data = self.redis_client.lrange(redis_key, 0, count - 1)
                    if data:
                        candlestick_data = [(item, i) for i, item in enumerate(data)]
                        used_key = redis_key
                        logger.info(f"Found candlestick data with key: {redis_key} (list)")
                        break
                        
                except Exception as e:
                    logger.debug(f"Key {redis_key} not found or error: {e}")
                    continue
            
            if not candlestick_data:
                logger.warning(f"No candlestick data found for {currency_pair} {timeframe}")
                return candlesticks
            
            # Convert Redis data to candlestick format
            if isinstance(candlestick_data, list) and candlestick_data:
                # Handle new JSON format (list of dictionaries)
                raw_candles = []
                for candle_info in candlestick_data:
                    try:
                        # Direct dictionary format from JSON
                        if isinstance(candle_info, dict):
                            # Map different possible field names
                            open_price = candle_info.get('open') or candle_info.get('open_price', 0)
                            high_price = candle_info.get('high') or candle_info.get('high_price', 0) 
                            low_price = candle_info.get('low') or candle_info.get('low_price', 0)
                            close_price = candle_info.get('close') or candle_info.get('close_price', 0)
                            volume = candle_info.get('volume', 0)
                            
                            # Use either 'time' or 'timestamp' field for datetime
                            candle_time = candle_info.get('time') or candle_info.get('timestamp') or candle_info.get('collection_time')
                            
                            if candle_time:
                                raw_candles.append({
                                    'time': candle_time,
                                    'open': float(open_price),
                                    'high': float(high_price), 
                                    'low': float(low_price),
                                    'close': float(close_price),
                                    'volume': int(volume)
                                })
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Error processing candlestick data: {e}")
                        continue
                
                # Apply aggregation if needed
                if timeframe == 'H1' and used_key and 'M5' in used_key and raw_candles:
                    logger.info(f"🔄 Converting {len(raw_candles)} M5 candles to H1 for {currency_pair}")
                    h1_candles = self.aggregate_m5_to_h1(raw_candles)
                    candlesticks.extend(h1_candles)
                else:
                    # Use raw data as-is
                    for candle in raw_candles:
                        candlesticks.append({
                            'timestamp': int(time.time()),
                            'datetime': candle['time'],
                            'open': candle['open'],
                            'high': candle['high'], 
                            'low': candle['low'],
                            'close': candle['close'],
                            'volume': candle['volume']
                        })
            else:
                # Handle legacy format (tuples)
                for data, timestamp in candlestick_data:
                    try:
                        # Handle different data formats
                        if isinstance(data, str):
                            try:
                                candle_info = json.loads(data)
                            except json.JSONDecodeError:
                                # If not JSON, might be comma-separated values
                                parts = data.split(',')
                                if len(parts) >= 4:
                                    candle_info = {
                                        'open': float(parts[0]),
                                        'high': float(parts[1]),
                                        'low': float(parts[2]),
                                        'close': float(parts[3]),
                                        'volume': int(parts[4]) if len(parts) > 4 else 0
                                    }
                                else:
                                    continue
                        else:
                            candle_info = data
                        
                        # Convert timestamp to int if it's from a sorted set
                        if isinstance(timestamp, float):
                            ts = int(timestamp)
                        else:
                            ts = int(timestamp) if isinstance(timestamp, (int, str)) else int(datetime.now(timezone.utc).timestamp())
                        
                        # Convert to expected format for frontend  
                        candlestick = {
                            'timestamp': ts,
                            'datetime': datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                            'open': float(candle_info.get('open', 0)),
                            'high': float(candle_info.get('high', 0)),
                            'low': float(candle_info.get('low', 0)),
                            'close': float(candle_info.get('close', 0)),
                            'volume': int(candle_info.get('volume', 0))
                        }
                        candlesticks.append(candlestick)
                        
                    except Exception as e:
                        logger.warning(f"Failed to parse candlestick data: {e}, data: {data}")
                        continue
            
            logger.info(f"Retrieved {len(candlesticks)} candlesticks for {currency_pair} {timeframe}")
            
        except Exception as e:
            logger.error(f"Failed to get candlestick data: {str(e)}")
        
        return candlesticks

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary combining positions and exposures"""
        summary = {
            'total_positions': 0,
            'total_unrealized_pnl': 0.0,
            'total_margin_used': 0.0,
            'currency_exposures': 0,
            'highest_risk_currency': None,
            'largest_position': None,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        
        try:
            positions = self.get_positions_list()
            exposures = self.get_exposures_list()
            
            if positions:
                summary['total_positions'] = len(positions)
                summary['total_unrealized_pnl'] = sum(p['unrealized_pnl'] for p in positions)
                summary['total_margin_used'] = sum(p['margin_used'] for p in positions)
                
                # Find largest position by P&L
                largest_pos = max(positions, key=lambda x: abs(x['unrealized_pnl'])) if positions else None
                if largest_pos:
                    summary['largest_position'] = {
                        'currency_pair': largest_pos['currency_pair'],
                        'net_units': largest_pos['net_units'],
                        'unrealized_pnl': largest_pos['unrealized_pnl'],
                        'direction': largest_pos['direction']
                    }
            
            if exposures:
                summary['currency_exposures'] = len(exposures)
                
                # Find highest risk currency
                highest_risk = max(exposures, key=lambda x: abs(x['risk_percent'])) if exposures else None
                if highest_risk:
                    summary['highest_risk_currency'] = {
                        'currency': highest_risk['currency'],
                        'risk_percent': highest_risk['risk_percent'],
                        'usd_value': highest_risk['usd_value'],
                        'direction': highest_risk['exposure_direction']
                    }
                    
        except Exception as e:
            logger.error(f"Failed to get portfolio summary: {str(e)}")
            summary['error'] = str(e)
        
        return summary

def lambda_handler(event, context):
    """Simple Lambda handler focused on active trades"""
    
    http_method = event.get('httpMethod', 'GET')
    path = event.get('path', '/')
    
    # CORS headers
    response = {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token,X-Requested-With',
            'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS,HEAD',
            'Access-Control-Max-Age': '86400',
            'Access-Control-Allow-Credentials': 'false'
        }
    }
    
    if http_method == 'OPTIONS':
        return response
    
    try:
        provider = DashboardDataProvider()
        
        if path == '/active-trades':
            data = provider.get_active_trades_list()
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/closed-trades-quality':
            data = provider.get_closed_trades_quality_report()
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/positions':
            data = provider.get_positions_list()
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/exposures':
            data = provider.get_exposures_list()
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/portfolio-summary':
            data = provider.get_portfolio_summary()
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/redis-status':
            # Get Redis status and keys
            redis_status = provider.get_redis_status()
            response['body'] = json.dumps({
                'success': True,
                'data': redis_status,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        elif path == '/candlestick-data':
            # Get query parameters
            query_params = event.get('queryStringParameters') or {}
            currency_pair = query_params.get('currency_pair', 'EUR_USD')
            timeframe = query_params.get('timeframe', 'H1')
            count = int(query_params.get('count', 50))
            
            data = provider.get_candlestick_data(currency_pair, timeframe, count)
            response['body'] = json.dumps({
                'success': True,
                'data': data,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        else:
            response['body'] = json.dumps({
                'success': True,
                'message': 'Simple Dashboard API is running',
                'endpoints': ['/active-trades', '/closed-trades-quality', '/positions', '/exposures', '/portfolio-summary', '/candlestick-data'],
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        response['statusCode'] = 500
        response['body'] = json.dumps({
            'success': False,
            'error': str(e),
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    
    return response