#!/usr/bin/env python3
"""
Test DemoTradingBot initialization step by step
"""

import sys
import os
import traceback
sys.path.append('..')

def test_demo_bot_init():
    print("🧪 Testing DemoTradingBot initialization step by step...")
    
    # Import config
    try:
        from config.oanda_config import API_KEY, ACCOUNT_ID
        print("✅ Config imported")
    except:
        print("❌ Config import failed")
        return
    
    # Import classes
    try:
        from momentum_calculator import MarketAwareMomentumCalculator, ForexMarketSchedule
        from oanda_api import OandaAPI
        from psychological_levels_trader import EnhancedPennyCurveStrategy, PsychologicalLevelsDetector
        from metadata_storage import TradeMetadataStore, TradeMetadata
        print("✅ All classes imported")
    except Exception as e:
        print(f"❌ Class import failed: {e}")
        return
    
    print("\n🔧 Testing DemoTradingBot initialization components...")
    
    # Test step 1: API initialization
    print("1️⃣ Testing OandaAPI...")
    try:
        api = OandaAPI(API_KEY, ACCOUNT_ID, "practice")
        print("   ✅ OandaAPI created")
    except Exception as e:
        print(f"   ❌ OandaAPI failed: {e}")
        return
    
    # Test step 2: Momentum calculator
    print("2️⃣ Testing MarketAwareMomentumCalculator...")
    try:
        momentum_calc = MarketAwareMomentumCalculator(api)
        print("   ✅ MarketAwareMomentumCalculator created")
    except Exception as e:
        print(f"   ❌ MarketAwareMomentumCalculator failed: {e}")
        traceback.print_exc()
        return
    
    # Test step 3: Levels detector
    print("3️⃣ Testing PsychologicalLevelsDetector...")
    try:
        levels_detector = PsychologicalLevelsDetector()
        print("   ✅ PsychologicalLevelsDetector created")
    except Exception as e:
        print(f"   ❌ PsychologicalLevelsDetector failed: {e}")
        return
    
    # Test step 4: Strategy
    print("4️⃣ Testing EnhancedPennyCurveStrategy...")
    try:
        strategy = EnhancedPennyCurveStrategy(momentum_calc, levels_detector)
        print("   ✅ EnhancedPennyCurveStrategy created")
    except Exception as e:
        print(f"   ❌ EnhancedPennyCurveStrategy failed: {e}")
        return
    
    # Test step 5: Risk manager
    print("5️⃣ Testing FixedDollarRiskManager...")
    try:
        # Import the class from the main file
        import Demo_Trading_Penny_Curve_Strategy
        risk_manager = Demo_Trading_Penny_Curve_Strategy.FixedDollarRiskManager(api, 10.0)
        print("   ✅ FixedDollarRiskManager created")
    except Exception as e:
        print(f"   ❌ FixedDollarRiskManager failed: {e}")
        traceback.print_exc()
        return
    
    # Test step 6: Metadata store
    print("6️⃣ Testing TradeMetadataStore...")
    try:
        metadata_store = TradeMetadataStore()
        print("   ✅ TradeMetadataStore created")
    except Exception as e:
        print(f"   ❌ TradeMetadataStore failed: {e}")
        return
    
    # Test step 7: ForexMarketSchedule (likely culprit)
    print("7️⃣ Testing ForexMarketSchedule... (THIS MIGHT HANG)")
    try:
        market_schedule = ForexMarketSchedule()
        print("   ✅ ForexMarketSchedule created")
    except Exception as e:
        print(f"   ❌ ForexMarketSchedule failed: {e}")
        traceback.print_exc()
        return
    
    # Test step 8: Complete DemoTradingBot
    print("8️⃣ Testing complete DemoTradingBot initialization...")
    try:
        bot = Demo_Trading_Penny_Curve_Strategy.DemoTradingBot(max_risk_usd=10.0, max_open_trades=5)
        print("   ✅ DemoTradingBot created successfully!")
    except Exception as e:
        print(f"   ❌ DemoTradingBot initialization failed: {e}")
        traceback.print_exc()
        return
    
    print("\n🎉 All tests passed! The bot should work now.")

if __name__ == "__main__":
    try:
        test_demo_bot_init()
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted - this tells us where it hung!")
    except Exception as e:
        print(f"\n💥 Test crashed: {e}")
        traceback.print_exc()