# strategy_weekend_patch.py
# Quick patch to make your existing strategies work with weekend testing

import os
import sys
from datetime import datetime, timedelta

def patch_existing_strategy_file(strategy_file_path: str):
    """
    Quick patch for existing strategy files to work with weekend testing
    
    This adds weekend testing support without major code changes
    """
    
    # Weekend testing patch code to insert
    patch_code = '''
# Weekend Testing Patch - Auto-inserted
import os
from datetime import datetime, timedelta

class WeekendTestingPatch:
    """Quick weekend testing patch for existing strategies"""
    
    def __init__(self):
        self.enabled = False
        self.simulated_time = None
        
    def enable_wednesday_9am(self):
        """Enable Wednesday 9am simulation"""
        today = datetime.now()
        days_ahead = 2 - today.weekday()  # Wednesday is weekday 2
        if days_ahead <= 0:
            days_ahead += 7
        
        next_wednesday = today + timedelta(days=days_ahead)
        self.simulated_time = next_wednesday.replace(hour=9, minute=0, second=0, microsecond=0)
        self.enabled = True
        
        print(f"🧪 WEEKEND TESTING: Simulating {self.simulated_time.strftime('%A %B %d, %Y at %I:%M %p')}")
        
        # Monkey patch datetime.now
        import datetime as dt_module
        original_now = dt_module.datetime.now
        
        def patched_now(*args, **kwargs):
            if self.enabled:
                return self.simulated_time
            return original_now(*args, **kwargs)
        
        dt_module.datetime.now = patched_now
        
        # Also patch the global datetime
        globals()['datetime'] = dt_module
        
    def is_market_open(self):
        """Check if market is open during testing"""
        if self.enabled:
            return self.simulated_time.weekday() < 5  # Monday-Friday
        return datetime.now().weekday() < 5

# Global weekend testing instance
weekend_patch = WeekendTestingPatch()

# Auto-enable if it's weekend
if datetime.now().weekday() >= 5:  # Saturday or Sunday
    enable_testing = input("🧪 Enable weekend testing (simulate Wednesday 9am)? (y/N): ").lower() == 'y'
    if enable_testing:
        weekend_patch.enable_wednesday_9am()

# Weekend Testing Patch End
'''
    
    try:
        # Read the original file
        with open(strategy_file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Check if already patched
        if "Weekend Testing Patch" in original_content:
            print(f"✅ {strategy_file_path} already has weekend testing patch")
            return True
        
        # Find where to insert (after imports, before classes)
        lines = original_content.split('\n')
        insert_index = 0
        
        # Find a good place to insert (after imports, before main logic)
        for i, line in enumerate(lines):
            if line.strip().startswith('class ') or line.strip().startswith('def main'):
                insert_index = i
                break
            elif line.strip().startswith('# Import') or line.strip().startswith('from ') or line.strip().startswith('import '):
                insert_index = i + 1
        
        # Insert the patch code
        lines.insert(insert_index, patch_code)
        
        # Write back to file
        patched_content = '\n'.join(lines)
        
        # Create backup first
        backup_path = strategy_file_path + '.backup'
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        # Write patched version
        with open(strategy_file_path, 'w', encoding='utf-8') as f:
            f.write(patched_content)
        
        print(f"✅ Patched {strategy_file_path}")
        print(f"💾 Backup saved as {backup_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error patching {strategy_file_path}: {e}")
        return False

def patch_is_market_open_method(strategy_file_path: str):
    """
    Specifically patch the is_market_open method to work with weekend testing
    """
    
    replacement_method = '''
    def is_market_open(self) -> bool:
        """Check if forex market is currently open (weekend testing compatible)"""
        try:
            # Check for weekend testing patch
            if hasattr(globals().get('weekend_patch'), 'enabled') and weekend_patch.enabled:
                return weekend_patch.is_market_open()
            
            # Original logic
            if self.market_schedule:
                current_market_time = self.market_schedule.get_market_time()
                return self.market_schedule.is_market_open(current_market_time)
            else:
                # Simple fallback - assume market is always open except weekends
                current_time = datetime.now()
                return current_time.weekday() < 5  # Monday=0, Sunday=6
        except Exception as e:
            self.logger.error(f"Error checking market open status: {e}")
            return True  # Default to open if check fails
'''
    
    try:
        with open(strategy_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find and replace the is_market_open method
        import re
        
        # Pattern to find the is_market_open method
        pattern = r'def is_market_open\(self\).*?(?=\n    def |\nclass |\n\n|\Z)'
        
        if re.search(pattern, content, re.DOTALL):
            # Replace the method
            new_content = re.sub(pattern, replacement_method.strip(), content, flags=re.DOTALL)
            
            # Write back
            with open(strategy_file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"✅ Patched is_market_open method in {strategy_file_path}")
            return True
        else:
            print(f"⚠️ Could not find is_market_open method in {strategy_file_path}")
            return False
            
    except Exception as e:
        print(f"❌ Error patching is_market_open: {e}")
        return False

def create_weekend_test_runner():
    """
    Create a simple test runner for weekend testing
    """
    
    runner_code = '''#!/usr/bin/env python3
# weekend_test_runner.py
# Simple weekend testing runner

import os
import sys
from datetime import datetime

def main():
    print("🧪 Weekend Strategy Testing")
    print("="*40)
    
    # Check if it's weekend
    today = datetime.now()
    if today.weekday() < 5:
        print("ℹ️ It's a weekday - you can test strategies normally")
        choice = input("Continue with weekend testing anyway? (y/N): ")
        if choice.lower() != 'y':
            return
    
    # Find strategy files
    strategy_files = []
    for file in os.listdir('.'):
        if file.endswith('.py') and ('Strategy' in file or 'Trading' in file):
            strategy_files.append(file)
    
    if not strategy_files:
        print("❌ No strategy files found!")
        return
    
    print(f"\\n📊 Found {len(strategy_files)} strategy files:")
    for i, file in enumerate(strategy_files, 1):
        print(f"{i:2d}. {file}")
    
    # Let user choose
    try:
        choice = input("\\nEnter strategy number (or 'all' for all): ").strip()
        
        if choice.lower() == 'all':
            for file in strategy_files:
                print(f"\\n🎯 Testing {file}...")
                os.system(f"python {file}")
        else:
            strategy_num = int(choice) - 1
            if 0 <= strategy_num < len(strategy_files):
                file = strategy_files[strategy_num]
                print(f"\\n🎯 Testing {file}...")
                os.system(f"python {file}")
            else:
                print("❌ Invalid choice")
                
    except ValueError:
        print("❌ Invalid input")

if __name__ == "__main__":
    main()
'''
    
    try:
        with open('weekend_test_runner.py', 'w', encoding='utf-8') as f:
            f.write(runner_code)
        
        print("✅ Created weekend_test_runner.py")
        return True
        
    except Exception as e:
        print(f"❌ Error creating test runner: {e}")
        return False

def quick_fix_for_penny_curve():
    """
    Quick fix specifically for your Penny Curve strategy
    """
    
    print("🔧 Quick Fix for Penny Curve Strategy")
    print("="*40)
    
    strategy_file = "Demo_Trading_Penny_Curve_Strategy.py"
    
    if not os.path.exists(strategy_file):
        print(f"❌ {strategy_file} not found")
        return False
    
    # Add the weekend testing patch
    success1 = patch_existing_strategy_file(strategy_file)
    
    # Patch the is_market_open method
    success2 = patch_is_market_open_method(strategy_file)
    
    if success1 or success2:
        print(f"✅ {strategy_file} patched for weekend testing")
        print("ℹ️ Run the strategy again - it should now work on weekends")
        return True
    else:
        print(f"❌ Failed to patch {strategy_file}")
        return False

if __name__ == "__main__":
    print("🔧 Strategy Weekend Patch Utility")
    print("="*40)
    
    print("Options:")
    print("1. Quick fix for Penny Curve Strategy")
    print("2. Patch all strategy files")
    print("3. Create weekend test runner")
    print("4. Exit")
    
    choice = input("Enter choice (1-4): ").strip()
    
    if choice == "1":
        quick_fix_for_penny_curve()
    elif choice == "2":
        # Find and patch all strategy files
        strategy_files = []
        for file in os.listdir('.'):
            if file.endswith('.py') and ('Strategy' in file or 'Trading' in file):
                strategy_files.append(file)
        
        print(f"Found {len(strategy_files)} strategy files")
        for file in strategy_files:
            patch_existing_strategy_file(file)
    elif choice == "3":
        create_weekend_test_runner()
    elif choice == "4":
        print("Exiting")
    else:
        print("Invalid choice")