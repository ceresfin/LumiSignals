#!/usr/bin/env python3
"""
Comprehensive Data Flow Monitor for LumiSignals
Monitors the entire data flow from OANDA -> Data Orchestrator -> Redis -> Lambda
"""

import json
import time
import boto3
from datetime import datetime
import os

class LumiSignalsMonitor:
    def __init__(self):
        self.lambda_client = boto3.client('lambda', region_name='us-east-1')
        self.logs_client = boto3.client('logs', region_name='us-east-1')
        self.ecs_client = boto3.client('ecs', region_name='us-east-1')
        self.secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
        
    def test_data_orchestrator_status(self):
        """Check if Data Orchestrator is running and connected"""
        print("🔍 Checking Data Orchestrator Status...")
        
        try:
            # Check ECS service status
            response = self.ecs_client.describe_services(
                cluster='LumiSignals-prod-cluster',
                services=['institutional-orchestrator-postgresql17']
            )
            
            service = response['services'][0]
            status = {
                'service_status': service['status'],
                'running_count': service['runningCount'],
                'pending_count': service['pendingCount'],
                'desired_count': service['desiredCount'],
                'last_event': service['events'][0]['message'] if service['events'] else 'No events'
            }
            
            print(f"   Service Status: {status['service_status']}")
            print(f"   Running Tasks: {status['running_count']}/{status['desired_count']}")
            print(f"   Latest Event: {status['last_event']}")
            
            # Check recent logs
            try:
                log_events = self.logs_client.get_log_events(
                    logGroupName='/ecs/lumisignals-institutional-postgresql',
                    logStreamName=f"orchestrator/orchestrator/{self._get_latest_task_id()}",
                    limit=5,
                    startFromHead=False
                )
                
                latest_logs = [event['message'] for event in log_events['events']]
                if latest_logs:
                    print(f"   Latest Log: {latest_logs[-1]}")
                    
                    # Check for success indicators
                    success_indicators = ['Connected', 'SUCCESS', '✅', 'initialized']
                    failure_indicators = ['Failed', 'ERROR', '❌', 'authentication failed']
                    
                    has_success = any(indicator in log for log in latest_logs for indicator in success_indicators)
                    has_failure = any(indicator in log for log in latest_logs for indicator in failure_indicators)
                    
                    if has_success:
                        print("   ✅ Data Orchestrator appears to be working!")
                        return True
                    elif has_failure:
                        print("   ❌ Data Orchestrator has connection issues")
                        return False
                        
            except Exception as e:
                print(f"   ⚠️ Could not retrieve logs: {str(e)}")
            
            return status['running_count'] > 0
            
        except Exception as e:
            print(f"❌ Error checking Data Orchestrator: {str(e)}")
            return False
    
    def _get_latest_task_id(self):
        """Get the latest running task ID"""
        try:
            tasks = self.ecs_client.list_tasks(
                cluster='LumiSignals-prod-cluster',
                serviceName='institutional-orchestrator-postgresql17'
            )
            if tasks['taskArns']:
                return tasks['taskArns'][0].split('/')[-1]
        except:
            pass
        return "unknown"
    
    def test_lambda_data_source(self):
        """Test what data source Lambda functions are using"""
        print("\n🔍 Testing Lambda Data Sources...")
        
        test_functions = [
            'lumisignals-dime_curve_dc_h1_all_dual_limit_100sl',
            'lumisignals-dime_curve_ren_dc_h4_all_001'
        ]
        
        results = {}
        
        for func_name in test_functions:
            try:
                print(f"   Testing {func_name}...")
                
                response = self.lambda_client.invoke(
                    FunctionName=func_name,
                    Payload=json.dumps({})
                )
                
                payload = json.loads(response['Payload'].read())
                
                if payload['statusCode'] == 200:
                    body = json.loads(payload['body'])
                    
                    data_source = body.get('market_data_source', ['UNKNOWN'])
                    account_balance = body.get('account_balance', 0)
                    centralized_used = body.get('centralized_data_used', False)
                    api_calls_saved = body.get('api_calls_saved', 0)
                    
                    results[func_name] = {
                        'data_source': data_source,
                        'account_balance': account_balance,
                        'centralized_used': centralized_used,
                        'api_calls_saved': api_calls_saved,
                        'status': 'success'
                    }
                    
                    print(f"      Data Source: {data_source}")
                    print(f"      Account Balance: ${account_balance:,.2f}")
                    print(f"      Centralized Data: {'✅' if centralized_used else '❌'}")
                    print(f"      API Calls Saved: {api_calls_saved}")
                    
                    # Determine data quality
                    if 'SIMULATION_FALLBACK' in data_source:
                        print(f"      ⚠️ Using simulated data (Data Orchestrator issue)")
                    elif centralized_used and api_calls_saved > 0:
                        print(f"      ✅ Using real centralized data!")
                    else:
                        print(f"      ❓ Unknown data source")
                else:
                    results[func_name] = {'status': 'error', 'error': payload}
                    print(f"      ❌ Lambda error: {payload}")
                    
            except Exception as e:
                results[func_name] = {'status': 'error', 'error': str(e)}
                print(f"      ❌ Failed to invoke: {str(e)}")
        
        return results
    
    def test_redis_connectivity(self):
        """Test Redis connectivity and data availability"""
        print("\n🔍 Testing Redis Data Availability...")
        
        # Create a simple Lambda function to test Redis
        redis_test_code = '''
import json
import redis
import boto3
from datetime import datetime

def lambda_handler(event, context):
    try:
        # Get Redis credentials
        secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
        secret_response = secrets_client.get_secret_value(
            SecretId='lumisignals/redis/market-data/auth-token'
        )
        redis_auth = json.loads(secret_response['SecretString'])['auth_token']
        
        # Connect to Redis
        redis_client = redis.Redis(
            host='lumisignals-prod-redis-pg17.wo9apa.ng.0001.use1.cache.amazonaws.com',
            port=6379,
            password=redis_auth,
            ssl=True,
            decode_responses=True,
            socket_timeout=5
        )
        
        # Test connection
        redis_client.ping()
        
        # Look for market data
        patterns = ['market_data:*', 'oanda:*', 'EUR_USD:*', '*price*']
        found_keys = []
        
        for pattern in patterns:
            keys = redis_client.keys(pattern)
            found_keys.extend(keys[:3])  # Get first 3 of each pattern
        
        # Get some sample data
        sample_data = {}
        for key in found_keys[:5]:
            try:
                value = redis_client.get(key)
                if value:
                    sample_data[key] = value[:50] + '...' if len(value) > 50 else value
            except:
                sample_data[key] = "Error reading"
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'redis_connected': True,
                'keys_found': len(found_keys),
                'sample_keys': found_keys[:10],
                'sample_data': sample_data,
                'timestamp': datetime.utcnow().isoformat()
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'redis_connected': False,
                'error': str(e)
            })
        }
        '''
        
        print("   Redis connectivity test would require deploying a test Lambda...")
        print("   Skipping for now - use Lambda function test results instead")
        
        return {'status': 'skipped', 'reason': 'Requires Lambda deployment'}
    
    def generate_report(self):
        """Generate comprehensive system status report"""
        print("=" * 80)
        print("🚀 LumiSignals Data Flow Status Report")
        print("=" * 80)
        print(f"Timestamp: {datetime.utcnow().isoformat()}")
        
        # Test components
        orchestrator_ok = self.test_data_orchestrator_status()
        lambda_results = self.test_lambda_data_source()
        redis_results = self.test_redis_connectivity()
        
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        
        # Overall system status
        real_data_flowing = False
        for func_name, result in lambda_results.items():
            if result.get('status') == 'success':
                data_source = result.get('data_source', [])
                if 'SIMULATION_FALLBACK' not in data_source and result.get('centralized_used'):
                    real_data_flowing = True
                    break
        
        print(f"Data Orchestrator Running: {'✅' if orchestrator_ok else '❌'}")
        print(f"Real OANDA Data Flowing: {'✅' if real_data_flowing else '❌ (Using simulation)'}")
        print(f"Lambda Functions Working: {'✅' if lambda_results else '❌'}")
        
        if real_data_flowing:
            print("\n🎉 SUCCESS: Real OANDA data is flowing through the system!")
        elif orchestrator_ok:
            print("\n⚠️ PARTIAL: Data Orchestrator running but using simulation data")
            print("   This suggests PostgreSQL connection issues")
        else:
            print("\n❌ ISSUE: Data Orchestrator not running properly")
            print("   Check PostgreSQL authentication and VPC connectivity")
        
        print("\n💡 RECOMMENDATIONS:")
        if not orchestrator_ok:
            print("   1. Check Data Orchestrator logs for PostgreSQL connection errors")
            print("   2. Verify RDS password matches secret in Secrets Manager")
            print("   3. Ensure VPC connectivity between ECS and RDS")
        elif not real_data_flowing:
            print("   1. Data Orchestrator is running but may have OANDA API issues")
            print("   2. Check Redis connectivity from Data Orchestrator")
            print("   3. Verify OANDA API credentials in Secrets Manager")
        else:
            print("   1. System is working correctly!")
            print("   2. Monitor account balance in Lambda responses for accuracy")
        
        return {
            'orchestrator_running': orchestrator_ok,
            'real_data_flowing': real_data_flowing,
            'lambda_results': lambda_results,
            'timestamp': datetime.utcnow().isoformat()
        }

def main():
    monitor = LumiSignalsMonitor()
    report = monitor.generate_report()
    
    # Save report to file
    with open('/tmp/lumisignals_status_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n📄 Full report saved to: /tmp/lumisignals_status_report.json")

if __name__ == "__main__":
    main()