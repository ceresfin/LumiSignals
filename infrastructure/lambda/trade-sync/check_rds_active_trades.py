#!/usr/bin/env python3
"""
Check active trades in RDS database to identify discrepancies with OANDA.
Expected: 4 trades (IDs: 1515, 914, 568, 516)
Current: 7 trades in RDS
"""

import json
import boto3
import psycopg2
from datetime import datetime
from typing import List, Dict, Any
from botocore.exceptions import ClientError


def get_rds_credentials() -> Dict[str, str]:
    """Retrieve RDS credentials from AWS Secrets Manager."""
    client = boto3.client('secretsmanager', region_name='us-east-1')
    
    try:
        response = client.get_secret_value(SecretId='lumisignals/rds/postgresql/credentials')
        secret = json.loads(response['SecretString'])
        
        return {
            'host': secret.get('host'),
            'port': secret.get('port', 5432),
            'database': secret.get('database', 'postgres'),
            'username': secret.get('username'),
            'password': secret.get('password')
        }
    except ClientError as e:
        print(f"Error retrieving secrets: {e}")
        raise


def query_active_trades(conn) -> List[Dict[str, Any]]:
    """Query all active trades from RDS."""
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
    
    with conn.cursor() as cursor:
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        
        return [dict(zip(columns, row)) for row in rows]


def format_trade_info(trade: Dict[str, Any]) -> str:
    """Format trade information for display."""
    return (
        f"Trade ID: {trade['trade_id']}\n"
        f"  Instrument: {trade['instrument']}\n"
        f"  Direction: {trade['direction']}\n"
        f"  Units: {trade['units']}\n"
        f"  Open Time: {trade['open_time']}\n"
        f"  Last Updated: {trade['last_updated']}\n"
    )


def main():
    """Main function to check RDS active trades."""
    print("Connecting to RDS to check active trades...")
    print("=" * 60)
    
    # Get credentials
    try:
        creds = get_rds_credentials()
        print("✓ Retrieved RDS credentials from Secrets Manager")
    except Exception as e:
        print(f"✗ Failed to get credentials: {e}")
        return
    
    # Connect to RDS
    try:
        conn = psycopg2.connect(
            host=creds['host'],
            port=creds['port'],
            database=creds['database'],
            user=creds['username'],
            password=creds['password']
        )
        print("✓ Connected to RDS successfully")
        print("=" * 60)
    except Exception as e:
        print(f"✗ Failed to connect to RDS: {e}")
        return
    
    try:
        # Query active trades
        trades = query_active_trades(conn)
        
        # Expected trade IDs from OANDA
        expected_trade_ids = {'1515', '914', '568', '516'}
        
        print(f"\nTotal trades in RDS: {len(trades)}")
        print(f"Expected trades from OANDA: {len(expected_trade_ids)} (IDs: {', '.join(sorted(expected_trade_ids))})")
        print("\n" + "=" * 60)
        
        # Display all trades
        print("\nALL TRADES IN RDS:")
        print("-" * 60)
        
        found_trade_ids = set()
        for trade in trades:
            print(format_trade_info(trade))
            found_trade_ids.add(str(trade['trade_id']))
        
        # Identify discrepancies
        print("\n" + "=" * 60)
        print("\nDISCREPANCY ANALYSIS:")
        print("-" * 60)
        
        # Extra trades in RDS (not in OANDA)
        extra_trades = found_trade_ids - expected_trade_ids
        if extra_trades:
            print(f"\n✗ EXTRA TRADES IN RDS (not in OANDA): {len(extra_trades)}")
            print(f"  Trade IDs: {', '.join(sorted(extra_trades))}")
            
            print("\n  Details of extra trades:")
            for trade in trades:
                if str(trade['trade_id']) in extra_trades:
                    print(f"\n  {'-' * 40}")
                    print(f"  {format_trade_info(trade).replace(chr(10), chr(10) + '  ')}")
        
        # Missing trades from OANDA
        missing_trades = expected_trade_ids - found_trade_ids
        if missing_trades:
            print(f"\n✗ MISSING TRADES (in OANDA but not in RDS): {len(missing_trades)}")
            print(f"  Trade IDs: {', '.join(sorted(missing_trades))}")
        
        # Matching trades
        matching_trades = expected_trade_ids & found_trade_ids
        if matching_trades:
            print(f"\n✓ MATCHING TRADES: {len(matching_trades)}")
            print(f"  Trade IDs: {', '.join(sorted(matching_trades))}")
        
        # Summary
        print("\n" + "=" * 60)
        print("\nSUMMARY:")
        print(f"- RDS has {len(trades)} total trades")
        print(f"- OANDA has {len(expected_trade_ids)} trades")
        print(f"- {len(extra_trades)} extra trades need to be removed from RDS")
        print(f"- {len(missing_trades)} trades need to be added to RDS")
        print(f"- {len(matching_trades)} trades are correctly synced")
        
    except Exception as e:
        print(f"\n✗ Error querying trades: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()
        print("\n✓ Connection closed")


if __name__ == "__main__":
    main()