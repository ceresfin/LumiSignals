#!/usr/bin/env python3
"""
Quick Diagnostic - Check what you have in your trading bot setup
Save this as: quick_diagnostic.py
"""

import os
import json
import sys
from datetime import datetime

def check_trading_bot_setup():
    """Quick check of your trading bot setup"""
    print("🔍 Quick Trading Bot Diagnostic")
    print("=" * 50)
    
    # Check current directory
    current_dir = os.getcwd()
    print(f"📁 Current directory: {current_dir}")
    
    # List all Python files
    python_files = [f for f in os.listdir('.') if f.endswith('.py')]
    print(f"\n🐍 Python files found ({len(python_files)}):")
    for f in python_files:
        size = os.path.getsize(f)
        print(f"   📄 {f} ({size:,} bytes)")
    
    # Check for key files
    key_files = {
        'Demo_Trading_Penny_Curve_Strategy.py': '🤖 Main trading bot',
        'metadata_storage.py': '📝 Metadata storage',
        'oanda_api.py': '🔌 OANDA API',
        'psychological_levels_trader.py': '📊 Strategy logic',
        'momentum_calculator.py': '📈 Momentum calculator',
        'airtable_utils.py': '📋 Airtable integration',
        'airtable_debugger.py': '🔍 This diagnostic tool'
    }
    
    print(f"\n🔑 Key files check:")
    found_files = []
    missing_files = []
    
    for filename, description in key_files.items():
        if os.path.exists(filename):
            size = os.path.getsize(filename)
            print(f"   ✅ {filename} - {description} ({size:,} bytes)")
            found_files.append(filename)
        else:
            print(f"   ❌ {filename} - {description} (NOT FOUND)")
            missing_files.append(filename)
    
    # Check config directory
    if os.path.exists('config'):
        print(f"\n📂 Config directory contents:")
        config_files = os.listdir('config')
        for f in config_files:
            if f.endswith('.py'):
                print(f"   📄 config/{f}")
    else:
        print(f"\n❌ No 'config' directory found")
    
    # Check for metadata/data directories
    data_dirs = ['metadata', 'data', 'trading_logs', 'logs']
    print(f"\n📊 Data directories:")
    for dirname in data_dirs:
        if os.path.exists(dirname):
            files = os.listdir(dirname)
            print(f"   ✅ {dirname}/ ({len(files)} files)")
            # Show a few sample files
            for f in files[:3]:
                print(f"      📄 {f}")
            if len(files) > 3:
                print(f"      ... and {len(files) - 3} more")
        else:
            print(f"   ❌ {dirname}/ (not found)")
    
    # Try to import key modules
    print(f"\n🔧 Module import test:")
    test_imports = [
        'requests',
        'json', 
        'datetime',
        'os',
        'sys'
    ]
    
    for module in test_imports:
        try:
            __import__(module)
            print(f"   ✅ {module}")
        except ImportError:
            print(f"   ❌ {module} (need to install)")
    
    # Check if main trading bot can be analyzed
    main_bot = 'Demo_Trading_Penny_Curve_Strategy.py'
    if main_bot in found_files:
        print(f"\n🤖 Analyzing main trading bot...")
        try:
            with open(main_bot, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for key components
            checks = {
                'Airtable': 'airtable' in content.lower(),
                'Metadata Storage': 'metadata' in content.lower(),
                'OANDA API': 'oanda' in content.lower(),
                'Client Extensions': 'clientExtensions' in content,
                'Risk Management': 'risk' in content.lower(),
                'Polars/Pandas': ('polars' in content.lower() or 'pandas' in content.lower())
            }
            
            for check, found in checks.items():
                status = "✅" if found else "❌"
                print(f"   {status} {check} references found")
            
            # Count lines
            lines = content.split('\n')
            print(f"   📏 Total lines: {len(lines):,}")
            
        except Exception as e:
            print(f"   ❌ Error reading main bot: {e}")
    
    # Generate recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    
    if 'airtable_debugger.py' not in found_files:
        print("   1. Create airtable_debugger.py with the diagnostic code")
    
    if not any('airtable' in f.lower() for f in found_files):
        print("   2. No Airtable integration files found - this may be why data isn't syncing")
    
    if 'metadata_storage.py' not in found_files:
        print("   3. Missing metadata_storage.py - trades may not be logged locally")
    
    if not os.path.exists('metadata') and not os.path.exists('data'):
        print("   4. No data directories found - check if trades are being stored")
    
    print(f"\n📋 NEXT STEPS:")
    print("   1. Copy the full diagnostic code into 'airtable_debugger.py'")
    print("   2. Update the configuration with your API keys")
    print("   3. Run: python airtable_debugger.py")
    print("   4. Check if your bot is actually placing trades")
    
    # Save this analysis
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"quick_diagnostic_{timestamp}.txt"
    
    # Redirect output to file as well
    with open(report_file, 'w') as f:
        f.write(f"Quick Trading Bot Diagnostic - {datetime.now()}\n")
        f.write("=" * 50 + "\n")
        f.write(f"Current directory: {current_dir}\n\n")
        f.write(f"Python files: {', '.join(python_files)}\n\n")
        f.write(f"Found key files: {', '.join(found_files)}\n")
        f.write(f"Missing key files: {', '.join(missing_files)}\n")
    
    print(f"\n💾 Report saved to: {report_file}")

if __name__ == "__main__":
    check_trading_bot_setup()