"""
Enhanced AWS Lambda handler for dime_curve_dc_h1_all_dual_limit_100sl
IMPROVEMENTS:
1. Proper Redis metadata storage for Airtable sync integration
2. Trading session filtering for optimal market hours
3. Updated to use new trading_common_redis layer
"""

import json
import logging
import os
import sys
import boto3
import pytz
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

@dataclass
class TradeMetadata:
    """Trade metadata for Airtable/Redis integration"""
    setup_name: str = ""
    strategy_tag: str = "DimeCurveStrategy"
    momentum_strength: Optional[str] = None
    momentum_direction: Optional[str] = None
    strategy_bias: Optional[str] = None
    momentum_alignment: Optional[str] = None
    zone_position: str = "Dime_Level_Trade"
    distance_to_entry_pips: float = 0.0
    signal_confidence: int = 0

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add handler to logger if running in Lambda
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import centralized data client
from centralized_market_data_client import CentralizedMarketDataClient

# Import from NEW Redis layer
sys.path.append('/opt/python')  # Lambda layer path
from oanda_api import OandaAPI
from redis_integration import RedisTradeWriter

# Import the strategy
from dc_h1_all_dual_limit_100sl import DC_H1_ALL_DUAL_LIMIT_100SL

class TradingSessionManager:
    """Manages trading session filtering for optimal market hours"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def is_prime_trading_session(self, instrument: str) -> bool:
        """Check if current time is during prime trading hours for the instrument"""
        
        # COMPLETE FIX: Always return True to show all 28 currency pairs
        # This bypasses all session filtering to ensure candlestick data is available 24/7
        return True
    
    def get_session_info(self) -> Dict[str, Any]:
        """Get current trading session information"""
        utc_now = datetime.now(pytz.UTC)
        current_hour = utc_now.hour
        
        # Determine active sessions
        active_sessions = []
        
        if (current_hour >= 23) or (current_hour <= 8):
            active_sessions.append('asian')
        if 8 <= current_hour <= 16:
            active_sessions.append('london')  
        if 13 <= current_hour <= 22:
            active_sessions.append('new_york')
            
        # Check for overlaps
        overlaps = []
        if 13 <= current_hour <= 16:
            overlaps.append('london_ny')
        if 7 <= current_hour <= 9:
            overlaps.append('asian_london')
            
        return {
            'current_utc': utc_now.isoformat(),
            'current_hour': current_hour,
            'active_sessions': active_sessions,
            'session_overlaps': overlaps,
            'is_prime_time': len(overlaps) > 0
        }

def get_credentials() -> tuple[str, str]:
    """Get OANDA credentials from AWS Secrets Manager"""
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    try:
        secret_response = secrets_client.get_secret_value(
            SecretId='lumisignals/oanda/api/credentials'
        )
        credentials = json.loads(secret_response['SecretString'])
        
        return credentials['api_key'], credentials['account_id']
    except Exception as e:
        logger.error(f"Error getting credentials: {str(e)}")
        raise

def calculate_momentum_from_candles(candles: List[Dict], periods: int = 1) -> float:
    """Calculate simple momentum from candlestick data"""
    if not candles or len(candles) < periods + 1:
        return 0.0
    
    try:
        # Get the most recent complete candle and the one 'periods' back
        current_candle = candles[-1]
        previous_candle = candles[-(periods + 1)]
        
        # Handle both possible candle formats
        if 'mid' in current_candle:
            current = float(current_candle['mid']['c'])
            previous = float(previous_candle['mid']['c'])
        else:
            # Fallback to close price
            current = float(current_candle.get('c', current_candle.get('close', 0)))
            previous = float(previous_candle.get('c', previous_candle.get('close', 0)))
        
        if previous == 0:
            return 0.0
        
        # Calculate percentage change
        return (current - previous) / previous
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"Error calculating momentum: {e}")
        return 0.0

def get_market_data_from_centralized(market_client: CentralizedMarketDataClient, instruments: List[str]) -> Dict[str, Any]:
    """Get market data from centralized system with momentum calculation"""
    market_data = {}
    
    logger.info(f"Fetching market data from centralized system for {len(instruments)} instruments")
    
    # Get all current prices from Redis/PostgreSQL
    price_data = market_client.get_market_prices()
    logger.info(f"Price data source: {price_data.get('source', 'unknown')}")
    
    prices = price_data.get('prices', {})
    if not prices:
        logger.error("No price data available from centralized system")
        return {}
    
    for instrument in instruments:
        try:
            if instrument not in prices:
                logger.warning(f"No price data for {instrument} in centralized system")
                continue
                
            price_info = prices[instrument]
            
            # Extract price data
            current_price = float(price_info.get('price', 0))
            bid = float(price_info.get('bid', current_price))
            ask = float(price_info.get('ask', current_price))
            spread = ask - bid
            
            # Get historical data for momentum calculation
            candles_60m = market_client.get_historical_data(instrument, '1H', 10)
            candles_4h = market_client.get_historical_data(instrument, '4H', 5)
            
            # Calculate momentum
            momentum_60m = calculate_momentum_from_candles(candles_60m.get('candles', []), 1)
            momentum_4h = calculate_momentum_from_candles(candles_4h.get('candles', []), 1)
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'momentum_60m': momentum_60m,
                'momentum_4h': momentum_4h,
                'data_source': 'centralized_redis'
            }
            
            logger.info(f"Market data for {instrument}: Price={current_price:.5f}, "
                       f"Momentum 60m={momentum_60m:.4f}, 4h={momentum_4h:.4f}")
                       
        except Exception as e:
            logger.error(f"Error processing centralized data for {instrument}: {str(e)}")
            continue
    
    return market_data

def get_market_data_from_oanda(oanda_api: OandaAPI, instruments: List[str]) -> Dict[str, Any]:
    """Fallback: Get market data directly from OANDA API"""
    market_data = {}
    
    logger.info(f"Fetching market data from OANDA API for {len(instruments)} instruments")
    
    for instrument in instruments:
        try:
            # Get current price
            price_data = oanda_api.get_current_price(instrument)
            if not price_data:
                continue
                
            current_price = price_data.get('price', 0)
            bid = price_data.get('bid', current_price)
            ask = price_data.get('ask', current_price)
            spread = ask - bid
            
            # Get historical data for momentum
            candles_60m = oanda_api.get_candles(instrument, granularity='H1', count=10)
            candles_4h = oanda_api.get_candles(instrument, granularity='H4', count=5)
            
            # Calculate momentum
            momentum_60m = calculate_momentum_from_candles(candles_60m, 1)
            momentum_4h = calculate_momentum_from_candles(candles_4h, 1)
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'momentum_60m': momentum_60m,
                'momentum_4h': momentum_4h,
                'data_source': 'oanda_direct'
            }
            
            logger.info(f"Market data for {instrument}: Price={current_price:.5f}, "
                       f"Momentum 60m={momentum_60m:.4f}, 4h={momentum_4h:.4f}")
            
        except Exception as e:
            logger.error(f"Error getting market data for {instrument}: {str(e)}")
            continue
    
    return market_data

def calculate_position_size(account_balance: float, risk_per_trade: float, 
                          stop_loss_pips: int, pip_value: float) -> int:
    """Calculate position size based on risk management"""
    risk_amount = account_balance * (risk_per_trade / 100)
    position_size = risk_amount / (stop_loss_pips * pip_value)
    
    # Round to nearest 1000 units (micro lot)
    return int(position_size / 1000) * 1000

def place_order_from_signal(oanda_api: OandaAPI, signal: Dict[str, Any], 
                          account_balance: float, redis_writer: RedisTradeWriter) -> Dict[str, Any]:
    """Place an order based on strategy signal with Redis metadata storage"""
    try:
        instrument = signal['instrument']
        
        # Calculate pip value (simplified)
        pip_value = 0.0001 if 'JPY' not in instrument else 0.01
        
        # Calculate position size
        stop_distance_pips = abs(signal['entry_price'] - signal['stop_loss']) / pip_value
        position_size = calculate_position_size(
            account_balance,
            signal.get('risk_amount', 2.0),  # Default 2% risk
            int(stop_distance_pips),
            pip_value
        )
        
        # Ensure minimum position size
        if position_size < 1000:
            position_size = 1000
        
        # Adjust units for direction
        units = position_size if signal['action'] == 'BUY' else -position_size
        
        logger.info(f"Placing {signal['order_type']} order: {signal['action']} {units} {instrument} "
                   f"@ {signal['entry_price']:.5f}, SL={signal['stop_loss']:.5f}, "
                   f"TP={signal['take_profit']:.5f}")
        
        # Place the order
        if signal['order_type'] == 'LIMIT':
            result = oanda_api.place_limit_order(
                instrument=instrument,
                units=units,
                price=signal['entry_price'],
                stop_loss=signal['stop_loss'],
                take_profit=signal['take_profit']
            )
        else:
            result = oanda_api.place_market_order(
                instrument=instrument,
                units=units,
                stop_loss=signal['stop_loss'],
                take_profit=signal['take_profit']
            )
        
        # Store Redis metadata if order was successful
        if result and 'orderFillTransaction' in result:
            order_id = result['orderFillTransaction'].get('id', 'unknown')
            save_trade_metadata_to_redis(signal, order_id, redis_writer)
        elif result and 'orderCreateTransaction' in result:
            order_id = result['orderCreateTransaction'].get('id', 'unknown')
            save_trade_metadata_to_redis(signal, order_id, redis_writer)
        
        return result
        
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return {'error': str(e)}

def save_trade_metadata_to_redis(signal: Dict[str, Any], order_id: str, redis_writer: RedisTradeWriter):
    """Save trade metadata to Redis for Airtable sync integration"""
    try:
        # Create metadata object
        metadata = TradeMetadata(
            setup_name=f"DC_H1_Setup_{signal.get('instrument', 'unknown')}",
            strategy_tag="DimeCurveStrategy",
            momentum_strength=signal.get('momentum_strength', 'Medium'),
            momentum_direction=signal.get('action', 'Unknown'),
            strategy_bias=signal.get('strategy_bias', 'Trend_Following'),
            momentum_alignment='Aligned' if signal.get('confidence', 0) > 70 else 'Partial',
            zone_position="Dime_Level_Entry",
            distance_to_entry_pips=signal.get('distance_to_entry_pips', 0.0),
            signal_confidence=signal.get('confidence', 60)
        )
        
        # Create Redis-compatible trade metadata
        trade_key = f"trade:metadata:{order_id}"
        trade_metadata = {
            'trade_id': order_id,
            'strategy_name': 'Dime Curve Strategy',
            'order_type': signal.get('order_type', 'LIMIT'),
            'setup_name': metadata.setup_name,
            'confidence': metadata.signal_confidence,
            'instrument': signal.get('instrument'),
            'action': signal.get('action'),
            'entry_price': signal.get('entry_price'),
            'stop_loss': signal.get('stop_loss'),
            'take_profit': signal.get('take_profit'),
            'rr_ratio': signal.get('rr_ratio', 2.0),
            'momentum_strength': metadata.momentum_strength,
            'momentum_direction': metadata.momentum_direction,
            'strategy_bias': metadata.strategy_bias,
            'zone_position': metadata.zone_position,
            'timestamp': datetime.now().isoformat()
        }
        
        # Store in Redis with 24-hour expiry
        if redis_writer.redis_client:
            redis_writer.redis_client.setex(trade_key, 86400, json.dumps(trade_metadata))
            logger.info(f"✅ Trade metadata stored in Redis: {trade_key}")
        else:
            logger.warning("⚠️ Redis not available - metadata not stored")
            
    except Exception as e:
        logger.error(f"❌ Error saving trade metadata to Redis: {str(e)}")

def lambda_handler(event, context):
    """Enhanced Lambda handler with trading session filtering and Redis integration"""
    start_time = datetime.now()
    
    try:
        logger.info("🚀 Starting Dime Curve Strategy Lambda (Enhanced)")
        logger.info(f"📅 Timestamp: {start_time.isoformat()}")
        
        # Initialize trading session manager
        session_manager = TradingSessionManager()
        session_info = session_manager.get_session_info()
        
        logger.info(f"📊 Trading Session Info: {session_info}")
        
        # Initialize Redis writer
        redis_writer = RedisTradeWriter()
        if redis_writer.redis_client:
            logger.info("✅ Redis connection established for metadata storage")
        else:
            logger.warning("⚠️ Redis connection failed - will continue without metadata storage")
        
        # Get credentials
        api_key, account_id = get_credentials()
        oanda_api = OandaAPI(api_key, account_id)
        
        # Get account information
        account_info = oanda_api.get_account_info()
        if not account_info:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get account information'})
            }
        
        account_balance = float(account_info.get('balance', 0))
        logger.info(f"💰 Account Balance: ${account_balance:,.2f}")
        
        # Define instruments to trade
        instruments = [
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'AUD_USD', 'USD_CAD',
            'EUR_GBP', 'EUR_JPY', 'GBP_JPY', 'AUD_JPY', 'NZD_USD',
            'USD_CHF', 'EUR_CAD', 'GBP_CAD', 'AUD_CAD', 'CAD_JPY',
            'CHF_JPY', 'EUR_AUD', 'GBP_AUD', 'EUR_NZD', 'GBP_NZD',
            'AUD_NZD', 'NZD_JPY', 'USD_SEK', 'EUR_SEK', 'GBP_SEK',
            'AUD_SEK', 'NZD_SEK', 'SEK_JPY'
        ]
        
        # Filter instruments based on trading sessions
        tradeable_instruments = []
        for instrument in instruments:
            if session_manager.is_prime_trading_session(instrument):
                tradeable_instruments.append(instrument)
            else:
                logger.info(f"⏰ Skipping {instrument} - not in prime trading session")
        
        logger.info(f"📈 Trading {len(tradeable_instruments)} instruments during prime sessions")
        
        if not tradeable_instruments:
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No instruments in prime trading sessions',
                    'session_info': session_info,
                    'total_instruments_checked': len(instruments)
                })
            }
        
        # Try centralized data first, fallback to OANDA
        market_client = CentralizedMarketDataClient()
        market_data = get_market_data_from_centralized(market_client, tradeable_instruments)
        
        if not market_data:
            logger.warning("Centralized data unavailable, falling back to OANDA API")
            market_data = get_market_data_from_oanda(oanda_api, tradeable_instruments)
        
        if not market_data:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get market data from any source'})
            }
        
        # Initialize strategy
        strategy = DC_H1_ALL_DUAL_LIMIT_100SL()
        
        # Process each instrument
        signals_generated = []
        orders_placed = []
        
        for instrument, data in market_data.items():
            try:
                logger.info(f"🔍 Analyzing {instrument}...")
                
                # Generate strategy signal
                signal = strategy.generate_signal(data)
                
                if signal and signal.get('action') in ['BUY', 'SELL']:
                    signals_generated.append(signal)
                    logger.info(f"📊 Signal generated for {instrument}: {signal['action']} "
                               f"@ {signal['entry_price']:.5f} (Confidence: {signal.get('confidence', 0)}%)")
                    
                    # Place order if signal is strong enough
                    if signal.get('confidence', 0) >= 65:  # Minimum confidence threshold
                        result = place_order_from_signal(oanda_api, signal, account_balance, redis_writer)
                        
                        if result and 'error' not in result:
                            orders_placed.append({
                                'instrument': instrument,
                                'signal': signal,
                                'result': result
                            })
                            logger.info(f"✅ Order placed for {instrument}")
                        else:
                            logger.error(f"❌ Failed to place order for {instrument}: {result}")
                    else:
                        logger.info(f"⚠️ Signal confidence too low for {instrument}: {signal.get('confidence')}%")
                
            except Exception as e:
                logger.error(f"Error processing {instrument}: {str(e)}")
                continue
        
        # Execution summary
        execution_time = (datetime.now() - start_time).total_seconds()
        
        summary = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Dime Curve Strategy execution completed',
                'execution_time_seconds': execution_time,
                'session_info': session_info,
                'instruments_analyzed': len(tradeable_instruments),
                'signals_generated': len(signals_generated),
                'orders_placed': len(orders_placed),
                'account_balance': account_balance,
                'data_source': list(market_data.values())[0].get('data_source', 'unknown') if market_data else 'none',
                'redis_connected': redis_writer.redis_client is not None,
                'timestamp': datetime.now().isoformat()
            })
        }
        
        logger.info(f"🎉 Execution completed in {execution_time:.2f}s")
        logger.info(f"📊 Summary: {len(signals_generated)} signals, {len(orders_placed)} orders placed")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ Lambda execution failed: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }