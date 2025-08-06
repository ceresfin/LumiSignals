#!/usr/bin/env python3
"""
Query RDS active_trades table via Fargate container that already has database access.
"""

import boto3
import json
import subprocess
import time

def get_running_tasks():
    """Get running tasks in the lumisignals cluster."""
    ecs_client = boto3.client('ecs', region_name='us-east-1')
    
    response = ecs_client.list_tasks(
        cluster='lumisignals-cluster',
        serviceName='lumisignals-data-orchestrator',
        desiredStatus='RUNNING'
    )
    
    if not response['taskArns']:
        print("❌ No running tasks found")
        return None
    
    # Get task details
    task_arn = response['taskArns'][0]
    task_id = task_arn.split('/')[-1]
    
    print(f"✅ Found running task: {task_id}")
    return task_id

def execute_query_in_fargate(task_id):
    """Execute query in Fargate container via ECS exec."""
    
    # SQL query to get active trades
    sql_query = """
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
    
    # Python script to run inside the container
    python_script = f'''
import psycopg2
import json
import sys
from datetime import datetime

# Database connection details (should be available in container environment)
import os

try:
    # Use the same connection method as the data orchestrator
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "lumisignals-postgresql.cg12a06y29s3.us-east-1.rds.amazonaws.com"),
        database=os.environ.get("DB_NAME", "lumisignals_trading"),
        user=os.environ.get("DB_USER", "lumisignals"),
        password=os.environ.get("DB_PASSWORD"),
        port=5432
    )
    
    cursor = conn.cursor()
    cursor.execute("""{sql_query}""")
    
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    
    trades = []
    for row in rows:
        trade = dict(zip(columns, row))
        # Convert datetime objects to strings
        for key, value in trade.items():
            if hasattr(value, "isoformat"):
                trade[key] = value.isoformat()
            elif value is None:
                trade[key] = None
            else:
                trade[key] = str(value)
        trades.append(trade)
    
    # Expected trade IDs from OANDA
    expected_trade_ids = {{"1515", "914", "568", "516"}}
    found_trade_ids = {{str(trade["trade_id"]) for trade in trades}}
    
    extra_trades = found_trade_ids - expected_trade_ids
    missing_trades = expected_trade_ids - found_trade_ids
    
    result = {{
        "success": True,
        "total_trades": len(trades),
        "expected_trades": len(expected_trade_ids),
        "extra_trades": list(extra_trades),
        "missing_trades": list(missing_trades),
        "trades": trades
    }}
    
    print("=== RDS ACTIVE TRADES QUERY RESULT ===")
    print(json.dumps(result, indent=2))
    
    cursor.close()
    conn.close()
    
except Exception as e:
    error_result = {{
        "success": False,
        "error": str(e),
        "error_type": type(e).__name__
    }}
    print("=== RDS QUERY ERROR ===")
    print(json.dumps(error_result, indent=2))
    sys.exit(1)
'''
    
    # Write Python script to a temporary file in the container and execute it
    command = [
        'aws', 'ecs', 'execute-command',
        '--cluster', 'lumisignals-cluster',
        '--task', task_id,
        '--container', 'lumisignals-data-orchestrator',
        '--interactive',
        '--command', f'python3 -c "{python_script}"'
    ]
    
    print("🔄 Executing query in Fargate container...")
    
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print("✅ Query executed successfully")
            print("\n" + "="*60)
            print("RESULT:")
            print("="*60)
            print(result.stdout)
            
            # Try to extract JSON from output
            lines = result.stdout.split('\n')
            json_started = False
            json_lines = []
            
            for line in lines:
                if "=== RDS ACTIVE TRADES QUERY RESULT ===" in line:
                    json_started = True
                    continue
                elif "=== RDS QUERY ERROR ===" in line:
                    json_started = True
                    continue
                elif json_started and line.strip():
                    json_lines.append(line)
            
            if json_lines:
                try:
                    json_result = json.loads('\\n'.join(json_lines))
                    return json_result
                except json.JSONDecodeError:
                    print("⚠️  Could not parse JSON result")
                    return {{"raw_output": result.stdout}}
            
        else:
            print("❌ Query failed")
            print(f"Exit code: {result.returncode}")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            return {{"error": f"Command failed with exit code {result.returncode}", "stderr": result.stderr}}
            
    except subprocess.TimeoutExpired:
        print("❌ Query timed out")
        return {{"error": "Query timed out after 60 seconds"}}
    except Exception as e:
        print(f"❌ Error executing query: {e}")
        return {{"error": str(e)}}

def main():
    """Main function to query RDS via Fargate."""
    print("🚀 Querying RDS active_trades table via Fargate container...")
    print("="*60)
    
    # Get running task
    task_id = get_running_tasks()
    if not task_id:
        return
    
    # Execute query
    result = execute_query_in_fargate(task_id)
    
    if result and result.get("success"):
        print("\n" + "="*60)
        print("📊 ANALYSIS SUMMARY:")
        print("="*60)
        print(f"Total trades in RDS: {result['total_trades']}")
        print(f"Expected from OANDA: {result['expected_trades']}")
        print(f"Extra trades to remove: {len(result['extra_trades'])}")
        print(f"Missing trades to add: {len(result['missing_trades'])}")
        
        if result['extra_trades']:
            print(f"\\n🔴 Extra trade IDs in RDS: {', '.join(result['extra_trades'])}")
            
            # Show details of extra trades
            print("\\n📋 Details of extra trades:")
            for trade in result['trades']:
                if str(trade['trade_id']) in result['extra_trades']:
                    print(f"  - Trade {trade['trade_id']}: {trade['instrument']} {trade['direction']} {trade['units']} units")
                    print(f"    Open: {trade['open_time']}, Updated: {trade['last_updated']}")
        
        if result['missing_trades']:
            print(f"\\n🟡 Missing trade IDs from OANDA: {', '.join(result['missing_trades'])}")
            
        print(f"\\n✅ Correctly synced trades: {result['expected_trades'] - len(result['missing_trades'])}")
        
    else:
        print("\\n❌ Query failed or returned no results")
        if result:
            print(f"Error: {result.get('error', 'Unknown error')}")

if __name__ == "__main__":
    main()