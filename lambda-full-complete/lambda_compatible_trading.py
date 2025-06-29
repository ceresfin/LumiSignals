import json
import logging
import requests
import boto3
from datetime import datetime, timezone
from decimal import Decimal
import time

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

class TradingOrderLogger:
    def __init__(self, use_cloudwatch=True, use_dynamodb=True):
        self.use_cloudwatch = use_cloudwatch
        self.use_dynamodb = use_dynamodb
        
        # Setup DynamoDB for persistent storage
        if use_dynamodb:
            try:
                self.dynamodb = boto3.resource('dynamodb')
                self.orders_table = self.dynamodb.Table('trading-orders-log')
            except Exception as e:
                logger.error(f"Failed to initialize DynamoDB: {str(e)}")
                self.use_dynamodb = False
    
    def log_order_decision(self, instrument, action, order_details, market_data, analysis_data):
        """Log detailed information about why an order was placed or skipped"""
        timestamp = datetime.utcnow().isoformat()
        
        log_entry = {
            'timestamp': timestamp,
            'instrument': instrument,
            'action': action,  # 'PLACED', 'SKIPPED', 'REJECTED'
            'order_details': order_details,
            'market_data': market_data,
            'analysis_data': analysis_data
        }
        
        # Log to CloudWatch
        if self.use_cloudwatch:
            logger.info(f"ORDER_LOG: {json.dumps(log_entry, default=str)}")
        
        # Store in DynamoDB
        if self.use_dynamodb:
            self._store_to_dynamodb(log_entry)
        
        return log_entry
    
    def _store_to_dynamodb(self, log_entry):
        """Store order log to DynamoDB for queryable history"""
        try:
            # Convert floats to Decimal for DynamoDB
            item = self._convert_floats_to_decimal(log_entry)
            item['id'] = f"{log_entry['instrument']}_{log_entry['timestamp']}"
            
            self.orders_table.put_item(Item=item)
        except Exception as e:
            logger.error(f"Failed to store to DynamoDB: {str(e)}")
    
    def _convert_floats_to_decimal(self, obj):
        """Convert floats to Decimal for DynamoDB compatibility"""
        if isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(v) for v in obj]
        elif isinstance(obj, float):
            return Decimal(str(obj))
        return obj

class OandaAPI:
    def __init__(self, api_key, account_id, environment='practice'):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = 'https://api-fxpractice.oanda.com' if environment == 'practice' else 'https://api-fxtrade.oanda.com'
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def get_account_info(self):
        """Get account information"""
        try:
            response = requests.get(f'{self.base_url}/v3/accounts/{self.account_id}', headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get account info: {str(e)}")
            return None
    
    def get_open_trades(self):
        """Get open trades"""
        try:
            response = requests.get(f'{self.base_url}/v3/accounts/{self.account_id}/openTrades', headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get open trades: {str(e)}")
            return None
    
    def get_pricing(self, instruments):
        """Get current pricing for instruments"""
        try:
            instruments_str = ','.join(instruments)
            response = requests.get(
                f'{self.base_url}/v3/accounts/{self.account_id}/pricing',
                headers=self.headers,
                params={'instruments': instruments_str}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get pricing: {str(e)}")
            return None
    
    def get_candles(self, instrument, count=100, granularity='M15'):
        """Get historical candles for technical analysis"""
        try:
            response = requests.get(
                f'{self.base_url}/v3/instruments/{instrument}/candles',
                headers=self.headers,
                params={
                    'count': count,
                    'granularity': granularity,
                    'price': 'M'  # Mid prices
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get candles for {instrument}: {str(e)}")
            return None
    
    def place_market_order(self, instrument, units, stop_loss=None, take_profit=None):
        """Place a market order"""
        try:
            order_data = {
                'order': {
                    'type': 'MARKET',
                    'instrument': instrument,
                    'units': str(units)
                }
            }
            
            if stop_loss:
                order_data['order']['stopLossOnFill'] = {'price': str(stop_loss)}
            if take_profit:
                order_data['order']['takeProfitOnFill'] = {'price': str(take_profit)}
            
            response = requests.post(
                f'{self.base_url}/v3/accounts/{self.account_id}/orders',
                headers=self.headers,
                json=order_data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to place market order: {str(e)}")
            raise e

class TechnicalAnalyzer:
    def __init__(self):
        pass
    
    def calculate_sma(self, prices, period):
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period
    
    def calculate_rsi(self, prices, period=14):
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return None
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [delta if delta > 0 else 0 for delta in deltas]
        losses = [-delta if delta < 0 else 0 for delta in deltas]
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calculate_momentum(self, prices, period=10):
        """Calculate price momentum"""
        if len(prices) < period + 1:
            return 0
        
        current_price = prices[-1]
        past_price = prices[-period-1]
        
        if past_price == 0:
            return 0
        
        momentum = (current_price - past_price) / past_price
        return momentum
    
    def analyze_instrument(self, candles_data):
        """Perform comprehensive technical analysis"""
        if not candles_data or 'candles' not in candles_data:
            return None
        
        candles = candles_data['candles']
        if len(candles) < 50:  # Need enough data for analysis
            return None
        
        # Extract close prices
        prices = [float(candle['mid']['c']) for candle in candles if candle['complete']]
        
        if len(prices) < 20:
            return None
        
        current_price = prices[-1]
        
        # Calculate indicators
        sma_20 = self.calculate_sma(prices, 20)
        sma_50 = self.calculate_sma(prices, 50)
        rsi = self.calculate_rsi(prices)
        momentum_10 = self.calculate_momentum(prices, 10)
        momentum_20 = self.calculate_momentum(prices, 20)
        
        # Determine trend and signals
        trend = 'NEUTRAL'
        signal_triggers = []
        
        if sma_20 and sma_50:
            if sma_20 > sma_50:
                trend = 'BULLISH'
                signal_triggers.append('SMA_BULLISH')
            elif sma_20 < sma_50:
                trend = 'BEARISH'
                signal_triggers.append('SMA_BEARISH')
        
        # RSI signals
        if rsi:
            if rsi > 70:
                signal_triggers.append('RSI_OVERBOUGHT')
            elif rsi < 30:
                signal_triggers.append('RSI_OVERSOLD')
            elif 40 < rsi < 60:
                signal_triggers.append('RSI_NEUTRAL')
        
        # Momentum analysis
        momentum_bias = 'NEUTRAL'
        momentum_strength = abs(momentum_10) if momentum_10 else 0
        
        if momentum_10 > 0.001:  # 0.1% threshold
            momentum_bias = 'BULLISH'
        elif momentum_10 < -0.001:
            momentum_bias = 'BEARISH'
        
        # Generate trading signal
        signal_action = 'WAIT'
        confidence = 0
        
        if momentum_bias == 'BULLISH' and trend == 'BULLISH' and rsi and rsi < 70:
            signal_action = 'BUY'
            confidence = min(80 + int(momentum_strength * 100), 95)
        elif momentum_bias == 'BEARISH' and trend == 'BEARISH' and rsi and rsi > 30:
            signal_action = 'SELL'
            confidence = min(80 + int(momentum_strength * 100), 95)
        
        return {
            'current_price': current_price,
            'sma_20': sma_20,
            'sma_50': sma_50,
            'rsi': rsi,
            'momentum_10': momentum_10,
            'momentum_20': momentum_20,
            'momentum_bias': momentum_bias,
            'momentum_strength': momentum_strength,
            'trend': trend,
            'signal_action': signal_action,
            'confidence': confidence,
            'signal_triggers': signal_triggers
        }

def get_market_session():
    """Determine current market session based on UTC time"""
    utc_hour = datetime.utcnow().hour
    
    if 0 <= utc_hour < 7:
        return "ASIA_PACIFIC"
    elif 7 <= utc_hour < 15:
        return "LONDON"
    elif 15 <= utc_hour < 22:
        return "NEW_YORK"
    else:
        return "SYDNEY"

def is_trading_time_optimal():
    """Check if current time is optimal for trading"""
    utc_hour = datetime.utcnow().hour
    
    # Optimal times: London session (8-16 UTC) and NY session overlap (13-17 UTC)
    if 8 <= utc_hour <= 16:
        return True, "London session"
    elif 13 <= utc_hour <= 17:
        return True, "London-NY overlap"
    elif 22 <= utc_hour <= 23 or 0 <= utc_hour <= 6:
        return False, "Low liquidity period"
    else:
        return False, "Between major sessions"

def get_secrets():
    """Retrieve API credentials from AWS Secrets Manager"""
    secret_name = "oanda-trading-bot/credentials"
    region_name = "us-east-1"
    
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(get_secret_value_response['SecretString'])
        return secret['API_KEY'], secret['ACCOUNT_ID']
    except Exception as e:
        logger.error(f"Failed to retrieve secrets: {str(e)}")
        raise e

def lambda_handler(event, context):
    """Main Lambda handler with detailed logging"""
    
    try:
        # Initialize components
        order_logger = TradingOrderLogger(use_cloudwatch=True, use_dynamodb=True)
        
        # Get API credentials from Secrets Manager
        api_key, account_id = get_secrets()
        
        oanda_api = OandaAPI(api_key, account_id)
        analyzer = TechnicalAnalyzer()
        
        # Get account info
        account_info = oanda_api.get_account_info()
        if not account_info:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get account info'})
            }
        
        account_balance = float(account_info['account']['balance'])
        
        # Get open trades
        open_trades_response = oanda_api.get_open_trades()
        open_trades_count = len(open_trades_response['trades']) if open_trades_response else 0
        
        # Check trading time
        is_optimal, time_reason = is_trading_time_optimal()
        current_session = get_market_session()
        
        # Instruments to analyze
        instruments = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD']
        
        # Get current pricing
        pricing_data = oanda_api.get_pricing(instruments)
        if not pricing_data:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get pricing data'})
            }
        
        # Analyze each instrument
        analysis_summary = []
        signals_generated = 0
        trades_executed = 0
        opportunities_skipped = 0
        
        for instrument in instruments:
            try:
                # Get candles for technical analysis
                candles_data = oanda_api.get_candles(instrument)
                if not candles_data:
                    continue
                
                # Perform technical analysis
                analysis = analyzer.analyze_instrument(candles_data)
                if not analysis:
                    continue
                
                # Get current market data
                instrument_pricing = next((p for p in pricing_data['prices'] if p['instrument'] == instrument), None)
                if not instrument_pricing:
                    continue
                
                current_price = float(instrument_pricing['closeoutBid'])
                bid = float(instrument_pricing['bids'][0]['price'])
                ask = float(instrument_pricing['asks'][0]['price'])
                spread = ask - bid
                
                # Market data for logging
                market_data = {
                    'current_price': current_price,
                    'bid': bid,
                    'ask': ask,
                    'spread': spread,
                    'time_of_day': datetime.utcnow().hour,
                    'market_session': current_session
                }
                
                # Analysis data for logging
                analysis_data = {
                    'momentum_strength': analysis['momentum_strength'],
                    'momentum_direction': analysis['momentum_bias'],
                    'rsi': analysis['rsi'],
                    'sma_20': analysis['sma_20'],
                    'sma_50': analysis['sma_50'],
                    'trend': analysis['trend'],
                    'signal_triggers': analysis['signal_triggers']
                }
                
                # Determine if we should trade
                should_trade = False
                skip_reason = "No signal"
                
                if analysis['signal_action'] in ['BUY', 'SELL'] and analysis['confidence'] > 75:
                    signals_generated += 1
                    
                    if not is_optimal:
                        skip_reason = "Poor timing"
                    elif spread > 0.0005:  # 0.5 pip spread threshold
                        skip_reason = "High spread"
                    elif open_trades_count >= 5:  # Max open trades
                        skip_reason = "Too many open trades"
                    elif account_balance < 10000:  # Minimum balance check
                        skip_reason = "Insufficient balance"
                    else:
                        should_trade = True
                
                # Prepare order details for logging
                units = 1000 if analysis['signal_action'] == 'BUY' else -1000
                stop_loss = current_price * 0.995 if analysis['signal_action'] == 'BUY' else current_price * 1.005
                take_profit = current_price * 1.01 if analysis['signal_action'] == 'BUY' else current_price * 0.99
                
                order_details = {
                    'order_type': 'MARKET',
                    'side': analysis['signal_action'],
                    'units': units,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'confidence': analysis['confidence']
                }
                
                if should_trade:
                    try:
                        # Place the order
                        order_response = oanda_api.place_market_order(
                            instrument=instrument,
                            units=units,
                            stop_loss=stop_loss,
                            take_profit=take_profit
                        )
                        
                        # Log successful order
                        if order_response and 'orderFillTransaction' in order_response:
                            fill_transaction = order_response['orderFillTransaction']
                            order_details['order_id'] = fill_transaction.get('id')
                            order_details['fill_price'] = float(fill_transaction.get('price', current_price))
                            order_details['transaction_id'] = fill_transaction.get('id')
                            
                            order_logger.log_order_decision(
                                instrument=instrument,
                                action='PLACED',
                                order_details=order_details,
                                market_data=market_data,
                                analysis_data=analysis_data
                            )
                            
                            trades_executed += 1
                        else:
                            # Order failed
                            order_details['error'] = 'Order execution failed'
                            order_logger.log_order_decision(
                                instrument=instrument,
                                action='REJECTED',
                                order_details=order_details,
                                market_data=market_data,
                                analysis_data=analysis_data
                            )
                            opportunities_skipped += 1
                            skip_reason = "Order execution failed"
                    
                    except Exception as e:
                        # Log failed order
                        order_details['error'] = str(e)
                        order_logger.log_order_decision(
                            instrument=instrument,
                            action='REJECTED',
                            order_details=order_details,
                            market_data=market_data,
                            analysis_data=analysis_data
                        )
                        opportunities_skipped += 1
                        skip_reason = f"Order failed: {str(e)}"
                
                else:
                    # Log skipped opportunity
                    if analysis['signal_action'] in ['BUY', 'SELL']:
                        order_logger.log_order_decision(
                            instrument=instrument,
                            action='SKIPPED',
                            order_details={**order_details, 'skip_reason': skip_reason},
                            market_data=market_data,
                            analysis_data=analysis_data
                        )
                        opportunities_skipped += 1
                
                # Add to summary
                analysis_summary.append({
                    'instrument': instrument,
                    'current_price': current_price,
                    'momentum_bias': analysis['momentum_bias'],
                    'momentum_strength': analysis['momentum_strength'],
                    'signal_action': analysis['signal_action'],
                    'confidence': analysis['confidence'],
                    'skip_reason': skip_reason if not should_trade else None
                })
                
            except Exception as e:
                logger.error(f"Error analyzing {instrument}: {str(e)}")
                continue
        
        # Prepare response
        response_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'account_balance': account_balance,
            'open_trades': open_trades_count,
            'trading_time_optimal': is_optimal,
            'time_reason': time_reason,
            'market_session': current_session,
            'instruments_analyzed': len(instruments),
            'signals_generated': signals_generated,
            'trades_executed': trades_executed,
            'opportunities_skipped': opportunities_skipped,
            'analysis_summary': analysis_summary
        }
        
        return {
            'statusCode': 200,
            'body': json.dumps(response_data, default=str)
        }
        
    except Exception as e:
        logger.error(f"Lambda execution error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })
        }