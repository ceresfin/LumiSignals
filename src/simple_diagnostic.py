#!/usr/bin/env python3
"""
Simple diagnostic to find actual order IDs and check a few records
"""

import os
import sys

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    from pyairtable import Api
    print("SUCCESS: Imported Airtable config")
except ImportError as e:
    print(f"ERROR: Failed to import Airtable config: {e}")
    sys.exit(1)

# Airtable setup
try:
    airtable_api = Api(AIRTABLE_API_TOKEN)
    table = airtable_api.table(BASE_ID, TABLE_NAME)
    print("SUCCESS: Airtable connection established")
except Exception as e:
    print(f"ERROR: Failed to connect to Airtable: {e}")
    sys.exit(1)

def safe_float(value, default=0.0):
    """Safely convert value to float"""
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def main():
    """Main diagnostic function"""
    print("🔍 FINDING ACTUAL ORDER IDS AND DIAGNOSING ISSUES")
    print("=" * 60)
    
    try:
        # Get all records
        records = table.all()
        print(f"📋 Found {len(records)} total records")
        
        # Show first 10 order IDs
        print(f"\n📝 First 10 Order IDs found:")
        order_ids = []
        for i, record in enumerate(records[:10]):
            fields = record['fields']
            order_id = fields.get('OANDA Order ID', 'Unknown')
            order_ids.append(order_id)
            print(f"   {i+1}. Order ID: {order_id}")
        
        print(f"\n🔍 DETAILED DIAGNOSIS OF FIRST 3 RECORDS:")
        print("=" * 50)
        
        # Diagnose first 3 records in detail
        for i, record in enumerate(records[:3]):
            fields = record['fields']
            order_id = fields.get('OANDA Order ID', 'Unknown')
            
            print(f"\n📊 RECORD {i+1} - ORDER ID: {order_id}")
            print("-" * 30)
            
            # Key fields for calculation
            entry_price = fields.get('Entry Price')
            stop_loss = fields.get('Stop Loss')
            units = fields.get('Units')
            direction = fields.get('Direction', '')
            order_status = fields.get('Order Status', '')
            account_balance_before = fields.get('Account Balance Before')
            position_size_calc = fields.get('Position Size % Calculated')
            risk_amount_calc = fields.get('Risk Amount Calculated')
            
            print(f"Order Status: '{order_status}'")
            print(f"Direction: '{direction}'")
            print(f"Entry Price: {entry_price} → {safe_float(entry_price)}")
            print(f"Stop Loss: {stop_loss} → {safe_float(stop_loss)}")
            print(f"Units: {units} → {safe_float(units)}")
            print(f"Account Balance Before: {account_balance_before} → {safe_float(account_balance_before)}")
            print(f"Position Size % Calculated: {position_size_calc}")
            print(f"Risk Amount Calculated: {risk_amount_calc}")
            
            # Manual calculation
            entry_float = safe_float(entry_price)
            stop_float = safe_float(stop_loss)
            units_float = safe_float(units)
            
            print(f"\n🧮 MANUAL CALCULATION:")
            if entry_float > 0 and stop_float > 0 and units_float > 0:
                if direction == "Long":
                    risk_per_unit = entry_float - stop_float
                else:  # Short
                    risk_per_unit = stop_float - entry_float
                
                risk_amount = abs(risk_per_unit * units_float)
                print(f"   Risk per unit: {risk_per_unit}")
                print(f"   Risk amount: {risk_amount}")
                
                # Position size calculation
                balance = safe_float(account_balance_before)
                if balance > 0:
                    position_size_pct = (risk_amount / balance) * 100
                    print(f"   Position Size %: {position_size_pct:.4f}%")
                else:
                    print(f"   Position Size %: Cannot calculate (no account balance)")
            else:
                print(f"   Cannot calculate - missing data:")
                if entry_float <= 0: print(f"     - Entry Price invalid")
                if stop_float <= 0: print(f"     - Stop Loss invalid") 
                if units_float <= 0: print(f"     - Units invalid")
        
        # Quick summary of all records
        print(f"\n📊 QUICK SUMMARY OF ALL {len(records)} RECORDS:")
        print("=" * 50)
        
        has_entry_price = 0
        has_stop_loss = 0
        has_units = 0
        has_account_balance = 0
        has_calculated_position_size = 0
        filled_orders = 0
        pending_orders = 0
        
        for record in records:
            fields = record['fields']
            
            if safe_float(fields.get('Entry Price', 0)) > 0:
                has_entry_price += 1
            if safe_float(fields.get('Stop Loss', 0)) > 0:
                has_stop_loss += 1
            if safe_float(fields.get('Units', 0)) > 0:
                has_units += 1
            if safe_float(fields.get('Account Balance Before', 0)) > 0:
                has_account_balance += 1
            if safe_float(fields.get('Position Size % Calculated', 0)) > 0:
                has_calculated_position_size += 1
            
            status = fields.get('Order Status', '')
            if status == 'Filled':
                filled_orders += 1
            elif status == 'Pending':
                pending_orders += 1
        
        print(f"Records with Entry Price > 0: {has_entry_price}/{len(records)}")
        print(f"Records with Stop Loss > 0: {has_stop_loss}/{len(records)}")
        print(f"Records with Units > 0: {has_units}/{len(records)}")
        print(f"Records with Account Balance > 0: {has_account_balance}/{len(records)}")
        print(f"Records with Position Size % > 0: {has_calculated_position_size}/{len(records)}")
        print(f"Filled Orders: {filled_orders}")
        print(f"Pending Orders: {pending_orders}")
        
        print(f"\n💡 LIKELY ISSUES:")
        if has_stop_loss < len(records):
            print(f"   🚨 {len(records) - has_stop_loss} records missing Stop Loss!")
        if has_entry_price < len(records):
            print(f"   🚨 {len(records) - has_entry_price} records missing Entry Price!")
        if has_units < len(records):
            print(f"   🚨 {len(records) - has_units} records missing Units!")
        if has_account_balance < filled_orders:
            print(f"   ⚠️  {filled_orders - has_account_balance} filled orders missing Account Balance!")
        
    except Exception as e:
        print(f"❌ Error in diagnostic: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()