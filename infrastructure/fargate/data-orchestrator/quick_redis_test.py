#!/usr/bin/env python3
"""
Quick Redis Verification Test - Run from ECS Task
This script verifies the tiered storage system has 500+ candles
"""

import redis
import json
import os
import boto3
from typing import Dict, List

def get_redis_auth():
    """Get Redis auth token from AWS Secrets Manager"""
    client = boto3.client('secretsmanager', region_name='us-east-1')
    response = client.get_secret_value(SecretId='lumisignals/redis/market-data/auth-token')
    return json.loads(response['SecretString'])

def test_tiered_storage():
    """Test the tiered storage system"""
    print("🔍 Testing Tiered Storage System")
    print("=" * 40)
    
    # Get Redis credentials
    try:
        redis_creds = get_redis_auth()
        auth_token = redis_creds['auth_token']
        print(f"✅ Redis auth token retrieved ({len(auth_token)} chars)")
    except Exception as e:
        print(f"❌ Failed to get Redis auth: {e}")
        return False
    
    # Test pairs and timeframes
    test_pairs = ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD']
    timeframes = ['M5', 'H1']
    
    # Connect to Redis nodes
    redis_nodes = [
        "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
        "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
        "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
        "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
    ]
    
    total_candles = 0
    success_count = 0
    
    for pair in test_pairs:
        for timeframe in timeframes:
            try:
                # Try each Redis node for this pair/timeframe
                found_data = False
                for node in redis_nodes:
                    try:
                        host, port = node.split(':')
                        r = redis.Redis(host=host, port=int(port), password=auth_token, 
                                      socket_timeout=5, socket_connect_timeout=5)
                        
                        # Check hot tier
                        hot_key = f"market_data:{pair}:{timeframe}:hot"
                        hot_data = r.get(hot_key)
                        
                        # Check warm tier  
                        warm_key = f"market_data:{pair}:{timeframe}:warm"
                        warm_data = r.get(warm_key)
                        
                        # Check cold/historical tier
                        cold_key = f"market_data:{pair}:{timeframe}:historical"
                        cold_data = r.get(cold_key)
                        
                        hot_count = len(json.loads(hot_data)) if hot_data else 0
                        warm_count = len(json.loads(warm_data)) if warm_data else 0
                        cold_count = len(json.loads(cold_data)) if cold_data else 0
                        
                        pair_total = hot_count + warm_count + cold_count
                        
                        if pair_total > 0:
                            print(f"✅ {pair} {timeframe}: {pair_total} candles (Hot:{hot_count}, Warm:{warm_count}, Cold:{cold_count})")
                            total_candles += pair_total
                            success_count += 1
                            found_data = True
                            break
                            
                    except Exception as node_error:
                        continue  # Try next node
                
                if not found_data:
                    print(f"❌ {pair} {timeframe}: No data found")
                    
            except Exception as e:
                print(f"❌ {pair} {timeframe}: Error - {e}")
    
    print("\n" + "=" * 40)
    print(f"📊 SUMMARY:")
    print(f"   Total candles found: {total_candles}")
    print(f"   Successful pair/timeframe combinations: {success_count}")
    print(f"   Expected: 500+ candles per major pair")
    
    if total_candles >= 2000:  # 4 pairs × 2 timeframes × ~250 candles minimum
        print("✅ TIERED STORAGE SYSTEM: WORKING")
        return True
    else:
        print("⚠️  TIERED STORAGE SYSTEM: MAY NEED INVESTIGATION")
        return False

if __name__ == "__main__":
    test_tiered_storage()