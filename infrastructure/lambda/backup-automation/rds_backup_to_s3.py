import boto3
import json
from datetime import datetime
import os

def lambda_handler(event, context):
    """
    Automated backup Lambda for LumiSignals
    Exports RDS snapshots and Lambda configs to S3
    """
    
    rds = boto3.client('rds')
    s3 = boto3.client('s3')
    lambda_client = boto3.client('lambda')
    
    backup_bucket = 'lumisignals-backups-e5558a85'
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    
    results = {
        'timestamp': timestamp,
        'backups': []
    }
    
    # 1. Export latest RDS snapshot metadata
    try:
        db_instance = 'lumisignals-postgresql'
        snapshots = rds.describe_db_snapshots(
            DBInstanceIdentifier=db_instance,
            SnapshotType='automated'
        )
        
        if snapshots['DBSnapshots']:
            latest_snapshot = sorted(
                snapshots['DBSnapshots'], 
                key=lambda x: x['SnapshotCreateTime'], 
                reverse=True
            )[0]
            
            snapshot_info = {
                'db_instance': db_instance,
                'snapshot_id': latest_snapshot['DBSnapshotIdentifier'],
                'created_time': str(latest_snapshot['SnapshotCreateTime']),
                'size_gb': latest_snapshot.get('AllocatedStorage', 0),
                'status': latest_snapshot['Status']
            }
            
            # Save snapshot metadata
            s3.put_object(
                Bucket=backup_bucket,
                Key=f'rds-snapshots/{timestamp}_snapshot_info.json',
                Body=json.dumps(snapshot_info, indent=2),
                ServerSideEncryption='AES256'
            )
            
            results['backups'].append({
                'type': 'rds_snapshot_metadata',
                'status': 'success',
                'details': snapshot_info
            })
            
    except Exception as e:
        results['backups'].append({
            'type': 'rds_snapshot_metadata',
            'status': 'error',
            'error': str(e)
        })
    
    # 2. Backup critical Lambda function configurations
    critical_lambdas = [
        'lumisignals-dashboard-api',
        'lumisignals-direct-candlestick-api',
        'lumisignals-central-data-collector',
        'oanda-trading-bot-minimal'
    ]
    
    for func_name in critical_lambdas:
        try:
            # Get function configuration
            func_config = lambda_client.get_function_configuration(
                FunctionName=func_name
            )
            
            # Remove response metadata
            func_config.pop('ResponseMetadata', None)
            
            # Save configuration
            s3.put_object(
                Bucket=backup_bucket,
                Key=f'lambda-configs/{timestamp}/{func_name}_config.json',
                Body=json.dumps(func_config, indent=2, default=str),
                ServerSideEncryption='AES256'
            )
            
            results['backups'].append({
                'type': 'lambda_config',
                'function': func_name,
                'status': 'success'
            })
            
        except Exception as e:
            results['backups'].append({
                'type': 'lambda_config',
                'function': func_name,
                'status': 'error',
                'error': str(e)
            })
    
    # 3. Create backup inventory
    try:
        # List all backups in the bucket
        paginator = s3.get_paginator('list_objects_v2')
        backup_inventory = []
        
        for page in paginator.paginate(Bucket=backup_bucket):
            if 'Contents' in page:
                for obj in page['Contents']:
                    backup_inventory.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': str(obj['LastModified'])
                    })
        
        # Save inventory
        s3.put_object(
            Bucket=backup_bucket,
            Key=f'inventory/{timestamp}_backup_inventory.json',
            Body=json.dumps({
                'generated_at': timestamp,
                'total_files': len(backup_inventory),
                'files': backup_inventory
            }, indent=2),
            ServerSideEncryption='AES256'
        )
        
        results['backups'].append({
            'type': 'inventory',
            'status': 'success',
            'total_files': len(backup_inventory)
        })
        
    except Exception as e:
        results['backups'].append({
            'type': 'inventory',
            'status': 'error',
            'error': str(e)
        })
    
    return {
        'statusCode': 200,
        'body': json.dumps(results)
    }