import json
import boto3
import os

def lambda_handler(event, context):
    """Test PostgreSQL credentials from Secrets Manager"""
    
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    results = []
    
    # Test both secrets
    secrets_to_test = [
        'lumisignals/postgresql',
        'lumisignals/rds/postgresql/credentials'
    ]
    
    for secret_name in secrets_to_test:
        try:
            response = secrets_client.get_secret_value(SecretId=secret_name)
            secret = json.loads(response['SecretString'])
            
            result = {
                'secret_name': secret_name,
                'host': secret.get('host'),
                'database': secret.get('database') or secret.get('dbname'),
                'username': secret.get('username'),
                'password_length': len(secret.get('password', '')),
                'password_first_3': secret.get('password', '')[:3] + '...',
                'port': secret.get('port', 5432)
            }
            results.append(result)
            
        except Exception as e:
            results.append({
                'secret_name': secret_name,
                'error': str(e)
            })
    
    # Also check what the Data Orchestrator would see
    endpoint = "lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com"
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'secrets': results,
            'data_orchestrator_endpoint': endpoint,
            'message': 'Check which secret has the correct password for this endpoint'
        }, indent=2)
    }