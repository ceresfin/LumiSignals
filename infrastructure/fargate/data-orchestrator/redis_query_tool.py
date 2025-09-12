#!/usr/bin/env python3
"""
Redis Query Tool - Quick Commands for Redis Cluster

This tool provides quick commands to query the Redis tiered storage system:
- List all keys for a currency pair
- Count candles in each tier
- Get sample candle data
- Check TTL settings
- Verify shard distribution

Usage:
    python redis_query_tool.py --pair EUR_USD --timeframe M5
    python redis_query_tool.py --list-all-pairs
    python redis_query_tool.py --shard-info
"""

import argparse
import json
import redis
import boto3
from typing import Dict, List, Any
import sys
import os

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from config import Settings
except ImportError as e:
    print(f"❌ Failed to import Settings: {e}")
    sys.exit(1)


class RedisQueryTool:
    """Quick Redis query tool for debugging and verification"""
    
    def __init__(self):
        self.settings = Settings()
        self.redis_clients = {}
        self.setup_connections()
    
    def get_redis_auth_token(self) -> str:
        """Get Redis auth token from AWS Secrets Manager"""
        try:
            session = boto3.Session(region_name=self.settings.aws_region)
            secrets_client = session.client('secretsmanager')
            
            response = secrets_client.get_secret_value(SecretId='prod/redis/credentials')
            redis_creds = json.loads(response['SecretString'])
            return redis_creds.get('auth_token', '')
        except Exception as e:
            print(f"⚠️ Could not retrieve auth token: {e}")
            return ""
    
    def setup_connections(self):
        """Setup Redis connections"""
        auth_token = self.get_redis_auth_token()
        
        for i, node_endpoint in enumerate(self.settings.redis_cluster_nodes):
            shard_name = f"shard_{i}"
            
            try:
                host, port = node_endpoint.split(':')
                port = int(port)
                
                client_config = {
                    'host': host,
                    'port': port,
                    'decode_responses': True,
                    'socket_timeout': 5,
                    'socket_connect_timeout': 5
                }
                
                if auth_token:
                    client_config['password'] = auth_token
                
                client = redis.Redis(**client_config)
                client.ping()  # Test connection
                self.redis_clients[shard_name] = client
                print(f"✓ Connected to {shard_name}")
                
            except Exception as e:
                print(f"❌ Failed to connect to {shard_name}: {e}")
    
    def get_client_for_pair(self, currency_pair: str) -> redis.Redis:
        """Get Redis client for currency pair"""
        shard_index = self.settings.get_redis_node_for_pair(currency_pair)
        shard_name = f"shard_{shard_index}"
        
        if shard_name not in self.redis_clients:
            raise Exception(f"No connection to {shard_name} for pair {currency_pair}")
        
        return self.redis_clients[shard_name]
    
    def query_pair_data(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Query all tier data for a currency pair"""
        try:
            client = self.get_client_for_pair(currency_pair)
            shard_index = self.settings.get_redis_node_for_pair(currency_pair)
            keys = self.settings.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            result = {
                'pair': currency_pair,
                'timeframe': timeframe,
                'shard': f"shard_{shard_index}",
                'tiers': {}
            }
            
            total_candles = 0
            
            for tier_name, key in keys.items():
                if tier_name in ['hot', 'warm', 'cold', 'current']:
                    exists = client.exists(key)
                    
                    if exists:
                        data_type = client.type(key)
                        ttl = client.ttl(key)
                        
                        if data_type == 'list':
                            count = client.llen(key)
                            total_candles += count
                            
                            # Get latest candle as sample
                            latest = client.lindex(key, 0)
                            sample_data = json.loads(latest) if latest else None
                            
                            result['tiers'][tier_name] = {
                                'exists': True,
                                'type': data_type,
                                'count': count,
                                'ttl': ttl,
                                'key': key,
                                'latest_candle': sample_data
                            }
                        else:
                            result['tiers'][tier_name] = {
                                'exists': True,
                                'type': data_type,
                                'ttl': ttl,
                                'key': key
                            }
                    else:
                        result['tiers'][tier_name] = {
                            'exists': False,
                            'key': key
                        }
            
            result['total_candles'] = total_candles
            return result
            
        except Exception as e:
            return {'error': str(e), 'pair': currency_pair, 'timeframe': timeframe}
    
    def list_all_pairs_data(self) -> Dict[str, Any]:
        """List data for all configured currency pairs"""
        results = {}
        
        print(f"📊 Scanning {len(self.settings.currency_pairs)} currency pairs...")
        
        for pair in self.settings.currency_pairs:
            try:
                pair_data = self.query_pair_data(pair, "M5")
                results[pair] = pair_data
                
                total = pair_data.get('total_candles', 0)
                shard = pair_data.get('shard', 'unknown')
                print(f"  {pair}: {total} candles ({shard})")
                
            except Exception as e:
                results[pair] = {'error': str(e)}
                print(f"  {pair}: ERROR - {e}")
        
        return results
    
    def show_shard_info(self):
        """Show shard configuration and connectivity"""
        print("\n🔗 SHARD CONFIGURATION")
        print("="*50)
        
        for shard_name, pairs in self.settings.shard_configuration.items():
            shard_index = int(shard_name.split("_")[1])
            endpoint = self.settings.redis_cluster_nodes[shard_index]
            connected = shard_name in self.redis_clients
            
            status_icon = "✓" if connected else "❌"
            print(f"\n{status_icon} {shard_name.upper()}")
            print(f"  Endpoint: {endpoint}")
            print(f"  Status: {'Connected' if connected else 'Disconnected'}")
            print(f"  Currency Pairs ({len(pairs)}):")
            
            for pair in pairs:
                print(f"    - {pair}")
    
    def get_key_patterns(self, pattern: str = "*") -> Dict[str, List[str]]:
        """Get keys matching pattern from all shards"""
        all_keys = {}
        
        for shard_name, client in self.redis_clients.items():
            try:
                keys = client.keys(pattern)
                all_keys[shard_name] = keys
                print(f"{shard_name}: {len(keys)} keys matching '{pattern}'")
            except Exception as e:
                print(f"❌ Error scanning {shard_name}: {e}")
        
        return all_keys
    
    def show_tier_distribution(self):
        """Show distribution of data across tiers"""
        print("\n📊 TIER DISTRIBUTION ANALYSIS")
        print("="*60)
        
        tier_totals = {'hot': 0, 'warm': 0, 'cold': 0, 'current': 0}
        pair_count = 0
        
        for pair in ['EUR_USD', 'GBP_USD', 'USD_JPY', 'USD_CAD']:  # Sample major pairs
            try:
                data = self.query_pair_data(pair, 'M5')
                if 'error' not in data:
                    pair_count += 1
                    print(f"\n💱 {pair} (M5) - Shard: {data.get('shard', 'unknown')}")
                    
                    for tier_name, tier_info in data.get('tiers', {}).items():
                        if tier_info.get('exists') and tier_name in tier_totals:
                            count = tier_info.get('count', 0)
                            ttl = tier_info.get('ttl', 'N/A')
                            tier_totals[tier_name] += count
                            
                            print(f"  {tier_name.upper()}: {count:,} candles (TTL: {ttl}s)")
                            
                            # Show sample candle if available
                            if 'latest_candle' in tier_info and tier_info['latest_candle']:
                                candle = tier_info['latest_candle']
                                timestamp = candle.get('timestamp', 'N/A')
                                price = candle.get('close', 'N/A')
                                print(f"    Latest: {timestamp} @ {price}")
                        else:
                            print(f"  {tier_name.upper()}: No data")
                    
                    total = data.get('total_candles', 0)
                    target_status = "✓" if total >= 500 else "⚠️"
                    print(f"  TOTAL: {total:,} candles {target_status}")
                    
            except Exception as e:
                print(f"❌ Error analyzing {pair}: {e}")
        
        # Summary
        print(f"\n📈 SUMMARY")
        print(f"Pairs Analyzed: {pair_count}")
        print(f"Total Distribution:")
        for tier, total in tier_totals.items():
            if total > 0:
                print(f"  {tier.upper()}: {total:,} candles")


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(description='Redis Query Tool for Tiered Storage')
    
    parser.add_argument('--pair', type=str, help='Currency pair to query (e.g., EUR_USD)')
    parser.add_argument('--timeframe', type=str, default='M5', help='Timeframe (default: M5)')
    parser.add_argument('--list-all-pairs', action='store_true', help='List data for all pairs')
    parser.add_argument('--shard-info', action='store_true', help='Show shard configuration')
    parser.add_argument('--keys', type=str, help='List keys matching pattern')
    parser.add_argument('--tier-distribution', action='store_true', help='Show tier distribution')
    
    args = parser.parse_args()
    
    # Initialize tool
    tool = RedisQueryTool()
    
    if not tool.redis_clients:
        print("❌ No Redis connections available. Exiting.")
        sys.exit(1)
    
    # Execute requested operation
    if args.pair:
        print(f"\n🔍 Querying {args.pair} {args.timeframe}...")
        result = tool.query_pair_data(args.pair, args.timeframe)
        print(json.dumps(result, indent=2, default=str))
        
    elif args.list_all_pairs:
        tool.list_all_pairs_data()
        
    elif args.shard_info:
        tool.show_shard_info()
        
    elif args.keys:
        keys = tool.get_key_patterns(args.keys)
        for shard, key_list in keys.items():
            print(f"\n{shard}:")
            for key in key_list[:20]:  # Limit output
                print(f"  {key}")
            if len(key_list) > 20:
                print(f"  ... and {len(key_list) - 20} more keys")
                
    elif args.tier_distribution:
        tool.show_tier_distribution()
        
    else:
        print("Please specify an operation. Use --help for options.")
        print("\nQuick examples:")
        print("  python redis_query_tool.py --pair EUR_USD")
        print("  python redis_query_tool.py --list-all-pairs")
        print("  python redis_query_tool.py --tier-distribution")
        print("  python redis_query_tool.py --shard-info")


if __name__ == "__main__":
    main()