
"""
AWS Lambda handler for Dime Curve DC H1 Dual Limit Strategy
Uses centralized market data from Redis/PostgreSQL with OANDA API fallback
"""

import json
import logging
import os
import sys
import boto3
from datetime import datetime, timedelta
from typing import Dict, Any, List

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import strategy, momentum calculator, and centralized data client
from dc_h1_all_dual_limit_100sl import DC_H1_ALL_DUAL_LIMIT_100SL
from momentum_calculator import calculate_momentum
from centralized_market_data_client import CentralizedMarketDataClient

# Import OANDA API from trading common layer (only for trade execution)
sys.path.append('/opt/python')  # Lambda layer path
from oanda_api import OandaAPI


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


def get_market_data(market_client: CentralizedMarketDataClient, instruments: List[str]) -> Dict[str, Any]:
    """Get current market data from centralized system and calculate momentum"""
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
            # Get current price from centralized data
            if instrument not in prices:
                logger.warning(f"No price data for {instrument} in centralized system")
                continue
            
            price_info = prices[instrument]
            current_price = float(price_info.get('bid', price_info.get('price', 0)))
            bid = float(price_info.get('bid', current_price))
            ask = float(price_info.get('ask', current_price))
            spread = ask - bid
            
            # Get historical candles for momentum calculation from centralized system
            h1_candles = market_client.get_candlesticks_for_pair(instrument, 'H1')
            h4_candles = market_client.get_candlesticks_for_pair(instrument, 'H4')
            
            # Calculate momentum
            momentum_60m = 0.0
            momentum_4h = 0.0
            
            if h1_candles and len(h1_candles) >= 2:
                momentum_60m = calculate_momentum_from_centralized(h1_candles)
            
            if h4_candles and len(h4_candles) >= 2:
                momentum_4h = calculate_momentum_from_centralized(h4_candles)
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'momentum_60m': momentum_60m,
                'momentum_4h': momentum_4h,
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'data_source': price_data.get('source', 'unknown')
            }
            
            logger.info(f"Market data for {instrument}: Price={current_price:.5f}, "
                       f"Momentum 60m={momentum_60m:.4f}, 4h={momentum_4h:.4f}, "
                       f"Source={price_data.get('source', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Error processing market data for {instrument}: {str(e)}")
            continue
    
    return market_data


def calculate_momentum_from_centralized(candles: List[Dict[str, Any]], periods: int = 2) -> float:
    """Calculate momentum from centralized candlestick data"""
    if not candles or len(candles) < periods:
        return 0.0
    
    try:
        # Centralized data format may be different than OANDA format
        current_candle = candles[-1]
        previous_candle = candles[-periods]
        
        # Try different possible formats for close price
        current_close = None
        previous_close = None
        
        for key in ['c', 'close', 'close_price']:
            if key in current_candle:
                current_close = float(current_candle[key])
                break
        
        for key in ['c', 'close', 'close_price']:
            if key in previous_candle:
                previous_close = float(previous_candle[key])
                break
        
        if current_close is None or previous_close is None or previous_close == 0:
            return 0.0
        
        # Calculate percentage change
        momentum = (current_close - previous_close) / previous_close
        return momentum
        
    except (KeyError, ValueError, IndexError, TypeError) as e:
        logger.warning(f"Error calculating momentum: {str(e)}")
        return 0.0


def calculate_position_size(account_balance: float, risk_per_trade: float, 
                          stop_loss_pips: int, pip_value: float) -> int:
    """Calculate position size based on risk management"""
    risk_amount = account_balance * (risk_per_trade / 100)
    position_size = risk_amount / (stop_loss_pips * pip_value)
    
    # Round to nearest 1000 units (micro lot)
    return int(position_size / 1000) * 1000


def place_order_from_signal(oanda_api: OandaAPI, signal: Dict[str, Any], 
                          account_balance: float) -> Dict[str, Any]:
    """Place an order based on strategy signal"""
    try:
        instrument = signal['instrument']
        
        # Calculate pip value (simplified)
        pip_value = 0.0001 if 'JPY' not in instrument else 0.01
        
        # Calculate position size
        stop_distance_pips = abs(signal['entry_price'] - signal['stop_loss']) / pip_value
        position_size = calculate_position_size(
            account_balance,
            signal['risk_per_trade'],
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
        
        return result
        
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return {'error': str(e)}


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler"""
    
    strategy_name = 'dime_curve_dc_h1_all_dual_limit_100sl'
    
    try:
        logger.info(f"🚀 Starting {strategy_name} strategy execution")
        
        # Initialize centralized market data client
        market_client = CentralizedMarketDataClient()
        logger.info("✅ Initialized centralized market data client")
        
        # Get credentials for trade execution only
        api_key, account_id = get_credentials()
        
        # Initialize OANDA API for trade execution only
        oanda_api = OandaAPI(api_key, account_id, environment='practice')
        
        # Get account info
        account_info = oanda_api.get_account_summary()
        account_balance = float(account_info['account']['balance'])
        logger.info(f"Account balance: {account_balance}")
        
        # Define instruments to trade (major pairs)
        instruments = [
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CHF',
            'AUD_USD', 'USD_CAD', 'NZD_USD', 'EUR_GBP',
            'EUR_JPY', 'GBP_JPY'
        ]
        
        # Get market data from centralized system
        market_data_dict = get_market_data(market_client, instruments)
        
        if not market_data_dict:
            logger.warning("No market data available")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'strategy': strategy_name,
                    'status': 'no_data',
                    'message': 'No market data available'
                })
            }
        
        # Initialize strategy with lower momentum threshold for forex
        config = {
            'momentum_threshold': 0.001,  # 0.1% instead of 5% for realistic forex trading
            'stop_loss_pips': 100,
            'risk_per_trade': 2.0,  # Risk 2% per trade
            'debug_mode': True,
            'log_signals': True
        }
        
        strategy = DC_H1_ALL_DUAL_LIMIT_100SL(config)
        
        # Analyze each instrument
        signals_generated = []
        orders_placed = []
        
        for instrument, market_data in market_data_dict.items():
            try:
                # Analyze market
                analysis = strategy.analyze_market(market_data)
                
                if analysis.get('opportunity_detected'):
                    # Generate signal
                    signal = strategy.generate_signal(analysis)
                    
                    if signal:
                        # Validate signal
                        is_valid, reason = strategy.validate_signal(signal)
                        
                        if is_valid:
                            logger.info(f"Valid signal for {instrument}: {signal['reasoning'][0]}")
                            signals_generated.append(signal)
                            
                            # Place order
                            order_result = place_order_from_signal(
                                oanda_api, signal, account_balance
                            )
                            
                            if 'orderCreateTransaction' in order_result:
                                orders_placed.append({
                                    'instrument': instrument,
                                    'order_id': order_result['orderCreateTransaction']['id'],
                                    'action': signal['action'],
                                    'entry_price': signal['entry_price'],
                                    'rr_ratio': signal['rr_ratio']
                                })
                                logger.info(f"✅ Order placed successfully for {instrument}")
                            else:
                                logger.error(f"Failed to place order for {instrument}: {order_result}")
                        else:
                            logger.info(f"Signal invalid for {instrument}: {reason}")
                
            except Exception as e:
                logger.error(f"Error analyzing {instrument}: {str(e)}")
                continue
        
        # Get active orders for this strategy
        active_orders = strategy.get_active_orders()
        
        # Get data source information
        data_sources = list(set([data.get('data_source', 'unknown') for data in market_data_dict.values()]))
        
        # Prepare response
        result = {
            'strategy': strategy_name,
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'account_balance': account_balance,
            'instruments_analyzed': len(market_data_dict),
            'signals_generated': len(signals_generated),
            'orders_placed': len(orders_placed),
            'active_orders': len(active_orders),
            'orders': orders_placed,
            'curve_info': strategy.get_curve_info(),
            'market_data_source': data_sources,
            'centralized_data_used': True,
            'api_calls_saved': len(market_data_dict) * 3  # Price + 2 candlestick calls per instrument
        }
        
        logger.info(f"✅ Strategy execution completed: {len(orders_placed)} orders placed")
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        logger.error(f"❌ Strategy execution failed: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'strategy': strategy_name,
                'status': 'error',
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            })
        }
