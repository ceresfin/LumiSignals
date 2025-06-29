#!/usr/bin/env python3
"""
Trading Bot Log Analyzer
Run this script to analyze your trading bot's decision history
"""

import boto3
import json
from datetime import datetime, timedelta
from decimal import Decimal
import sys

class OrderLogAnalyzer:
    def __init__(self):
        self.dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        self.table = self.dynamodb.Table('trading-orders-log')
        self.logs_client = boto3.client('logs', region_name='us-east-1')
    
    def get_placed_orders(self, days_back=7, instrument=None):
        """Get all orders that were actually placed"""
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days_back)
        
        # Base scan parameters
        scan_params = {
            'FilterExpression': '#action = :action',
            'ExpressionAttributeNames': {'#action': 'action'},
            'ExpressionAttributeValues': {
                ':action': 'PLACED'
            }
        }
        
        # Add instrument filter if specified
        if instrument:
            scan_params['FilterExpression'] += ' AND instrument = :instrument'
            scan_params['ExpressionAttributeValues'][':instrument'] = instrument
        
        # Add date range filter
        scan_params['FilterExpression'] += ' AND #ts BETWEEN :start_date AND :end_date'
        scan_params['ExpressionAttributeNames']['#ts'] = 'timestamp'
        scan_params['ExpressionAttributeValues'][':start_date'] = start_date.isoformat()
        scan_params['ExpressionAttributeValues'][':end_date'] = end_date.isoformat()
        
        try:
            response = self.table.scan(**scan_params)
            return response['Items']
        except Exception as e:
            print(f"Error querying placed orders: {e}")
            return []
    
    def get_skipped_opportunities(self, days_back=7):
        """Analyze what opportunities were skipped and why"""
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days_back)
        
        try:
            response = self.table.scan(
                FilterExpression='#action = :action AND #ts BETWEEN :start_date AND :end_date',
                ExpressionAttributeNames={'#action': 'action', '#ts': 'timestamp'},
                ExpressionAttributeValues={
                    ':action': 'SKIPPED',
                    ':start_date': start_date.isoformat(),
                    ':end_date': end_date.isoformat()
                }
            )
            return response['Items']
        except Exception as e:
            print(f"Error querying skipped opportunities: {e}")
            return []
    
    def get_cloudwatch_logs(self, hours_back=24):
        """Query CloudWatch logs for order decisions"""
        
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours_back)
        
        try:
            response = self.logs_client.filter_log_events(
                logGroupName='/aws/lambda/oanda-trading-bot-complete',
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                filterPattern='ORDER_LOG'
            )
            
            logs = []
            for event in response['events']:
                try:
                    log_data = json.loads(event['message'].replace('ORDER_LOG: ', ''))
                    logs.append(log_data)
                except:
                    continue
            return logs
        except Exception as e:
            print(f"Error querying CloudWatch logs: {e}")
            return []
    
    def generate_trading_report(self, days_back=7):
        """Generate comprehensive trading activity report"""
        
        print(f"\n🤖 TRADING BOT ANALYSIS REPORT - Last {days_back} days")
        print("=" * 60)
        
        placed_orders = self.get_placed_orders(days_back)
        skipped_orders = self.get_skipped_opportunities(days_back)
        
        # Analyze skip reasons
        skip_reasons = {}
        for order in skipped_orders:
            reason = order.get('order_details', {}).get('skip_reason', 'Unknown')
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        
        # Analyze instruments with signals
        instruments_with_signals = {}
        for order in skipped_orders + placed_orders:
            instrument = order['instrument']
            instruments_with_signals[instrument] = instruments_with_signals.get(instrument, 0) + 1
        
        # Analyze instruments traded
        instruments_traded = {}
        for order in placed_orders:
            instrument = order['instrument']
            instruments_traded[instrument] = instruments_traded.get(instrument, 0) + 1
        
        # Print summary
        print(f"📊 SUMMARY:")
        print(f"   • Orders Placed: {len(placed_orders)}")
        print(f"   • Opportunities Skipped: {len(skipped_orders)}")
        print(f"   • Total Signals Generated: {len(placed_orders) + len(skipped_orders)}")
        
        if instruments_traded:
            print(f"\n💰 INSTRUMENTS TRADED:")
            for instrument, count in instruments_traded.items():
                print(f"   • {instrument}: {count} trades")
        else:
            print(f"\n💰 INSTRUMENTS TRADED: None")
        
        if instruments_with_signals:
            print(f"\n📈 SIGNALS BY INSTRUMENT:")
            for instrument, count in instruments_with_signals.items():
                print(f"   • {instrument}: {count} signals")
        
        if skip_reasons:
            print(f"\n⏭️  SKIP REASONS:")
            for reason, count in skip_reasons.items():
                print(f"   • {reason}: {count} times")
        
        return {
            'placed_orders': placed_orders,
            'skipped_orders': skipped_orders,
            'skip_reasons': skip_reasons,
            'instruments_traded': instruments_traded
        }
    
    def show_recent_decisions(self, hours_back=24):
        """Show recent trading decisions from CloudWatch"""
        
        print(f"\n📋 RECENT DECISIONS - Last {hours_back} hours")
        print("=" * 60)
        
        logs = self.get_cloudwatch_logs(hours_back)
        
        if not logs:
            print("No recent trading decisions found in CloudWatch logs.")
            return
        
        for i, log in enumerate(logs[-10:], 1):  # Show last 10 decisions
            timestamp = log.get('timestamp', 'Unknown')
            instrument = log.get('instrument', 'Unknown')
            action = log.get('action', 'Unknown')
            
            print(f"\n{i}. {timestamp}")
            print(f"   Instrument: {instrument}")
            print(f"   Action: {action}")
            
            if action == 'SKIPPED':
                skip_reason = log.get('order_details', {}).get('skip_reason', 'Unknown')
                confidence = log.get('order_details', {}).get('confidence', 'Unknown')
                print(f"   Skip Reason: {skip_reason}")
                print(f"   Confidence: {confidence}%")
            elif action == 'PLACED':
                order_id = log.get('order_details', {}).get('order_id', 'Unknown')
                fill_price = log.get('order_details', {}).get('fill_price', 'Unknown')
                print(f"   Order ID: {order_id}")
                print(f"   Fill Price: {fill_price}")
            
            # Market data
            market_data = log.get('market_data', {})
            if market_data:
                current_price = market_data.get('current_price', 'Unknown')
                spread = market_data.get('spread', 'Unknown')
                session = market_data.get('market_session', 'Unknown')
                print(f"   Price: {current_price} | Spread: {spread} | Session: {session}")
    
    def show_detailed_order(self, order):
        """Show detailed information about a specific order"""
        
        print(f"\n📋 DETAILED ORDER INFORMATION")
        print("=" * 40)
        print(f"Timestamp: {order.get('timestamp', 'Unknown')}")
        print(f"Instrument: {order.get('instrument', 'Unknown')}")
        print(f"Action: {order.get('action', 'Unknown')}")
        
        # Order details
        order_details = order.get('order_details', {})
        print(f"\nOrder Details:")
        for key, value in order_details.items():
            print(f"  {key}: {value}")
        
        # Market data
        market_data = order.get('market_data', {})
        if market_data:
            print(f"\nMarket Context:")
            for key, value in market_data.items():
                print(f"  {key}: {value}")
        
        # Analysis data
        analysis_data = order.get('analysis_data', {})
        if analysis_data:
            print(f"\nTechnical Analysis:")
            for key, value in analysis_data.items():
                print(f"  {key}: {value}")

def main():
    """Main function to run the analysis"""
    
    print("🤖 Trading Bot Log Analyzer")
    print("=" * 40)
    
    try:
        analyzer = OrderLogAnalyzer()
        
        # Generate comprehensive report
        analyzer.generate_trading_report(days_back=7)
        
        # Show recent decisions
        analyzer.show_recent_decisions(hours_back=24)
        
        # Interactive options
        print(f"\n🔍 INTERACTIVE OPTIONS:")
        print("1. View placed orders details")
        print("2. View skipped opportunities details") 
        print("3. Query specific instrument")
        print("4. Exit")
        
        while True:
            try:
                choice = input(f"\nEnter your choice (1-4): ").strip()
                
                if choice == '1':
                    placed_orders = analyzer.get_placed_orders(days_back=7)
                    if placed_orders:
                        print(f"\n📈 PLACED ORDERS ({len(placed_orders)} found):")
                        for i, order in enumerate(placed_orders, 1):
                            print(f"\n{i}. {order.get('instrument')} - {order.get('timestamp')}")
                            analyzer.show_detailed_order(order)
                    else:
                        print("No placed orders found in the last 7 days.")
                
                elif choice == '2':
                    skipped_orders = analyzer.get_skipped_opportunities(days_back=7)
                    if skipped_orders:
                        print(f"\n⏭️  SKIPPED OPPORTUNITIES ({len(skipped_orders)} found):")
                        for i, order in enumerate(skipped_orders, 1):
                            print(f"\n{i}. {order.get('instrument')} - {order.get('timestamp')}")
                            skip_reason = order.get('order_details', {}).get('skip_reason', 'Unknown')
                            confidence = order.get('order_details', {}).get('confidence', 'Unknown')
                            print(f"   Skip Reason: {skip_reason} | Confidence: {confidence}%")
                    else:
                        print("No skipped opportunities found in the last 7 days.")
                
                elif choice == '3':
                    instrument = input("Enter instrument (e.g., EUR_USD): ").strip().upper()
                    placed_orders = analyzer.get_placed_orders(days_back=7, instrument=instrument)
                    print(f"\n📊 {instrument} ANALYSIS:")
                    print(f"Placed orders: {len(placed_orders)}")
                    
                    for order in placed_orders:
                        analyzer.show_detailed_order(order)
                
                elif choice == '4':
                    print("Goodbye! 👋")
                    break
                
                else:
                    print("Invalid choice. Please enter 1-4.")
                    
            except KeyboardInterrupt:
                print(f"\nGoodbye! 👋")
                break
            except Exception as e:
                print(f"Error: {e}")
                
    except Exception as e:
        print(f"Failed to initialize analyzer: {e}")
        print("Make sure you have:")
        print("1. AWS credentials configured")
        print("2. DynamoDB table 'trading-orders-log' exists")
        print("3. Proper IAM permissions")

if __name__ == "__main__":
    main()