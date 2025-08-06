#!/usr/bin/env python3
"""
Check the correct database - lumisignals_trading instead of postgres.
"""

import boto3
import json
import time

def get_rds_credentials():
    """Get RDS credentials from Secrets Manager."""
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    try:
        response = secrets_client.get_secret_value(SecretId='lumisignals/rds/postgresql/credentials')
        secret = json.loads(response['SecretString'])
        return secret
    except Exception as e:
        print(f"❌ Error getting credentials: {e}")
        return None

def check_database_via_ssm(instance_id, credentials, database_name):
    """Check specific database in RDS via SSM."""
    
    ssm_client = boto3.client('ssm', region_name='us-east-1')
    
    # Create the PostgreSQL command to check specific database
    psql_command = f"""
export PGPASSWORD='{credentials['password']}'

echo "=== CHECKING DATABASE: {database_name} ==="
psql -h {credentials['host']} -p {credentials.get('port', 5432)} -U {credentials['username']} -d {database_name} << 'EOF'

\\echo '=== DATABASE INFORMATION ==='
SELECT current_database() as database_name;

\\echo ''
\\echo '=== ALL TABLES IN PUBLIC SCHEMA ==='
SELECT 
    schemaname,
    tablename,
    tableowner
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY tablename;

\\echo ''
\\echo '=== CHECK FOR ACTIVE_TRADES TABLE ==='
SELECT 
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'active_trades'
ORDER BY ordinal_position;

\\echo ''
\\echo '=== COUNT RECORDS IN ACTIVE_TRADES (if exists) ==='
SELECT COUNT(*) as total_records FROM active_trades;

\\echo ''
\\echo '=== SAMPLE ACTIVE_TRADES RECORDS ==='
SELECT 
    trade_id,
    instrument, 
    direction,
    units,
    open_time
FROM active_trades
ORDER BY trade_id
LIMIT 10;

EOF
"""

    try:
        print(f"🔄 Checking database '{database_name}' in instance {instance_id}...")
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                'commands': [psql_command]
            },
            TimeoutSeconds=120
        )
        
        command_id = response['Command']['CommandId']
        print(f"✅ Command sent: {command_id}")
        
        # Wait for command to complete
        print("⏳ Waiting for command to complete...")
        
        max_attempts = 30
        for attempt in range(max_attempts):
            time.sleep(1)
            
            try:
                invocation = ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )
                
                status = invocation['Status']
                
                if status == 'Success':
                    print("✅ Command completed successfully!")
                    print("\n" + "="*80)
                    print(f"📊 DATABASE '{database_name}' RESULTS:")
                    print("="*80)
                    output = invocation['StandardOutputContent']
                    print(output)
                    
                    if invocation.get('StandardErrorContent'):
                        print("\n" + "="*80)
                        print("⚠️  STDERR:")
                        print("="*80)
                        stderr = invocation['StandardErrorContent']
                        print(stderr)
                        
                        # Return both for analysis
                        return output, stderr
                    
                    return output, None
                    
                elif status == 'Failed':
                    print("❌ Command failed!")
                    error = invocation.get('StandardErrorContent', 'No error details')
                    print(f"Error: {error}")
                    return None, error
                    
                elif status in ['InProgress', 'Pending']:
                    continue
                else:
                    print(f"❌ Unexpected status: {status}")
                    return None, f"Unexpected status: {status}"
                    
            except Exception as e:
                print(f"Error checking command status: {e}")
                continue
        
        print("❌ Command timed out")
        return None, "Command timed out"
        
    except Exception as e:
        print(f"❌ Error running SSM command: {e}")
        return None, str(e)

def main():
    """Main function."""
    print("🔍 Checking correct RDS database for active_trades...")
    print("="*60)
    
    # Get credentials
    credentials = get_rds_credentials()
    if not credentials:
        return
    
    print(f"✅ Retrieved credentials for {credentials['host']}")
    
    # Try both database names
    databases_to_check = [
        'lumisignals_trading',  # Most likely correct database
        'postgres',             # Default database
        credentials.get('database', 'postgres')  # Whatever is in secrets
    ]
    
    instance_id = 'i-082bf92c7ffb3af30'
    
    for db_name in databases_to_check:
        print(f"\n{'='*60}")
        print(f"🗃️  CHECKING DATABASE: {db_name}")
        print("="*60)
        
        output, stderr = check_database_via_ssm(instance_id, credentials, db_name)
        
        if output:
            # Analyze the output
            if "active_trades" in output and "total_records" in output:
                print(f"\n✅ FOUND active_trades table in database '{db_name}'!")
                
                # Extract record count
                lines = output.split('\n')
                for line in lines:
                    if 'total_records' in line and '|' in line:
                        print(f"📊 {line.strip()}")
                
                # Check if there are actual records
                if any('1515' in line or '914' in line or '568' in line or '516' in line for line in lines):
                    print("✅ Found expected OANDA trade IDs in the table")
                else:
                    print("⚠️  Expected OANDA trade IDs not found in sample")
                
                break
            elif stderr and "does not exist" in stderr:
                print(f"❌ Database '{db_name}' exists but no active_trades table")
            elif stderr and "FATAL" in stderr:
                print(f"❌ Cannot connect to database '{db_name}'")
            else:
                print(f"❓ Unclear result for database '{db_name}'")
        else:
            print(f"❌ Failed to check database '{db_name}'")
    
    else:
        print("\n❌ Could not find active_trades table in any database!")
        print("This confirms that the RDS database doesn't have active trades data.")
        print("The Fargate logs claiming '7 trades in RDS' might be:")
        print("1. Reading from a different data source")
        print("2. Using cached/stale data")  
        print("3. Referring to a different table or database")

if __name__ == "__main__":
    main()