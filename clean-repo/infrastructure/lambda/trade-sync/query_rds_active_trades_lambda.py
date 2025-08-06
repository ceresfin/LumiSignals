import json
import boto3
import psycopg2
from datetime import datetime
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """Query RDS active_trades table to identify discrepancies with OANDA."""
    
    # Expected trade IDs from OANDA (from Fargate logs)
    expected_trade_ids = {'1515', '914', '568', '516'}
    
    # Get RDS credentials from Secrets Manager
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    try:
        response = secrets_client.get_secret_value(SecretId='lumisignals/rds/postgresql/credentials')
        secret = json.loads(response['SecretString'])
        
        credentials = {
            'host': secret.get('host'),
            'port': secret.get('port', 5432),
            'database': secret.get('database', 'postgres'),
            'user': secret.get('username'),
            'password': secret.get('password')
        }
        
    except ClientError as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Failed to retrieve RDS credentials: {str(e)}'
            })
        }
    
    # Connect to RDS and query active trades
    try:
        conn = psycopg2.connect(**credentials)
        cursor = conn.cursor()
        
        # Query all active trades
        query = """
        SELECT 
            trade_id,
            instrument,
            direction,
            units,
            open_time,
            last_updated
        FROM active_trades
        ORDER BY trade_id DESC;
        """
        
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        # Convert to list of dictionaries
        trades = []
        for row in rows:
            trade = dict(zip(columns, row))
            # Convert datetime objects to strings for JSON serialization
            if trade.get('open_time'):
                trade['open_time'] = trade['open_time'].isoformat() if hasattr(trade['open_time'], 'isoformat') else str(trade['open_time'])
            if trade.get('last_updated'):
                trade['last_updated'] = trade['last_updated'].isoformat() if hasattr(trade['last_updated'], 'isoformat') else str(trade['last_updated'])
            trades.append(trade)
        
        cursor.close()
        conn.close()
        
        # Analyze discrepancies
        found_trade_ids = {str(trade['trade_id']) for trade in trades}
        extra_trades = found_trade_ids - expected_trade_ids
        missing_trades = expected_trade_ids - found_trade_ids
        matching_trades = expected_trade_ids & found_trade_ids
        
        # Prepare detailed analysis
        extra_trade_details = [
            trade for trade in trades 
            if str(trade['trade_id']) in extra_trades
        ]
        
        analysis = {
            'total_trades_in_rds': len(trades),
            'expected_trades_from_oanda': len(expected_trade_ids),
            'matching_trades': len(matching_trades),
            'extra_trades_count': len(extra_trades),
            'missing_trades_count': len(missing_trades),
            'expected_trade_ids': list(expected_trade_ids),
            'found_trade_ids': list(found_trade_ids),
            'extra_trade_ids': list(extra_trades),
            'missing_trade_ids': list(missing_trades),
            'matching_trade_ids': list(matching_trades),
            'extra_trade_details': extra_trade_details,
            'all_trades': trades
        }
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'analysis': analysis,
                'summary': {
                    'status': 'DISCREPANCY_FOUND' if extra_trades or missing_trades else 'SYNCED',
                    'message': f'RDS has {len(trades)} trades, OANDA has {len(expected_trade_ids)} trades. {len(extra_trades)} extra trades need removal.'
                }
            }, indent=2)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Database query failed: {str(e)}',
                'credentials_host': credentials.get('host', 'unknown')
            })
        }