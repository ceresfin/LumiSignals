#!/usr/bin/env python3
"""
Run RDS query via SSM Session Manager on EC2 instance.
"""

import boto3
import json
import time
import subprocess

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

def run_ssm_command(instance_id, credentials):
    """Run PostgreSQL query via SSM on EC2 instance."""
    
    ssm_client = boto3.client('ssm', region_name='us-east-1')
    
    # Create the PostgreSQL connection command
    psql_command = f"""
export PGPASSWORD='{credentials['password']}'
psql -h {credentials['host']} -p {credentials.get('port', 5432)} -U {credentials['username']} -d {credentials.get('database', 'postgres')} << 'EOF'

-- Query active trades from RDS to identify discrepancies with OANDA
-- Expected trades from OANDA: 1515, 914, 568, 516 (4 trades total)

\\echo '=== RDS Active Trades Analysis ==='
\\echo 'Expected OANDA trades: 1515, 914, 568, 516'
\\echo ''

-- Show all active trades
\\echo '--- ALL ACTIVE TRADES IN RDS ---'
SELECT 
    trade_id,
    instrument,
    direction,
    units,
    open_time,
    last_updated
FROM active_trades
ORDER BY trade_id DESC;

\\echo ''
\\echo '--- TRADE COUNT ANALYSIS ---'
SELECT 
    COUNT(*) as total_trades_in_rds,
    COUNT(*) - 4 as extra_trades_count
FROM active_trades;

\\echo ''
\\echo '--- EXTRA TRADES (not in OANDA) ---'
SELECT 
    trade_id,
    instrument,
    direction,
    units,
    open_time,
    'EXTRA - NOT IN OANDA' as status
FROM active_trades
WHERE trade_id NOT IN ('1515', '914', '568', '516')
ORDER BY trade_id DESC;

\\echo ''
\\echo '--- MISSING TRADES (in OANDA but not RDS) ---'
WITH expected_trades AS (
    SELECT unnest(ARRAY['1515', '914', '568', '516']) as expected_trade_id
)
SELECT 
    expected_trade_id,
    'MISSING FROM RDS' as status
FROM expected_trades
WHERE expected_trade_id NOT IN (
    SELECT trade_id::text FROM active_trades
);

\\echo ''
\\echo '--- SUMMARY ---'
WITH stats AS (
    SELECT 
        COUNT(*) as rds_trades,
        COUNT(CASE WHEN trade_id::text IN ('1515', '914', '568', '516') THEN 1 END) as matching_trades,
        COUNT(CASE WHEN trade_id::text NOT IN ('1515', '914', '568', '516') THEN 1 END) as extra_trades
    FROM active_trades
)
SELECT 
    'RDS Trades: ' || rds_trades as summary,
    'OANDA Trades: 4' as oanda_count,
    'Matching: ' || matching_trades as matching,
    'Extra in RDS: ' || extra_trades as extra,
    'Missing in RDS: ' || (4 - matching_trades) as missing
FROM stats;

EOF
"""

    try:
        print(f"🔄 Sending command to instance {instance_id}...")
        
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
        
        max_attempts = 30  # 30 seconds
        for attempt in range(max_attempts):
            time.sleep(1)
            
            try:
                invocation = ssm_client.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id
                )
                
                status = invocation['Status']
                print(f"Status: {status}")
                
                if status == 'Success':
                    print("✅ Command completed successfully!")
                    print("\n" + "="*80)
                    print("🔍 QUERY RESULTS:")
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
    print("🚀 Querying RDS active_trades table via SSM...")
    print("="*60)
    
    # Get credentials
    credentials = get_rds_credentials()
    if not credentials:
        return
    
    print(f"✅ Retrieved credentials for {credentials['host']}")
    
    # Try both EC2 instances
    instance_ids = ['i-082bf92c7ffb3af30', 'i-02c77fcae71ac188a']
    
    for instance_id in instance_ids:
        print(f"\n📡 Trying instance {instance_id}...")
        
        result = run_ssm_command(instance_id, credentials)
        
        if result:
            print(f"\n✅ Successfully queried RDS via instance {instance_id}")
            
            # Parse and summarize results
            if "EXTRA - NOT IN OANDA" in result:
                print("\n🔴 DISCREPANCY DETECTED!")
                print("There are extra trades in RDS that are not in OANDA.")
            
            if "Missing in RDS: 0" in result and "Extra in RDS: 0" in result:
                print("\n✅ TRADES ARE IN SYNC!")
            
            break
        else:
            print(f"❌ Failed to query via instance {instance_id}")
    
    else:
        print("\n❌ Failed to query RDS via any EC2 instance")

if __name__ == "__main__":
    main()