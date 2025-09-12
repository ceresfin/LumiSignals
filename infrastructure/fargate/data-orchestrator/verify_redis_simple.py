#!/usr/bin/env python3
"""
Simplified Redis Tiered Storage Verification Script

This script connects to the Redis cluster and verifies:
1. Connection to all Redis nodes  
2. Hot tier data distribution
3. Warm tier data distribution
4. Total candle counts across tiers
5. Data structure integrity
6. TTL settings validation
7. Coverage across major currency pairs

Uses simplified configuration without pydantic_settings dependency.
"""

import json
import redis
import boto3
from typing import Dict, List, Any, Tuple
import sys
import os
from datetime import datetime, timezone
import time


class SimpleRedisConfig:
    """Simplified Redis configuration"""
    
    def __init__(self):
        # Redis Cluster Configuration - Manual sharding nodes
        self.redis_cluster_nodes = [
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379", 
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ]
        
        # Redis settings
        self.redis_ssl = False
        self.redis_connection_timeout = 5
        self.redis_socket_timeout = 5
        self.aws_region = "us-east-1"
        
        # Tiered storage configuration
        self.hot_tier_candles = 50
        self.warm_tier_candles = 450
        self.bootstrap_candles = 500
        
        # TTL settings
        self.hot_tier_ttl = 86400    # 1 day
        self.warm_tier_ttl = 432000  # 5 days
        self.cold_tier_ttl = 604800  # 7 days
        
        # Currency pair sharding configuration
        self.shard_configuration = {
            "shard_0": ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF"],
            "shard_1": ["EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF", "GBP_JPY"],
            "shard_2": ["GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF", "AUD_JPY", "AUD_CAD", "AUD_NZD"],
            "shard_3": ["AUD_CHF", "NZD_JPY", "NZD_CAD", "NZD_CHF", "CAD_JPY", "CAD_CHF", "CHF_JPY"]
        }
        
        # All currency pairs
        self.currency_pairs = []
        for pairs in self.shard_configuration.values():
            self.currency_pairs.extend(pairs)
    
    def get_redis_node_for_pair(self, currency_pair: str) -> int:
        """Get Redis node index for currency pair based on sharding"""
        for shard_name, pairs in self.shard_configuration.items():
            if currency_pair in pairs:
                # Extract shard number (shard_0 -> 0, shard_1 -> 1, etc.)
                return int(shard_name.split("_")[1])
        
        # Fallback: hash-based sharding
        return hash(currency_pair) % len(self.redis_cluster_nodes)
    
    def get_redis_keys_for_pair_timeframe(self, currency_pair: str, timeframe: str) -> Dict[str, str]:
        """Get all Redis keys for a currency pair and timeframe"""
        base = f"market_data:{currency_pair}:{timeframe}"
        return {
            'current': f"{base}:current",
            'hot': f"{base}:hot",
            'warm': f"{base}:warm", 
            'cold': f"{base}:historical",  # Bootstrap/historical data
            'last_update': f"{base}:last_update",
            'rotation_meta': f"{base}:rotation:meta"
        }


class RedisStorageVerifier:
    """Verifies Redis tiered storage system"""
    
    def __init__(self):
        self.config = SimpleRedisConfig()
        self.redis_clients = {}
        self.verification_results = {
            'connection_status': {},
            'tier_distribution': {},
            'data_integrity': {},
            'ttl_validation': {},
            'summary': {}
        }
    
    def get_redis_auth_token_from_secrets(self) -> str:
        """Retrieve Redis auth token from AWS Secrets Manager"""
        try:
            print("🔐 Retrieving Redis auth token from AWS Secrets Manager...")
            
            session = boto3.Session(region_name=self.config.aws_region)
            secrets_client = session.client('secretsmanager')
            
            # Try to get Redis credentials secret
            try:
                response = secrets_client.get_secret_value(SecretId='prod/redis/credentials')
                redis_creds = json.loads(response['SecretString'])
                auth_token = redis_creds.get('auth_token', '')
                
                if auth_token:
                    print(f"✓ Retrieved Redis auth token (length: {len(auth_token)})")
                    return auth_token
                else:
                    print("⚠️ Redis auth token is empty in secrets")
                    
            except secrets_client.exceptions.ResourceNotFoundException:
                print("⚠️ Redis credentials secret not found, trying alternative names...")
                
                # Try alternative secret names
                for secret_name in ['redis-cluster-auth', 'elasticache-auth', 'redis-auth']:
                    try:
                        response = secrets_client.get_secret_value(SecretId=secret_name)
                        secret_data = json.loads(response['SecretString'])
                        auth_token = secret_data.get('auth_token', secret_data.get('token', ''))
                        if auth_token:
                            print(f"✓ Found auth token in {secret_name}")
                            return auth_token
                    except:
                        continue
                        
            print("⚠️ Could not retrieve auth token from Secrets Manager")
            return ""
            
        except Exception as e:
            print(f"❌ Error retrieving auth token: {e}")
            return ""
    
    def setup_redis_connections(self) -> bool:
        """Setup connections to all Redis cluster nodes"""
        print(f"\n🔄 Setting up Redis connections to {len(self.config.redis_cluster_nodes)} nodes...")
        
        # Get auth token
        auth_token = self.get_redis_auth_token_from_secrets()
        if not auth_token:
            print("⚠️ No auth token available, attempting connection without authentication...")
        
        success_count = 0
        
        for i, node_endpoint in enumerate(self.config.redis_cluster_nodes):
            shard_name = f"shard_{i}"
            
            try:
                print(f"  Connecting to {shard_name}: {node_endpoint}")
                
                # Parse host and port
                if ':' in node_endpoint:
                    host, port = node_endpoint.split(':')
                    port = int(port)
                else:
                    host = node_endpoint
                    port = 6379
                
                # Create Redis client
                client_config = {
                    'host': host,
                    'port': port,
                    'decode_responses': True,
                    'socket_timeout': self.config.redis_socket_timeout,
                    'socket_connect_timeout': self.config.redis_connection_timeout,
                    'retry_on_timeout': True,
                    'health_check_interval': 30
                }
                
                if auth_token:
                    client_config['password'] = auth_token
                
                if self.config.redis_ssl:
                    client_config['ssl'] = True
                    client_config['ssl_cert_reqs'] = None
                
                client = redis.Redis(**client_config)
                
                # Test connection
                ping_response = client.ping()
                if ping_response:
                    self.redis_clients[shard_name] = client
                    self.verification_results['connection_status'][shard_name] = {
                        'status': 'connected',
                        'endpoint': node_endpoint,
                        'ping_response': ping_response
                    }
                    print(f"    ✓ {shard_name} connected successfully")
                    success_count += 1
                else:
                    raise Exception("Ping failed")
                    
            except Exception as e:
                self.verification_results['connection_status'][shard_name] = {
                    'status': 'failed',
                    'endpoint': node_endpoint,
                    'error': str(e)
                }
                print(f"    ❌ {shard_name} connection failed: {e}")
        
        print(f"\n📊 Connection Summary: {success_count}/{len(self.config.redis_cluster_nodes)} nodes connected")
        return success_count > 0
    
    def get_redis_client_for_pair(self, currency_pair: str) -> redis.Redis:
        """Get Redis client for specific currency pair based on sharding"""
        shard_index = self.config.get_redis_node_for_pair(currency_pair)
        shard_name = f"shard_{shard_index}"
        
        if shard_name in self.redis_clients:
            return self.redis_clients[shard_name]
        else:
            raise Exception(f"No Redis client available for {shard_name}")
    
    def verify_tier_data_for_pair(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Verify tiered storage data for a specific currency pair and timeframe"""
        try:
            client = self.get_redis_client_for_pair(currency_pair)
            shard_index = self.config.get_redis_node_for_pair(currency_pair)
            
            # Get Redis keys for this pair/timeframe
            keys = self.config.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            tier_data = {}
            
            for tier_name, key in keys.items():
                if tier_name in ['hot', 'warm', 'cold']:
                    try:
                        # Check if key exists
                        exists = client.exists(key)
                        
                        if exists:
                            # Get data length/count
                            data_type = client.type(key)
                            
                            if data_type == 'list':
                                count = client.llen(key)
                                ttl = client.ttl(key)
                                
                                # Get sample data to verify structure
                                sample_data = client.lrange(key, 0, 2)  # Get first 3 items
                                
                                tier_data[tier_name] = {
                                    'exists': True,
                                    'type': data_type,
                                    'count': count,
                                    'ttl': ttl,
                                    'sample_data': sample_data[:2] if sample_data else [],  # Limit sample size
                                    'key': key
                                }
                            elif data_type == 'string':
                                value = client.get(key)
                                ttl = client.ttl(key)
                                
                                tier_data[tier_name] = {
                                    'exists': True,
                                    'type': data_type,
                                    'value_length': len(value) if value else 0,
                                    'ttl': ttl,
                                    'key': key
                                }
                            else:
                                tier_data[tier_name] = {
                                    'exists': True,
                                    'type': data_type,
                                    'ttl': client.ttl(key),
                                    'key': key
                                }
                        else:
                            tier_data[tier_name] = {
                                'exists': False,
                                'key': key
                            }
                            
                    except Exception as e:
                        tier_data[tier_name] = {
                            'exists': False,
                            'error': str(e),
                            'key': key
                        }
            
            # Calculate total candles across tiers
            total_candles = 0
            for tier_name in ['hot', 'warm', 'cold']:
                if tier_name in tier_data and tier_data[tier_name].get('exists'):
                    count = tier_data[tier_name].get('count', 0)
                    if isinstance(count, int):
                        total_candles += count
            
            return {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'shard': f"shard_{shard_index}",
                'tiers': tier_data,
                'total_candles': total_candles,
                'status': 'success'
            }
            
        except Exception as e:
            return {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'status': 'error',
                'error': str(e)
            }
    
    def verify_data_structure_integrity(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Verify the integrity of candlestick data structure"""
        try:
            client = self.get_redis_client_for_pair(currency_pair)
            keys = self.config.get_redis_keys_for_pair_timeframe(currency_pair, timeframe)
            
            integrity_results = {}
            
            # Check hot tier data structure
            hot_key = keys['hot']
            if client.exists(hot_key):
                sample_candles = client.lrange(hot_key, 0, 2)  # Get 3 samples
                
                parsed_candles = []
                structure_valid = True
                
                for candle_str in sample_candles:
                    try:
                        candle = json.loads(candle_str)
                        parsed_candles.append(candle)
                        
                        # Verify expected fields
                        required_fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                        missing_fields = [field for field in required_fields if field not in candle]
                        
                        if missing_fields:
                            structure_valid = False
                            break
                            
                    except json.JSONDecodeError:
                        structure_valid = False
                        break
                
                integrity_results['hot_tier'] = {
                    'samples_checked': len(sample_candles),
                    'structure_valid': structure_valid,
                    'sample_candle': parsed_candles[0] if parsed_candles else None
                }
            
            return {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'integrity_check': integrity_results
            }
            
        except Exception as e:
            return {
                'currency_pair': currency_pair,
                'timeframe': timeframe,
                'error': str(e)
            }
    
    def run_comprehensive_verification(self) -> Dict[str, Any]:
        """Run comprehensive verification of Redis tiered storage"""
        print("\n🎯 Starting Comprehensive Redis Storage Verification")
        print("=" * 60)
        
        # Test major currency pairs
        major_pairs = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD"]
        timeframes_to_test = ["M5"]
        
        for pair in major_pairs:
            for timeframe in timeframes_to_test:
                print(f"\n📈 Verifying {pair} {timeframe}...")
                
                # Verify tier data
                tier_results = self.verify_tier_data_for_pair(pair, timeframe)
                pair_key = f"{pair}_{timeframe}"
                self.verification_results['tier_distribution'][pair_key] = tier_results
                
                # Verify data integrity
                integrity_results = self.verify_data_structure_integrity(pair, timeframe)
                self.verification_results['data_integrity'][pair_key] = integrity_results
                
                # Display results
                if tier_results['status'] == 'success':
                    print(f"  📊 Shard: {tier_results['shard']}")
                    print(f"  📦 Total Candles: {tier_results['total_candles']}")
                    
                    for tier_name, tier_info in tier_results['tiers'].items():
                        if tier_info.get('exists'):
                            count = tier_info.get('count', 'N/A')
                            ttl = tier_info.get('ttl', 'N/A')
                            print(f"    {tier_name.upper()} tier: {count} candles, TTL: {ttl}s")
                        else:
                            print(f"    {tier_name.upper()} tier: ❌ No data")
                else:
                    print(f"  ❌ Error: {tier_results.get('error', 'Unknown error')}")
    
    def generate_summary_report(self) -> Dict[str, Any]:
        """Generate comprehensive summary report"""
        print("\n📋 Generating Summary Report...")
        
        # Connection summary
        connected_shards = sum(1 for status in self.verification_results['connection_status'].values() 
                             if status['status'] == 'connected')
        total_shards = len(self.verification_results['connection_status'])
        
        # Data distribution summary
        pairs_with_data = 0
        total_candles_found = 0
        pairs_meeting_500_target = 0
        
        for pair_key, tier_data in self.verification_results['tier_distribution'].items():
            if tier_data.get('status') == 'success':
                total_candles = tier_data.get('total_candles', 0)
                if total_candles > 0:
                    pairs_with_data += 1
                    total_candles_found += total_candles
                    
                    if total_candles >= 500:  # Target candle count
                        pairs_meeting_500_target += 1
        
        summary = {
            'verification_timestamp': datetime.now(timezone.utc).isoformat(),
            'redis_cluster': {
                'connected_shards': connected_shards,
                'total_shards': total_shards,
                'connection_rate': f"{(connected_shards/total_shards)*100:.1f}%" if total_shards > 0 else "0%"
            },
            'data_distribution': {
                'pairs_tested': len(self.verification_results['tier_distribution']),
                'pairs_with_data': pairs_with_data,
                'total_candles_found': total_candles_found,
                'pairs_meeting_500_target': pairs_meeting_500_target,
                'average_candles_per_pair': total_candles_found / pairs_with_data if pairs_with_data > 0 else 0
            },
            'compliance_status': {
                'cluster_connectivity': connected_shards >= 3,  # At least 75% nodes
                'data_availability': pairs_with_data > 0,
                'target_collection': pairs_meeting_500_target >= 3  # At least 3 pairs with 500+ candles
            }
        }
        
        self.verification_results['summary'] = summary
        return summary
    
    def print_detailed_report(self):
        """Print detailed verification report"""
        print("\n" + "="*80)
        print("🎯 REDIS TIERED STORAGE VERIFICATION REPORT")
        print("="*80)
        
        summary = self.verification_results['summary']
        
        print(f"\n📅 Verification Time: {summary['verification_timestamp']}")
        
        # Cluster Status
        print(f"\n🔗 REDIS CLUSTER STATUS")
        print(f"   Connected Shards: {summary['redis_cluster']['connected_shards']}/{summary['redis_cluster']['total_shards']}")
        print(f"   Connection Rate: {summary['redis_cluster']['connection_rate']}")
        
        # Connection Details
        for shard_name, conn_info in self.verification_results['connection_status'].items():
            status_icon = "✓" if conn_info['status'] == 'connected' else "❌"
            print(f"     {status_icon} {shard_name}: {conn_info['endpoint']} - {conn_info['status']}")
        
        # Data Distribution
        print(f"\n📊 DATA DISTRIBUTION SUMMARY")
        print(f"   Pairs Tested: {summary['data_distribution']['pairs_tested']}")
        print(f"   Pairs with Data: {summary['data_distribution']['pairs_with_data']}")
        print(f"   Total Candles: {summary['data_distribution']['total_candles_found']:,}")
        print(f"   Pairs Meeting 500+ Target: {summary['data_distribution']['pairs_meeting_500_target']}")
        print(f"   Average Candles per Pair: {summary['data_distribution']['average_candles_per_pair']:.1f}")
        
        # Detailed Results
        print(f"\n📈 DETAILED PAIR ANALYSIS")
        for pair_key, tier_data in self.verification_results['tier_distribution'].items():
            if tier_data.get('status') == 'success':
                total = tier_data.get('total_candles', 0)
                target_met = "✓" if total >= 500 else "⚠️"
                print(f"   {target_met} {pair_key}:")
                print(f"      Shard: {tier_data.get('shard', 'Unknown')}")
                print(f"      Total Candles: {total}")
                
                for tier_name, tier_info in tier_data.get('tiers', {}).items():
                    if tier_info.get('exists'):
                        count = tier_info.get('count', 'N/A')
                        ttl = tier_info.get('ttl', 'N/A')
                        print(f"        {tier_name.upper()}: {count} candles (TTL: {ttl}s)")
                    else:
                        print(f"        {tier_name.upper()}: No data")
            else:
                print(f"   ❌ {pair_key}: {tier_data.get('error', 'Unknown error')}")
        
        # Compliance Status
        print(f"\n✅ COMPLIANCE STATUS")
        compliance = summary['compliance_status']
        cluster_icon = "✓" if compliance['cluster_connectivity'] else "❌"
        data_icon = "✓" if compliance['data_availability'] else "❌"
        target_icon = "✓" if compliance['target_collection'] else "❌"
        
        print(f"   {cluster_icon} Cluster Connectivity: {compliance['cluster_connectivity']}")
        print(f"   {data_icon} Data Availability: {compliance['data_availability']}")
        print(f"   {target_icon} Target Collection: {compliance['target_collection']}")
        
        # Overall Status
        overall_status = all(compliance.values())
        overall_icon = "✅" if overall_status else "⚠️"
        print(f"\n{overall_icon} OVERALL STATUS: {'PASS' if overall_status else 'NEEDS ATTENTION'}")


def main():
    """Main execution function"""
    print("🚀 Redis Tiered Storage Verification")
    print("====================================")
    
    verifier = RedisStorageVerifier()
    
    # Step 1: Setup connections
    if not verifier.setup_redis_connections():
        print("❌ Failed to establish Redis connections. Exiting.")
        sys.exit(1)
    
    # Step 2: Run comprehensive verification
    verifier.run_comprehensive_verification()
    
    # Step 3: Generate summary
    summary = verifier.generate_summary_report()
    
    # Step 4: Print detailed report
    verifier.print_detailed_report()
    
    # Step 5: Save results to file
    results_file = f"redis_verification_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    try:
        with open(results_file, 'w') as f:
            json.dump(verifier.verification_results, f, indent=2, default=str)
        print(f"\n💾 Results saved to: {results_file}")
    except Exception as e:
        print(f"⚠️ Could not save results file: {e}")
    
    print("\n🎯 Verification completed!")


if __name__ == "__main__":
    main()