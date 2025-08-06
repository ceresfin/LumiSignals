#!/usr/bin/env python3
"""
Main Lambda Handler for OANDA-Airtable Trade Sync
Consolidated and organized version
"""

import json
import boto3
import logging
from datetime import datetime, timezone

# Import sync modules (using try-except for Lambda environment)
try:
    from sync.closed_trades import sync_closed_trades_enhanced
    from sync.active_trades import sync_active_trades_enhanced
    from sync.pending_orders import sync_pending_orders_enhanced
    from sync.positions import sync_currency_pair_positions_enhanced
    from sync.exposures import sync_currency_exposures_enhanced
    from utils.oanda_api import fetch_all_oanda_data
except ImportError:
    # Fallback to absolute imports for Lambda environment
    import sys
    import os
    sys.path.append(os.path.dirname(__file__))
    from sync.closed_trades import sync_closed_trades_enhanced
    from sync.active_trades import sync_active_trades_enhanced
    from sync.pending_orders import sync_pending_orders_enhanced
    from sync.positions import sync_currency_pair_positions_enhanced
    from sync.exposures import sync_currency_exposures_enhanced
    from utils.oanda_api import fetch_all_oanda_data

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """Enhanced AWS Lambda handler for OANDA-Airtable sync"""
    
    start_time = datetime.now(timezone.utc)
    
    try:
        logger.info("🚀 Starting OANDA-Airtable sync")
        logger.info(f"📅 Timestamp: {start_time.isoformat()}")
        
        # Get credentials from AWS Secrets Manager
        credentials = get_credentials()
        oanda_creds = credentials['oanda']
        airtable_creds = credentials['airtable']
        
        # Run the sync process
        sync_result = run_sync(oanda_creds, airtable_creds)
        
        # Calculate duration
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"✅ Sync completed successfully in {duration:.1f}s")
        logger.info(f"📊 Results: {sync_result}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'OANDA-Airtable sync completed successfully',
                'duration_seconds': duration,
                'sync_results': sync_result,
                'timestamp': start_time.isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"❌ Sync failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'timestamp': start_time.isoformat()
            })
        }

def get_credentials():
    """Retrieve credentials from AWS Secrets Manager"""
    
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    
    # Get OANDA credentials
    oanda_secret = secrets_client.get_secret_value(
        SecretId='lumisignals/oanda/api/credentials'
    )
    oanda_creds = json.loads(oanda_secret['SecretString'])
    
    # Get Airtable credentials
    airtable_secret = secrets_client.get_secret_value(
        SecretId='lumisignals/airtable/api/credentials'
    )
    airtable_creds = json.loads(airtable_secret['SecretString'])
    
    return {
        'oanda': oanda_creds,
        'airtable': airtable_creds
    }

def run_sync(oanda_creds, airtable_creds):
    """Run the complete sync process"""
    
    # Setup OANDA connection parameters
    api_key = oanda_creds['api_key']
    account_id = oanda_creds['account_id']
    environment = oanda_creds.get('environment', 'practice')
    
    # Determine base URL
    if environment == 'practice':
        base_url = "https://api-fxpractice.oanda.com"
    else:
        base_url = "https://api-fxtrade.oanda.com"
    
    # Setup Airtable connection parameters
    airtable_headers = {
        'Authorization': f'Bearer {airtable_creds["api_token"]}',
        'Content-Type': 'application/json'
    }
    base_id = airtable_creds['base_id']
    
    # Fetch all OANDA data
    logger.info("📡 Fetching data from OANDA...")
    oanda_data = fetch_all_oanda_data(api_key, account_id, environment)
    
    results = {}
    
    # 1. Sync Active Trades
    logger.info("1️⃣ Syncing Active Trades...")
    results['active_trades'] = sync_active_trades_enhanced(
        oanda_data['trades'],
        oanda_data['prices'],
        airtable_headers,
        base_id
    )
    
    # 2. Sync Pending Orders
    logger.info("2️⃣ Syncing Pending Orders...")
    results['pending_orders'] = sync_pending_orders_enhanced(
        oanda_data['orders'],
        oanda_data['prices'],
        airtable_headers,
        base_id
    )
    
    # 3. Sync Currency Exposures
    logger.info("3️⃣ Syncing Currency Exposures...")
    account_balance = float(oanda_data['account'].get('account', {}).get('balance', 100000.0))
    logger.info(f"💰 Account balance for Risk % calculation: ${account_balance:,.2f}")
    results['exposures'] = sync_currency_exposures_enhanced(
        oanda_data['positions'],
        airtable_headers,
        base_id,
        account_balance
    )
    
    # 4. Sync Currency Pair Positions
    logger.info("4️⃣ Syncing Currency Pair Positions...")
    results['positions'] = sync_currency_pair_positions_enhanced(
        oanda_data['positions'],
        airtable_headers,
        base_id
    )
    
    # 5. Sync Closed Trades (ALL from June 2025)
    logger.info("5️⃣ Syncing Closed Trades...")
    results['closed_trades'] = sync_closed_trades_enhanced(
        api_key,
        account_id,
        base_url,
        airtable_headers,
        base_id
    )
    
    # Calculate totals
    total_operations = sum(
        result.get('operations', 0) 
        for result in results.values() 
        if isinstance(result, dict)
    )
    
    results['total_operations'] = total_operations
    
    return results

# For local testing
if __name__ == "__main__":
    print("🧪 Testing OANDA-Airtable sync locally...")
    
    # Create a test event
    test_event = {}
    test_context = {}
    
    # Run the handler
    result = lambda_handler(test_event, test_context)
    
    print(f"✅ Result: {json.dumps(result, indent=2)}")