#!/usr/bin/env python3
"""
Batch Order Placement Script for LumiTrade Setups
Reads CSV file and places limit orders in Oanda with stop loss and take profit
"""

import os
import sys
import pandas as pd
import time
from datetime import datetime

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

# Import our existing modules
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID, ENVIRONMENT
    from oanda_api import OandaTrader
    print("✅ Successfully imported trading modules")
except ImportError as e:
    print(f"❌ Failed to import modules: {e}")
    sys.exit(1)

class BatchOrderPlacer:
    """
    Places batch orders from LumiTrade CSV setups
    """
    
    def __init__(self, csv_file_path):
        self.csv_file = csv_file_path
        self.trader = OandaTrader(API_KEY, ACCOUNT_ID, ENVIRONMENT)
        self.results = []
    
    def load_setups(self):
        """Load trading setups from CSV file"""
        try:
            # Try different possible filenames
            possible_files = [
                self.csv_file,
                "LumiTrade Trading Setups.csv",
                "lumitrade_setups.csv"
            ]
            
            df = None
            for filename in possible_files:
                filepath = os.path.join(current_dir, filename)
                if os.path.exists(filepath):
                    print(f"📁 Found setup file: {filename}")
                    df = pd.read_csv(filepath)
                    break
            
            if df is None:
                raise FileNotFoundError("No CSV setup file found")
            
            print(f"📊 Loaded {len(df)} trading setups")
            print("Setups found:")
            for idx, row in df.iterrows():
                print(f"  {idx+1}. {row['Setup_Name']} - {row['Direction']} {row['Units']} units")
            
            return df
            
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return None
    
    def place_limit_order(self, setup):
        """
        Place a single limit order from setup data
        """
        try:
            instrument = setup['Instrument'].replace('_', '_')  # Ensure format like EUR_USD
            units = int(setup['Units'])
            entry_price = float(setup['Entry_Price'])
            stop_loss = float(setup['Stop_Loss'])
            target_price = float(setup['Target_Price'])
            direction = setup['Direction']
            setup_name = setup['Setup_Name']
            
            # Adjust units for direction (positive for buy, negative for sell)
            if direction.lower() == 'short':
                units = -abs(units)
            else:
                units = abs(units)
            
            print(f"\n🔄 Placing order: {setup_name}")
            print(f"   Instrument: {instrument}")
            print(f"   Entry: {entry_price}")
            print(f"   Stop Loss: {stop_loss}")
            print(f"   Take Profit: {target_price}")
            print(f"   Units: {units}")
            
            # Place the limit order
            result = self.trader.api.place_limit_order(
                instrument=instrument,
                units=units,
                price=entry_price,
                stop_loss=stop_loss,
                take_profit=target_price
            )
            
            if 'orderCreateTransaction' in result:
                order_id = result['orderCreateTransaction']['id']
                print(f"✅ Order placed successfully! Order ID: {order_id}")
                
                return {
                    'setup_name': setup_name,
                    'success': True,
                    'order_id': order_id,
                    'instrument': instrument,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'target_price': target_price,
                    'units': units,
                    'message': 'Order placed successfully'
                }
            else:
                print(f"⚠️ Unexpected response format")
                return {
                    'setup_name': setup_name,
                    'success': False,
                    'error': 'Unexpected response format',
                    'response': str(result)
                }
                
        except Exception as e:
            print(f"❌ Error placing order for {setup.get('Setup_Name', 'Unknown')}: {e}")
            return {
                'setup_name': setup.get('Setup_Name', 'Unknown'),
                'success': False,
                'error': str(e)
            }
    
    def place_all_orders(self):
        """
        Place all orders from the CSV file
        """
        print("🚀 Starting batch order placement...")
        
        # Load setups
        df = self.load_setups()
        if df is None:
            return False
        
        # Check account balance first
        try:
            account_info = self.trader.api.get_account_summary()
            balance = account_info['account']['balance']
            print(f"\n💰 Account Balance: ${balance}")
        except Exception as e:
            print(f"⚠️ Could not retrieve account balance: {e}")
        
        print(f"\n📋 Processing {len(df)} orders...")
        
        # Place each order
        for idx, setup in df.iterrows():
            result = self.place_limit_order(setup)
            self.results.append(result)
            
            # Small delay between orders to avoid rate limiting
            time.sleep(1)
        
        # Print summary
        self.print_summary()
        return True
    
    def print_summary(self):
        """Print summary of order placement results"""
        print("\n" + "="*60)
        print("📊 BATCH ORDER PLACEMENT SUMMARY")
        print("="*60)
        
        successful = [r for r in self.results if r['success']]
        failed = [r for r in self.results if not r['success']]
        
        print(f"✅ Successful orders: {len(successful)}")
        print(f"❌ Failed orders: {len(failed)}")
        print(f"📊 Total orders: {len(self.results)}")
        
        if successful:
            print(f"\n✅ SUCCESSFUL ORDERS:")
            for result in successful:
                print(f"   • {result['setup_name']} - Order ID: {result.get('order_id', 'N/A')}")
        
        if failed:
            print(f"\n❌ FAILED ORDERS:")
            for result in failed:
                print(f"   • {result['setup_name']} - Error: {result.get('error', 'Unknown error')}")
        
        print("\n💡 Next steps:")
        print("   1. Check your Oanda platform to verify orders")
        print("   2. Run 'python sync_all.py' to sync data to Airtable")
        print("   3. Monitor order fills and manage positions")

def main():
    """Main execution function"""
    print("🎯 LumiTrade Batch Order Placement")
    print("="*50)
    
    # Initialize batch order placer
    batch_placer = BatchOrderPlacer("LumiTrade Trading Setups.csv")
    
    # Confirm before placing orders
    print("\n⚠️  WARNING: This will place REAL limit orders in your Oanda account!")
    print("Make sure you're using the practice environment for testing.")
    
    confirm = input("\nDo you want to proceed? (yes/no): ").lower().strip()
    
    if confirm in ['yes', 'y']:
        print(f"\n🔄 Proceeding with order placement...")
        batch_placer.place_all_orders()
    else:
        print("❌ Order placement cancelled")
        return False
    
    return True

if __name__ == "__main__":
    main()