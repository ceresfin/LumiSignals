#\!/usr/bin/env python3
"""
Test Redis connectivity from primary VPC
"""

import json
import boto3
import redis

def lambda_handler(event, context):
    """Test Redis connection"""
    
    try:
        print("🔍 Testing Redis connection from primary VPC...")
        
        # Get Redis credentials
        secrets_client = boto3.client('secretsmanager')
        secret_response = secrets_client.get_secret_value(SecretId="lumisignals/redis/market-data/auth-token")
        redis_credentials = json.loads(secret_response['SecretString'])
        
        print(f"📡 Connecting to Redis: {redis_credentials['endpoint']}")
        
        redis_client = redis.StrictRedis(
            host=redis_credentials['endpoint'],
            port=redis_credentials.get('port', 6379),
            password=redis_credentials.get('auth_token'),
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=10,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        # Test connection
        redis_client.ping()
        print("✅ Redis ping successful\!")
        
        # Test reading some keys
        keys = redis_client.keys("trade:*")[:5]  # Get first 5 trade keys
        print(f"📋 Found {len(keys)} trade keys: {keys}")
        
        # Test reading metadata
        if keys:
            metadata = redis_client.get(keys[0])
            print(f"📊 Sample metadata: {metadata}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Redis connection successful',
                'endpoint': redis_credentials['endpoint'],
                'keys_found': len(keys),
                'sample_keys': keys[:3]
            })
        }
        
    except Exception as e:
        print(f"❌ Redis connection failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
EOF < /dev/null
