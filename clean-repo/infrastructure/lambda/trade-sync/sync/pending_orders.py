#!/usr/bin/env python3
"""
Pending Orders Sync Module
Handles synchronization of pending orders from OANDA to Airtable
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def sync_pending_orders_enhanced(orders: List[Dict], current_prices: Dict[str, float], 
                                airtable_headers: Dict[str, str], base_id: str) -> Dict[str, int]:
    """Enhanced Pending Orders sync with intelligent updates"""
    
    table_url = f"https://api.airtable.com/v0/{base_id}/Pending%20Orders"
    
    # Import utilities
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
    from airtable_api import fetch_all_airtable_records
    import requests
    
    # Get existing records from Airtable
    existing_records = fetch_all_airtable_records(table_url, airtable_headers)
    existing_by_order_id = {str(record['fields'].get('Ticket Number', '')): record for record in existing_records}
    
    logger.info(f"📋 Found {len(existing_records)} existing Pending Orders records")
    
    # Filter valid orders
    valid_orders = []
    for order in orders:
        if 'instrument' in order and order['instrument']:
            valid_orders.append(order)
        else:
            logger.warning(f"⚠️  Skipping order {order.get('id', 'unknown')} - missing instrument field")
    
    operations = {'created': 0, 'updated': 0, 'deleted': 0}
    
    # Process OANDA orders
    current_order_ids = set()
    
    for order in valid_orders:
        order_id = str(order['id'])
        current_order_ids.add(order_id)
        
        instrument = order['instrument'].replace('_', '/')
        units = int(order.get('units', 0))
        direction = 'Long' if units > 0 else 'Short'
        absolute_units = abs(units)
        entry_price = float(order.get('price', 0))
        current_price = current_prices.get(order['instrument'], entry_price)
        
        # Extract Stop Loss and Take Profit from order
        stop_loss = None
        take_profit = None
        
        if 'stopLossOnFill' in order and order['stopLossOnFill'].get('price'):
            stop_loss = float(order['stopLossOnFill']['price'])
            
        if 'takeProfitOnFill' in order and order['takeProfitOnFill'].get('price'):
            take_profit = float(order['takeProfitOnFill']['price'])
        
        # Calculate distance to market
        distance_to_market = calculate_distance_to_market(current_price, entry_price, order['instrument'])
        
        # Determine order status based on type and conditions
        order_status = determine_order_status(order, current_price)
        
        # Prepare record data with MINIMAL fields
        record_data = {
            'Ticket Number': int(order_id),
            'Instrument': instrument,
            'Direction': direction,
            'Units': absolute_units,
            'Entry Price': entry_price,
            'Current Price': current_price
        }
        
        # Remove None values
        record_data = {k: v for k, v in record_data.items() if v is not None}
        
        if order_id in existing_by_order_id:
            # UPDATE existing record
            existing_record = existing_by_order_id[order_id]
            record_id = existing_record['id']
            
            # Only update if data has changed
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
                    logger.info(f"✅ Updated order {order_id}")
                else:
                    logger.error(f"❌ Failed to update order {order_id}: {response.text}")
        else:
            # CREATE new record
            response = requests.post(table_url, headers=airtable_headers, json={'fields': record_data})
            
            if response.status_code == 200:
                operations['created'] += 1
                logger.info(f"✅ Created order {order_id}")
            else:
                logger.error(f"❌ Failed to create order {order_id}: {response.text}")
    
    # PRESERVE Airtable-only orders (don't delete them - they might be manual entries)
    airtable_only_orders = set(existing_by_order_id.keys()) - current_order_ids
    if airtable_only_orders:
        logger.info(f'📋 Preserved {len(airtable_only_orders)} Airtable-only orders: {list(airtable_only_orders)[:5]}')
        
    logger.info(f"📊 Pending Orders: {operations['created']} created, {operations['updated']} updated, {operations['deleted']} deleted")
    
    return {
        'operations': operations['created'] + operations['updated'] + operations['deleted'],
        'created': operations['created'],
        'updated': operations['updated'],
        'deleted': operations['deleted']
    }

def calculate_distance_to_market(current_price: float, order_price: float, instrument: str) -> float:
    """Calculate distance from current market price to order price in pips"""
    
    if not current_price or not order_price:
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
    distance_pips = abs(current_price - order_price) / pip_value
    
    return round(distance_pips, 1)

def determine_order_status(order: Dict[str, Any], current_price: float) -> str:
    """Determine the status of a pending order"""
    
    order_type = order.get('type', '').upper()
    order_price = float(order.get('price', 0))
    state = order.get('state', 'PENDING').upper()
    
    # Check order state first
    if state == 'FILLED':
        return 'Filled'
    elif state == 'CANCELLED':
        return 'Cancelled'
    elif state == 'TRIGGERED':
        return 'Triggered'
    
    # For pending orders, determine more specific status
    if not current_price or not order_price:
        return 'Pending'
    
    if order_type in ['LIMIT', 'STOP']:
        # Calculate how close the order is to being triggered
        distance_pips = abs(current_price - order_price) / 0.0001  # Approximate
        
        if distance_pips < 5:  # Very close to trigger
            return 'Near Trigger'
        elif distance_pips < 20:  # Moderately close
            return 'Approaching'
        else:
            return 'Pending'
    
    return 'Pending'

def format_order_type(order_type: str) -> str:
    """Format OANDA order type for display"""
    
    type_mapping = {
        'MARKET': 'Market',
        'LIMIT': 'Limit',
        'STOP': 'Stop',
        'MARKET_IF_TOUCHED': 'Market If Touched',
        'TAKE_PROFIT': 'Take Profit',
        'STOP_LOSS': 'Stop Loss',
        'TRAILING_STOP_LOSS': 'Trailing Stop'
    }
    
    return type_mapping.get(order_type.upper(), order_type)