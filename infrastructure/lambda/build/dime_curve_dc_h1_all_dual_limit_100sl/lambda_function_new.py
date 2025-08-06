"""
AWS Lambda handler for dime_curve_dc_h1_all_dual_limit_100sl
Uses centralized market data from Redis/PostgreSQL with OANDA API fallback
Implements actual Dime Curve trading strategy with dual limit orders
"""

import json
import logging
import os
import sys
import boto3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Import centralized data client
from centralized_market_data_client import CentralizedMarketDataClient

# Import OANDA API from trading common layer (only for trade execution)
sys.path.append('/opt/python')  # Lambda layer path
from oanda_api import OandaAPI

# Import the strategy
from dc_h1_all_dual_limit_100sl import DC_H1_ALL_DUAL_LIMIT_100SL


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
    
    # Get momentum data from centralized system
    momentum_data = market_client.get_momentum_data()
    momentum_values = momentum_data.get('momentum', {})
    
    for instrument in instruments:
        try:
            if instrument not in prices:
                logger.warning(f"No price data for {instrument} in centralized system")
                continue
            
            price_info = prices[instrument]
            current_price = float(price_info.get('bid', price_info.get('price', 0)))
            bid = float(price_info.get('bid', current_price))
            ask = float(price_info.get('ask', current_price))
            spread = ask - bid
            
            # Get momentum values (default to 0 if not available)
            instrument_momentum = momentum_values.get(instrument, {})
            momentum_60m = instrument_momentum.get('momentum_60m', 0.0)
            momentum_4h = instrument_momentum.get('momentum_4h', 0.0)
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'momentum_60m': momentum_60m,
                'momentum_4h': momentum_4h,
                'data_source': price_data.get('source', 'unknown')
            }
            
            logger.info(f"Market data for {instrument}: Price={current_price:.5f}, "
                       f"Momentum 60m={momentum_60m:.4f}, 4h={momentum_4h:.4f}, "
                       f"Source={price_data.get('source', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Error processing market data for {instrument}: {str(e)}")
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
        
        return result
        
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return {'error': str(e)}


def save_trade_metadata(signal: Dict[str, Any], order_id: str):
    """Save trade metadata to Redis/PostgreSQL for strategy tracking"""
    try:
        # Initialize centralized client for metadata storage
        market_client = CentralizedMarketDataClient()
        
        metadata = {
            'order_id': order_id,
            'strategy_name': 'dime_curve_dc_h1_all_dual_limit_100sl',
            'strategy_tag': 'DimeCurve',
            'setup_name': 'DC_H1_ALL_DUAL_LIMIT_100SL',
            'signal_confidence': signal.get('confidence', 0),
            'entry_price': signal['entry_price'],
            'stop_loss': signal['stop_loss'],
            'take_profit': signal['take_profit'],
            'rr_ratio': signal['rr_ratio'],
            'reasoning': signal.get('reasoning', []),
            'timestamp': datetime.now().isoformat()
        }
        
        # Store in centralized system
        market_client.store_trade_metadata(metadata)
        logger.info(f"Stored trade metadata for order {order_id}")
        
    except Exception as e:
        logger.error(f"Error saving trade metadata: {str(e)}")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler using centralized market data and actual strategy logic"""
    
    strategy_name = os.environ.get('STRATEGY_NAME', 'dime_curve_dc_h1_all_dual_limit_100sl')
    
    try:
        logger.info(f"🚀 Starting {strategy_name} strategy execution with centralized data")
        
        # Initialize centralized market data client
        market_client = CentralizedMarketDataClient()
        logger.info("✅ Initialized centralized market data client")
        
        # Define instruments to trade (major pairs)
        instruments = [
            'EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CHF',
            'AUD_USD', 'USD_CAD', 'NZD_USD', 'EUR_GBP',
            'EUR_JPY', 'GBP_JPY'
        ]
        
        # Get market data from centralized system
        market_data_dict = get_market_data_from_centralized(market_client, instruments)
        
        if not market_data_dict:
            logger.warning("No market data available from centralized system")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'strategy': strategy_name,
                    'status': 'no_data',
                    'message': 'No market data available from centralized system',
                    'centralized_data_used': True
                })
            }
        
        # Get credentials for trade execution
        api_key, account_id = get_credentials()
        oanda_api = OandaAPI(api_key, account_id, environment='practice')
        account_info = oanda_api.get_account_summary()
        account_balance = float(account_info['account']['balance'])
        logger.info(f"Account balance: {account_balance}")
        
        # Initialize strategy with configuration
        config = {
            'momentum_threshold': 0.05,  # 5% momentum threshold
            'stop_loss_pips': 100,       # 100 pip stop loss for dime curve
            'risk_per_trade': 2.0,       # Risk 2% per trade
            'debug_mode': True,
            'log_signals': True
        }
        
        strategy = DC_H1_ALL_DUAL_LIMIT_100SL(config)
        logger.info("✅ Initialized Dime Curve strategy")
        
        # Analyze each instrument and generate signals
        signals_generated = []
        orders_placed = []
        
        for instrument, market_data in market_data_dict.items():
            try:
                # Analyze market
                analysis = strategy.analyze_market(market_data)
                
                # Check if zone penetration detected
                if analysis.get('penetration', {}).get('penetrated'):
                    # Generate signal (returns primary signal, but creates dual orders internally)
                    signal = strategy.generate_signal(analysis)
                    
                    if signal:
                        # Validate signal
                        is_valid, reason = strategy.validate_signal(signal)
                        
                        if is_valid:
                            logger.info(f"✅ Valid signal for {instrument}: {signal['reasoning'][0]}")
                            signals_generated.append(signal)
                            
                            # Place both dual limit orders
                            active_orders = strategy.get_active_orders()
                            
                            for order_signal in active_orders[-2:]:  # Get last 2 orders (dual)
                                order_result = place_order_from_signal(
                                    oanda_api, order_signal, account_balance
                                )
                                
                                if 'orderCreateTransaction' in order_result:
                                    order_id = order_result['orderCreateTransaction']['id']
                                    orders_placed.append({
                                        'instrument': instrument,
                                        'order_id': order_id,
                                        'action': order_signal['action'],
                                        'entry_price': order_signal['entry_price'],
                                        'order_type': order_signal['order_type'],
                                        'order_number': order_signal.get('order_number', 1),
                                        'rr_ratio': order_signal['rr_ratio']
                                    })
                                    
                                    # Save trade metadata
                                    save_trade_metadata(order_signal, order_id)
                                    
                                    logger.info(f"✅ Order #{order_signal.get('order_number', 1)} placed for {instrument}")
                                else:
                                    logger.error(f"Failed to place order for {instrument}: {order_result}")
                        else:
                            logger.info(f"Signal invalid for {instrument}: {reason}")
                else:
                    logger.debug(f"No zone penetration for {instrument}")
                
            except Exception as e:
                logger.error(f"Error analyzing {instrument}: {str(e)}")
                continue
        
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
            'active_orders': len(strategy.get_active_orders()),
            'market_data_source': data_sources,
            'centralized_data_used': True,
            'api_calls_saved': len(market_data_dict) * 3,
            'message': f'Dime Curve strategy executed with {len(orders_placed)} orders placed',
            'orders': orders_placed,
            'curve_info': strategy.get_curve_info() if hasattr(strategy, 'get_curve_info') else {
                'curve_type': 'DIME',
                'level_increment': 0.10,
                'zone_width_pips': 250,
                'stop_loss_pips': 100
            }
        }
        
        logger.info(f"✅ Strategy execution completed: {len(orders_placed)} orders placed from {len(signals_generated)} signals")
        
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
                'error': str(e),
                'centralized_data_attempted': True
            })
        }