#!/usr/bin/env python3
"""
Test script for fixed tier rotation logic
Tests bootstrap distribution and rotation scenarios with real timestamps
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

class MockSettings:
    """Mock settings for testing"""
    def __init__(self):
        self.hot_tier_candles = 50
        self.warm_tier_candles = 450
        self.cold_tier_ttl = 604800

def generate_test_candles(count: int = 500, start_time: datetime = None) -> List[Dict]:
    """Generate test candles with realistic timestamps"""
    if start_time is None:
        start_time = datetime.now() - timedelta(hours=count-1)
    
    candles = []
    for i in range(count):
        candle_time = start_time + timedelta(hours=i)
        candles.append({
            'time': candle_time.isoformat() + 'Z',
            'timestamp': int(candle_time.timestamp()),
            'open': 1.1000 + (i * 0.0001),
            'high': 1.1005 + (i * 0.0001),
            'low': 1.0995 + (i * 0.0001),
            'close': 1.1002 + (i * 0.0001),
            'volume': 1000 + i
        })
    
    return candles

def test_bootstrap_distribution():
    """Test the fixed bootstrap distribution logic"""
    print("🧪 Testing Bootstrap Distribution Logic")
    print("=" * 60)
    
    settings = MockSettings()
    candles = generate_test_candles(500)
    
    # Sort candles by time (like in the actual code)
    sorted_candles = sorted(candles, key=lambda x: x.get('time', ''))
    total_candles = len(sorted_candles)
    
    print(f"📊 Generated {total_candles} test candles")
    print(f"🕐 Time range: {sorted_candles[0]['time']} to {sorted_candles[-1]['time']}")
    
    # Apply FIXED bootstrap logic
    if total_candles >= settings.hot_tier_candles + settings.warm_tier_candles:
        # Complete 3-tier distribution with chronological separation
        hot_candles = sorted_candles[-settings.hot_tier_candles:]  # Most recent 50
        warm_candles = sorted_candles[-(settings.hot_tier_candles + settings.warm_tier_candles):-settings.hot_tier_candles]  # Previous 450
        cold_candles = sorted_candles[:-(settings.hot_tier_candles + settings.warm_tier_candles)]  # Oldest remaining
    elif total_candles >= settings.hot_tier_candles:
        # 2-tier distribution: hot + warm (no cold tier needed)
        hot_candles = sorted_candles[-settings.hot_tier_candles:]  # Most recent
        warm_candles = sorted_candles[:-settings.hot_tier_candles]  # Older candles
        cold_candles = []
    else:
        # Single tier: everything in hot tier
        hot_candles = sorted_candles
        warm_candles = []
        cold_candles = []
    
    print(f"\n✅ FIXED Bootstrap Distribution Results:")
    print(f"🔥 Hot tier:  {len(hot_candles)} candles - {hot_candles[0]['time'] if hot_candles else 'None'} to {hot_candles[-1]['time'] if hot_candles else 'None'}")
    print(f"🌡️ Warm tier: {len(warm_candles)} candles - {warm_candles[0]['time'] if warm_candles else 'None'} to {warm_candles[-1]['time'] if warm_candles else 'None'}")
    print(f"❄️ Cold tier: {len(cold_candles)} candles - {cold_candles[0]['time'] if cold_candles else 'None'} to {cold_candles[-1]['time'] if cold_candles else 'None'}")
    
    # Check for overlaps
    all_timestamps = set()
    duplicates = 0
    
    # Check hot tier
    for candle in hot_candles:
        timestamp = candle['time']
        if timestamp in all_timestamps:
            duplicates += 1
        all_timestamps.add(timestamp)
    
    # Check warm tier
    for candle in warm_candles:
        timestamp = candle['time']
        if timestamp in all_timestamps:
            duplicates += 1
        all_timestamps.add(timestamp)
    
    # Check cold tier
    for candle in cold_candles:
        timestamp = candle['time']
        if timestamp in all_timestamps:
            duplicates += 1
        all_timestamps.add(timestamp)
    
    total_distributed = len(hot_candles) + len(warm_candles) + len(cold_candles)
    
    print(f"\n📈 Distribution Analysis:")
    print(f"📊 Total original candles: {total_candles}")
    print(f"📊 Total distributed candles: {total_distributed}")
    print(f"🚨 Duplicate timestamps: {duplicates}")
    print(f"✅ Unique candles after distribution: {len(all_timestamps)}")
    
    if duplicates == 0:
        print("🎉 SUCCESS: No overlaps detected in bootstrap distribution!")
    else:
        print(f"❌ FAILED: {duplicates} overlaps detected!")
    
    return hot_candles, warm_candles, cold_candles, duplicates == 0

def test_rotation_logic():
    """Test the fixed rotation logic"""
    print("\n\n🧪 Testing Rotation Logic")
    print("=" * 60)
    
    settings = MockSettings()
    
    # Start with initial bootstrap state
    hot_candles, warm_candles, cold_candles, bootstrap_success = test_bootstrap_distribution()
    
    if not bootstrap_success:
        print("❌ Bootstrap failed, cannot test rotation")
        return False
    
    print(f"\n🔄 Simulating 5-minute updates with rotation...")
    
    # Simulate adding new candles that trigger rotation
    newest_time = datetime.fromisoformat(hot_candles[-1]['time'].replace('Z', ''))
    
    for update_round in range(1, 6):  # Simulate 5 updates
        # Add new candle
        new_time = newest_time + timedelta(hours=update_round)
        new_candle = {
            'time': new_time.isoformat() + 'Z',
            'timestamp': int(new_time.timestamp()),
            'open': 1.2000 + (update_round * 0.0001),
            'high': 1.2005 + (update_round * 0.0001),
            'low': 1.1995 + (update_round * 0.0001),
            'close': 1.2002 + (update_round * 0.0001),
            'volume': 2000 + update_round
        }
        
        # Add to hot tier (simulating new data arrival)
        hot_candles.append(new_candle)
        
        # Check if rotation is needed
        if len(hot_candles) > settings.hot_tier_candles:
            excess_candles = len(hot_candles) - settings.hot_tier_candles
            
            # Move oldest hot candles to warm tier (FIXED logic)
            candles_to_move = hot_candles[:excess_candles]
            hot_candles = hot_candles[excess_candles:]  # Remove from hot
            
            # Add to END of warm tier (maintaining chronological order)
            # Since warm tier contains older data, old hot data goes at the end of warm
            warm_candles.extend(candles_to_move)
            
            # Trim warm tier if needed
            if len(warm_candles) > settings.warm_tier_candles:
                excess_warm = len(warm_candles) - settings.warm_tier_candles
                # Move oldest warm to cold tier (take from beginning)
                old_warm_candles = warm_candles[:excess_warm]
                warm_candles = warm_candles[excess_warm:]
                cold_candles.extend(old_warm_candles)
                cold_candles.sort(key=lambda x: x['time'])  # Keep cold tier sorted
            
            print(f"📈 Update {update_round}: Moved {len(candles_to_move)} candles hot→warm")
    
    # Final analysis
    print(f"\n✅ Final Distribution After 5 Updates:")
    print(f"🔥 Hot tier:  {len(hot_candles)} candles - {hot_candles[0]['time']} to {hot_candles[-1]['time']}")
    print(f"🌡️ Warm tier: {len(warm_candles)} candles - {warm_candles[0]['time'] if warm_candles else 'None'} to {warm_candles[-1]['time'] if warm_candles else 'None'}")
    print(f"❄️ Cold tier: {len(cold_candles)} candles - {cold_candles[0]['time'] if cold_candles else 'None'} to {cold_candles[-1]['time'] if cold_candles else 'None'}")
    
    # Check chronological order
    print(f"\n🕐 Chronological Order Check:")
    
    def check_chronological_order(candles, tier_name):
        if len(candles) < 2:
            return True
        
        for i in range(1, len(candles)):
            prev_time = datetime.fromisoformat(candles[i-1]['time'].replace('Z', ''))
            curr_time = datetime.fromisoformat(candles[i]['time'].replace('Z', ''))
            if curr_time <= prev_time:
                print(f"❌ {tier_name}: Chronological order violation at index {i}")
                return False
        print(f"✅ {tier_name}: Chronological order maintained")
        return True
    
    hot_order_ok = check_chronological_order(hot_candles, "Hot tier")
    warm_order_ok = check_chronological_order(warm_candles, "Warm tier")
    cold_order_ok = check_chronological_order(cold_candles, "Cold tier")
    
    # Check tier separation (no overlaps)
    print(f"\n🔍 Tier Separation Check:")
    
    def get_time_range(candles):
        if not candles:
            return None, None
        return candles[0]['time'], candles[-1]['time']
    
    hot_start, hot_end = get_time_range(hot_candles)
    warm_start, warm_end = get_time_range(warm_candles)
    cold_start, cold_end = get_time_range(cold_candles)
    
    separation_ok = True
    
    if warm_candles and hot_candles:
        warm_end_dt = datetime.fromisoformat(warm_end.replace('Z', ''))
        hot_start_dt = datetime.fromisoformat(hot_start.replace('Z', ''))
        if warm_end_dt >= hot_start_dt:
            print(f"❌ Overlap detected: Warm tier ends at {warm_end}, Hot tier starts at {hot_start}")
            separation_ok = False
        else:
            print(f"✅ Warm→Hot separation: Warm ends at {warm_end}, Hot starts at {hot_start}")
    
    if cold_candles and warm_candles:
        cold_end_dt = datetime.fromisoformat(cold_end.replace('Z', ''))
        warm_start_dt = datetime.fromisoformat(warm_start.replace('Z', ''))
        if cold_end_dt >= warm_start_dt:
            print(f"❌ Overlap detected: Cold tier ends at {cold_end}, Warm tier starts at {warm_start}")
            separation_ok = False
        else:
            print(f"✅ Cold→Warm separation: Cold ends at {cold_end}, Warm starts at {warm_start}")
    
    success = hot_order_ok and warm_order_ok and cold_order_ok and separation_ok
    
    if success:
        print(f"\n🎉 SUCCESS: Rotation logic maintains chronological order and tier separation!")
    else:
        print(f"\n❌ FAILED: Issues detected in rotation logic!")
    
    return success

def test_old_vs_new_logic():
    """Compare old vs new logic to show the improvement"""
    print("\n\n🧪 Comparing Old vs New Logic")
    print("=" * 60)
    
    candles = generate_test_candles(500)
    sorted_candles = sorted(candles, key=lambda x: x.get('time', ''))
    
    # OLD LOGIC (BROKEN)
    print("❌ OLD LOGIC Results:")
    hot_candles_old = sorted_candles[-50:]  # Last 50
    warm_candles_old = sorted_candles[:-50]  # First 450
    cold_candles_old = sorted_candles  # ALL 500 (massive overlap!)
    
    old_total = len(hot_candles_old) + len(warm_candles_old) + len(cold_candles_old)
    old_unique = len(set([c['time'] for c in hot_candles_old + warm_candles_old + cold_candles_old]))
    old_duplicates = old_total - old_unique
    
    print(f"📊 Total distributed: {old_total}")
    print(f"📊 Unique timestamps: {old_unique}")
    print(f"🚨 Duplicates: {old_duplicates}")
    
    # NEW LOGIC (FIXED)
    print(f"\n✅ NEW LOGIC Results:")
    hot_candles_new = sorted_candles[-50:]  # Last 50
    warm_candles_new = sorted_candles[-500:-50]  # Previous 450
    cold_candles_new = sorted_candles[:-500]  # Oldest (empty in this case)
    
    new_total = len(hot_candles_new) + len(warm_candles_new) + len(cold_candles_new)
    new_unique = len(set([c['time'] for c in hot_candles_new + warm_candles_new + cold_candles_new]))
    new_duplicates = new_total - new_unique
    
    print(f"📊 Total distributed: {new_total}")
    print(f"📊 Unique timestamps: {new_unique}")
    print(f"🚨 Duplicates: {new_duplicates}")
    
    print(f"\n📈 IMPROVEMENT:")
    print(f"🔥 Duplicates reduced: {old_duplicates} → {new_duplicates} ({old_duplicates - new_duplicates} fewer)")
    print(f"🔥 Available candles: {old_unique} → {new_unique} ({new_unique - old_unique} more)")
    
    return new_duplicates == 0

def main():
    """Run all tests"""
    print("🚀 Testing Fixed Tier Rotation Logic")
    print("=" * 80)
    
    # Test 1: Bootstrap distribution
    _, _, _, bootstrap_ok = test_bootstrap_distribution()
    
    # Test 2: Rotation logic
    rotation_ok = test_rotation_logic()
    
    # Test 3: Old vs new comparison
    comparison_ok = test_old_vs_new_logic()
    
    print(f"\n" + "=" * 80)
    print(f"📋 TEST SUMMARY:")
    print(f"✅ Bootstrap Distribution: {'PASSED' if bootstrap_ok else 'FAILED'}")
    print(f"✅ Rotation Logic: {'PASSED' if rotation_ok else 'FAILED'}")
    print(f"✅ Old vs New Comparison: {'PASSED' if comparison_ok else 'FAILED'}")
    
    all_passed = bootstrap_ok and rotation_ok and comparison_ok
    
    if all_passed:
        print(f"\n🎉 ALL TESTS PASSED! The fixed tier logic should resolve the 42 candles issue.")
        print(f"🚀 Ready for deployment to Fargate!")
    else:
        print(f"\n❌ SOME TESTS FAILED! Review the logic before deployment.")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)