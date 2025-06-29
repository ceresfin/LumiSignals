#!/usr/bin/env python3
"""
TradePhantoms Batch Order Placement Script
Reads TradePhantoms CSV file and places orders in Oanda with stop loss and take profit
"""

import os
import sys
import pandas as pd
import time
import glob
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
    print("Make sure oanda_config.py and oanda_api.py are properly set up")
    sys.exit(1)

class TradePhantomsBatchOrderPlacer:
    """
    Places batch orders from TradePhantoms CSV setups
    """
    
    def __init__(self, csv_file_path=None):
        self.csv_file = csv_file_path
        self.trader = OandaTrader(API_KEY, ACCOUNT_ID, ENVIRONMENT)
        self.results = []
        print(f"🔗 Connected to Oanda {ENVIRONMENT} environment")
    
    def find_latest_setup_file(self):
        """Find the most recent TradePhantoms setup file"""
        # Look for trade_setups_*.csv files
        pattern = "trade_setups_*.csv"
        setup_files = glob.glob(pattern)
        
        if not setup_files:
            print("❌ No TradePhantoms setup files found!")
            print("Please run trade_setup_generator.py first to create setups")
            return None
        
        # Get the most recent file
        latest_file = max(setup_files, key=os.path.getctime)
        file_time = datetime.fromtimestamp(os.path.getctime(latest_file))
        
        print(f"📁 Found setup file: {latest_file}")
        print(f"📅 Created: {file_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return latest_file
    
    def load_setups(self):
        """Load trading setups from TradePhantoms CSV file"""
        try:
            # If no file specified, find the latest one
            if not self.csv_file:
                self.csv_file = self.find_latest_setup_file()
                if not self.csv_file:
                    return None
            
            # Check if file exists
            if not os.path.exists(self.csv_file):
                print(f"❌ File not found: {self.csv_file}")
                return None
            
            # Load the CSV
            df = pd.read_csv(self.csv_file)
            
            print(f"📊 Loaded {len(df)} TradePhantoms setups")
            print("\\nSetups found:")
            for idx, row in df.iterrows():
                risk_dollars = row.get('stop_loss_risk_dollars', 'N/A')
                print(f"  {idx+1}. {row['setup_id']} - {row['direction']} {row['position_size']} units (Risk: ${risk_dollars})")
            
            return df
            
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return None
    
    def place_limit_order(self, setup):
        """
        Place a single limit order from TradePhantoms setup data
        """
        try:
            instrument = setup['instrument']  # Already in EUR_USD format
            units = int(setup['position_size'])
            entry_price = float(setup['entry_price'])
            stop_loss = float(setup['stop_loss']) if setup['stop_loss'] else None
            target_price = float(setup['target_price'])
            direction = setup['direction']
            setup_id = setup['setup_id']
            order_type = setup['order_type']
            risk_dollars = setup.get('stop_loss_risk_dollars', 0)
            
            # Adjust units for direction (positive for buy, negative for sell)
            if direction.lower() == 'short':
                units = -abs(units)
            else:
                units = abs(units)
            
            print(f"\\n🔄 Placing order: {setup_id}")
            print(f"   Instrument: {instrument}")
            print(f"   Type: {order_type}")
            print(f"   Entry: {entry_price}")
            print(f"   Stop Loss: {stop_loss}")
            print(f"   Take Profit: {target_price}")
            print(f"   Units: {units}")
            print(f"   Risk: ${risk_dollars}")
            
            # Place the order based on type
            if order_type.upper() == 'MARKET':
                result = self.trader.api.place_market_order(
                    instrument=instrument,
                    units=units,
                    stop_loss=stop_loss,
                    take_profit=target_price
                )
            else:  # LIMIT
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
                    'setup_id': setup_id,
                    'success': True,
                    'order_id': order_id,
                    'instrument': instrument,
                    'order_type': order_type,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'target_price': target_price,
                    'units': units,
                    'risk_dollars': risk_dollars,
                    'message': 'Order placed successfully'
                }
            else:
                print(f"⚠️ Unexpected response format: {result}")
                return {
                    'setup_id': setup_id,
                    'success': False,
                    'error': 'Unexpected response format',
                    'response': str(result)
                }
                
        except Exception as e:
            print(f"❌ Error placing order for {setup.get('setup_id', 'Unknown')}: {e}")
            return {
                'setup_id': setup.get('setup_id', 'Unknown'),
                'success': False,
                'error': str(e)
            }
    
    def place_all_orders(self, dry_run=False):
        """
        Place all orders from the TradePhantoms CSV file
        """
        if dry_run:
            print("🔍 DRY RUN MODE - No actual orders will be placed")
        else:
            print("🚀 Starting batch order placement...")
        
        # Load setups
        df = self.load_setups()
        if df is None:
            return False
        
        # Check account balance first
        try:
            account_info = self.trader.api.get_account_summary()
            balance = account_info['account']['balance']
            currency = account_info['account']['currency']
            print(f"\\n💰 Account Balance: {balance} {currency}")
        except Exception as e:
            print(f"⚠️ Could not retrieve account balance: {e}")
        
        # Calculate total risk
        total_risk = df['stop_loss_risk_dollars'].sum()
        print(f"💸 Total risk for all setups: ${total_risk:.2f}")
        
        print(f"\\n📋 Processing {len(df)} orders...")
        
        if dry_run:
            print("\\n🔍 DRY RUN - Simulating order placement:")
            for idx, setup in df.iterrows():
                print(f"\\n   Would place: {setup['setup_id']}")
                print(f"   {setup['instrument']} {setup['direction']} {setup['order_type']}")
                print(f"   Entry: {setup['entry_price']} | Stop: {setup['stop_loss']} | Target: {setup['target_price']}")
                print(f"   Units: {setup['position_size']} | Risk: ${setup['stop_loss_risk_dollars']}")
            
            print(f"\\n✅ Dry run completed - {len(df)} orders would be placed")
            return True
        
        # Place each order (real mode)
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
        print("\\n" + "="*70)
        print("📊 TRADEPHANTOMS BATCH ORDER PLACEMENT SUMMARY")
        print("="*70)
        
        successful = [r for r in self.results if r['success']]
        failed = [r for r in self.results if not r['success']]
        
        print(f"✅ Successful orders: {len(successful)}")
        print(f"❌ Failed orders: {len(failed)}")
        print(f"📊 Total orders: {len(self.results)}")
        
        if successful:
            total_risk = sum(r.get('risk_dollars', 0) for r in successful)
            print(f"💰 Total risk deployed: ${total_risk:.2f}")
            
            print(f"\\n✅ SUCCESSFUL ORDERS:")
            for result in successful:
                risk = result.get('risk_dollars', 0)
                print(f"   • {result['setup_id']} - Order ID: {result.get('order_id', 'N/A')} (Risk: ${risk})")
        
        if failed:
            print(f"\\n❌ FAILED ORDERS:")
            for result in failed:
                print(f"   • {result['setup_id']} - Error: {result.get('error', 'Unknown error')}")
        
        print("\\n💡 Next steps:")
        print("   1. Check your Oanda platform to verify orders")
        print("   2. Monitor order fills and manage positions")
        print("   3. Adjust stop losses to breakeven after target 1 is hit")

def main():
    """Main execution function"""
    print("🎯 TRADEPHANTOMS BATCH ORDER PLACEMENT")
    print("="*50)
    
    # Initialize batch order placer
    batch_placer = TradePhantomsBatchOrderPlacer()
    
    # Show environment info
    print(f"🔗 Environment: {ENVIRONMENT}")
    print(f"📊 Account ID: {ACCOUNT_ID}")
    
    # Ask for mode
    print("\\n🤔 Choose mode:")
    print("   d = Dry run (simulate orders)")
    print("   y = Place real orders")
    print("   n = Cancel")
    
    choice = input("\\nYour choice (d/y/n): ").lower().strip()
    
    if choice == 'd':
        print("\\n🔍 Running in DRY RUN mode...")
        batch_placer.place_all_orders(dry_run=True)
    elif choice == 'y':
        print(f"\\n⚠️  WARNING: This will place REAL orders in your {ENVIRONMENT} account!")
        print("All TradePhantoms setups will be sent to Oanda with stop losses and take profits.")
        
        confirm = input("\\nAre you absolutely sure? Type 'YES' to proceed: ").strip()
        
        if confirm == 'YES':
            print(f"\\n🔄 Proceeding with REAL order placement...")
            batch_placer.place_all_orders(dry_run=False)
        else:
            print("❌ Order placement cancelled")
    else:
        print("❌ Operation cancelled")
        return False
    
    return True

if __name__ == "__main__":
    main()