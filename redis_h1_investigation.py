#!/usr/bin/env python3
"""
Redis H1 Data Investigation Script
Investigates the H1 candlestick data issue for the dashboard
"""

import redis
import json
from datetime import datetime
from typing import Dict, List, Any

class RedisH1Investigation:
    """Investigate Redis H1 data structure and availability"""
    
    def __init__(self):
        # Redis cluster configuration (same as Lambda function)
        self.redis_nodes = [
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ]
        
        # Currency pair to shard mapping (same as Lambda function)
        self.shard_mapping = {
            # Shard 0: Major USD pairs
            "EUR_USD": 0, "GBP_USD": 0, "USD_JPY": 0, "USD_CAD": 0, 
            "AUD_USD": 0, "NZD_USD": 0, "USD_CHF": 0,
            
            # Shard 1: EUR cross pairs + GBP_JPY
            "EUR_GBP": 1, "EUR_JPY": 1, "EUR_CAD": 1, "EUR_AUD": 1, 
            "EUR_NZD": 1, "EUR_CHF": 1, "GBP_JPY": 1,
            
            # Shard 2: GBP and AUD cross pairs
            "GBP_CAD": 2, "GBP_AUD": 2, "GBP_NZD": 2, "GBP_CHF": 2,
            "AUD_JPY": 2, "AUD_CAD": 2, "AUD_NZD": 2,
            
            # Shard 3: Remaining cross pairs
            "AUD_CHF": 3, "NZD_JPY": 3, "NZD_CAD": 3, "NZD_CHF": 3,
            "CAD_JPY": 3, "CAD_CHF": 3, "CHF_JPY": 3
        }
        
        # Initialize Redis connections
        self.redis_connections = {}
        self._connect_to_redis()
    
    def _connect_to_redis(self):
        """Initialize Redis connections to all shards"""
        for i, node in enumerate(self.redis_nodes):
            try:
                host, port = node.split(':')
                self.redis_connections[i] = redis.Redis(
                    host=host,
                    port=int(port),
                    decode_responses=False,  # Keep as bytes for JSON parsing
                    socket_connect_timeout=30,
                    socket_timeout=30,
                    retry_on_timeout=True,
                    health_check_interval=30
                )
                print(f"✅ Connected to Redis shard {i}: {node}")
            except Exception as e:
                print(f"❌ Failed to connect to Redis shard {i}: {e}")
    
    def get_shard_for_pair(self, currency_pair: str) -> int:
        """Get Redis shard index for currency pair"""
        return self.shard_mapping.get(currency_pair, 0)
    
    def investigate_currency_pair(self, currency_pair: str):
        """Investigate Redis data for a specific currency pair"""
        print(f"\n🔍 Investigating {currency_pair}...")
        
        # Get appropriate Redis connection
        shard_index = self.get_shard_for_pair(currency_pair)
        redis_conn = self.redis_connections.get(shard_index)
        
        if not redis_conn:
            print(f"❌ No Redis connection for shard {shard_index}")
            return
        
        print(f"📡 Using Redis shard {shard_index}")
        
        # Test connection
        try:
            redis_conn.ping()
            print("✅ Redis connection healthy")
        except Exception as e:
            print(f"❌ Redis connection failed: {e}")
            return
        
        # List all keys for this currency pair
        try:
            pattern = f"*{currency_pair}*"
            all_keys = redis_conn.keys(pattern)
            print(f"🔑 Found {len(all_keys)} keys matching pattern '{pattern}':")
            
            for key in all_keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                print(f"   - {key_str}")
                
                # Get key info
                try:
                    ttl = redis_conn.ttl(key)
                    key_type = redis_conn.type(key).decode()
                    print(f"     Type: {key_type}, TTL: {ttl} seconds")
                    
                    # If it's a string key, check its size
                    if key_type == 'string':
                        size = redis_conn.strlen(key)
                        print(f"     Size: {size} bytes")
                        
                        # Try to parse JSON and show sample
                        try:
                            data = redis_conn.get(key)
                            if data:
                                parsed = json.loads(data.decode('utf-8'))
                                if isinstance(parsed, dict):
                                    if 'candles' in parsed:
                                        candle_count = len(parsed['candles'])
                                        print(f"     Contains {candle_count} candles")
                                        
                                        # Show date range if candles exist
                                        if candle_count > 0:
                                            first_candle = parsed['candles'][0]
                                            last_candle = parsed['candles'][-1]
                                            first_time = first_candle.get('time', 'unknown')
                                            last_time = last_candle.get('time', 'unknown')
                                            print(f"     Date range: {first_time} to {last_time}")
                                    else:
                                        print(f"     Data keys: {list(parsed.keys())}")
                                elif isinstance(parsed, list):
                                    print(f"     List with {len(parsed)} items")
                                    if len(parsed) > 0:
                                        first_item = parsed[0]
                                        if isinstance(first_item, dict) and 'time' in first_item:
                                            print(f"     First item time: {first_item.get('time')}")
                        except json.JSONDecodeError as e:
                            print(f"     ⚠️ Invalid JSON: {e}")
                        except Exception as e:
                            print(f"     ⚠️ Error reading data: {e}")
                            
                except Exception as e:
                    print(f"     ⚠️ Error getting key info: {e}")
                    
        except Exception as e:
            print(f"❌ Error listing keys: {e}")
        
        # Specifically check for H1 data keys
        h1_keys = [
            f"market_data:{currency_pair}:H1:historical",
            f"market_data:{currency_pair}:H1:current",
            f"candlestick:{currency_pair}:H1",
            f"ohlc:{currency_pair}:H1",
        ]
        
        print(f"\n🎯 Checking specific H1 data keys:")
        for key in h1_keys:
            try:
                exists = redis_conn.exists(key)
                if exists:
                    print(f"✅ {key} exists")
                    
                    # Get detailed info
                    data = redis_conn.get(key)
                    if data:
                        try:
                            parsed = json.loads(data.decode('utf-8'))
                            if isinstance(parsed, dict) and 'candles' in parsed:
                                candle_count = len(parsed['candles'])
                                print(f"   📊 Contains {candle_count} H1 candles")
                                
                                # Show recent candles
                                if candle_count > 0:
                                    recent_candles = parsed['candles'][-3:]  # Last 3 candles
                                    print("   🕐 Recent candles:")
                                    for candle in recent_candles:
                                        time_str = candle.get('time', 'unknown')
                                        close_price = candle.get('close', 'unknown')
                                        print(f"      {time_str}: Close = {close_price}")
                            elif isinstance(parsed, list):
                                print(f"   📊 List format with {len(parsed)} items")
                            else:
                                print(f"   📊 Data format: {type(parsed)}")
                        except Exception as e:
                            print(f"   ⚠️ Error parsing data: {e}")
                else:
                    print(f"❌ {key} does not exist")
            except Exception as e:
                print(f"❌ Error checking {key}: {e}")
        
        # Check for M5 data that could be aggregated to H1
        print(f"\n🔄 Checking M5 data for potential H1 aggregation:")
        m5_keys = [
            f"market_data:{currency_pair}:M5:historical",
            f"market_data:{currency_pair}:M5:current",
        ]
        
        for key in m5_keys:
            try:
                exists = redis_conn.exists(key)
                if exists:
                    print(f"✅ {key} exists")
                    
                    data = redis_conn.get(key)
                    if data:
                        try:
                            parsed = json.loads(data.decode('utf-8'))
                            if isinstance(parsed, dict) and 'candles' in parsed:
                                candle_count = len(parsed['candles'])
                                print(f"   📊 Contains {candle_count} M5 candles")
                                
                                # Show time range
                                if candle_count > 0:
                                    first_candle = parsed['candles'][0]
                                    last_candle = parsed['candles'][-1]
                                    first_time = first_candle.get('time', 'unknown')
                                    last_time = last_candle.get('time', 'unknown')
                                    print(f"   📅 M5 range: {first_time} to {last_time}")
                                    
                                    # Estimate H1 candles that could be created
                                    estimated_h1 = candle_count // 12  # 12 M5 candles per H1
                                    print(f"   🔢 Could create ~{estimated_h1} H1 candles from M5 data")
                        except Exception as e:
                            print(f"   ⚠️ Error parsing M5 data: {e}")
                else:
                    print(f"❌ {key} does not exist")
            except Exception as e:
                print(f"❌ Error checking M5 key {key}: {e}")

    def investigate_all_major_pairs(self):
        """Investigate all major currency pairs"""
        major_pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF"]
        
        print("🌍 Investigating all major currency pairs for H1 data...")
        
        for pair in major_pairs:
            self.investigate_currency_pair(pair)
            print("\n" + "="*80)

def main():
    """Main investigation function"""
    print("🔍 Redis H1 Data Investigation Starting...")
    print(f"🕐 Timestamp: {datetime.now().isoformat()}")
    
    investigator = RedisH1Investigation()
    
    # Test a specific pair first
    print("\n" + "="*80)
    investigator.investigate_currency_pair("EUR_USD")
    
    # Ask if user wants to investigate all pairs
    print("\n" + "="*80)
    response = input("Do you want to investigate all major pairs? (y/n): ").lower()
    if response == 'y':
        investigator.investigate_all_major_pairs()
    
    print("\n🎯 Investigation completed!")
    print("\nKey findings to look for:")
    print("1. Do H1 keys exist?")
    print("2. How many H1 candles are stored?")
    print("3. What's the date range of H1 data?")
    print("4. Is M5 data available for aggregation?")
    print("5. Are the timestamps recent or old (like 9/8)?")

if __name__ == "__main__":
    main()