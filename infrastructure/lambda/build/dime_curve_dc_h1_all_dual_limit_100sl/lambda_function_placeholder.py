"""
AWS Lambda handler for dime_curve_dc_h1_all_dual_limit_100sl
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

# Import centralized data client
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


def get_market_data_from_centralized(market_client: CentralizedMarketDataClient, instruments: List[str]) -> Dict[str, Any]:
    """Get market data from centralized system"""
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
            current_price = float(price_info.get('bid', price_info.get('price', 0)))
            bid = float(price_info.get('bid', current_price))
            ask = float(price_info.get('ask', current_price))
            spread = ask - bid
            
            market_data[instrument] = {
                'instrument': instrument,
                'current_price': current_price,
                'bid': bid,
                'ask': ask,
                'spread': spread,
                'data_source': price_data.get('source', 'unknown')
            }
            
            logger.info(f"Market data for {instrument}: Price={current_price:.5f}, "
                       f"Source={price_data.get('source', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Error processing market data for {instrument}: {str(e)}")
            continue
    
    return market_data


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler using centralized market data"""
    
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
        
        # Get credentials for potential trade execution
        try:
            api_key, account_id = get_credentials()
            oanda_api = OandaAPI(api_key, account_id, environment='practice')
            account_info = oanda_api.get_account_summary()
            account_balance = float(account_info['account']['balance'])
            logger.info(f"Account balance: {account_balance}")
        except Exception as e:
            logger.warning(f"Could not get account info: {str(e)}")
            account_balance = 100000.0  # Default for testing
        
        # Analyze market data (placeholder for strategy logic)
        signals_generated = []
        orders_placed = []
        
        # TODO: Add specific strategy logic here
        # For now, just log that we have centralized data
        for instrument, data in market_data_dict.items():
            logger.info(f"{instrument}: {data['current_price']:.5f} from {data['data_source']}")
        
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
            'market_data_source': data_sources,
            'centralized_data_used': True,
            'api_calls_saved': len(market_data_dict) * 3,  # Price + 2 candlestick calls per instrument
            'message': f'Strategy updated to use centralized data from {data_sources[0] if data_sources else "unknown"}'
        }
        
        logger.info(f"✅ Strategy execution completed with centralized data from {data_sources}")
        
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
