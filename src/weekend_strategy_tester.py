# weekend_strategy_tester.py
# Universal Weekend Testing Interface for All Trading Strategies
# Run this script to test any/all strategies over the weekend

import os
import sys
import subprocess
import importlib.util
from datetime import datetime, timedelta
from typing import List, Dict

# Import the weekend testing framework
try:
    from weekend_testing_framework import (
        start_weekend_testing, stop_weekend_testing, weekend_testing,
        quick_wednesday_9am, quick_friday_2pm, quick_tuesday_london_open
    )
    FRAMEWORK_AVAILABLE = True
except ImportError:
    print("❌ Weekend testing framework not found!")
    print("   Please ensure weekend_testing_framework.py is in the same directory")
    sys.exit(1)

class StrategyTester:
    """
    Universal Strategy Tester for Weekend Sessions
    
    Automatically discovers and tests all your trading strategies
    """
    
    def __init__(self):
        self.strategies = self._discover_strategies()
        self.current_session = None
        
    def _discover_strategies(self) -> Dict[str, str]:
        """Automatically discover strategy files in current directory"""
        strategies = {}
        
        # Known strategy patterns
        strategy_patterns = [
            "Demo_Trading_Penny_Curve_Strategy.py",
            "Quarter_Curve_Butter_Strategy.py", 
            "Dime_Curve_Strategies.py",
            "*Curve*Strategy*.py",
            "*Trading*Strategy*.py"
        ]
        
        current_dir = os.getcwd()
        
        # Look for strategy files
        for file in os.listdir(current_dir):
            if file.endswith('.py') and any(pattern.replace('*', '') in file for pattern in strategy_patterns):
                strategy_name = file.replace('.py', '').replace('_', ' ').title()
                strategies[strategy_name] = file
        
        # Also check for specific known files
        known_strategies = {
            "Penny Curve Momentum": "Demo_Trading_Penny_Curve_Strategy.py",
            "Quarter Curve Butter Middle": "Quarter_Curve_Butter_Strategy.py",
            "Dime Curve Strategies": "Dime_Curve_Strategies.py"
        }
        
        for name, file in known_strategies.items():
            if os.path.exists(file) and name not in strategies:
                strategies[name] = file
        
        return strategies
    
    def list_available_strategies(self):
        """List all discovered strategies"""
        print("\n📊 DISCOVERED TRADING STRATEGIES:")
        print("="*50)
        
        if not self.strategies:
            print("❌ No strategy files found!")
            print("   Make sure your strategy files are in the current directory")
            return False
        
        for i, (name, file) in enumerate(self.strategies.items(), 1):
            print(f"{i:2d}. {name}")
            print(f"     File: {file}")
            print(f"     Status: {'✅ Found' if os.path.exists(file) else '❌ Missing'}")
        
        print("="*50)
        return True
    
    def select_testing_time(self):
        """Interactive time selection for testing"""
        print("\n⏰ SELECT TESTING TIME:")
        print("="*40)
        print("1. Wednesday 9:00 AM (High liquidity - London/NY prep)")
        print("2. Friday 2:00 PM (End of week trading)")
        print("3. Tuesday 8:00 AM (London market open)")
        print("4. Monday 9:30 AM (Week opening)")
        print("5. Custom date and time")
        
        choice = input("\nEnter choice (1-5) or press Enter for Wednesday 9am: ").strip()
        
        if choice == "2":
            return quick_friday_2pm()
        elif choice == "3":
            return quick_tuesday_london_open()
        elif choice == "4":
            return start_weekend_testing("next_monday", "09:30")
        elif choice == "5":
            date = input("Enter date (next_wednesday/2025-01-08): ").strip() or "next_wednesday"
            time = input("Enter time (09:00): ").strip() or "09:00"
            return start_weekend_testing(date, time)
        else:
            return quick_wednesday_9am()
    
    def test_single_strategy(self, strategy_name: str, mode: str = "interactive"):
        """Test a single strategy"""
        if strategy_name not in self.strategies:
            print(f"❌ Strategy '{strategy_name}' not found")
            return False
        
        file_path = self.strategies[strategy_name]
        
        if not os.path.exists(file_path):
            print(f"❌ Strategy file '{file_path}' not found")
            return False
        
        print(f"\n🎯 TESTING STRATEGY: {strategy_name}")
        print("="*50)
        print(f"📁 File: {file_path}")
        print(f"⏰ Simulated Time: {weekend_testing.get_simulated_time().strftime('%A, %B %d, %Y at %I:%M %p')}")
        print("="*50)
        
        try:
            if mode == "interactive":
                # Run the strategy file directly (most compatible)
                print("🚀 Launching strategy in interactive mode...")
                print("   (You can choose demo/scan/place orders from the strategy menu)")
                print("")
                
                # Execute the strategy file as a subprocess to maintain isolation
                result = subprocess.run([sys.executable, file_path], 
                                      capture_output=False, text=True)
                
                if result.returncode == 0:
                    print("✅ Strategy test completed successfully")
                    return True
                else:
                    print(f"⚠️ Strategy exited with code {result.returncode}")
                    return False
            
            elif mode == "analysis_only":
                # Import and run analysis demo only
                spec = importlib.util.spec_from_file_location("strategy_module", file_path)
                strategy_module = importlib.util.module_from_spec(spec)
                
                # Execute the module
                spec.loader.exec_module(strategy_module)
                
                # Try to run analysis demo if available
                if hasattr(strategy_module, 'run_analysis_demo'):
                    strategy_module.run_analysis_demo()
                elif hasattr(strategy_module, 'main'):
                    # Some strategies might need main() called
                    strategy_module.main()
                
                return True
                
        except Exception as e:
            print(f"❌ Error testing strategy: {e}")
            return False
    
    def test_all_strategies(self, mode: str = "analysis_only"):
        """Test all discovered strategies"""
        print(f"\n🎯 TESTING ALL STRATEGIES ({mode.upper()})")
        print("="*60)
        
        results = {}
        
        for strategy_name in self.strategies:
            print(f"\n📊 Testing: {strategy_name}")
            print("-" * 40)
            
            try:
                success = self.test_single_strategy(strategy_name, mode)
                results[strategy_name] = "✅ Success" if success else "❌ Failed"
                
                if success:
                    print(f"✅ {strategy_name} completed successfully")
                else:
                    print(f"❌ {strategy_name} encountered issues")
                
                # Brief pause between strategies
                input("\nPress Enter to continue to next strategy...")
                
            except KeyboardInterrupt:
                print(f"\n⏹️ Testing interrupted at {strategy_name}")
                results[strategy_name] = "⏹️ Interrupted"
                break
            except Exception as e:
                print(f"❌ Error testing {strategy_name}: {e}")
                results[strategy_name] = f"❌ Error: {e}"
        
        # Show summary
        print("\n" + "="*60)
        print("📊 TESTING SUMMARY")
        print("="*60)
        for strategy, result in results.items():
            print(f"{result} {strategy}")
        print("="*60)
        
        return results
    
    def interactive_testing_menu(self):
        """Main interactive testing menu"""
        while True:
            print("\n" + "="*60)
            print("🧪 WEEKEND STRATEGY TESTING FRAMEWORK")
            print("="*60)
            print(f"⏰ Current Mode: {'🧪 Testing' if weekend_testing.enabled else '🕒 Real Time'}")
            
            if weekend_testing.enabled:
                sim_time = weekend_testing.get_simulated_time()
                print(f"📅 Simulated Time: {sim_time.strftime('%A, %B %d, %Y at %I:%M %p')}")
                print(f"🌍 Session: {weekend_testing._get_simulated_session()}")
            
            print("\n📋 MENU OPTIONS:")
            print("1. 🕒 Set Testing Time")
            print("2. 📊 List Available Strategies") 
            print("3. 🎯 Test Single Strategy")
            print("4. 🎪 Test All Strategies")
            print("5. 📈 Quick Analysis (All Strategies)")
            print("6. 🏁 Stop Testing & Exit")
            print("7. ❌ Exit Without Testing")
            
            choice = input("\nEnter choice (1-7): ").strip()
            
            if choice == "1":
                self.select_testing_time()
                
            elif choice == "2":
                self.list_available_strategies()
                
            elif choice == "3":
                if not weekend_testing.enabled:
                    print("⚠️ Please set testing time first (option 1)")
                    continue
                
                self.list_available_strategies()
                try:
                    strategy_num = int(input("\nEnter strategy number: ")) - 1
                    strategy_names = list(self.strategies.keys())
                    
                    if 0 <= strategy_num < len(strategy_names):
                        strategy_name = strategy_names[strategy_num]
                        self.test_single_strategy(strategy_name, "interactive")
                    else:
                        print("❌ Invalid strategy number")
                        
                except (ValueError, IndexError):
                    print("❌ Invalid input")
                    
            elif choice == "4":
                if not weekend_testing.enabled:
                    print("⚠️ Please set testing time first (option 1)")
                    continue
                
                mode = input("Mode (interactive/analysis_only) [analysis_only]: ").strip() or "analysis_only"
                self.test_all_strategies(mode)
                
            elif choice == "5":
                if not weekend_testing.enabled:
                    print("⚠️ Please set testing time first (option 1)")
                    continue
                
                print("🚀 Running quick analysis for all strategies...")
                self.test_all_strategies("analysis_only")
                
            elif choice == "6":
                print("🏁 Stopping weekend testing...")
                stop_weekend_testing()
                break
                
            elif choice == "7":
                print("❌ Exiting without testing")
                break
                
            else:
                print("❌ Invalid choice, please try again")

def quick_test_all():
    """Quick function to test all strategies with Wednesday 9am"""
    print("🚀 Quick Test All Strategies - Wednesday 9am")
    
    # Start testing
    if not quick_wednesday_9am():
        print("❌ Failed to start testing framework")
        return
    
    # Create tester and run all strategies
    tester = StrategyTester()
    tester.list_available_strategies()
    
    if input("\nProceed with testing all strategies? (y/N): ").lower() == 'y':
        results = tester.test_all_strategies("analysis_only")
        print("\n✅ Quick test completed!")
    
    # Stop testing
    stop_weekend_testing()

def quick_test_single(strategy_file: str):
    """Quick function to test a single strategy"""
    print(f"🎯 Quick Test Single Strategy: {strategy_file}")
    
    # Start testing
    if not quick_wednesday_9am():
        print("❌ Failed to start testing framework")
        return
    
    # Test the strategy
    tester = StrategyTester()
    
    # Find strategy by file name
    strategy_name = None
    for name, file in tester.strategies.items():
        if file == strategy_file:
            strategy_name = name
            break
    
    if strategy_name:
        tester.test_single_strategy(strategy_name, "interactive")
    else:
        print(f"❌ Strategy file '{strategy_file}' not found")
    
    # Stop testing
    stop_weekend_testing()

def main():
    """Main function - run interactive testing interface"""
    print("🧪 Weekend Strategy Testing Framework")
    print("="*50)
    print("Perfect for testing all your trading strategies over the weekend!")
    print("Simulates market hours so your strategies behave as if it's a trading day.")
    
    # Create tester instance
    tester = StrategyTester()
    
    # Check if strategies were found
    if not tester.strategies:
        print("\n❌ No trading strategies found in current directory!")
        print("   Make sure you're running this from your trading project directory")
        print("   Expected files: *Curve*Strategy*.py, *Trading*.py, etc.")
        return
    
    # Show discovered strategies
    tester.list_available_strategies()
    
    # Ask user what they want to do
    print("\n🚀 QUICK START OPTIONS:")
    print("1. 🎪 Interactive Testing Menu (Full Control)")
    print("2. ⚡ Quick Test All Strategies (Wednesday 9am)")
    print("3. 🎯 Quick Test Single Strategy")
    print("4. ❌ Exit")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        tester.interactive_testing_menu()
    elif choice == "2":
        quick_test_all()
    elif choice == "3":
        tester.list_available_strategies()
        try:
            strategy_num = int(input("\nEnter strategy number: ")) - 1
            strategy_names = list(tester.strategies.keys())
            if 0 <= strategy_num < len(strategy_names):
                strategy_file = tester.strategies[strategy_names[strategy_num]]
                quick_test_single(strategy_file)
            else:
                print("❌ Invalid strategy number")
        except (ValueError, IndexError):
            print("❌ Invalid input")
    elif choice == "4":
        print("❌ Exiting")
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()