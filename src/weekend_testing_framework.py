# weekend_testing_framework.py
# Universal Testing Framework for All Trading Strategies
# Enables weekend testing by simulating market hours and conditions

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import importlib

class WeekendTestingFramework:
    """
    Universal Weekend Testing Framework
    
    Features:
    - Time simulation for any day/hour
    - Market condition simulation
    - Multi-strategy testing support
    - Session and liquidity simulation
    - Real market data with simulated time
    """
    
    def __init__(self):
        self.enabled = False
        self.simulated_datetime = None
        self.original_modules = {}
        self.patched_modules = []
        self.test_session = None
        self.logger = self._setup_logger()
    
    def _setup_logger(self):
        """Setup testing framework logger"""
        logger = logging.getLogger('WeekendTesting')
        logger.setLevel(logging.INFO)
        
        # Create console handler if none exists
        if not logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(
                logging.Formatter('🧪 %(asctime)s - %(levelname)s - %(message)s')
            )
            logger.addHandler(console_handler)
        
        return logger
    
    def start_test_session(self, session_name: str = None):
        """Start a new testing session"""
        if not session_name:
            session_name = f"Weekend_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        self.test_session = {
            'name': session_name,
            'started_at': datetime.now().isoformat(),
            'strategies_tested': [],
            'total_opportunities': 0,
            'total_orders_placed': 0,
            'simulated_time': None
        }
        
        self.logger.info(f"🧪 Started testing session: {session_name}")
        return session_name
    
    def simulate_market_time(self, target_date: str = None, target_time: str = "09:00"):
        """
        Simulate specific market time
        
        Args:
            target_date: "next_wednesday", "2025-01-08", "next_friday", etc.
            target_time: "09:00", "14:30", "08:00", etc.
        """
        try:
            # Parse target time
            hour, minute = map(int, target_time.split(':'))
            
            # Parse target date
            if target_date is None or target_date == "next_wednesday":
                # Default to next Wednesday
                today = datetime.now()
                days_ahead = 2 - today.weekday()  # Wednesday is weekday 2
                if days_ahead <= 0:
                    days_ahead += 7
                target_dt = today + timedelta(days=days_ahead)
            
            elif target_date == "next_friday":
                today = datetime.now()
                days_ahead = 4 - today.weekday()  # Friday is weekday 4
                if days_ahead <= 0:
                    days_ahead += 7
                target_dt = today + timedelta(days=days_ahead)
            
            elif target_date == "next_monday":
                today = datetime.now()
                days_ahead = 0 - today.weekday()  # Monday is weekday 0
                if days_ahead <= 0:
                    days_ahead += 7
                target_dt = today + timedelta(days=days_ahead)
            
            elif target_date.startswith("2025-") or target_date.startswith("2024-"):
                # Specific date format: "2025-01-08"
                year, month, day = map(int, target_date.split('-'))
                target_dt = datetime(year, month, day)
            
            else:
                # Default to next weekday
                today = datetime.now()
                days_ahead = 0
                while (today + timedelta(days=days_ahead)).weekday() >= 5:
                    days_ahead += 1
                target_dt = today + timedelta(days=days_ahead)
            
            # Set the time
            self.simulated_datetime = target_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            self.enabled = True
            
            # Update test session
            if self.test_session:
                self.test_session['simulated_time'] = self.simulated_datetime.isoformat()
            
            # Log the simulation
            weekday_name = self.simulated_datetime.strftime('%A')
            is_market_day = self.simulated_datetime.weekday() < 5
            
            self.logger.info("⏰ MARKET TIME SIMULATION ENABLED")
            self.logger.info(f"   📅 Date: {self.simulated_datetime.strftime('%A, %B %d, %Y')}")
            self.logger.info(f"   🕒 Time: {self.simulated_datetime.strftime('%I:%M %p')}")
            self.logger.info(f"   📈 Market: {'OPEN' if is_market_day else 'CLOSED'} ({'Weekday' if is_market_day else 'Weekend'})")
            self.logger.info(f"   🌍 Session: {self._get_simulated_session()}")
            
            return self.simulated_datetime
            
        except Exception as e:
            self.logger.error(f"❌ Error setting simulated time: {e}")
            return None
    
    def _get_simulated_session(self):
        """Get trading session info for simulated time"""
        if not self.enabled:
            return "Real Time"
        
        hour = self.simulated_datetime.hour
        weekday = self.simulated_datetime.weekday()
        
        if weekday >= 5:  # Weekend
            return "CLOSED (Weekend)"
        
        # Determine session based on hour (ET)
        if 19 <= hour or hour < 4:
            return "Asian Session"
        elif 3 <= hour < 8:
            return "London Session" 
        elif 8 <= hour < 12:
            return "London-NY Overlap (HIGH LIQUIDITY)"
        elif 12 <= hour < 17:
            return "New York Session"
        else:
            return "After Hours"
    
    def get_simulated_time(self):
        """Get current simulated time or real time"""
        if self.enabled and self.simulated_datetime:
            return self.simulated_datetime
        return datetime.now()
    
    def patch_datetime_globally(self):
        """Patch datetime.now() globally for all modules"""
        try:
            import datetime as dt_module
            
            # Store original
            if 'datetime' not in self.original_modules:
                self.original_modules['datetime'] = dt_module.datetime.now
            
            # Create patched version
            def patched_now(*args, **kwargs):
                if self.enabled and self.simulated_datetime:
                    return self.simulated_datetime
                return self.original_modules['datetime'](*args, **kwargs)
            
            # Apply patch
            dt_module.datetime.now = patched_now
            self.patched_modules.append('datetime')
            
            self.logger.info("✅ Patched datetime.now() globally")
            
        except Exception as e:
            self.logger.error(f"❌ Error patching datetime: {e}")
    
    def patch_strategy_modules(self, strategy_modules: List[str] = None):
        """Patch specific strategy modules"""
        if strategy_modules is None:
            # Default strategy modules to patch
            strategy_modules = [
                'Demo_Trading_Penny_Curve_Strategy',
                'Quarter_Curve_Butter_Strategy', 
                'Dime_Curve_Strategies',
                'momentum_calculator'
            ]
        
        for module_name in strategy_modules:
            try:
                if module_name in sys.modules:
                    module = sys.modules[module_name]
                    
                    # Patch datetime usage in the module
                    if hasattr(module, 'datetime'):
                        if module_name not in self.original_modules:
                            self.original_modules[module_name] = module.datetime
                        
                        # Create patched datetime for this module
                        class PatchedDateTime:
                            @staticmethod
                            def now():
                                if self.enabled and self.simulated_datetime:
                                    return self.simulated_datetime
                                return self.original_modules[module_name].now()
                            
                            @staticmethod
                            def fromisoformat(date_string):
                                return self.original_modules[module_name].fromisoformat(date_string)
                            
                            @staticmethod
                            def strptime(date_string, format):
                                return self.original_modules[module_name].strptime(date_string, format)
                        
                        module.datetime = PatchedDateTime
                        self.patched_modules.append(module_name)
                        self.logger.info(f"✅ Patched datetime in {module_name}")
                
            except Exception as e:
                self.logger.warning(f"⚠️ Could not patch {module_name}: {e}")
    
    def simulate_market_conditions(self, liquidity: str = "HIGH", volatility: str = "NORMAL"):
        """Simulate specific market conditions"""
        conditions = {
            'liquidity_level': liquidity,
            'volatility_level': volatility,
            'simulated': True,
            'simulated_time': self.simulated_datetime.isoformat() if self.simulated_datetime else None
        }
        
        self.logger.info(f"🎭 Market conditions simulated: {liquidity} liquidity, {volatility} volatility")
        return conditions
    
    def test_strategy(self, strategy_file: str, mode: str = "scan"):
        """
        Test a specific strategy
        
        Args:
            strategy_file: "Dime_Curve_Strategies.py", "Quarter_Curve_Butter_Strategy.py", etc.
            mode: "scan", "demo", "analysis"
        """
        try:
            strategy_name = strategy_file.replace('.py', '')
            
            self.logger.info(f"🎯 Testing strategy: {strategy_name}")
            
            # Import the strategy module
            spec = importlib.util.spec_from_file_location(strategy_name, strategy_file)
            strategy_module = importlib.util.module_from_spec(spec)
            
            # Patch the module before execution
            sys.modules[strategy_name] = strategy_module
            self.patch_strategy_modules([strategy_name])
            
            # Execute the module
            spec.loader.exec_module(strategy_module)
            
            # Track in test session
            if self.test_session:
                self.test_session['strategies_tested'].append({
                    'name': strategy_name,
                    'mode': mode,
                    'tested_at': datetime.now().isoformat()
                })
            
            self.logger.info(f"✅ Strategy {strategy_name} tested successfully")
            return strategy_module
            
        except Exception as e:
            self.logger.error(f"❌ Error testing strategy {strategy_file}: {e}")
            return None
    
    def restore_original_time(self):
        """Restore original datetime functionality"""
        try:
            # Restore patched modules
            for module_name in self.patched_modules:
                if module_name == 'datetime':
                    import datetime as dt_module
                    if 'datetime' in self.original_modules:
                        dt_module.datetime.now = self.original_modules['datetime']
                elif module_name in sys.modules:
                    module = sys.modules[module_name]
                    if module_name in self.original_modules:
                        module.datetime = self.original_modules[module_name]
            
            self.enabled = False
            self.simulated_datetime = None
            self.patched_modules = []
            self.original_modules = {}
            
            self.logger.info("✅ Restored original datetime functionality")
            
        except Exception as e:
            self.logger.error(f"❌ Error restoring datetime: {e}")
    
    def get_test_session_summary(self):
        """Get summary of current test session"""
        if not self.test_session:
            return {"message": "No active test session"}
        
        duration = datetime.now() - datetime.fromisoformat(self.test_session['started_at'])
        
        return {
            'session_name': self.test_session['name'],
            'duration_minutes': duration.total_seconds() / 60,
            'strategies_tested': len(self.test_session['strategies_tested']),
            'simulated_time': self.test_session.get('simulated_time'),
            'strategies': self.test_session['strategies_tested']
        }
    
    def save_test_session(self, filename: str = None):
        """Save test session results"""
        if not self.test_session:
            return False
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"weekend_test_session_{timestamp}.json"
        
        try:
            # Add final summary
            self.test_session['ended_at'] = datetime.now().isoformat()
            self.test_session['summary'] = self.get_test_session_summary()
            
            # Save to file
            with open(filename, 'w') as f:
                json.dump(self.test_session, f, indent=2)
            
            self.logger.info(f"💾 Test session saved to {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Error saving test session: {e}")
            return False

# Global testing framework instance
weekend_testing = WeekendTestingFramework()

# Convenience functions for easy use
def start_weekend_testing(target_day="next_wednesday", target_time="09:00"):
    """
    Quick start weekend testing
    
    Usage:
        start_weekend_testing()  # Next Wednesday 9am
        start_weekend_testing("next_friday", "14:00")  # Next Friday 2pm
        start_weekend_testing("2025-01-08", "09:30")  # Specific date/time
    """
    print("\n" + "="*70)
    print("🧪 WEEKEND TESTING FRAMEWORK")
    print("="*70)
    
    # Start session
    session_name = weekend_testing.start_test_session(f"Weekend_Testing_{target_day}_{target_time}")
    
    # Simulate time
    simulated_time = weekend_testing.simulate_market_time(target_day, target_time)
    
    if simulated_time:
        # Patch datetime globally
        weekend_testing.patch_datetime_globally()
        
        print("✅ Weekend testing framework ready!")
        print("✅ All strategy files will use simulated time")
        print("✅ Market analysis will behave as if it's a trading day")
        print("="*70)
        return True
    else:
        print("❌ Failed to start weekend testing")
        return False

def stop_weekend_testing():
    """Stop weekend testing and restore normal operation"""
    weekend_testing.restore_original_time()
    
    # Save session
    filename = weekend_testing.save_test_session()
    
    # Show summary
    summary = weekend_testing.get_test_session_summary()
    
    print("\n" + "="*70)
    print("🏁 WEEKEND TESTING SESSION ENDED")
    print("="*70)
    print(f"📊 Session: {summary.get('session_name', 'Unknown')}")
    print(f"⏱️  Duration: {summary.get('duration_minutes', 0):.1f} minutes")
    print(f"🎯 Strategies Tested: {summary.get('strategies_tested', 0)}")
    if filename:
        print(f"💾 Results Saved: {filename}")
    print("✅ Back to real-time operation")
    print("="*70)

def test_strategy_with_override(strategy_file: str, mode: str = "scan"):
    """Test a specific strategy with time override"""
    return weekend_testing.test_strategy(strategy_file, mode)

def quick_wednesday_9am():
    """Quick setup for Wednesday 9am testing"""
    return start_weekend_testing("next_wednesday", "09:00")

def quick_friday_2pm():
    """Quick setup for Friday 2pm testing"""
    return start_weekend_testing("next_friday", "14:00")

def quick_tuesday_london_open():
    """Quick setup for Tuesday London market open"""
    return start_weekend_testing("2025-01-07", "08:00")

# Integration helper for existing strategy files
def add_weekend_testing_to_strategy(strategy_file_path: str):
    """
    Add weekend testing support to an existing strategy file
    
    This will insert the necessary imports and testing checks
    """
    integration_code = f'''
# Add this to the top of {strategy_file_path}:

import sys
import os

# Try to import weekend testing framework
try:
    from weekend_testing_framework import weekend_testing
    WEEKEND_TESTING_AVAILABLE = True
except ImportError:
    WEEKEND_TESTING_AVAILABLE = False
    print("⚠️ Weekend testing framework not available")

# In your main() function, add this option:
def main():
    # ... your existing code ...
    
    if WEEKEND_TESTING_AVAILABLE:
        test_choice = input("🧪 Enable weekend testing? (y/N): ").strip().lower()
        if test_choice == 'y':
            time_choice = input("Time (1=Wed 9am, 2=Fri 2pm, 3=Custom): ").strip()
            
            if time_choice == "1":
                quick_wednesday_9am()
            elif time_choice == "2": 
                quick_friday_2pm()
            elif time_choice == "3":
                date = input("Date (next_wednesday/2025-01-08): ") or "next_wednesday"
                time = input("Time (09:00): ") or "09:00"
                start_weekend_testing(date, time)
            else:
                quick_wednesday_9am()  # Default
    
    # ... rest of your main() function ...
'''
    
    return integration_code

if __name__ == "__main__":
    # Demo the weekend testing framework
    print("🧪 Weekend Testing Framework Demo")
    print("="*50)
    
    # Test different scenarios
    scenarios = [
        ("next_wednesday", "09:00", "Wednesday morning high liquidity"),
        ("next_friday", "14:00", "Friday afternoon before close"),
        ("2025-01-07", "08:00", "Tuesday London market open")
    ]
    
    for date, time, description in scenarios:
        print(f"\n📅 Testing: {description}")
        weekend_testing.simulate_market_time(date, time)
        print(f"   Simulated time: {weekend_testing.get_simulated_time()}")
        print(f"   Session info: {weekend_testing._get_simulated_session()}")
        weekend_testing.restore_original_time()
    
    print("\n✅ Weekend Testing Framework ready for use!")
    print("\nUsage:")
    print("from weekend_testing_framework import start_weekend_testing, stop_weekend_testing")
    print("start_weekend_testing()  # Start testing with Wednesday 9am")
    print("# ... run your strategies ...")
    print("stop_weekend_testing()   # Stop and save results")