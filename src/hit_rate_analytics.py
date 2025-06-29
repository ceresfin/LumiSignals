#!/usr/bin/env python3
"""
Hit Rate Analytics Script
Analyzes order execution statistics from Airtable data
"""

import os
import sys
import pandas as pd
from datetime import datetime

# Add parent directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    from pyairtable import Api
    print("✅ Successfully imported analytics modules")
except ImportError as e:
    print(f"❌ Failed to import modules: {e}")
    sys.exit(1)

class HitRateAnalyzer:
    """
    Analyzes trading hit rates and order execution statistics
    """
    
    def __init__(self):
        self.airtable_api = Api(AIRTABLE_API_TOKEN)
        self.table = self.airtable_api.table(BASE_ID, TABLE_NAME)
        self.data = None
    
    def load_data(self):
        """Load all records from Airtable"""
        try:
            records = self.table.all()
            
            # Convert to DataFrame for analysis
            data_list = []
            for record in records:
                fields = record['fields']
                fields['Record_ID'] = record['id']
                data_list.append(fields)
            
            self.data = pd.DataFrame(data_list)
            print(f"📊 Loaded {len(self.data)} records from Airtable")
            return True
            
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            return False
    
    def analyze_hit_rates(self):
        """Analyze overall hit rates"""
        if self.data is None:
            print("❌ No data loaded")
            return
        
        print("\n" + "="*60)
        print("📊 ORDER EXECUTION HIT RATE ANALYSIS")
        print("="*60)
        
        # Overall statistics
        total_orders = len(self.data)
        filled_orders = len(self.data[self.data['Order Status'] == 'Filled'])
        pending_orders = len(self.data[self.data['Order Status'] == 'Pending'])
        cancelled_orders = len(self.data[self.data['Order Status'] == 'Cancelled'])
        
        hit_rate = (filled_orders / total_orders * 100) if total_orders > 0 else 0
        
        print(f"\n📈 OVERALL STATISTICS:")
        print(f"   Total Orders Placed: {total_orders}")
        print(f"   Orders Filled: {filled_orders}")
        print(f"   Orders Pending: {pending_orders}")
        print(f"   Orders Cancelled: {cancelled_orders}")
        print(f"   Hit Rate: {hit_rate:.1f}%")
        
        return {
            'total_orders': total_orders,
            'filled_orders': filled_orders,
            'pending_orders': pending_orders,
            'cancelled_orders': cancelled_orders,
            'hit_rate': hit_rate
        }
    
    def analyze_by_instrument(self):
        """Analyze hit rates by instrument"""
        if self.data is None:
            return
        
        print(f"\n📊 HIT RATE BY INSTRUMENT:")
        print("-" * 40)
        
        instruments = self.data['Instrument'].value_counts().index
        
        for instrument in instruments:
            inst_data = self.data[self.data['Instrument'] == instrument]
            total = len(inst_data)
            filled = len(inst_data[inst_data['Order Status'] == 'Filled'])
            pending = len(inst_data[inst_data['Order Status'] == 'Pending'])
            cancelled = len(inst_data[inst_data['Order Status'] == 'Cancelled'])
            
            hit_rate = (filled / total * 100) if total > 0 else 0
            
            print(f"   {instrument}:")
            print(f"     Total: {total} | Filled: {filled} | Pending: {pending} | Cancelled: {cancelled}")
            print(f"     Hit Rate: {hit_rate:.1f}%")
    
    def analyze_by_direction(self):
        """Analyze hit rates by trade direction"""
        if self.data is None:
            return
        
        print(f"\n📊 HIT RATE BY DIRECTION:")
        print("-" * 40)
        
        for direction in ['Long', 'Short']:
            dir_data = self.data[self.data['Direction'] == direction]
            if len(dir_data) == 0:
                continue
                
            total = len(dir_data)
            filled = len(dir_data[dir_data['Order Status'] == 'Filled'])
            pending = len(dir_data[dir_data['Order Status'] == 'Pending'])
            cancelled = len(dir_data[dir_data['Order Status'] == 'Cancelled'])
            
            hit_rate = (filled / total * 100) if total > 0 else 0
            
            print(f"   {direction} Trades:")
            print(f"     Total: {total} | Filled: {filled} | Pending: {pending} | Cancelled: {cancelled}")
            print(f"     Hit Rate: {hit_rate:.1f}%")
    
    def analyze_time_to_fill(self):
        """Analyze time to fill statistics"""
        if self.data is None:
            return
        
        # Filter for filled orders with days pending data
        filled_data = self.data[
            (self.data['Order Status'] == 'Filled') & 
            (self.data['Days Pending'].notna()) &
            (self.data['Days Pending'] >= 0)
        ]
        
        if len(filled_data) == 0:
            print(f"\n⚠️  No time-to-fill data available yet")
            return
        
        print(f"\n⏱️  TIME TO FILL ANALYSIS:")
        print("-" * 40)
        
        avg_days = filled_data['Days Pending'].mean()
        max_days = filled_data['Days Pending'].max()
        min_days = filled_data['Days Pending'].min()
        
        print(f"   Average Days to Fill: {avg_days:.1f}")
        print(f"   Fastest Fill: {min_days:.1f} days")
        print(f"   Slowest Fill: {max_days:.1f} days")
        
        # Distribution
        same_day = len(filled_data[filled_data['Days Pending'] == 0])
        within_week = len(filled_data[filled_data['Days Pending'] <= 7])
        
        print(f"   Same Day Fills: {same_day} ({same_day/len(filled_data)*100:.1f}%)")
        print(f"   Within 1 Week: {within_week} ({within_week/len(filled_data)*100:.1f}%)")
    
    def analyze_setup_performance(self):
        """Analyze performance by setup type (from LumiTrade)"""
        if self.data is None or 'Setup_Name' not in self.data.columns:
            print(f"\n⚠️  No setup name data available for analysis")
            return
        
        print(f"\n🎯 SETUP PERFORMANCE ANALYSIS:")
        print("-" * 40)
        
        # Extract setup types from names (e.g., "EURUSD_Swing" -> "Swing")
        if 'Setup_Name' in self.data.columns:
            self.data['Setup_Type'] = self.data['Setup_Name'].str.extract(r'_(\w+)$')[0]
            
            setup_types = self.data['Setup_Type'].value_counts().index
            
            for setup_type in setup_types:
                if pd.isna(setup_type):
                    continue
                    
                setup_data = self.data[self.data['Setup_Type'] == setup_type]
                total = len(setup_data)
                filled = len(setup_data[setup_data['Order Status'] == 'Filled'])
                
                hit_rate = (filled / total * 100) if total > 0 else 0
                
                print(f"   {setup_type} Setups:")
                print(f"     Total: {total} | Filled: {filled} | Hit Rate: {hit_rate:.1f}%")
    
    def generate_summary_report(self):
        """Generate a comprehensive summary report"""
        print("\n" + "="*60)
        print("📋 EXECUTIVE SUMMARY")
        print("="*60)
        
        if self.data is None:
            print("❌ No data available for analysis")
            return
        
        overall_stats = self.analyze_hit_rates()
        
        # Key insights
        total_orders = overall_stats['total_orders']
        hit_rate = overall_stats['hit_rate']
        
        print(f"\n🎯 KEY INSIGHTS:")
        
        if hit_rate >= 80:
            print(f"   ✅ EXCELLENT hit rate of {hit_rate:.1f}% - Your setups are executing very well!")
        elif hit_rate >= 60:
            print(f"   ✅ GOOD hit rate of {hit_rate:.1f}% - Solid execution performance")
        elif hit_rate >= 40:
            print(f"   ⚠️  MODERATE hit rate of {hit_rate:.1f}% - Consider tighter entry criteria")
        else:
            print(f"   ❌ LOW hit rate of {hit_rate:.1f}% - Review setup criteria and market conditions")
        
        print(f"\n💡 RECOMMENDATIONS:")
        if overall_stats['pending_orders'] > 0:
            print(f"   • Monitor {overall_stats['pending_orders']} pending orders for execution")
        
        if overall_stats['cancelled_orders'] > 0:
            cancel_rate = overall_stats['cancelled_orders'] / total_orders * 100
            print(f"   • {cancel_rate:.1f}% cancellation rate - consider order management strategy")
        
        print(f"   • Continue tracking hit rates to optimize setup selection")
        print(f"   • Focus on instruments and setups with highest hit rates")

def main():
    """Main execution function"""
    print("🎯 Trading Hit Rate Analytics")
    print("=" * 50)
    
    analyzer = HitRateAnalyzer()
    
    # Load data
    if not analyzer.load_data():
        return False
    
    # Run all analyses
    analyzer.analyze_hit_rates()
    analyzer.analyze_by_instrument()
    analyzer.analyze_by_direction()
    analyzer.analyze_time_to_fill()
    analyzer.analyze_setup_performance()
    analyzer.generate_summary_report()
    
    print(f"\n🔄 Next steps:")
    print(f"   1. Run 'python sync_all.py' to update data")
    print(f"   2. Re-run this analysis to see updated hit rates")
    print(f"   3. Use insights to optimize your trading setups")
    
    return True

if __name__ == "__main__":
    main()