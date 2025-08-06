#!/usr/bin/env python3
"""
Airtable API Utilities
Handles common Airtable operations and pagination
"""

import requests
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def fetch_all_airtable_records(table_url: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetch all records from an Airtable table with pagination support"""
    
    all_records = []
    offset = None
    
    while True:
        # Build URL with offset if provided
        url = table_url
        if offset:
            url = f"{table_url}?offset={offset}"
        
        try:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                records = data.get('records', [])
                all_records.extend(records)
                
                # Check if there are more pages
                offset = data.get('offset')
                if not offset:
                    break
                    
                logger.info(f"Fetched {len(records)} records, continuing with offset...")
            else:
                logger.error(f"Error fetching Airtable records: {response.status_code} - {response.text}")
                break
                
        except Exception as e:
            logger.error(f"Exception fetching Airtable records: {str(e)}")
            break
    
    logger.info(f"Total records fetched: {len(all_records)}")
    return all_records

def create_airtable_record(table_url: str, headers: Dict[str, str], fields: Dict[str, Any]) -> bool:
    """Create a single Airtable record"""
    
    try:
        response = requests.post(
            table_url,
            headers=headers,
            json={'fields': fields}
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Created record successfully")
            return True
        else:
            logger.error(f"❌ Failed to create record: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception creating record: {str(e)}")
        return False

def update_airtable_record(table_url: str, record_id: str, headers: Dict[str, str], fields: Dict[str, Any]) -> bool:
    """Update a single Airtable record"""
    
    try:
        update_url = f"{table_url}/{record_id}"
        response = requests.patch(
            update_url,
            headers=headers,
            json={'fields': fields}
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Updated record {record_id} successfully")
            return True
        else:
            logger.error(f"❌ Failed to update record {record_id}: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception updating record {record_id}: {str(e)}")
        return False

def delete_airtable_record(table_url: str, record_id: str, headers: Dict[str, str]) -> bool:
    """Delete a single Airtable record"""
    
    try:
        delete_url = f"{table_url}/{record_id}"
        response = requests.delete(delete_url, headers=headers)
        
        if response.status_code == 200:
            logger.info(f"✅ Deleted record {record_id} successfully")
            return True
        else:
            logger.error(f"❌ Failed to delete record {record_id}: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception deleting record {record_id}: {str(e)}")
        return False

def batch_create_records(table_url: str, headers: Dict[str, str], records: List[Dict[str, Any]], batch_size: int = 10) -> Dict[str, int]:
    """Create multiple Airtable records in batches"""
    
    created = 0
    failed = 0
    
    # Process in batches
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        
        # Prepare batch data
        batch_data = {'records': [{'fields': record} for record in batch]}
        
        try:
            response = requests.post(
                table_url,
                headers=headers,
                json=batch_data
            )
            
            if response.status_code == 200:
                created += len(batch)
                logger.info(f"✅ Created batch of {len(batch)} records")
            else:
                failed += len(batch)
                logger.error(f"❌ Failed to create batch: {response.status_code} - {response.text}")
                
        except Exception as e:
            failed += len(batch)
            logger.error(f"❌ Exception creating batch: {str(e)}")
    
    return {'created': created, 'failed': failed}