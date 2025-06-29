#!/usr/bin/env python3
"""
Trade Setup Generator
Converts TradePhantoms signals into actionable trade setups
Handles multiple targets by splitting positions
"""

import os
import sys
import csv
import json
import re
from datetime import datetime, timedelta

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("Starting Trade Setup Generator...")

def parse_price(price_str):
    """Extract numeric price from various formats"""
    if not price_str:
        return None
    
    # Remove common text and extract number
    price_str = str(price_str).strip()
    
    # Handle formats like "Limit @ 1.3800", "Market @ .6532"
    if "@" in price_str:
        price_str = price_str.split("@")[1].strip()
    
    # Handle formats like "105 Pips"
    if "Pips" in price_str or "pips" in price_str:
        return float(re.findall(r'[\d.]+', price_str)[0])
    
    # Clean up and convert to float
    price_str = re.sub(r'[^\d.]', '', price_str)
    
    try:
        return float(price_str)
    except:
        return None

def is_pip_value(value_str):
    """Check if the value is in pips format"""
    if not value_str:
        return False
    return "Pips" in str(value_str) or "pips" in str(value_str)

def calculate_target_price(entry_price, target_value, direction, instrument, is_pips=True):
    """Calculate target price from entry price and target value (either pips or direct price)"""
    if not all([entry_price, target_value, direction]):
        return None
    
    # If it's a direct price value, return it as-is
    if not is_pips:
        return target_value
    
    # Otherwise, convert pips to price
    # Determine pip value based on instrument
    if any(pair in instrument.upper() for pair in ['JPY']):
        pip_value = 0.01  # JPY pairs: 1 pip = 0.01
    else:
        pip_value = 0.0001  # Most pairs: 1 pip = 0.0001
    
    pip_distance = target_value * pip_value
    
    if direction.lower() == "long":
        return entry_price + pip_distance
    else:  # Short
        return entry_price - pip_distance

def calculate_stop_price(entry_price, stop_value, direction, instrument, is_pips=True):
    """Calculate stop loss price from entry price and stop value (either pips or direct price)"""
    if not all([entry_price, stop_value, direction]):
        return None
    
    # If it's a direct price value, return it as-is
    if not is_pips:
        return stop_value
    
    # Otherwise, convert pips to price
    # Determine pip value based on instrument
    if any(pair in instrument.upper() for pair in ['JPY']):
        pip_value = 0.01  # JPY pairs: 1 pip = 0.01
    else:
        pip_value = 0.0001  # Most pairs: 1 pip = 0.0001
    
    pip_distance = stop_value * pip_value
    
    if direction.lower() == "long":
        return entry_price - pip_distance
    else:  # Short
        return entry_price + pip_distance

def calculate_pip_distance(entry_price, target_price, instrument):
    """Calculate pip distance between entry and target prices"""
    if not all([entry_price, target_price]):
        return None
    
    # Determine pip value based on instrument
    if any(pair in instrument.upper() for pair in ['JPY']):
        pip_value = 0.01  # JPY pairs: 1 pip = 0.01
    else:
        pip_value = 0.0001  # Most pairs: 1 pip = 0.0001
    
    price_distance = abs(target_price - entry_price)
    return price_distance / pip_value

def calculate_position_size(account_balance, risk_percent, entry_price, stop_price, max_risk_dollars=10):
    """Calculate position size based on maximum dollar risk"""
    if not all([entry_price, stop_price]):
        return 100  # Default minimum size
    
    price_risk = abs(entry_price - stop_price)
    
    if price_risk > 0:
        # Calculate position size to risk exactly max_risk_dollars
        position_size = int(max_risk_dollars / price_risk)
        return max(position_size, 1)  # Minimum 1 unit
    
    return 100  # Default if no price risk calculated

def calculate_stop_loss_risk_dollars(position_size, entry_price, stop_price):
    """Calculate the dollar amount at risk if stop loss is hit"""
    if not all([position_size, entry_price, stop_price]):
        return 0
    
    price_difference = abs(entry_price - stop_price)
    risk_dollars = position_size * price_difference
    return round(risk_dollars, 2)

def determine_order_type(entry_str, current_price, direction):
    """Determine if order should be market or limit"""
    if not entry_str or not current_price:
        return "MARKET"
    
    if "market" in entry_str.lower():
        return "MARKET"
    elif "limit" in entry_str.lower():
        return "LIMIT"
    else:
        return "LIMIT"  # Default to limit orders

def convert_instrument_format(ticker):
    """Convert ticker format to Oanda format"""
    if not ticker:
        return ticker
    
    # Remove slashes and convert to underscore format
    ticker = ticker.replace("/", "_").replace("-", "_")
    ticker = ticker.upper()
    
    # Common conversions
    conversions = {
        "USDCAD": "USD_CAD",
        "CHFJPY": "CHF_JPY", 
        "EURGBP": "EUR_GBP",
        "EURUSD": "EUR_USD",
        "GBPUSD": "GBP_USD",
        "USDJPY": "USD_JPY"
    }
    
    return conversions.get(ticker, ticker)

def create_trade_setups(csv_file_path, account_balance=100000, default_risk_percent=1.0, max_risk_dollars=10):
    """
    Convert TradePhantoms signals to trade setups
    Split positions for multiple targets
    Handles both pip values and direct price values
    Uses fixed dollar risk instead of percentage risk
    """
    
    setups = []
    
    print(f"\\n🔍 Opening CSV file: {csv_file_path}")
    
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            
            # Print headers for debugging
            headers = reader.fieldnames
            print(f"📋 CSV Headers found: {headers}")
            print()
            
            for row_num, row in enumerate(reader, 1):
                print(f"\\nProcessing signal {row_num}: {row.get('Ticker/ Pair', 'Unknown')}")
                
                # Extract basic trade info
                date = row.get('Date', '')
                asset_class = row.get('Asset Class', '')
                ticker = row.get('Ticker/ Pair', '')
                direction = row.get('Direction', '')
                trade_type = row.get('Type of Trade', '')
                entry_str = row.get('Entry', '')
                current_price = row.get('Current Price (Delayed)', 0)
                stop_str = row.get('Stop Loss', '')
                target1_str = row.get('Target 1', '')
                target2_str = row.get('Target 2', '')
                target3_str = row.get('Target 3', '')
                notes = row.get('Notes / Trade Management::', '')
                results = row.get('Results::', '')
                
                print(f"  Entry: {entry_str}")
                print(f"  Stop: {stop_str}")
                print(f"  T1: {target1_str}")
                print(f"  T2: {target2_str}")
                print(f"  Results: '{results}'")
                
                # Skip if not forex or already closed
                if asset_class.lower() != 'forex':
                    print(f"  Skipping non-forex signal: {asset_class}")
                    continue
                
                if results and results.lower() not in ['', 'active', 'pending']:
                    print(f"  Skipping closed signal: {results}")
                    continue
                
                # Parse entry price
                entry_price = parse_price(entry_str)
                if not entry_price:
                    print(f"  Error: Could not parse entry price: {entry_str}")
                    continue
                
                # Parse stop and targets, checking if they're in pips or direct prices
                stop_value = parse_price(stop_str)
                target1_value = parse_price(target1_str)
                target2_value = parse_price(target2_str)
                
                # Determine if values are in pips or direct prices
                stop_is_pips = is_pip_value(stop_str)
                target1_is_pips = is_pip_value(target1_str)
                target2_is_pips = is_pip_value(target2_str)
                
                print(f"  Entry: {entry_price}")
                print(f"  Stop: {stop_value} ({'pips' if stop_is_pips else 'price'})")
                print(f"  T1: {target1_value} ({'pips' if target1_is_pips else 'price'})")
                print(f"  T2: {target2_value} ({'pips' if target2_is_pips else 'price'})")
                
                # Convert instrument format
                instrument = convert_instrument_format(ticker)
                
                # Calculate actual prices
                stop_price = calculate_stop_price(entry_price, stop_value, direction, instrument, stop_is_pips)
                target1_price = calculate_target_price(entry_price, target1_value, direction, instrument, target1_is_pips)
                target2_price = None
                if target2_value:
                    target2_price = calculate_target_price(entry_price, target2_value, direction, instrument, target2_is_pips)
                
                print(f"  Calculated Stop: {stop_price}")
                print(f"  Calculated T1: {target1_price}")
                print(f"  Calculated T2: {target2_price}")
                
                # Calculate pip distances for R:R ratios
                if stop_price and target1_price:
                    stop_pips = calculate_pip_distance(entry_price, stop_price, instrument)
                    target1_pips = calculate_pip_distance(entry_price, target1_price, instrument)
                    target1_rr = target1_pips / stop_pips if stop_pips else None
                else:
                    target1_rr = None
                
                if stop_price and target2_price:
                    target2_pips = calculate_pip_distance(entry_price, target2_price, instrument)
                    target2_rr = target2_pips / stop_pips if stop_pips else None
                else:
                    target2_rr = None
                
                # Determine order type
                order_type = determine_order_type(entry_str, current_price, direction)
                
                # Calculate position sizes (split for multiple targets)
                total_risk_percent = default_risk_percent
                
                if target1_price and target2_price:
                    # Split position: $10 risk for each target
                    position1_size = calculate_position_size(account_balance, 0, entry_price, stop_price, max_risk_dollars)
                    position2_size = calculate_position_size(account_balance, 0, entry_price, stop_price, max_risk_dollars)
                    
                    # Calculate actual risk percentages based on position sizes
                    risk1_dollars = calculate_stop_loss_risk_dollars(position1_size, entry_price, stop_price)
                    risk2_dollars = calculate_stop_loss_risk_dollars(position2_size, entry_price, stop_price)
                    risk1_percent = (risk1_dollars / account_balance) * 100
                    risk2_percent = (risk2_dollars / account_balance) * 100
                    
                    # Create setup 1 (Target 1)
                    setup1 = {
                        "signal_source": "TradePhantoms",
                        "signal_date": date,
                        "setup_id": f"TP_{ticker}_{direction}_T1_{datetime.now().strftime('%Y%m%d')}",
                        "instrument": instrument,
                        "direction": direction.title(),
                        "order_type": order_type,
                        "entry_price": round(entry_price, 5),
                        "stop_loss": round(stop_price, 5) if stop_price else None,
                        "stop_loss_risk_dollars": risk1_dollars,
                        "target_price": round(target1_price, 5),
                        "position_size": position1_size,
                        "risk_percent": round(risk1_percent, 3),
                        "notes": f"TradePhantoms {trade_type} - Target 1",
                        "original_signal": entry_str,
                        "target_number": 1,
                        "r_r_ratio": round(target1_rr, 2) if target1_rr else None
                    }
                    setups.append(setup1)
                    
                    # Create setup 2 (Target 2)
                    setup2 = {
                        "signal_source": "TradePhantoms",
                        "signal_date": date,
                        "setup_id": f"TP_{ticker}_{direction}_T2_{datetime.now().strftime('%Y%m%d')}",
                        "instrument": instrument,
                        "direction": direction.title(),
                        "order_type": order_type,
                        "entry_price": round(entry_price, 5),
                        "stop_loss": round(stop_price, 5) if stop_price else None,
                        "stop_loss_risk_dollars": risk2_dollars,
                        "target_price": round(target2_price, 5),
                        "position_size": position2_size,
                        "risk_percent": round(risk2_percent, 3),
                        "notes": f"TradePhantoms {trade_type} - Target 2",
                        "original_signal": entry_str,
                        "target_number": 2,
                        "r_r_ratio": round(target2_rr, 2) if target2_rr else None
                    }
                    setups.append(setup2)
                    
                    print(f"  ✅ Created 2 setups for {instrument} {direction}")
                    print(f"    Setup 1: {position1_size} units to {target1_price} (R:R {setup1['r_r_ratio']}) - Risk: ${risk1_dollars}")
                    print(f"    Setup 2: {position2_size} units to {target2_price} (R:R {setup2['r_r_ratio']}) - Risk: ${risk2_dollars}")
                    
                elif target1_price:
                    # Single target setup with $10 risk
                    position_size = calculate_position_size(account_balance, 0, entry_price, stop_price, max_risk_dollars)
                    
                    # Calculate actual risk
                    risk_dollars = calculate_stop_loss_risk_dollars(position_size, entry_price, stop_price)
                    risk_percent = (risk_dollars / account_balance) * 100
                    
                    setup = {
                        "signal_source": "TradePhantoms",
                        "signal_date": date,
                        "setup_id": f"TP_{ticker}_{direction}_{datetime.now().strftime('%Y%m%d')}",
                        "instrument": instrument,
                        "direction": direction.title(),
                        "order_type": order_type,
                        "entry_price": round(entry_price, 5),
                        "stop_loss": round(stop_price, 5) if stop_price else None,
                        "stop_loss_risk_dollars": risk_dollars,
                        "target_price": round(target1_price, 5),
                        "position_size": position_size,
                        "risk_percent": round(risk_percent, 3),
                        "notes": f"TradePhantoms {trade_type} - Single Target",
                        "original_signal": entry_str,
                        "target_number": 1,
                        "r_r_ratio": round(target1_rr, 2) if target1_rr else None
                    }
                    setups.append(setup)
                    
                    print(f"  ✅ Created 1 setup for {instrument} {direction}")
                    print(f"    {position_size} units to {target1_price} (R:R {setup['r_r_ratio']}) - Risk: ${risk_dollars}")
                else:
                    print(f"  ⚠️  No valid targets found for {ticker}")
    
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    return setups

def export_setups(setups, output_format='json'):
    """Export trade setups to file"""
    
    if not setups:
        print("No setups to export")
        return
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if output_format == 'json':
        filename = f"trade_setups_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump(setups, f, indent=2)
        print(f"\\n📁 Exported {len(setups)} setups to: {filename}")
    
    elif output_format == 'csv':
        filename = f"trade_setups_{timestamp}.csv"
        if setups:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=setups[0].keys())
                writer.writeheader()
                writer.writerows(setups)
            print(f"\\n📁 Exported {len(setups)} setups to: {filename}")
    
    return filename

def print_setup_summary(setups):
    """Print a summary of generated setups"""
    
    if not setups:
        print("\\n❌ No trade setups generated")
        return
    
    print(f"\\n🎯 TRADE SETUP SUMMARY")
    print("=" * 50)
    print(f"Total setups generated: {len(setups)}")
    
    # Group by instrument
    instruments = {}
    for setup in setups:
        inst = setup['instrument']
        if inst not in instruments:
            instruments[inst] = []
        instruments[inst].append(setup)
    
    print(f"\\nSetups by instrument:")
    for instrument, inst_setups in instruments.items():
        print(f"  {instrument}: {len(inst_setups)} setups")
        for setup in inst_setups:
            direction = setup['direction']
            target = setup['target_number']
            entry = setup['entry_price']
            target_price = setup['target_price']
            rr = setup['r_r_ratio']
            risk_dollars = setup['stop_loss_risk_dollars']
            print(f"    T{target}: {direction} @ {entry} → {target_price} (R:R {rr}) - Risk: ${risk_dollars}")
    
    print(f"\\n📊 Risk Analysis:")
    total_risk = sum(setup['risk_percent'] for setup in setups)
    total_risk_dollars = sum(setup['stop_loss_risk_dollars'] for setup in setups)
    print(f"  Total risk exposure: {total_risk:.1f}% of account")
    print(f"  Total risk in dollars: ${total_risk_dollars:,.2f}")
    
    avg_rr = sum(setup['r_r_ratio'] for setup in setups if setup['r_r_ratio']) / len(setups)
    print(f"  Average R:R ratio: {avg_rr:.2f}")

def main():
    """Main execution function"""
    
    print("=" * 60)
    print("🚀 TRADE SETUP GENERATOR STARTING")
    print("=" * 60)
    
    # Configuration
    csv_file = "TradePhantoms062025.csv"  # Updated filename
    account_balance = 100000  # Adjust to your account size
    default_risk_percent = 1.0  # This is now just for reference
    max_risk_dollars = 10  # Maximum dollar risk per trade
    
    # Check if file exists
    if not os.path.exists(csv_file):
        print(f"❌ ERROR: CSV file '{csv_file}' not found!")
        print(f"📁 Current directory: {os.getcwd()}")
        print("📋 Files in current directory:")
        for file in os.listdir('.'):
            if file.endswith('.csv'):
                print(f"  📄 {file}")
            else:
                print(f"  📁 {file}")
        print("\\n💡 Make sure the CSV file is in the same directory as this script.")
        return 0
    
    print(f"✅ Found CSV file: {csv_file}")
    print(f"📊 Account balance: ${account_balance:,}")
    print(f"💰 Maximum risk per trade: ${max_risk_dollars}")
    print()
    
    try:
        # Generate trade setups
        print("🔄 Starting trade setup generation...")
        setups = create_trade_setups(csv_file, account_balance, default_risk_percent, max_risk_dollars)
        print(f"✅ Trade setup generation completed! Generated {len(setups)} setups.")
    except Exception as e:
        print(f"❌ ERROR during setup generation: {e}")
        import traceback
        traceback.print_exc()
        return 0
    
    # Print summary
    try:
        print("📋 Generating summary...")
        print_setup_summary(setups)
    except Exception as e:
        print(f"❌ ERROR during summary generation: {e}")
    
    # Export setups
    if setups:
        try:
            print("💾 Exporting setups...")
            json_file = export_setups(setups, 'json')
            csv_file_out = export_setups(setups, 'csv')
            print(f"✅ Export completed successfully!")
        except Exception as e:
            print(f"❌ ERROR during export: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"\\n🚀 Ready to implement {len(setups)} trade setups!")
        print("\\n💡 Next steps:")
        print("  1. Review the generated setups")
        print("  2. Adjust position sizes if needed")
        print("  3. Place orders in your trading platform")
        print("  4. Monitor and manage according to TradePhantoms updates")
    else:
        print("⚠️ No setups were generated. Check the input data and try again.")
    
    print("\\n" + "=" * 60)
    print(f"🏁 TRADE SETUP GENERATOR FINISHED - Generated {len(setups)} setups")
    print("=" * 60)
    
    return len(setups)

if __name__ == "__main__":
    main()