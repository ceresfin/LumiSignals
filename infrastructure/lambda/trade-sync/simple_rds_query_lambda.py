import json
import boto3
import pg8000.native
from datetime import datetime
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """Simple query of RDS active_trades table using pg8000."""
    
    # Expected trade IDs from OANDA (from Fargate logs)
    expected_trade_ids = {'1515', '914', '568', '516'}
    
    try:
        # Get RDS credentials from Secrets Manager
        secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
        response = secrets_client.get_secret_value(SecretId='lumisignals/rds/postgresql/credentials')
        secret = json.loads(response['SecretString'])
        
        # Connect to RDS using pg8000
        conn = pg8000.native.Connection(
            host=secret.get('host'),
            port=secret.get('port', 5432),
            database=secret.get('database', 'postgres'),
            user=secret.get('username'),
            password=secret.get('password')
        )
        
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
        
        rows = conn.run(query)
        
        # Convert to list of dictionaries
        columns = ['trade_id', 'instrument', 'direction', 'units', 'open_time', 'last_updated']
        trades = []
        
        for row in rows:
            trade = dict(zip(columns, row))
            # Convert datetime objects to strings for JSON serialization
            for key, value in trade.items():
                if hasattr(value, 'isoformat'):
                    trade[key] = value.isoformat()
                elif value is None:
                    trade[key] = None
                else:
                    trade[key] = str(value)
            trades.append(trade)
        
        conn.close()
        
        # Analyze discrepancies
        found_trade_ids = {str(trade['trade_id']) for trade in trades}
        extra_trades = found_trade_ids - expected_trade_ids
        missing_trades = expected_trade_ids - found_trade_ids
        matching_trades = expected_trade_ids & found_trade_ids
        
        # Get details of extra trades
        extra_trade_details = [
            trade for trade in trades 
            if str(trade['trade_id']) in extra_trades
        ]
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'timestamp': datetime.utcnow().isoformat(),
                'database_info': {
                    'host': secret.get('host'),
                    'database': secret.get('database')
                },
                'analysis': {
                    'total_trades_in_rds': len(trades),
                    'expected_trades_from_oanda': len(expected_trade_ids),
                    'matching_trades': len(matching_trades),
                    'extra_trades_count': len(extra_trades),
                    'missing_trades_count': len(missing_trades)
                },
                'trade_ids': {
                    'expected_from_oanda': sorted(list(expected_trade_ids)),
                    'found_in_rds': sorted(list(found_trade_ids)),
                    'extra_in_rds': sorted(list(extra_trades)),
                    'missing_from_rds': sorted(list(missing_trades)),
                    'matching': sorted(list(matching_trades))
                },
                'extra_trades_details': extra_trade_details,
                'all_trades': trades,
                'summary': {
                    'status': 'DISCREPANCY_FOUND' if extra_trades or missing_trades else 'SYNCED',
                    'message': f'RDS has {len(trades)} trades, OANDA has {len(expected_trade_ids)} trades. {len(extra_trades)} extra trades found, {len(missing_trades)} missing trades.'
                }
            }, indent=2, default=str)
        }
        
    except Exception as e:
        import traceback
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc()
            }, indent=2)
        }