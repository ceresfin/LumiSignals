#!/usr/bin/env python3
"""
Test script to check H1 data in Redis and diagnose the issue
"""

import redis
import json
import sys

# Redis connection details (from Lambda function)
redis_nodes = [
    "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
    "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
    "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
]

# Currency pair to shard mapping (from Lambda)
shard_mapping = {
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

def check_h1_data(currency_pair="EUR_USD"):
    """Check H1 data for a specific currency pair"""
    print(f"\n=== Checking H1 data for {currency_pair} ===")
    
    # Get shard for this pair
    shard_index = shard_mapping.get(currency_pair, 0)
    node = redis_nodes[shard_index]
    host, port = node.split(':')
    
    print(f"Currency pair: {currency_pair}")
    print(f"Shard index: {shard_index}")
    print(f"Redis node: {node}")
    
    try:
        # Connect to Redis
        r = redis.Redis(
            host=host,
            port=int(port),
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        
        # Test connection
        r.ping()
        print("✓ Redis connection successful")
        
        # List all keys for this currency pair
        pattern = f"market_data:{currency_pair}:*"
        keys = r.keys(pattern)
        print(f"\nFound {len(keys)} keys matching pattern '{pattern}':")
        for key in sorted(keys):
            print(f"  - {key.decode()}")
        
        # Check H1 historical data
        h1_historical_key = f"market_data:{currency_pair}:H1:historical"
        h1_data = r.get(h1_historical_key)
        
        if h1_data:
            print(f"\n✓ Found H1 historical data in key: {h1_historical_key}")
            try:
                parsed_data = json.loads(h1_data.decode('utf-8'))
                
                # Check structure
                if isinstance(parsed_data, dict):
                    print(f"  Structure: Dict with keys: {list(parsed_data.keys())}")
                    if 'candles' in parsed_data:
                        candles = parsed_data['candles']
                        print(f"  Candles count: {len(candles)}")
                        if candles:
                            print(f"  First candle: {candles[0]}")
                            print(f"  Last candle: {candles[-1]}")
                            
                            # Check time range
                            first_time = candles[0].get('time', 'unknown')
                            last_time = candles[-1].get('time', 'unknown')
                            print(f"  Time range: {first_time} to {last_time}")
                    else:
                        print("  WARNING: No 'candles' key in data structure")
                        print(f"  Data sample: {str(parsed_data)[:200]}...")
                        
                elif isinstance(parsed_data, list):
                    print(f"  Structure: List with {len(parsed_data)} items")
                    if parsed_data:
                        print(f"  First item: {parsed_data[0]}")
                        print(f"  Last item: {parsed_data[-1]}")
                else:
                    print(f"  Structure: {type(parsed_data)}")
                    print(f"  Data: {str(parsed_data)[:200]}...")
                    
            except json.JSONDecodeError as e:
                print(f"  ERROR: Failed to parse JSON: {e}")
        else:
            print(f"\n✗ No H1 historical data found in key: {h1_historical_key}")
        
        # Check H1 current data
        h1_current_key = f"market_data:{currency_pair}:H1:current"
        h1_current = r.get(h1_current_key)
        
        if h1_current:
            print(f"\n✓ Found H1 current data in key: {h1_current_key}")
            try:
                current_data = json.loads(h1_current.decode('utf-8'))
                print(f"  Current candle: {current_data}")
            except json.JSONDecodeError as e:
                print(f"  ERROR: Failed to parse JSON: {e}")
        else:
            print(f"\n✗ No H1 current data found in key: {h1_current_key}")
        
        # Check M5 data for comparison
        m5_historical_key = f"market_data:{currency_pair}:M5:historical"
        m5_data = r.get(m5_historical_key)
        
        if m5_data:
            try:
                m5_parsed = json.loads(m5_data.decode('utf-8'))
                m5_count = len(m5_parsed) if isinstance(m5_parsed, list) else len(m5_parsed.get('candles', []))
                print(f"\n✓ Found M5 data: {m5_count} candles")
            except:
                print("\n✓ Found M5 data but failed to parse")
        else:
            print("\n✗ No M5 data found")
            
    except redis.ConnectionError as e:
        print(f"\n✗ Redis connection failed: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

def check_all_pairs():
    """Check H1 data for all currency pairs"""
    pairs_with_h1 = []
    pairs_without_h1 = []
    
    for pair in sorted(shard_mapping.keys()):
        shard_index = shard_mapping[pair]
        node = redis_nodes[shard_index]
        host, port = node.split(':')
        
        try:
            r = redis.Redis(host=host, port=int(port), decode_responses=False, socket_timeout=2)
            h1_key = f"market_data:{pair}:H1:historical"
            h1_data = r.get(h1_key)
            
            if h1_data:
                try:
                    parsed = json.loads(h1_data.decode('utf-8'))
                    candle_count = len(parsed.get('candles', [])) if isinstance(parsed, dict) else len(parsed)
                    pairs_with_h1.append((pair, candle_count))
                except:
                    pairs_with_h1.append((pair, "?"))
            else:
                pairs_without_h1.append(pair)
                
        except Exception as e:
            print(f"Error checking {pair}: {e}")
    
    print("\n=== H1 Data Summary ===")
    print(f"\nPairs WITH H1 data ({len(pairs_with_h1)}):")
    for pair, count in pairs_with_h1:
        print(f"  ✓ {pair}: {count} candles")
    
    print(f"\nPairs WITHOUT H1 data ({len(pairs_without_h1)}):")
    for pair in pairs_without_h1:
        print(f"  ✗ {pair}")
    
    print(f"\nTotal: {len(pairs_with_h1)}/{len(shard_mapping)} pairs have H1 data")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Check specific pair
        check_h1_data(sys.argv[1])
    else:
        # Check EUR_USD in detail
        check_h1_data("EUR_USD")
        
        # Then check all pairs
        print("\n" + "="*50)
        check_all_pairs()