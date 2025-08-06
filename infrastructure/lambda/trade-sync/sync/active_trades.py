#!/usr/bin/env python3
"""
Active Trades Sync Module
Handles synchronization of active/open trades from OANDA to Airtable
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def sync_active_trades_enhanced(trades: List[Dict], current_prices: Dict[str, float], 
                              airtable_headers: Dict[str, str], base_id: str) -> Dict[str, int]:
    """Enhanced Active Trades sync with intelligent updates"""
    
    table_url = f"https://api.airtable.com/v0/{base_id}/Active%20Trades"
    
    # Import utilities
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
    from airtable_api import fetch_all_airtable_records
    import requests
    
    # Get existing records from Airtable
    existing_records = fetch_all_airtable_records(table_url, airtable_headers)
    existing_by_trade_id = {record['fields'].get('Trade ID'): record for record in existing_records}
    
    logger.info(f"📋 Found {len(existing_records)} existing Active Trades records")
    
    operations = {'created': 0, 'updated': 0, 'deleted': 0}
    
    # Process OANDA trades
    current_trade_ids = set()
    
    for trade in trades:
        trade_id = trade['id']
        current_trade_ids.add(trade_id)
        
        instrument = trade['instrument'].replace('_', '/')
        current_units = float(trade.get('currentUnits', 0))
        direction = 'Long' if current_units > 0 else 'Short'
        absolute_units = abs(int(current_units))
        entry_price = float(trade.get('price', 0))
        current_price = current_prices.get(trade['instrument'], entry_price)
        
        # Extract Stop Loss and Take Profit
        stop_loss = None
        take_profit = None
        
        if 'stopLossOrder' in trade and trade['stopLossOrder'].get('price'):
            stop_loss = float(trade['stopLossOrder']['price'])
            
        if 'takeProfitOrder' in trade and trade['takeProfitOrder'].get('price'):
            take_profit = float(trade['takeProfitOrder']['price'])
        
        # Calculate distance to entry
        distance_to_entry = calculate_distance_to_entry(current_price, entry_price, trade['instrument'])
        
        # Calculate risk and potential profit
        risk_amount = abs(float(trade.get('marginUsed', 0)))
        potential_profit = float(trade.get('unrealizedPL', 0))
        
        # Prepare record data with MINIMAL fields
        record_data = {
            'Trade ID': trade_id,
            'Instrument': instrument,
            'Direction': direction,
            'Units': absolute_units,
            'Entry Price': entry_price,
            'Current Price': current_price,
            'Unrealized PnL': potential_profit
        }
        
        # Remove None values
        record_data = {k: v for k, v in record_data.items() if v is not None}
        
        if trade_id in existing_by_trade_id:
            # UPDATE existing record
            existing_record = existing_by_trade_id[trade_id]
            record_id = existing_record['id']
            
            # Only update if data has changed (preserve manually added fields)
            update_needed = False
            existing_fields = existing_record['fields']
            
            for field, value in record_data.items():
                if existing_fields.get(field) != value:
                    update_needed = True
                    break
            
            if update_needed:
                update_url = f"{table_url}/{record_id}"
                response = requests.patch(update_url, headers=airtable_headers, json={'fields': record_data})
                
                if response.status_code == 200:
                    operations['updated'] += 1
                    logger.info(f"✅ Updated trade {trade_id}")
                else:
                    logger.error(f"❌ Failed to update trade {trade_id}: {response.text}")
        else:
            # CREATE new record
            response = requests.post(table_url, headers=airtable_headers, json={'fields': record_data})
            
            if response.status_code == 200:
                operations['created'] += 1
                logger.info(f"✅ Created trade {trade_id}")
            else:
                logger.error(f"❌ Failed to create trade {trade_id}: {response.text}")
    
    # DELETE trades that no longer exist in OANDA
    for trade_id, record in existing_by_trade_id.items():
        if trade_id not in current_trade_ids:
            record_id = record['id']
            delete_url = f"{table_url}/{record_id}"
            
            response = requests.delete(delete_url, headers=airtable_headers)
            
            if response.status_code == 200:
                operations['deleted'] += 1
                logger.info(f"🗑️  Deleted closed trade {trade_id}")
            else:
                logger.error(f"❌ Failed to delete trade {trade_id}: {response.text}")
    
    logger.info(f"📊 Active Trades: {operations['created']} created, {operations['updated']} updated, {operations['deleted']} deleted")
    
    return {
        'operations': operations['created'] + operations['updated'] + operations['deleted'],
        'created': operations['created'],
        'updated': operations['updated'], 
        'deleted': operations['deleted']
    }

def calculate_distance_to_entry(current_price: float, entry_price: float, instrument: str) -> float:
    """Calculate distance to entry in pips"""
    
    if not current_price or not entry_price:
        return None
        
    # Pip values for different instrument types
    pip_values = {
        # Major pairs (4 decimal places)
        'EUR_USD': 0.0001, 'GBP_USD': 0.0001, 'USD_CHF': 0.0001, 'USD_CAD': 0.0001,
        'AUD_USD': 0.0001, 'NZD_USD': 0.0001, 'EUR_GBP': 0.0001, 'EUR_CHF': 0.0001,
        'GBP_CHF': 0.0001, 'EUR_CAD': 0.0001, 'GBP_CAD': 0.0001, 'AUD_CAD': 0.0001,
        'EUR_AUD': 0.0001, 'GBP_AUD': 0.0001, 'EUR_NZD': 0.0001, 'GBP_NZD': 0.0001,
        'AUD_NZD': 0.0001,
        
        # Yen pairs (2 decimal places)
        'USD_JPY': 0.01, 'EUR_JPY': 0.01, 'GBP_JPY': 0.01, 'CHF_JPY': 0.01,
        'CAD_JPY': 0.01, 'AUD_JPY': 0.01, 'NZD_JPY': 0.01
    }
    
    pip_value = pip_values.get(instrument, 0.0001)  # Default to 4 decimal places
    distance_pips = abs(current_price - entry_price) / pip_value
    
    return round(distance_pips, 1)