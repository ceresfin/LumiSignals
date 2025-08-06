#!/usr/bin/env python3
"""
Check what tables exist in RDS database.
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

def check_tables_via_ssm(instance_id, credentials):
    """Check what tables exist in RDS via SSM."""
    
    ssm_client = boto3.client('ssm', region_name='us-east-1')
    
    # Create the PostgreSQL command to list tables
    psql_command = f"""
export PGPASSWORD='{credentials['password']}'
psql -h {credentials['host']} -p {credentials.get('port', 5432)} -U {credentials['username']} -d {credentials.get('database', 'postgres')} << 'EOF'

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
\\echo '=== TABLES CONTAINING "trade" IN NAME ==='
SELECT 
    schemaname,
    tablename,
    tableowner
FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename LIKE '%trade%'
ORDER BY tablename;

\\echo ''
\\echo '=== TABLES CONTAINING "active" IN NAME ==='
SELECT 
    schemaname,
    tablename,
    tableowner
FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename LIKE '%active%'
ORDER BY tablename;

\\echo ''
\\echo '=== ALL TABLES IN DATABASE ==='
SELECT 
    table_schema,
    table_name,
    table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_schema, table_name;

EOF
"""

    try:
        print(f"🔄 Checking tables in instance {instance_id}...")
        
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
                    print("📊 DATABASE TABLES:")
                    print("="*80)
                    print(invocation['StandardOutputContent'])
                    
                    if invocation.get('StandardErrorContent'):
                        print("\n" + "="*80)
                        print("⚠️  STDERR:")
                        print("="*80)
                        print(invocation['StandardErrorContent'])
                    
                    return invocation['StandardOutputContent']
                    
                elif status == 'Failed':
                    print("❌ Command failed!")
                    print(f"Error: {invocation.get('StandardErrorContent', 'No error details')}")
                    return None
                    
                elif status in ['InProgress', 'Pending']:
                    continue
                else:
                    print(f"❌ Unexpected status: {status}")
                    return None
                    
            except Exception as e:
                print(f"Error checking command status: {e}")
                continue
        
        print("❌ Command timed out")
        return None
        
    except Exception as e:
        print(f"❌ Error running SSM command: {e}")
        return None

def main():
    """Main function."""
    print("🔍 Checking RDS database tables...")
    print("="*60)
    
    # Get credentials
    credentials = get_rds_credentials()
    if not credentials:
        return
    
    print(f"✅ Retrieved credentials for {credentials['host']}")
    print(f"Database: {credentials.get('database', 'postgres')}")
    
    # Try the first EC2 instance
    instance_id = 'i-082bf92c7ffb3af30'
    
    result = check_tables_via_ssm(instance_id, credentials)
    
    if result:
        print(f"\n✅ Successfully queried database structure")
        
        # Analyze results
        if "active_trades" in result:
            print("\n✅ active_trades table EXISTS")
        else:
            print("\n❌ active_trades table DOES NOT EXIST")
            print("This explains why there's a discrepancy in trade counts!")
        
        # Check for similar table names
        trade_related = []
        for line in result.split('\n'):
            if 'trade' in line.lower() and '|' in line:
                trade_related.append(line.strip())
        
        if trade_related:
            print(f"\n📋 Found {len(trade_related)} trade-related tables:")
            for table in trade_related:
                print(f"  {table}")
    else:
        print("❌ Failed to query database structure")

if __name__ == "__main__":
    main()