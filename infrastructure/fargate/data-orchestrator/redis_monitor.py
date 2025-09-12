#!/usr/bin/env python3
"""
Redis Storage Monitor

Lightweight monitoring script that can run alongside the data orchestrator
to continuously monitor Redis tiered storage health and report metrics.

This script:
1. Monitors candle counts across tiers
2. Checks TTL health
3. Validates data freshness
4. Reports storage efficiency
5. Alerts on anomalies

Can be run as:
- Sidecar container in Fargate
- Scheduled ECS task
- CloudWatch custom metrics source
"""

import json
import redis
import boto3
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import signal
import sys


class RedisStorageMonitor:
    """Monitors Redis tiered storage health"""
    
    def __init__(self):
        self.setup_logging()
        self.load_config()
        self.redis_clients = {}
        self.running = True
        self.setup_signal_handlers()
    
    def setup_logging(self):
        """Setup structured logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('redis-monitor')
    
    def setup_signal_handlers(self):
        """Setup graceful shutdown"""
        signal.signal(signal.SIGTERM, self.shutdown_handler)
        signal.signal(signal.SIGINT, self.shutdown_handler)
    
    def shutdown_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def load_config(self):
        """Load configuration from environment"""
        self.redis_cluster_nodes = [
            "lumisignals-main-vpc-trading-shard-1-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-2-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-3-001.wo9apa.0001.use1.cache.amazonaws.com:6379",
            "lumisignals-main-vpc-trading-shard-4-001.wo9apa.0001.use1.cache.amazonaws.com:6379"
        ]
        
        self.aws_region = os.getenv('AWS_REGION', 'us-east-1')
        self.monitor_interval = int(os.getenv('MONITOR_INTERVAL_SECONDS', '300'))  # 5 minutes
        self.cloudwatch_enabled = os.getenv('CLOUDWATCH_METRICS', 'true').lower() == 'true'
        
        # Currency pairs to monitor (focus on majors)
        self.monitor_pairs = [
            "EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD"
        ]
        
        # Sharding configuration
        self.shard_configuration = {
            "shard_0": ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CAD", "AUD_USD", "NZD_USD", "USD_CHF"],
            "shard_1": ["EUR_GBP", "EUR_JPY", "EUR_CAD", "EUR_AUD", "EUR_NZD", "EUR_CHF", "GBP_JPY"],
            "shard_2": ["GBP_CAD", "GBP_AUD", "GBP_NZD", "GBP_CHF", "AUD_JPY", "AUD_CAD", "AUD_NZD"],
            "shard_3": ["AUD_CHF", "NZD_JPY", "NZD_CAD", "NZD_CHF", "CAD_JPY", "CAD_CHF", "CHF_JPY"]
        }
        
        self.logger.info(f"Monitor configured: interval={self.monitor_interval}s, cloudwatch={self.cloudwatch_enabled}")
    
    def get_redis_auth_token(self) -> str:
        """Get Redis auth token"""
        # Try environment first
        auth_token = os.getenv('REDIS_AUTH_TOKEN', '')
        if auth_token:
            return auth_token
        
        # Try parsed credentials
        redis_creds = os.getenv('REDIS_CREDENTIALS', '')
        if redis_creds:
            try:
                creds = json.loads(redis_creds)
                return creds.get('auth_token', '')
            except:
                pass
        
        # Try Secrets Manager
        try:
            session = boto3.Session(region_name=self.aws_region)
            secrets_client = session.client('secretsmanager')
            response = secrets_client.get_secret_value(SecretId='prod/redis/credentials')
            redis_creds = json.loads(response['SecretString'])
            return redis_creds.get('auth_token', '')
        except:
            pass
        
        return ""
    
    def setup_redis_connections(self) -> bool:
        """Setup Redis connections"""
        auth_token = self.get_redis_auth_token()
        connected_count = 0
        
        for i, node_endpoint in enumerate(self.redis_cluster_nodes):
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
                connected_count += 1
                
                self.logger.info(f"Connected to {shard_name}")
                
            except Exception as e:
                self.logger.error(f"Failed to connect to {shard_name}: {e}")
        
        self.logger.info(f"Redis connections: {connected_count}/{len(self.redis_cluster_nodes)}")
        return connected_count > 0
    
    def get_shard_for_pair(self, currency_pair: str) -> int:
        """Get shard index for currency pair"""
        for shard_name, pairs in self.shard_configuration.items():
            if currency_pair in pairs:
                return int(shard_name.split("_")[1])
        return 0
    
    def collect_storage_metrics(self) -> Dict[str, Any]:
        """Collect storage metrics for all monitored pairs"""
        metrics = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'pairs': {},
            'totals': {
                'hot_candles': 0,
                'warm_candles': 0,
                'cold_candles': 0,
                'total_candles': 0,
                'pairs_with_data': 0,
                'pairs_meeting_target': 0
            },
            'shard_health': {}
        }
        
        # Check each shard's health
        for shard_name, client in self.redis_clients.items():
            try:
                info = client.info()
                metrics['shard_health'][shard_name] = {
                    'connected_clients': info.get('connected_clients', 0),
                    'used_memory_human': info.get('used_memory_human', 'unknown'),
                    'operations_per_sec': info.get('instantaneous_ops_per_sec', 0),
                    'hit_rate': info.get('keyspace_hit_rate', -1)
                }
            except Exception as e:
                metrics['shard_health'][shard_name] = {'error': str(e)}
        
        # Collect metrics for each monitored pair
        for pair in self.monitor_pairs:
            try:
                pair_metrics = self.collect_pair_metrics(pair, 'M5')
                metrics['pairs'][pair] = pair_metrics
                
                # Update totals
                if pair_metrics.get('status') == 'success':
                    metrics['totals']['pairs_with_data'] += 1
                    
                    tiers = pair_metrics.get('tiers', {})
                    hot_count = tiers.get('hot', {}).get('count', 0)
                    warm_count = tiers.get('warm', {}).get('count', 0)
                    cold_count = tiers.get('cold', {}).get('count', 0)
                    total = hot_count + warm_count + cold_count
                    
                    metrics['totals']['hot_candles'] += hot_count
                    metrics['totals']['warm_candles'] += warm_count
                    metrics['totals']['cold_candles'] += cold_count
                    metrics['totals']['total_candles'] += total
                    
                    if total >= 500:
                        metrics['totals']['pairs_meeting_target'] += 1
                        
            except Exception as e:
                metrics['pairs'][pair] = {'error': str(e)}
                self.logger.error(f"Error collecting metrics for {pair}: {e}")
        
        return metrics
    
    def collect_pair_metrics(self, currency_pair: str, timeframe: str) -> Dict[str, Any]:
        """Collect metrics for specific currency pair"""
        shard_index = self.get_shard_for_pair(currency_pair)
        shard_name = f"shard_{shard_index}"
        
        if shard_name not in self.redis_clients:
            return {'status': 'error', 'error': f'No connection to {shard_name}'}
        
        client = self.redis_clients[shard_name]
        base_key = f"market_data:{currency_pair}:{timeframe}"
        
        metrics = {
            'status': 'success',
            'pair': currency_pair,
            'timeframe': timeframe,
            'shard': shard_name,
            'tiers': {}
        }
        
        # Check each tier
        tier_keys = {
            'hot': f"{base_key}:hot",
            'warm': f"{base_key}:warm",
            'cold': f"{base_key}:historical"
        }
        
        for tier_name, key in tier_keys.items():
            try:
                if client.exists(key):
                    count = client.llen(key)
                    ttl = client.ttl(key)
                    
                    # Get data freshness (latest timestamp)
                    freshness = None
                    if count > 0:
                        latest_item = client.lindex(key, 0)
                        if latest_item:
                            try:
                                candle = json.loads(latest_item)
                                timestamp_str = candle.get('timestamp', '')
                                if timestamp_str:
                                    # Parse timestamp and calculate age
                                    candle_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                    age_minutes = (datetime.now(timezone.utc) - candle_time).total_seconds() / 60
                                    freshness = {
                                        'latest_timestamp': timestamp_str,
                                        'age_minutes': round(age_minutes, 1)
                                    }
                            except:
                                pass
                    
                    metrics['tiers'][tier_name] = {
                        'count': count,
                        'ttl': ttl,
                        'freshness': freshness
                    }
                else:
                    metrics['tiers'][tier_name] = {'count': 0, 'ttl': -1}
                    
            except Exception as e:
                metrics['tiers'][tier_name] = {'error': str(e)}
        
        return metrics
    
    def send_cloudwatch_metrics(self, metrics: Dict[str, Any]):
        """Send metrics to CloudWatch"""
        if not self.cloudwatch_enabled:
            return
        
        try:
            cloudwatch = boto3.client('cloudwatch', region_name=self.aws_region)
            
            # Prepare metric data
            metric_data = []
            
            # Overall metrics
            totals = metrics['totals']
            for metric_name, value in totals.items():
                if isinstance(value, (int, float)):
                    metric_data.append({
                        'MetricName': f'Redis_{metric_name.title().replace("_", "")}',
                        'Value': value,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'Environment', 'Value': 'production'},
                            {'Name': 'Service', 'Value': 'data-orchestrator'}
                        ]
                    })
            
            # Per-pair metrics
            for pair, pair_metrics in metrics['pairs'].items():
                if pair_metrics.get('status') == 'success':
                    tiers = pair_metrics.get('tiers', {})
                    total_candles = sum(tier.get('count', 0) for tier in tiers.values())
                    
                    metric_data.append({
                        'MetricName': 'Redis_PairTotalCandles',
                        'Value': total_candles,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'CurrencyPair', 'Value': pair},
                            {'Name': 'Timeframe', 'Value': 'M5'}
                        ]
                    })
            
            # Send in batches (CloudWatch limit is 20 metrics per call)
            for i in range(0, len(metric_data), 20):
                batch = metric_data[i:i+20]
                cloudwatch.put_metric_data(
                    Namespace='LumiSignals/Redis',
                    MetricData=batch
                )
            
            self.logger.info(f"Sent {len(metric_data)} metrics to CloudWatch")
            
        except Exception as e:
            self.logger.error(f"Failed to send CloudWatch metrics: {e}")
    
    def log_metrics_summary(self, metrics: Dict[str, Any]):
        """Log a summary of current metrics"""
        totals = metrics['totals']
        
        self.logger.info(
            f"Storage Summary: "
            f"pairs_with_data={totals['pairs_with_data']}, "
            f"total_candles={totals['total_candles']}, "
            f"pairs_meeting_target={totals['pairs_meeting_target']}"
        )
        
        # Log any issues
        for pair, pair_metrics in metrics['pairs'].items():
            if pair_metrics.get('status') == 'error':
                self.logger.warning(f"{pair}: {pair_metrics.get('error', 'Unknown error')}")
            elif pair_metrics.get('status') == 'success':
                tiers = pair_metrics.get('tiers', {})
                total = sum(tier.get('count', 0) for tier in tiers.values())
                if total < 500:
                    self.logger.warning(f"{pair}: Only {total} candles (target: 500)")
    
    def run_monitoring_loop(self):
        """Main monitoring loop"""
        self.logger.info("Starting Redis storage monitoring...")
        
        if not self.setup_redis_connections():
            self.logger.error("Could not establish Redis connections. Exiting.")
            return
        
        while self.running:
            try:
                self.logger.info("Collecting storage metrics...")
                
                # Collect metrics
                metrics = self.collect_storage_metrics()
                
                # Log summary
                self.log_metrics_summary(metrics)
                
                # Send to CloudWatch
                self.send_cloudwatch_metrics(metrics)
                
                # Save snapshot (optional)
                if os.getenv('SAVE_SNAPSHOTS', 'false').lower() == 'true':
                    snapshot_file = f"redis_snapshot_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
                    with open(snapshot_file, 'w') as f:
                        json.dump(metrics, f, indent=2, default=str)
                
                # Wait for next cycle
                if self.running:
                    time.sleep(self.monitor_interval)
                    
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
        
        self.logger.info("Monitoring stopped.")


def main():
    """Main entry point"""
    monitor = RedisStorageMonitor()
    
    # Check if this is a one-time check or continuous monitoring
    if '--once' in sys.argv:
        monitor.setup_redis_connections()
        metrics = monitor.collect_storage_metrics()
        print(json.dumps(metrics, indent=2, default=str))
    else:
        monitor.run_monitoring_loop()


if __name__ == "__main__":
    main()