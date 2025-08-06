import json
import boto3
import redis
from datetime import datetime

def lambda_handler(event, context):
    """Test Redis for market data"""
    
    # Get Redis credentials
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    try:
        # Get Redis auth token
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
            decode_responses=True
        )
        
        # Test connection
        redis_client.ping()
        
        # Look for market data keys
        market_keys = []
        patterns = [
            'market_data:*',
            'oanda:*',
            'candles:*',
            'price:*',
            'EUR_USD:*'
        ]
        
        for pattern in patterns:
            keys = redis_client.keys(pattern)
            if keys:
                market_keys.extend(keys[:5])  # Get first 5 of each pattern
        
        # Check a few keys
        sample_data = {}
        for key in market_keys[:10]:
            try:
                value = redis_client.get(key)
                if value:
                    sample_data[key] = value[:100] if len(value) > 100 else value
            except:
                sample_data[key] = "Error reading value"
        
        # Check last update times
        last_update_key = 'market_data:last_update'
        last_update = redis_client.get(last_update_key)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'redis_connected': True,
                'market_data_keys_found': len(market_keys),
                'sample_keys': market_keys[:10],
                'sample_data': sample_data,
                'last_update': last_update,
                'current_time': datetime.utcnow().isoformat()
            }, indent=2)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'redis_connected': False
            })
        }