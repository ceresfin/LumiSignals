#!/usr/bin/env python3
"""
Integration Script for Airtable-Compatible Data Collection in Fargate
=====================================================================

This script modifies the existing Fargate Data Orchestrator to:
1. Add Airtable-compatible data collection alongside existing functionality
2. Populate the 6 RDS tables that match Airtable structure
3. Run on a schedule similar to Airtable Lambda (every 15 minutes)

Usage:
    python integrate_airtable_collector.py
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

# Import the new Airtable-compatible components
from airtable_compatible_data_collector import AirtableCompatibleDataCollector
from airtable_compatible_database_manager import AirtableCompatibleDatabaseManager

logger = logging.getLogger(__name__)

class AirtableDataOrchestrator:
    """
    Extension to the main Data Orchestrator that adds Airtable-compatible data collection
    This runs alongside the existing Redis/market data collection
    """
    
    def __init__(self, oanda_client, database_pool):
        self.oanda_client = oanda_client
        self.db_manager = AirtableCompatibleDatabaseManager(database_pool)
        self.collector = AirtableCompatibleDataCollector(oanda_client, self.db_manager)
        
        # Sync intervals (matching Airtable Lambda)
        self.market_hours_interval = 15 * 60  # 15 minutes during market hours
        self.off_hours_interval = 2 * 60 * 60  # 2 hours off market
        
    async def start_airtable_sync_loop(self):
        """
        Main loop for Airtable-compatible data sync
        Runs every 15 minutes during market hours, 2 hours otherwise
        """
        logger.info("🚀 Starting Airtable-compatible data sync loop...")
        
        while True:
            try:
                # Determine if market hours
                current_hour = datetime.now(timezone.utc).hour
                current_day = datetime.now(timezone.utc).weekday()
                
                # Market hours: Mon-Fri 13:00-21:00 UTC (9 AM - 5 PM EST)
                is_market_hours = (
                    current_day < 5 and  # Monday = 0, Friday = 4
                    13 <= current_hour < 21
                )
                
                # Run the sync
                logger.info(f"📊 Starting Airtable data sync (Market hours: {is_market_hours})")
                start_time = datetime.now()
                
                success = await self.collector.collect_and_sync_all_tables()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                if success:
                    logger.info(f"✅ Airtable sync completed successfully in {duration:.2f}s")
                    
                    # Get validation summary
                    validation = await self.db_manager.get_data_validation_summary()
                    if validation:
                        logger.info("📋 Data validation summary:")
                        for table_data in validation:
                            logger.info(f"  - {table_data['table_name']}: {table_data['record_count']} records")
                else:
                    logger.error(f"❌ Airtable sync failed after {duration:.2f}s")
                
                # Sleep until next sync
                sleep_interval = self.market_hours_interval if is_market_hours else self.off_hours_interval
                logger.info(f"💤 Sleeping for {sleep_interval/60:.0f} minutes until next sync...")
                await asyncio.sleep(sleep_interval)
                
            except Exception as e:
                logger.error(f"❌ Critical error in Airtable sync loop: {str(e)}", exc_info=True)
                # Sleep 5 minutes on error before retry
                await asyncio.sleep(300)

# ========== INTEGRATION INSTRUCTIONS ==========

"""
To integrate this into your existing Fargate Data Orchestrator:

1. **Add to main.py imports:**
```python
from .integrate_airtable_collector import AirtableDataOrchestrator
```

2. **In main.py, add database connection pool:**
```python
# Add after Redis manager initialization
database_pool = await create_database_pool(settings)
airtable_orchestrator = AirtableDataOrchestrator(
    data_orchestrator.oanda_client,
    database_pool
)
```

3. **Add to the asyncio task group:**
```python
# In the main run_orchestrator function
tasks = [
    asyncio.create_task(data_orchestrator.start_market_data_collection()),
    asyncio.create_task(data_orchestrator.start_candle_collection()),
    asyncio.create_task(airtable_orchestrator.start_airtable_sync_loop()),  # ADD THIS
    asyncio.create_task(health_monitor.start_monitoring()),
]
```

4. **Add database pool creation function:**
```python
async def create_database_pool(settings):
    import pg8000
    import boto3
    import json
    
    # Get RDS credentials from Secrets Manager
    secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
    secret_response = secrets_client.get_secret_value(
        SecretId="lumisignals/rds/postgresql/credentials"
    )
    rds_config = json.loads(secret_response['SecretString'])
    
    # Create connection pool
    # Note: pg8000 doesn't have built-in pooling, so you might want to use
    # asyncpg or implement a simple pool
    return rds_config  # For now, return config and create connections as needed
```

5. **Update requirements.txt:**
```
pg8000>=1.30.0
boto3>=1.26.0
```

6. **Environment variables to add:**
```
AWS_DEFAULT_REGION=us-east-1
```

7. **Deploy updated Fargate task:**
```bash
# Build and push new Docker image
docker build -t lumisignals-data-orchestrator .
docker tag lumisignals-data-orchestrator:latest YOUR_ECR_URI
docker push YOUR_ECR_URI

# Update ECS service to use new image
aws ecs update-service --cluster LumiSignals-prod-cluster \
    --service data-orchestrator-service --force-new-deployment
```
"""

# ========== TEST FUNCTION ==========

async def test_airtable_sync():
    """Test function to verify Airtable sync works"""
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from config import Settings
    from oanda_client import OandaClient
    
    # Initialize components
    settings = Settings()
    oanda_client = OandaClient(settings)
    
    # Mock database pool for testing
    class MockPool:
        async def getconn(self):
            # In production, this would return a real connection
            return None
        async def putconn(self, conn):
            pass
    
    mock_pool = MockPool()
    
    # Create orchestrator and run single sync
    orchestrator = AirtableDataOrchestrator(oanda_client, mock_pool)
    
    logger.info("🧪 Running test sync...")
    success = await orchestrator.collector.collect_and_sync_all_tables()
    
    if success:
        logger.info("✅ Test sync completed successfully!")
    else:
        logger.error("❌ Test sync failed!")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run test
    asyncio.run(test_airtable_sync())