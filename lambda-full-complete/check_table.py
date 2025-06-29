#!/usr/bin/env python3
"""
Complete Airtable Schema and Data Inspector
Reads all columns, formats, and data for debugging and development
Now works with empty tables too!
"""

import os
import sys
from collections import Counter

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    from pyairtable import Api
    
    print("🔍 COMPLETE AIRTABLE INSPECTOR")
    print("=" * 60)
    
    # Connect to Airtable
    api = Api(AIRTABLE_API_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
    
    # Get all records
    records = table.all()
    print(f"📊 Total records in table: {len(records)}")
    print(f"🗂️  Table name: {TABLE_NAME}")
    print(f"🆔 Base ID: {BASE_ID}")
    print()
    
    # GET SCHEMA INFORMATION EVEN FOR EMPTY TABLES
    print("📋 TABLE SCHEMA ANALYSIS:")
    print("=" * 60)
    
    try:
        # Method 1: Try to get schema from table metadata
        # This uses the Airtable API to get field information
        base = api.base(BASE_ID)
        schema_info = base.schema()
        
        # Find our table in the schema
        table_schema = None
        for table_def in schema_info.get('tables', []):
            if table_def.get('name') == TABLE_NAME:
                table_schema = table_def
                break
        
        if table_schema:
            fields = table_schema.get('fields', [])
            print(f"✅ Found schema with {len(fields)} fields defined:")
            print()
            
            for i, field in enumerate(fields, 1):
                field_name = field.get('name', 'Unknown')
                field_type = field.get('type', 'Unknown')
                field_id = field.get('id', 'Unknown')
                
                print(f"{i:2d}. 📝 {field_name}")
                print(f"    ID: {field_id}")
                print(f"    Type: {field_type}")
                
                # Show additional field configuration
                options = field.get('options', {})
                if options:
                    print(f"    Options: {options}")
                
                # Show field description if available
                description = field.get('description', '')
                if description:
                    print(f"    Description: {description}")
                
                print()
        else:
            print(f"❌ Could not find table '{TABLE_NAME}' in schema")
            
    except Exception as schema_error:
        print(f"⚠️  Could not retrieve schema via API: {schema_error}")
        print("Trying alternative method...")
        
        # Method 2: Create a test record to discover fields (then delete it)
        try:
            print("\n🧪 ATTEMPTING FIELD DISCOVERY:")
            print("Creating a test record to discover field structure...")
            
            # Create a minimal test record
            test_fields = {
                "Test Field": "Test Value"
            }
            
            test_record = table.create(test_fields)
            print(f"✅ Created test record: {test_record['id']}")
            
            # Now we can see what fields exist by trying to update with common field names
            common_trading_fields = [
                "Fill ID", "OANDA Order ID", "Instrument", "Order Type", "Direction",
                "Units", "Entry Price", "Filled Price", "Execution Time", "Order Time",
                "Order Status", "Realized PL", "Account Balance After", "Stop Loss",
                "Target Price", "Trade State", "Days Pending", "Unrealized PL"
            ]
            
            # Delete the test record
            table.delete(test_record['id'])
            print("🗑️  Cleaned up test record")
            
            print("\n📝 Expected fields based on your sync_all.py:")
            for i, field_name in enumerate(common_trading_fields, 1):
                print(f"{i:2d}. {field_name}")
            
        except Exception as discovery_error:
            print(f"❌ Field discovery failed: {discovery_error}")
    
    # ANALYZE EXISTING DATA (if any)
    if len(records) > 0:
        print("\n📊 DATA ANALYSIS:")
        print("=" * 60)
        
        all_fields = set()
        field_data_types = {}
        field_sample_values = {}
        field_null_counts = {}
        
        # Collect all field information from existing data
        for record in records:
            fields = record['fields']
            for field_name, value in fields.items():
                all_fields.add(field_name)
                
                # Track data types
                if field_name not in field_data_types:
                    field_data_types[field_name] = set()
                field_data_types[field_name].add(type(value).__name__)
                
                # Store sample values
                if field_name not in field_sample_values:
                    field_sample_values[field_name] = []
                if len(field_sample_values[field_name]) < 3 and value is not None:
                    field_sample_values[field_name].append(str(value)[:50])
        
        # Count nulls
        for field_name in all_fields:
            null_count = 0
            for record in records:
                if field_name not in record['fields'] or record['fields'][field_name] is None:
                    null_count += 1
            field_null_counts[field_name] = null_count
        
        # Display data field information
        print(f"📊 Found {len(all_fields)} fields with data:")
        print()
        
        for i, field_name in enumerate(sorted(all_fields), 1):
            data_types = list(field_data_types[field_name])
            sample_values = field_sample_values.get(field_name, [])
            null_count = field_null_counts[field_name]
            filled_count = len(records) - null_count
            
            print(f"{i:2d}. 📝 {field_name}")
            print(f"    Type(s): {', '.join(data_types)}")
            print(f"    Filled: {filled_count}/{len(records)} ({(filled_count/len(records)*100):.1f}%)")
            
            if sample_values:
                print(f"    Samples: {', '.join(sample_values[:3])}")
            else:
                print(f"    Samples: [No values]")
            print()
        
        # HIT RATE TRACKING ANALYSIS
        print("🎯 HIT RATE TRACKING ANALYSIS:")
        print("=" * 60)
        
        key_fields = ['Order Status', 'Trade State', 'OANDA Order ID', 'Fill ID', 'Order Type', 'Direction']
        
        for field in key_fields:
            if field in all_fields:
                values = [record['fields'].get(field) for record in records if field in record['fields']]
                value_counts = Counter(values)
                
                print(f"📊 {field}:")
                for value, count in value_counts.most_common():
                    print(f"    {value}: {count}")
                print()
            else:
                print(f"❌ Missing field: {field}")
                print()
        
        # SUMMARY STATISTICS
        print("📊 SUMMARY STATISTICS:")
        print("=" * 60)
        
        status_count = {}
        for record in records:
            status = record['fields'].get('Order Status', 'N/A')
            status_count[status] = status_count.get(status, 0) + 1
        
        print("Order Status Distribution:")
        for status, count in sorted(status_count.items()):
            percentage = (count / len(records)) * 100
            print(f"   {status}: {count} ({percentage:.1f}%)")
        
        # HIT RATE CALCULATION
        total_orders = len(records)
        filled_orders = status_count.get('Filled', 0)
        pending_orders = status_count.get('Pending', 0)
        cancelled_orders = status_count.get('Cancelled', 0)
        
        if total_orders > 0:
            hit_rate = (filled_orders / total_orders) * 100
            print(f"\n🎯 HIT RATE METRICS:")
            print(f"   Total Orders: {total_orders}")
            print(f"   Filled: {filled_orders}")
            print(f"   Pending: {pending_orders}")
            print(f"   Cancelled: {cancelled_orders}")
            print(f"   Hit Rate: {hit_rate:.1f}%")
    else:
        print("📊 No data to analyze - table is empty")
        print("Run your sync_all.py to populate the table, then run this again for data analysis")
    
    # RECOMMENDATIONS
    print("\n💡 DEVELOPMENT INSIGHTS:")
    print("=" * 60)
    
    if len(records) == 0:
        print("🔧 EMPTY TABLE RECOMMENDATIONS:")
        print("   1. Run sync_all.py to populate the table")
        print("   2. Check that your Oanda API is working")
        print("   3. Verify that you have trading activity to sync")
        print("   4. Check logs for any sync errors")
        print()
        print("📋 EXPECTED WORKFLOW:")
        print("   1. Place some trades or limit orders in Oanda")
        print("   2. Run: python sync_all.py")
        print("   3. Run: python check_table.py (this script)")
        print("   4. Analyze the hit rate and trading performance")
    else:
        # Existing recommendations for populated tables
        if 'Order Status' in all_fields:
            print("✅ Hit rate tracking is set up!")
        else:
            print("⚠️  Order Status field missing - needed for hit rate calculation")
        
        if 'Days Pending' in all_fields:
            print("✅ Days Pending tracking is working")
        else:
            print("⚠️  Days Pending field missing - useful for limit order analytics")
    
    print("\n📁 Analysis complete!")

except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("Make sure your config files exist:")
    print("   - config/airtable_config.py")
    print("   - config/oanda_config.py")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    print("\nMake sure your Airtable credentials are correct in config/airtable_config.py")