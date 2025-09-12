#!/usr/bin/env python3
"""
Redis Test Script for Fargate Environment

This script is designed to run from within the Fargate task to test
Redis connectivity and verify the tiered storage system.

This should be run from:
1. ECS Fargate task in the same VPC
2. EC2 instance in the VPC
3. Any environment with access to the ElastiCache cluster

Usage:
    # Quick connectivity test
    python3 test_redis_from_fargate.py --test-connection
    
    # Full verification 
    python3 test_redis_from_fargate.py --full-verification
    
    # Check specific pair
    python3 test_redis_from_fargate.py --pair EUR_USD --timeframe M5
"""

import argparse
import json
import redis
import boto3
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Any


class FargateRedisTest:
    """Redis testing from Fargate environment"""
    
    def __init__(self):
        # Redis configuration matching the existing setup
        self.redis_cluster_nodes = [
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ]
        
        self.aws_region = "us-east-1"
        self.redis_clients = {}
        
        # Currency pair to shard mapping
        self.shard_configuration = {
            "shard_0": ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF"],
            "shard_1": ["EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF", "GBP_JPY"],
            "shard_2": ["GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF", "AUD_JPY", "AUD_CAD", "AUD_NZD"],
            "shard_3": ["AUD_CHF", "NZD_JPY", "NZD_CAD", "NZD_CHF", "CAD_JPY", "CAD_CHF", "CHF_JPY"]
        }
    
    def get_redis_auth_token(self) -> str:
        """Get Redis auth token from environment or secrets manager"""
        
        # First try environment variable (ECS task definition)
        auth_token = os.getenv('REDIS_AUTH_TOKEN', '')
        if auth_token:
            print(f"✓ Using Redis auth token from environment (length: {len(auth_token)})")
            return auth_token
        
        # Try to get from parsed credentials
        redis_creds = os.getenv('REDIS_CREDENTIALS', '')
        if redis_creds:
            try:
                creds = json.loads(redis_creds)
                auth_token = creds.get('auth_token', '')
                if auth_token:
                    print(f"✓ Using Redis auth token from REDIS_CREDENTIALS (length: {len(auth_token)})")
                    return auth_token
            except json.JSONDecodeError:
                pass
        
        # Try AWS Secrets Manager
        try:
            print("🔐 Retrieving Redis auth token from AWS Secrets Manager...")
            session = boto3.Session(region_name=self.aws_region)
            secrets_client = session.client('secretsmanager')
            
            response = secrets_client.get_secret_value(SecretId='prod/redis/credentials')
            redis_creds = json.loads(response['SecretString'])
            auth_token = redis_creds.get('auth_token', '')
            
            if auth_token:
                print(f"✓ Retrieved Redis auth token from Secrets Manager (length: {len(auth_token)})")
                return auth_token
                
        except Exception as e:
            print(f"⚠️ Could not retrieve auth token from Secrets Manager: {e}")
        
        print("⚠️ No Redis auth token available")
        return ""
    
    def test_basic_connectivity(self) -> Dict[str, Any]:
        """Test basic connectivity to all Redis nodes"""
        print("\n🔄 Testing Redis Connectivity")
        print("=" * 40)
        
        auth_token = self.get_redis_auth_token()
        results = {}
        
        for i, node_endpoint in enumerate(self.redis_cluster_nodes):
            shard_name = f"shard_{i}"
            
            try:
                print(f"  Testing {shard_name}: {node_endpoint}")
                
                # Parse endpoint
                host, port = node_endpoint.split(':')
                port = int(port)
                
                # Create client
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
                
                # Test connection
                start_time = datetime.now()
                ping_result = client.ping()
                latency = (datetime.now() - start_time).total_seconds() * 1000
                
                # Get some info
                info = client.info()
                
                results[shard_name] = {
                    'status': 'connected',
                    'endpoint': node_endpoint,
                    'ping': ping_result,
                    'latency_ms': round(latency, 2),
                    'redis_version': info.get('redis_version', 'unknown'),
                    'used_memory_human': info.get('used_memory_human', 'unknown'),
                    'connected_clients': info.get('connected_clients', 0)
                }
                
                self.redis_clients[shard_name] = client
                print(f"    ✓ Connected (latency: {latency:.1f}ms)")
                
            except Exception as e:
                results[shard_name] = {
                    'status': 'failed',
                    'endpoint': node_endpoint,
                    'error': str(e)
                }
                print(f"    ❌ Failed: {e}")
        
        return results
    
    def get_shard_for_pair(self, currency_pair: str) -> int:
        """Get shard index for currency pair"""
        for shard_name, pairs in self.shard_configuration.items():
            if currency_pair in pairs:
                return int(shard_name.split("_")[1])
        return 0  # Default fallback
    
    def scan_redis_keys(self, pattern: str = "market_data:*") -> Dict[str, List[str]]:
        """Scan for keys matching pattern across all shards"""
        print(f"\n🔍 Scanning for keys: {pattern}")
        print("=" * 50)
        
        all_keys = {}
        total_keys = 0
        
        for shard_name, client in self.redis_clients.items():
            try:
                keys = client.keys(pattern)
                all_keys[shard_name] = keys
                total_keys += len(keys)
                print(f"  {shard_name}: {len(keys)} keys")
                
                # Show sample keys
                if keys:
                    for key in keys[:3]:  # Show first 3 keys
                        print(f"    - {key}")
                    if len(keys) > 3:
                        print(f"    ... and {len(keys) - 3} more")
                        
            except Exception as e:
                print(f"  ❌ {shard_name}: Error scanning - {e}")
                all_keys[shard_name] = []
        
        print(f"\n📊 Total keys found: {total_keys}")
        return all_keys
    
    def verify_pair_data(self, currency_pair: str, timeframe: str = "M5") -> Dict[str, Any]:
        """Verify data for specific currency pair"""
        print(f"\n📈 Verifying {currency_pair} {timeframe}")
        print("=" * 40)
        
        shard_index = self.get_shard_for_pair(currency_pair)
        shard_name = f"shard_{shard_index}"
        
        if shard_name not in self.redis_clients:
            return {
                'error': f"No connection to {shard_name}",
                'pair': currency_pair,
                'timeframe': timeframe
            }
        
        client = self.redis_clients[shard_name]
        
        # Check different tier keys
        base_key = f"market_data:{currency_pair}:{timeframe}"
        keys_to_check = {
            'hot': f"{base_key}:hot",
            'warm': f"{base_key}:warm", 
            'cold': f"{base_key}:historical",
            'current': f"{base_key}:current",
            'last_update': f"{base_key}:last_update"
        }
        
        results = {
            'pair': currency_pair,
            'timeframe': timeframe,
            'shard': shard_name,
            'tiers': {}
        }
        
        total_candles = 0
        
        print(f"  Using {shard_name} for {currency_pair}")
        
        for tier_name, key in keys_to_check.items():
            try:
                exists = client.exists(key)
                
                if exists:
                    data_type = client.type(key)
                    ttl = client.ttl(key)
                    
                    tier_info = {
                        'exists': True,
                        'type': data_type,
                        'ttl': ttl,
                        'key': key
                    }
                    
                    if data_type == 'list':
                        count = client.llen(key)
                        tier_info['count'] = count
                        
                        if tier_name in ['hot', 'warm', 'cold']:
                            total_candles += count
                        
                        # Get sample data
                        if count > 0:
                            latest = client.lindex(key, 0)
                            if latest:
                                try:
                                    sample = json.loads(latest)
                                    tier_info['latest_timestamp'] = sample.get('timestamp', 'unknown')
                                    tier_info['latest_close'] = sample.get('close', 'unknown')
                                except:
                                    pass
                        
                        print(f"    {tier_name.upper()}: {count} items (TTL: {ttl}s)")
                        
                    elif data_type == 'string':
                        value = client.get(key)
                        tier_info['value'] = value
                        print(f"    {tier_name.upper()}: {value} (TTL: {ttl}s)")
                    
                    results['tiers'][tier_name] = tier_info
                    
                else:
                    results['tiers'][tier_name] = {
                        'exists': False,
                        'key': key
                    }
                    print(f"    {tier_name.upper()}: ❌ No data")
                    
            except Exception as e:
                results['tiers'][tier_name] = {
                    'exists': False,
                    'error': str(e),
                    'key': key
                }
                print(f"    {tier_name.upper()}: ❌ Error - {e}")
        
        results['total_candles'] = total_candles
        target_met = "✓" if total_candles >= 500 else "⚠️"
        print(f"\n  📊 Total Candles: {total_candles} {target_met}")
        
        return results
    
    def verify_multiple_pairs(self, pairs: List[str] = None) -> Dict[str, Any]:
        """Verify data for multiple currency pairs"""
        if pairs is None:
            pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD"]
        
        print(f"\n🎯 Verifying {len(pairs)} Currency Pairs")
        print("=" * 50)
        
        results = {}
        pairs_with_500_plus = 0
        total_candles = 0
        
        for pair in pairs:
            result = self.verify_pair_data(pair, "M5")
            results[pair] = result
            
            candles = result.get('total_candles', 0)
            total_candles += candles
            
            if candles >= 500:
                pairs_with_500_plus += 1
        
        # Summary
        print(f"\n📊 SUMMARY")
        print(f"  Pairs tested: {len(pairs)}")
        print(f"  Pairs with 500+ candles: {pairs_with_500_plus}")
        print(f"  Total candles across all pairs: {total_candles:,}")
        print(f"  Average candles per pair: {total_candles/len(pairs):.1f}")
        
        target_status = "✅ TARGET MET" if pairs_with_500_plus >= 3 else "⚠️ NEEDS ATTENTION"
        print(f"  Status: {target_status}")
        
        return {
            'pairs': results,
            'summary': {
                'pairs_tested': len(pairs),
                'pairs_with_500_plus': pairs_with_500_plus,
                'total_candles': total_candles,
                'average_per_pair': total_candles/len(pairs),
                'target_met': pairs_with_500_plus >= 3
            }
        }
    
    def run_full_verification(self) -> Dict[str, Any]:
        """Run complete verification suite"""
        print("🚀 Redis Tiered Storage Full Verification")
        print("=" * 60)
        
        # Step 1: Test connectivity
        connectivity = self.test_basic_connectivity()
        
        connected_shards = sum(1 for result in connectivity.values() 
                             if result.get('status') == 'connected')
        
        if connected_shards == 0:
            print("❌ No Redis connections available. Cannot proceed.")
            return {'error': 'No Redis connectivity'}
        
        print(f"\n✓ Connected to {connected_shards}/4 shards")
        
        # Step 2: Scan for keys
        keys_found = self.scan_redis_keys("market_data:*")
        
        # Step 3: Verify major pairs
        verification_results = self.verify_multiple_pairs()
        
        # Final report
        final_results = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'connectivity': connectivity,
            'keys_scan': keys_found,
            'verification': verification_results,
            'overall_status': {
                'connected_shards': connected_shards,
                'total_shards': 4,
                'has_data': verification_results['summary']['total_candles'] > 0,
                'meets_target': verification_results['summary']['target_met']
            }
        }
        
        return final_results


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(description='Redis Test from Fargate Environment')
    
    parser.add_argument('--test-connection', action='store_true', 
                       help='Test basic connectivity only')
    parser.add_argument('--full-verification', action='store_true',
                       help='Run full verification suite')
    parser.add_argument('--pair', type=str,
                       help='Test specific currency pair')
    parser.add_argument('--timeframe', type=str, default='M5',
                       help='Timeframe (default: M5)')
    parser.add_argument('--scan-keys', type=str,
                       help='Scan for keys matching pattern')
    parser.add_argument('--save-results', action='store_true',
                       help='Save results to JSON file')
    
    args = parser.parse_args()
    
    tester = FargateRedisTest()
    
    if args.test_connection:
        results = tester.test_basic_connectivity()
        if args.save_results:
            filename = f"redis_connectivity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"💾 Results saved to {filename}")
            
    elif args.full_verification:
        results = tester.run_full_verification()
        if args.save_results:
            filename = f"redis_full_verification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"💾 Results saved to {filename}")
            
    elif args.pair:
        results = tester.verify_pair_data(args.pair, args.timeframe)
        print(f"\n📋 Results for {args.pair}:")
        print(json.dumps(results, indent=2, default=str))
        
    elif args.scan_keys:
        results = tester.scan_redis_keys(args.scan_keys)
        
    else:
        print("Please specify an operation. Examples:")
        print("  python3 test_redis_from_fargate.py --test-connection")
        print("  python3 test_redis_from_fargate.py --full-verification")
        print("  python3 test_redis_from_fargate.py --pair EUR_USD")
        print("  python3 test_redis_from_fargate.py --scan-keys 'market_data:EUR_USD:*'")


if __name__ == "__main__":
    main()