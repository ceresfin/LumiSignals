"""
AWS Lambda handler for Dime Curve DC H1 Dual Limit Strategy
Integrates with OANDA API to get real market data and place trades
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

# Import strategy and OANDA API
from dc_h1_all_dual_limit_100sl import DC_H1_ALL_DUAL_LIMIT_100SL

# Import OANDA API from trading common layer
sys.path.append('/opt/python')  # Lambda layer path
from oanda_api import OandaAPI
from momentum_calculator import calculate_momentum


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


def get_market_data(oanda_api: OandaAPI, instruments: List[str]) -> Dict[str, Any]:
    """Get current market data and calculate momentum for instruments"""
    market_data = {}
    
    for instrument in instruments:
        try:
            # Get current price
            prices = oanda_api.get_current_prices([instrument])
            if not prices.get('prices'):
                logger.warning(f"No price data for {instrument}")
                continue
            
            price_data = prices['prices'][0]
            current_price = float(price_data['bid'])  # Use bid for conservative entry
            
            # Get historical candles for momentum calculation
            # H1 candles for 60m momentum (need 2 candles)
            h1_candles = oanda_api.get_candles(instrument, 'H1', count=25)
            
            # H4 candles for 4h momentum (need 2 candles)
            h4_candles = oanda_api.get_candles(instrument, 'H4', count=25)
            
            # Calculate momentum
            momentum_60m = 0.0
            momentum_4h = 0.0
            
            if h1_candles.get('candles') and len(h1_candles['candles']) >= 2:
                # Simple momentum: (current - previous) / previous
                current_candle = h1_candles['candles'][-1]
                previous_candle = h1_candles['candles'][-2]
                
                current_close = float(current_candle['mid']['c'])
                previous_close = float(previous_candle['mid']['c'])
                
                if previous_close > 0:
                    momentum_60m = (current_close - previous_close) / previous_close
            
            if h4_candles.get('candles') and len(h4_candles['candles']) >= 2:
                current_candle = h4_candles['candles'][-1]
                previous_candle = h4_candles['candles'][-2]
                
                current_close = float(current_candle['mid']['c'])
                previous_close = float(previous_candle['mid']['c'])
                
                if previous_close > 0:
                    momentum_4h = (current_close - previous_close) / previous_close
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'momentum_60m': momentum_60m,
                'momentum_4h': momentum_4h,
                'bid': float(price_data['bid']),
                'ask': float(price_data['ask']),
                'spread': float(price_data['ask']) - float(price_data['bid'])
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
        
        # Get credentials
        api_key, account_id = get_credentials()
        
        # Initialize OANDA API
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
        
        # Get market data
        market_data_dict = get_market_data(oanda_api, instruments)
        
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
        
        # Initialize strategy
        config = {
            'momentum_threshold': 0.05,
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
            'curve_info': strategy.get_curve_info()
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


# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {}
    
    # Mock context
    class MockContext:
        aws_request_id = 'test-request-id'
        function_name = 'dime_curve_dc_h1_all_dual_limit_100sl'
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))