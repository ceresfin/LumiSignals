#!/usr/bin/env python3
"""
Currency Pair Positions Sync Module
Handles synchronization of currency pair positions from OANDA to Airtable
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def sync_currency_pair_positions_enhanced(positions: List[Dict], airtable_headers: Dict[str, str], base_id: str, current_prices: Dict[str, float] = None) -> Dict[str, int]:
    """Sync currency pair positions from OANDA positions API (OANDA Positions tab)"""
    
    table_url = f"https://api.airtable.com/v0/{base_id}/Positions"
    
    logger.info(f"💱 Syncing {len(positions)} currency pair positions from OANDA API")
    logger.info(f"🔍 Positions data preview: {positions[:2] if positions else 'No positions'}")
    
    # Import utilities
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
    from airtable_api import fetch_all_airtable_records
    from calculations import calculate_usd_exposure
    import requests
    
    # Process actual OANDA positions data
    pair_data = {}
    
    for position in positions:
        instrument = position.get('instrument', '').replace('_', '/')  # USD_CHF -> USD/CHF for display
        clean_instrument = instrument.replace('/', '')  # For calculations
        
        # Get long and short positions
        long_position = position.get('long', {})
        short_position = position.get('short', {})
        
        long_units = int(float(long_position.get('units', 0)))
        short_units = abs(int(float(short_position.get('units', 0))))  # Make positive for display
        
        # Skip if no position
        if long_units == 0 and short_units == 0:
            continue
        
        # Calculate net position
        net_units = long_units - short_units
        
        # Get unrealized P&L
        long_pl = float(long_position.get('unrealizedPL', 0))
        short_pl = float(short_position.get('unrealizedPL', 0))
        total_pl = long_pl + short_pl
        
        # Get average prices
        avg_short_price = float(short_position.get('averagePrice', 0))
        avg_long_price = float(long_position.get('averagePrice', 0))
        
        # Determine the effective average price based on net position
        if net_units > 0:  # Net long
            avg_price = avg_long_price
        elif net_units < 0:  # Net short
            avg_price = avg_short_price
        else:  # Flat
            avg_price = (avg_long_price + avg_short_price) / 2 if avg_long_price and avg_short_price else 0
        
        # Get margin info
        margin_usd = float(position.get('marginUsed', 0))
        
        # Calculate proper USD exposure (fallback to simple calculation if function fails)
        try:
            exposure_usd = calculate_usd_exposure(clean_instrument, abs(net_units), avg_price)
        except Exception as e:
            logger.warning(f"USD exposure calculation failed for {clean_instrument}: {e}")
            # Fallback: simple USD exposure calculation
            exposure_usd = abs(net_units) * avg_price if avg_price > 0 else abs(net_units)
        
        # Calculate position direction
        if net_units > 0:
            direction = 'Long'
        elif net_units < 0:
            direction = 'Short'
        else:
            direction = 'Flat'
        
        pair_data[instrument] = {
            'long_units': long_units,
            'short_units': short_units,
            'net_units': net_units,
            'direction': direction,
            'margin_usd': margin_usd,
            'exposure_usd': exposure_usd,
            'avg_short_price': avg_short_price,
            'avg_long_price': avg_long_price,
            'avg_price': avg_price,
            'unrealized_pnl': total_pl,
            'long_pl': long_pl,
            'short_pl': short_pl
        }
    
    # Get existing records
    existing_records = fetch_all_airtable_records(table_url, airtable_headers)
    existing_by_instrument = {record['fields'].get('Currency Pair'): record for record in existing_records}
    
    operations = {'created': 0, 'updated': 0, 'deleted': 0}
    current_instruments = set()
    
    # Process each currency pair
    for instrument, data in pair_data.items():
        current_instruments.add(instrument)
        
        # Calculate profit percentage
        profit_percent = (data['unrealized_pnl'] / data['exposure_usd'] * 100) if data['exposure_usd'] > 0 else 0
        
        # Calculate profit in pips (simplified - assumes 4 decimal places for most pairs, 2 for JPY)
        pip_multiplier = 100 if 'JPY' in instrument else 10000
        profit_pips = data['unrealized_pnl'] * pip_multiplier / abs(data['net_units']) if data['net_units'] != 0 else 0
        
        # Get current market price if available
        current_price = current_prices.get(instrument.replace('/', '_'), 0) if current_prices else 0
        
        # Calculate additional fields that match Airtable schema
        trade_count = 1 if data['net_units'] != 0 else 0
        long_trades = 1 if data['long_units'] > 0 else 0
        short_trades = 1 if data['short_units'] > 0 else 0
        
        # Calculate distance in pips (current price vs entry)
        if current_price > 0 and data['avg_price'] > 0:
            price_diff = current_price - data['avg_price']
            if data['net_units'] < 0:  # Short position
                price_diff = -price_diff  # Invert for short positions
            pip_multiplier = 100 if 'JPY' in instrument else 10000
            distance_pips = price_diff * pip_multiplier
        else:
            distance_pips = 0
            
        # Calculate profit in pips (matches OANDA's PROFIT (PIPS) calculation)
        pip_multiplier = 100 if 'JPY' in instrument else 10000
        if abs(data['net_units']) > 0:
            # This matches how OANDA calculates pips: P&L per unit * pip multiplier
            profit_pips = (data['unrealized_pnl'] / abs(data['net_units'])) * pip_multiplier
        else:
            profit_pips = 0
        
        # Position type
        if data['net_units'] > 0:
            position_type = 'Long'
        elif data['net_units'] < 0:
            position_type = 'Short'
        else:
            position_type = 'Flat'
        
        # Prepare complete record data matching Airtable fields (excluding Position Type due to select field restrictions)
        record_data = {
            'Currency Pair': instrument,
            'Long Units': data['long_units'],
            'Short Units': data['short_units'], 
            'Net Units': data['net_units'],
            'Trade Count': trade_count,
            'Long Trades': long_trades,
            'Short Trades': short_trades,
            'Average Entry': round(data['avg_price'], 5) if data['avg_price'] else 0,
            'Current Price': round(current_price, 5) if current_price else 0,
            'Distance (Pips)': round(distance_pips, 1),
            'Profit (Pips)': round(profit_pips, 1),  # Matches OANDA's PROFIT (PIPS)
            'Unrealized P&L': round(data['unrealized_pnl'], 2),
            'Margin Used': round(data['margin_usd'], 2),
            'Largest Position': abs(data['net_units']),
            'Concentration %': round(profit_percent, 2),  # Using profit % as concentration
            'Last Updated': datetime.now(timezone.utc).isoformat()
        }
        
        # Log the position type for reference (but don't send to Airtable)
        logger.info(f"📊 Position Type: {position_type}")
        
        logger.info(f"📊 Position {instrument}: Net={data['net_units']}, P&L=${data['unrealized_pnl']:.2f}, Profit Pips={profit_pips:.1f}, Margin=${data['margin_usd']:.2f}, Current Price={current_price}")
        logger.info(f"🔄 Sending to Airtable: {record_data}")
        
        if instrument in existing_by_instrument:
            # UPDATE existing record
            existing_record = existing_by_instrument[instrument]
            record_id = existing_record['id']
            
            # Only update if data has changed significantly
            existing_fields = existing_record['fields']
            update_needed = False
            
            # Check for significant changes
            for field, value in record_data.items():
                existing_value = existing_fields.get(field)
                if field in ['Unrealized P&L', 'Average Entry', 'Current Price', 'Distance (Pips)', 'Profit (Pips)', 'Margin Used', 'Concentration %']:
                    # For numeric fields, check if difference is significant
                    if existing_value is None or abs(float(existing_value) - float(value)) > 0.01:
                        update_needed = True
                        break
                elif existing_value != value:
                    update_needed = True
                    break
            
            if update_needed:
                update_url = f"{table_url}/{record_id}"
                response = requests.patch(update_url, headers=airtable_headers, json={'fields': record_data})
                
                if response.status_code == 200:
                    operations['updated'] += 1
                    logger.info(f"✅ Updated position {instrument}")
                    logger.info(f"📤 Airtable response: {response.json()}")
                else:
                    logger.error(f"❌ Failed to update position {instrument}: {response.text}")
        else:
            # CREATE new record
            response = requests.post(table_url, headers=airtable_headers, json={'fields': record_data})
            
            if response.status_code == 200:
                operations['created'] += 1
                logger.info(f"✅ Created position {instrument}")
                logger.info(f"📤 Airtable response: {response.json()}")
            else:
                logger.error(f"❌ Failed to create position {instrument}: {response.text}")
    
    # DELETE instruments that no longer have positions
    for instrument, record in existing_by_instrument.items():
        if instrument not in current_instruments:
            record_id = record['id']
            delete_url = f"{table_url}/{record_id}"
            
            response = requests.delete(delete_url, headers=airtable_headers)
            
            if response.status_code == 200:
                operations['deleted'] += 1
                logger.info(f"🗑️  Deleted position {instrument}")
            else:
                logger.error(f"❌ Failed to delete position {instrument}: {response.text}")
    
    logger.info(f"💱 Currency Pair Positions: {operations['created']} created, {operations['updated']} updated, {operations['deleted']} deleted")
    
    return {
        'operations': operations['created'] + operations['updated'] + operations['deleted'],
        'created': operations['created'],
        'updated': operations['updated'],
        'deleted': operations['deleted']
    }

def calculate_position_metrics(position: Dict[str, Any]) -> Dict[str, float]:
    """Calculate additional metrics for a position"""
    
    long_position = position.get('long', {})
    short_position = position.get('short', {})
    
    long_units = float(long_position.get('units', 0))
    short_units = float(short_position.get('units', 0))
    net_units = long_units + short_units  # short_units is already negative
    
    long_pl = float(long_position.get('unrealizedPL', 0))
    short_pl = float(short_position.get('unrealizedPL', 0))
    total_pl = long_pl + short_pl
    
    # Calculate weighted average price
    long_price = float(long_position.get('averagePrice', 0))
    short_price = float(short_position.get('averagePrice', 0))
    
    if abs(long_units) > 0 and abs(short_units) > 0:
        # Mixed position - calculate weighted average
        total_abs_units = abs(long_units) + abs(short_units)
        weighted_price = (abs(long_units) * long_price + abs(short_units) * short_price) / total_abs_units
    elif abs(long_units) > 0:
        weighted_price = long_price
    elif abs(short_units) > 0:
        weighted_price = short_price
    else:
        weighted_price = 0
    
    return {
        'net_units': net_units,
        'total_pl': total_pl,
        'weighted_avg_price': weighted_price,
        'position_size': abs(net_units),
        'is_long': net_units > 0,
        'is_short': net_units < 0,
        'is_flat': abs(net_units) < 1
    }