import json
import boto3
import os
import sys
from datetime import datetime

def get_secrets():
    """Get Oanda credentials from AWS Secrets Manager"""
    try:
        secrets_client = boto3.client('secretsmanager')
        response = secrets_client.get_secret_value(
            SecretId='oanda-trading-bot/credentials'
        )
        secrets = json.loads(response['SecretString'])
        return secrets['API_KEY'], secrets['ACCOUNT_ID']
    except Exception as e:
        print(f"Error getting secrets: {e}")
        raise

def lambda_handler(event, context):
    """Full trading bot Lambda handler with complete functionality"""
    try:
        print("🚀 Starting FULL trading bot with complete functionality...")
        
        # Get credentials from Secrets Manager
        api_key, account_id = get_secrets()
        print("✅ Retrieved credentials from AWS Secrets Manager")
        
        # Set environment variables for your existing code
        os.environ['API_KEY'] = api_key
        os.environ['ACCOUNT_ID'] = account_id
        
        # Import your complete trading bot
        print("📦 Importing trading bot modules...")
        
        # Import all your existing classes
        from momentum_calculator import MarketAwareMomentumCalculator, ForexMarketSchedule
        from oanda_api import OandaAPI  
        from psychological_levels_trader import EnhancedPennyCurveStrategy, PsychologicalLevelsDetector
        
        print("✅ All modules imported successfully")
        
        # Initialize your complete trading system
        print("🔧 Initializing trading system...")
        api = OandaAPI(api_key, account_id, "practice")
        momentum_calc = MarketAwareMomentumCalculator(api)
        levels_detector = PsychologicalLevelsDetector()
        strategy = EnhancedPennyCurveStrategy(momentum_calc, levels_detector)
        
        print("✅ Trading system initialized")
        
        # Create the fixed dollar risk manager
        class FixedDollarRiskManager:
            def __init__(self, oanda_api, max_risk_usd=10.0):
                self.api = oanda_api
                self.max_risk_usd = max_risk_usd
                
            def calculate_position_size(self, instrument, entry_price, stop_loss_price, confidence=80):
                # Simplified but functional position sizing
                is_jpy = 'JPY' in instrument
                
                if is_jpy:
                    pip_value = 0.01
                else:
                    pip_value = 0.0001
                
                stop_loss_distance = abs(entry_price - stop_loss_price)
                stop_loss_pips = stop_loss_distance / pip_value
                
                # Confidence-based risk adjustment
                risk_multiplier = min(1.0, confidence / 100.0)
                adjusted_risk = self.max_risk_usd * risk_multiplier
                
                # Basic position size calculation
                if stop_loss_pips > 0:
                    pip_value_usd = 0.0001 if not is_jpy else 0.01
                    position_size = int(adjusted_risk / (stop_loss_pips * pip_value_usd))
                    position_size = max(1000, min(50000, position_size))
                else:
                    position_size = 1000
                
                return {
                    'position_size': position_size,
                    'risk_usd': round(stop_loss_pips * pip_value_usd, 2),
                    'is_risk_acceptable': True
                }
        
        # Initialize risk manager
        risk_manager = FixedDollarRiskManager(api, max_risk_usd=10.0)
        
        # Trading parameters
        instruments = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD', 'AUD_USD', 'NZD_USD']
        max_open_trades = 5
        
        print(f"📊 Analyzing {len(instruments)} instruments...")
        
        # Check market timing
        market_schedule = ForexMarketSchedule()
        current_market_time = market_schedule.get_market_time()
        is_market_open = market_schedule.is_market_open(current_market_time)
        
        if not is_market_open:
            print("🔒 Market is closed")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Market closed - no trading',
                    'market_open': False,
                    'timestamp': datetime.now().isoformat()
                })
            }
        
        print("✅ Market is open")
        
        # Get account info
        account_info = api.get_account_summary()
        balance = float(account_info['account']['balance'])
        open_trades = int(account_info['account']['openTradeCount'])
        
        print(f"💰 Account Balance: ${balance:.2f}")
        print(f"📈 Open Trades: {open_trades}")
        
        # Analysis results
        results = {
            'timestamp': datetime.now().isoformat(),
            'market_open': True,
            'account_balance': balance,
            'open_trades': open_trades,
            'instruments_analyzed': 0,
            'signals_generated': 0,
            'trades_executed': 0,
            'opportunities_skipped': 0,
            'analysis_details': []
        }
        
        # Analyze each instrument with full strategy
        for instrument in instruments:
            try:
                print(f"\n🔍 Analyzing {instrument} with full momentum-first strategy...")
                
                # Use your complete strategy analysis
                analysis = strategy.analyze_penny_curve_setup(instrument)
                
                if 'error' in analysis:
                    print(f"❌ Error analyzing {instrument}: {analysis['error']}")
                    continue
                
                results['instruments_analyzed'] += 1
                
                signals = analysis['signals']
                current_price = analysis['current_price']
                momentum_analysis = analysis['momentum_analysis']
                
                print(f"   Current Price: {current_price:.5f}")
                print(f"   Momentum: {momentum_analysis['direction']} ({momentum_analysis['momentum_strength']:+.3f}%)")
                print(f"   Strategy Bias: {momentum_analysis['strategy_bias']}")
                
                analysis_detail = {
                    'instrument': instrument,
                    'current_price': current_price,
                    'momentum_direction': momentum_analysis['direction'],
                    'momentum_strength': momentum_analysis['momentum_strength'],
                    'strategy_bias': momentum_analysis['strategy_bias'],
                    'signal_action': signals['action'],
                    'confidence': signals['confidence']
                }
                
                if signals['action'] != 'WAIT':
                    results['signals_generated'] += 1
                    
                    print(f"   🎯 Signal: {signals['action']} {signals['order_type']} @ {signals['entry_price']:.4f}")
                    print(f"   Confidence: {signals['confidence']}%")
                    
                    # Check if we should trade (timing, confidence, etc.)
                    current_hour = current_market_time.hour
                    
                    # Skip during rollover period
                    if 15 <= current_hour < 17:
                        print(f"   ⏰ Skipping - Rollover period")
                        results['opportunities_skipped'] += 1
                        analysis_detail['skip_reason'] = 'Rollover period'
                    
                    # Skip if confidence too low
                    elif signals['confidence'] < 70:
                        print(f"   ⏰ Skipping - Low confidence ({signals['confidence']}%)")
                        results['opportunities_skipped'] += 1
                        analysis_detail['skip_reason'] = f'Low confidence ({signals["confidence"]}%)'
                    
                    # Skip if too many open trades
                    elif open_trades >= max_open_trades:
                        print(f"   ⏰ Skipping - Max trades reached ({open_trades})")
                        results['opportunities_skipped'] += 1
                        analysis_detail['skip_reason'] = 'Max trades reached'
                    
                    else:
                        # Calculate position size with your risk management
                        position_info = risk_manager.calculate_position_size(
                            instrument,
                            signals['entry_price'],
                            signals['stop_loss'],
                            signals['confidence']
                        )
                        
                        print(f"   💰 Position Size: {position_info['position_size']} units")
                        print(f"   💰 Risk: ${position_info['risk_usd']:.2f} USD")
                        
                        # Execute trade (you can enable/disable this)
                        EXECUTE_TRADES = True  # Set to False for testing
                        
                        if EXECUTE_TRADES:
                            try:
                                # Create order
                                units = position_info['position_size']
                                if signals['action'] == 'SELL':
                                    units = -units
                                
                                order_data = {
                                    "order": {
                                        "type": signals['order_type'],
                                        "instrument": instrument,
                                        "units": str(units),
                                        "stopLossOnFill": {"price": str(signals['stop_loss'])},
                                        "takeProfitOnFill": {"price": str(signals['take_profit'])}
                                    }
                                }
                                
                                if signals['order_type'] == 'LIMIT':
                                    order_data["order"]["price"] = str(signals['entry_price'])
                                
                                # Place order
                                response = api.place_order(order_data)
                                
                                if response:
                                    results['trades_executed'] += 1
                                    print(f"   ✅ Trade executed successfully!")
                                    
                                    analysis_detail['trade_executed'] = True
                                    analysis_detail['position_size'] = position_info['position_size']
                                    analysis_detail['risk_usd'] = position_info['risk_usd']
                                else:
                                    print(f"   ❌ Trade execution failed")
                                    analysis_detail['trade_executed'] = False
                                    analysis_detail['error'] = 'Order placement failed'
                                    
                            except Exception as e:
                                print(f"   ❌ Trade execution error: {e}")
                                analysis_detail['trade_executed'] = False
                                analysis_detail['error'] = str(e)
                        else:
                            print(f"   📋 Trade execution disabled (testing mode)")
                            analysis_detail['trade_executed'] = False
                            analysis_detail['note'] = 'Execution disabled for testing'
                
                else:
                    print(f"   📊 No signal - {signals['reasoning'][0] if signals['reasoning'] else 'Neutral momentum'}")
                    analysis_detail['skip_reason'] = 'No signal generated'
                
                results['analysis_details'].append(analysis_detail)
                
            except Exception as e:
                print(f"❌ Error analyzing {instrument}: {e}")
                results['analysis_details'].append({
                    'instrument': instrument,
                    'error': str(e)
                })
        
        # Send metrics to CloudWatch
        try:
            cloudwatch = boto3.client('cloudwatch')
            
            metrics = [
                ('AccountBalance', balance, 'None'),
                ('OpenTrades', open_trades, 'Count'),
                ('InstrumentsAnalyzed', results['instruments_analyzed'], 'Count'),
                ('SignalsGenerated', results['signals_generated'], 'Count'),
                ('TradesExecuted', results['trades_executed'], 'Count'),
                ('OpportunitiesSkipped', results['opportunities_skipped'], 'Count')
            ]
            
            for metric_name, value, unit in metrics:
                cloudwatch.put_metric_data(
                    Namespace='TradingBot',
                    MetricData=[{
                        'MetricName': metric_name,
                        'Value': value,
                        'Unit': unit,
                        'Timestamp': datetime.now()
                    }]
                )
            
            print("✅ Metrics sent to CloudWatch")
            
        except Exception as e:
            print(f"⚠️ Error sending metrics: {e}")
        
        print(f"\n🎉 Trading cycle completed:")
        print(f"   📊 Analyzed: {results['instruments_analyzed']} instruments")
        print(f"   🎯 Signals: {results['signals_generated']}")
        print(f"   ✅ Trades: {results['trades_executed']}")
        print(f"   ⏰ Skipped: {results['opportunities_skipped']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps(results, default=str)
        }
        
    except Exception as e:
        print(f"❌ Critical error in full trading bot: {e}")
        import traceback
        traceback.print_exc()
        
        # Send error metric
        try:
            cloudwatch = boto3.client('cloudwatch')
            cloudwatch.put_metric_data(
                Namespace='TradingBot',
                MetricData=[{
                    'MetricName': 'CriticalErrors',
                    'Value': 1,
                    'Unit': 'Count',
                    'Timestamp': datetime.now()
                }]
            )
        except:
            pass
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            })
        }