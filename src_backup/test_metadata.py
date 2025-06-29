#!/usr/bin/env python3
"""
Test script to verify that metadata is being properly attached to orders
"""

import os
import sys
import json
from datetime import datetime

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import configs and API
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    from oanda_api import OandaAPI
    print("✅ Imported configs successfully")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def test_order_with_metadata():
    """Test placing an order with metadata to see what gets sent"""
    
    api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
    
    # Create test metadata
    test_metadata = {
        "setup_name": "Test_Penny_Curve_EUR_USD_LIMIT_BUY_Strong",
        "momentum_strength": 0.520,
        "momentum_direction": "STRONG_BULLISH",
        "strategy_bias": "BUY",
        "zone_position": "Above_Buy_Zone",
        "distance_pips": 35.5,
        "confidence": 100,
        "alignment_score": 0.85
    }
    
    # Create order data with metadata
    order_data = {
        "order": {
            "type": "LIMIT",
            "instrument": "EUR_USD",
            "units": "1000",
            "price": "1.15500",
            "timeInForce": "GTD",
            "gtdTime": "2025-06-25T17:00:00.000000000Z",
            "stopLossOnFill": {
                "price": "1.15300"
            },
            "takeProfitOnFill": {
                "price": "1.16500"
            },
            "clientExtensions": {
                "id": "Test_Penny_Curve_EUR_USD_LIMIT_BUY_Strong"[:50],
                "tag": "PennyCurveMomentum",
                "comment": f"Setup:{test_metadata['setup_name']}|Momentum:{test_metadata['momentum_strength']:.3f}|Direction:{test_metadata['momentum_direction']}|Bias:{test_metadata['strategy_bias']}|Zone:{test_metadata['zone_position']}|DistancePips:{test_metadata['distance_pips']:.1f}|Confidence:{test_metadata['confidence']}|Alignment:{test_metadata['alignment_score']:.2f}"[:500]
            }
        }
    }
    
    print("🔍 Testing order placement with metadata...")
    print(f"📋 Order data being sent:")
    print(json.dumps(order_data, indent=2))
    
    try:
        response = api.place_order(order_data)
        print(f"\n✅ Order response:")
        print(json.dumps(response, indent=2))
        
        # Check if the order was created and extract ID
        if 'orderCreateTransaction' in response:
            order_id = response['orderCreateTransaction']['id']
            print(f"\n🆔 Order ID: {order_id}")
            
            # Now let's check what the order looks like when we retrieve it
            print(f"\n🔍 Retrieving order details...")
            orders = api.get_open_orders()
            
            for order in orders.get('orders', []):
                if order['id'] == order_id:
                    print(f"\n📋 Order details from API:")
                    print(json.dumps(order, indent=2))
                    
                    # Check for clientExtensions
                    if 'clientExtensions' in order:
                        print(f"\n✅ ClientExtensions found:")
                        print(json.dumps(order['clientExtensions'], indent=2))
                    else:
                        print(f"\n❌ No clientExtensions found in order")
                    break
            else:
                print(f"\n❌ Could not find order {order_id} in open orders")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_recent_transactions():
    """Check recent transactions to see if metadata is preserved"""
    
    print(f"\n🔍 Checking recent transactions for metadata...")
    
    try:
        from oandapyV20 import API
        from oandapyV20.endpoints.transactions import TransactionIDRange
        
        client = API(access_token=API_KEY, environment="practice")
        
        # Get last 5 transactions
        r = TransactionIDRange(
            accountID=ACCOUNT_ID, 
            params={"from": "58", "to": "99999999"}  # Start from recent transaction
        )
        client.request(r)
        
        transactions = r.response.get("transactions", [])
        print(f"📋 Found {len(transactions)} recent transactions")
        
        for tx in transactions:
            tx_type = tx.get("type")
            tx_id = tx.get("id")
            
            print(f"\n🔍 Transaction {tx_id} ({tx_type}):")
            
            # Look for clientExtensions in various places
            client_extensions = None
            
            if 'clientExtensions' in tx:
                client_extensions = tx['clientExtensions']
                print(f"  ✅ Found clientExtensions in transaction")
            elif 'order' in tx and 'clientExtensions' in tx['order']:
                client_extensions = tx['order']['clientExtensions']
                print(f"  ✅ Found clientExtensions in order")
            else:
                print(f"  ❌ No clientExtensions found")
                
                # Print available keys for debugging
                print(f"  🔍 Available keys: {list(tx.keys())}")
                
                # If it's an ORDER_FILL, check if there's an orderID to trace back
                if tx_type == "ORDER_FILL" and 'orderID' in tx:
                    print(f"  🔍 ORDER_FILL references order ID: {tx['orderID']}")
            
            if client_extensions:
                print(f"  📋 ClientExtensions:")
                print(json.dumps(client_extensions, indent=4))
        
    except Exception as e:
        print(f"❌ Error checking transactions: {e}")

if __name__ == "__main__":
    print("🧪 Testing Metadata Placement in Oanda Orders")
    print("="*60)
    
    # Test 1: Place an order with metadata
    if test_order_with_metadata():
        print(f"\n✅ Order placement test completed")
    else:
        print(f"\n❌ Order placement test failed")
    
    # Test 2: Check recent transactions
    test_recent_transactions()
    
    print(f"\n" + "="*60)
    print("🧪 Test completed!")