#!/usr/bin/env python3
"""
Currency Exposures Sync Module
Handles synchronization of currency exposures from OANDA to Airtable
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def calculate_simple_usd_value(currency: str, amount: float) -> float:
    """Simple USD conversion using approximate rates"""
    # Approximate exchange rates (in production, you'd get these from an API)
    rates = {
        'USD': 1.0,
        'EUR': 1.08,
        'GBP': 1.25,
        'JPY': 0.0067,
        'CAD': 0.74,
        'AUD': 0.65,
        'CHF': 1.10,
        'NZD': 0.60,
        'CNY': 0.14,
        'SEK': 0.092,
        'NOK': 0.092,
        'DKK': 0.145
    }
    return amount * rates.get(currency, 1.0)

def sync_currency_exposures_enhanced(positions: List[Dict], airtable_headers: Dict[str, str], base_id: str, account_balance: float = 100000.0) -> Dict[str, int]:
    """Sync currency exposures from OANDA positions data"""
    
    table_url = f"https://api.airtable.com/v0/{base_id}/Exposure"
    
    logger.info(f"💱 Calculating currency exposures from {len(positions)} OANDA positions")
    logger.info(f"🔍 Positions data preview: {positions[:2] if positions else 'No positions'}")
    
    # Import utilities
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
    from airtable_api import fetch_all_airtable_records
    import requests
    
    # Calculate currency exposures from OANDA positions data
    currency_data = {}
    
    for position in positions:
        instrument = position.get('instrument', '')
        if '_' not in instrument:
            continue
            
        base_currency, quote_currency = instrument.split('_')
        
        # Get position details from OANDA positions structure
        long_data = position.get('long', {})
        short_data = position.get('short', {})
        
        long_units = float(long_data.get('units', 0))
        short_units = float(short_data.get('units', 0))
        
        # Skip if no position
        if long_units == 0 and short_units == 0:
            continue
            
        # Calculate net position
        net_units = long_units + short_units  # short_units is negative
        
        # Get unrealized P&L
        long_pnl = float(long_data.get('unrealizedPL', 0))
        short_pnl = float(short_data.get('unrealizedPL', 0))
        total_pnl = long_pnl + short_pnl
            
        # Initialize currency data
        for currency in [base_currency, quote_currency]:
            if currency not in currency_data:
                currency_data[currency] = {
                    'net_position': 0,
                    'long_exposure': 0,
                    'short_exposure': 0,
                    'unrealized_pnl': 0
                }
        
        # Get average prices for conversion
        long_price = float(long_data.get('averagePrice', 0)) if long_units != 0 else 0
        short_price = float(short_data.get('averagePrice', 0)) if short_units != 0 else 0
        avg_price = long_price if long_price > 0 else short_price
        
        # Calculate currency exposures
        if long_units > 0:
            # Long position: Long base currency, short quote currency
            base_amount = abs(long_units)
            quote_amount = abs(long_units) * avg_price if avg_price > 0 else abs(long_units)
            
            currency_data[base_currency]['net_position'] += base_amount
            currency_data[base_currency]['long_exposure'] += base_amount
            currency_data[quote_currency]['net_position'] -= quote_amount
            currency_data[quote_currency]['short_exposure'] += quote_amount
            
        if short_units < 0:
            # Short position: Short base currency, long quote currency  
            base_amount = abs(short_units)
            quote_amount = abs(short_units) * avg_price if avg_price > 0 else abs(short_units)
            
            currency_data[base_currency]['net_position'] -= base_amount
            currency_data[base_currency]['short_exposure'] += base_amount
            currency_data[quote_currency]['net_position'] += quote_amount
            currency_data[quote_currency]['long_exposure'] += quote_amount
            
        # Add P&L (split between currencies)
        currency_data[base_currency]['unrealized_pnl'] += total_pnl / 2
        currency_data[quote_currency]['unrealized_pnl'] += total_pnl / 2
    
    # Get existing records
    existing_records = fetch_all_airtable_records(table_url, airtable_headers)
    existing_by_currency = {record['fields'].get('Currency'): record for record in existing_records}
    
    operations = {'created': 0, 'updated': 0, 'deleted': 0}
    current_currencies = set()
    
    # Process each currency that has a non-zero position
    for currency, data in currency_data.items():
        if abs(data['net_position']) < 0.01:  # Skip currencies with negligible exposure
            continue
            
        current_currencies.add(currency)
        
        # Calculate USD value using simple approximation (since we don't have real-time rates)
        usd_value = calculate_simple_usd_value(currency, abs(data['net_position']))
        
        # Calculate Risk % as USD Value divided by total account value
        risk_percentage = (usd_value / account_balance * 100) if account_balance > 0 else 0.0
        
        # Prepare record data with USD Value and Risk %
        record_data = {
            'Currency': currency,
            'Net Exposure': round(data['net_position'], 2),
            'Long Exposure': round(data['long_exposure'], 2),
            'Short Exposure': round(data['short_exposure'], 2),
            'USD Value': round(usd_value, 2),
            'Risk %': round(risk_percentage, 2),
            'Last Updated': datetime.now(timezone.utc).isoformat()
        }
        
        if currency in existing_by_currency:
            # UPDATE existing record
            existing_record = existing_by_currency[currency]
            record_id = existing_record['id']
            
            # Only update if data has changed significantly
            existing_fields = existing_record['fields']
            update_needed = False
            
            # Check for significant changes (avoid updates for tiny differences)
            for field, value in record_data.items():
                existing_value = existing_fields.get(field)
                if field in ['Net Exposure', 'Long Exposure', 'Short Exposure', 'USD Value', 'Risk %']:
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
                    logger.info(f"✅ Updated currency exposure {currency}")
                else:
                    logger.error(f"❌ Failed to update currency {currency}: {response.text}")
        else:
            # CREATE new record
            response = requests.post(table_url, headers=airtable_headers, json={'fields': record_data})
            
            if response.status_code == 200:
                operations['created'] += 1
                logger.info(f"✅ Created currency exposure {currency}")
            else:
                logger.error(f"❌ Failed to create currency {currency}: {response.text}")
    
    # DELETE currencies that no longer have positions
    for currency, record in existing_by_currency.items():
        if currency not in current_currencies:
            record_id = record['id']
            delete_url = f"{table_url}/{record_id}"
            
            response = requests.delete(delete_url, headers=airtable_headers)
            
            if response.status_code == 200:
                operations['deleted'] += 1
                logger.info(f"🗑️  Deleted currency exposure {currency}")
            else:
                logger.error(f"❌ Failed to delete currency {currency}: {response.text}")
    
    logger.info(f"💱 Currency Exposures: {operations['created']} created, {operations['updated']} updated, {operations['deleted']} deleted")
    
    return {
        'operations': operations['created'] + operations['updated'] + operations['deleted'],
        'created': operations['created'],
        'updated': operations['updated'],
        'deleted': operations['deleted']
    }

def calculate_currency_exposure_from_trades(trades: List[Dict]) -> Dict[str, Dict[str, float]]:
    """
    Calculate currency exposures from individual trades (matches OANDA's Exposures tab logic)
    Returns dictionary with currency as key and exposure data as value
    """
    
    currency_data = {}
    
    for trade in trades:
        instrument = trade.get('instrument', '')
        if '_' not in instrument:
            continue
            
        base_currency, quote_currency = instrument.split('_')
        current_units = float(trade.get('currentUnits', 0))
        
        if current_units == 0:
            continue
        
        # Initialize currency tracking
        for currency in [base_currency, quote_currency]:
            if currency not in currency_data:
                currency_data[currency] = {
                    'net_position': 0,
                    'long_exposure': 0,
                    'short_exposure': 0,
                    'trade_count': 0
                }
        
        # Calculate position impact on each currency
        opening_price = float(trade.get('price', 0))
        trade_units = abs(current_units)
        
        if current_units > 0:  # Long position
            # Long EUR/USD = Long EUR, Short USD
            currency_data[base_currency]['net_position'] += trade_units
            currency_data[base_currency]['long_exposure'] += trade_units
            
            quote_amount = trade_units * opening_price if quote_currency != 'JPY' else trade_units * opening_price
            currency_data[quote_currency]['net_position'] -= quote_amount
            currency_data[quote_currency]['short_exposure'] += quote_amount
        else:  # Short position
            # Short EUR/USD = Short EUR, Long USD
            currency_data[base_currency]['net_position'] -= trade_units
            currency_data[base_currency]['short_exposure'] += trade_units
            
            quote_amount = trade_units * opening_price if quote_currency != 'JPY' else trade_units * opening_price
            currency_data[quote_currency]['net_position'] += quote_amount
            currency_data[quote_currency]['long_exposure'] += quote_amount
        
        # Increment trade count
        currency_data[base_currency]['trade_count'] += 1
        currency_data[quote_currency]['trade_count'] += 1
    
    return currency_data