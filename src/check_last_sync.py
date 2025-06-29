#!/usr/bin/env python3
"""
Quick script to check the current sync status
Run this from your src/ directory
"""

import os
import sys
import json
from datetime import datetime

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("SYNC STATUS CHECK")
print("=" * 50)

# Check last sync file
sync_file = os.path.join(current_dir, "last_sync.json")
if os.path.exists(sync_file):
    try:
        with open(sync_file, 'r') as f:
            sync_data = json.load(f)
        print(f"✅ Last sync file exists: {sync_file}")
        print(f"   Last transaction ID: {sync_data.get('last_transaction_id', 'N/A')}")
        print(f"   Last sync time: {sync_data.get('last_sync_time', 'N/A')}")
    except Exception as e:
        print(f"❌ Error reading sync file: {e}")
else:
    print(f"⚠️  No sync file found at: {sync_file}")

print()

# Check Oanda current status
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    from oandapyV20 import API
    from oandapyV20.endpoints.accounts import AccountSummary
    from oandapyV20.endpoints.transactions import TransactionIDRange
    
    print("OANDA STATUS:")
    print("-" * 20)
    
    client = API(access_token=API_KEY, environment="practice")
    
    # Get account summary
    r = AccountSummary(accountID=ACCOUNT_ID)
    client.request(r)
    account = r.response.get("account", {})
    
    print(f"Account Balance: ${account.get('balance', 'N/A')}")
    print(f"Open Trades: {account.get('openTradeCount', 'N/A')}")
    print(f"Open Orders: {account.get('pendingOrderCount', 'N/A')}")
    
    # Get latest transaction ID
    try:
        # Try to get just the latest transaction
        r2 = TransactionIDRange(accountID=ACCOUNT_ID, params={"from": "1", "to": "99999999"})
        client.request(r2)
        latest_tx_id = r2.response.get("lastTransactionID", "N/A")
        print(f"Latest Transaction ID: {latest_tx_id}")
        
        # Compare with our sync file
        if os.path.exists(sync_file):
            with open(sync_file, 'r') as f:
                sync_data = json.load(f)
            our_last_id = sync_data.get('last_transaction_id', '0')
            
            if str(latest_tx_id) == str(our_last_id):
                print("✅ SYNC IS UP TO DATE - No new transactions")
            else:
                print(f"📋 NEW TRANSACTIONS AVAILABLE: {our_last_id} -> {latest_tx_id}")
        
    except Exception as e:
        print(f"Error getting transaction info: {e}")
    
except Exception as e:
    print(f"❌ Error connecting to Oanda: {e}")

print()

# Check Airtable status
try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    from pyairtable import Api
    
    print("AIRTABLE STATUS:")
    print("-" * 20)
    
    airtable_api = Api(AIRTABLE_API_TOKEN)
    table = airtable_api.table(BASE_ID, TABLE_NAME)
    
    records = table.all(max_records=5)
    print(f"Total records in table: {len(records)}")
    
    if records:
        print("Recent records:")
        for i, record in enumerate(records[:3]):
            fields = record.get('fields', {})
            fill_id = fields.get('Fill ID', 'N/A')
            instrument = fields.get('Instrument', 'N/A')
            direction = fields.get('Direction', 'N/A')
            state = fields.get('Trade State', 'N/A')
            print(f"  {i+1}. Fill ID: {fill_id}, {instrument} {direction}, State: {state}")
    else:
        print("No records found in Airtable")
        
except Exception as e:
    print(f"❌ Error connecting to Airtable: {e}")

print()
print("RECOMMENDATIONS:")
print("-" * 20)
print("1. If 'SYNC IS UP TO DATE' - make a test trade to see sync in action")
print("2. If 'NEW TRANSACTIONS AVAILABLE' - run sync_all.py to process them")
print("3. If you see Airtable records - your sync is working perfectly!")
print()
print("To test: Place a small trade (100 units) in your Oanda practice account,")
print("then run: python sync_all.py")