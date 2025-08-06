#!/usr/bin/env python3
"""
Forex Calculation Utilities
Handles currency conversions, pip calculations, and exposure calculations
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

def calculate_usd_exposure(instrument: str, units: float, price: float) -> float:
    """
    Calculate USD exposure for a forex position
    Handles special cases like JPY pairs and cross-currency calculations
    """
    
    if not instrument or units == 0:
        return 0
    
    # Parse currency pair
    currencies = instrument.split('/')
    if len(currencies) != 2:
        logger.warning(f"Invalid instrument format: {instrument}")
        return 0
    
    base_currency = currencies[0]
    quote_currency = currencies[1]
    
    # Case 1: USD is the base currency (e.g., USD/CAD)
    if base_currency == 'USD':
        return abs(units)
    
    # Case 2: USD is the quote currency (e.g., EUR/USD)
    elif quote_currency == 'USD':
        return abs(units * price)
    
    # Case 3: Cross pairs (neither currency is USD)
    else:
        # For cross pairs, we need to convert through USD
        # This is a simplified calculation - in production, you'd want real-time USD rates
        
        # Special handling for JPY pairs
        if quote_currency == 'JPY':
            # For JPY pairs, the price represents larger numbers (e.g., 110.00)
            # Convert to USD using approximate rates
            if base_currency == 'EUR':
                # EUR/JPY -> EUR/USD approximation
                return abs(units * (price / 130.0))  # Rough EUR/USD rate
            elif base_currency == 'GBP':
                # GBP/JPY -> GBP/USD approximation
                return abs(units * (price / 140.0))  # Rough GBP/USD rate
            else:
                # Generic JPY conversion
                return abs(units * (price / 110.0))  # Rough USD/JPY rate
        else:
            # For other cross pairs, use the price as a rough USD equivalent
            return abs(units * price * 0.9)  # Conservative estimate
    
    return abs(units)

def calculate_currency_exposures(positions: list) -> dict:
    """
    Calculate net exposure by currency from positions
    Returns a dictionary with currency as key and net exposure as value
    """
    
    exposures = {}
    
    for position in positions:
        instrument = position.get('instrument', '').replace('_', '/')
        
        # Get long and short positions
        long_position = position.get('long', {})
        short_position = position.get('short', {})
        
        long_units = float(long_position.get('units', 0))
        short_units = float(short_position.get('units', 0))
        
        # Skip if no position
        if long_units == 0 and short_units == 0:
            continue
        
        # Parse currencies
        currencies = instrument.split('/')
        if len(currencies) != 2:
            continue
            
        base_currency = currencies[0]
        quote_currency = currencies[1]
        
        # Calculate base currency exposure
        base_exposure = long_units + short_units  # short_units is negative
        
        # Calculate quote currency exposure
        avg_price = 0
        if long_units != 0:
            avg_price = float(long_position.get('averagePrice', 0))
        elif short_units != 0:
            avg_price = float(short_position.get('averagePrice', 0))
        
        quote_exposure = -base_exposure * avg_price
        
        # Special handling for JPY pairs
        if quote_currency == 'JPY':
            # JPY amounts are typically 100x larger, but we want actual currency amounts
            # No adjustment needed as OANDA already provides correct units
            pass
        
        # Update exposures
        exposures[base_currency] = exposures.get(base_currency, 0) + base_exposure
        exposures[quote_currency] = exposures.get(quote_currency, 0) + quote_exposure
    
    return exposures

def convert_to_usd(amount: float, currency: str, rates: dict) -> float:
    """
    Convert any currency amount to USD using provided exchange rates
    rates should be a dict like {'EUR': 1.08, 'GBP': 1.25, 'JPY': 0.0091, ...}
    """
    
    if currency == 'USD':
        return amount
    
    rate = rates.get(currency, 1.0)
    return amount * rate

def calculate_pip_value(instrument: str, units: float, price: float) -> float:
    """Calculate the value of one pip for a position"""
    
    if 'JPY' in instrument:
        # JPY pairs: 1 pip = 0.01
        pip_size = 0.01
    else:
        # Other pairs: 1 pip = 0.0001
        pip_size = 0.0001
    
    # Calculate pip value in quote currency
    pip_value_quote = abs(units) * pip_size
    
    # Convert to USD if needed
    currencies = instrument.split('/')
    if len(currencies) == 2 and currencies[1] != 'USD':
        # This is a simplified calculation
        # In production, you'd use real-time conversion rates
        if currencies[1] == 'JPY':
            pip_value_usd = pip_value_quote / 110.0  # Rough USD/JPY rate
        else:
            pip_value_usd = pip_value_quote * price  # Approximate
    else:
        pip_value_usd = pip_value_quote
    
    return pip_value_usd

def calculate_margin_required(instrument: str, units: float, leverage: int = 50) -> float:
    """Calculate margin required for a position"""
    
    # Get position value in USD
    position_value = calculate_usd_exposure(instrument, units, 1.0)  # Simplified
    
    # Calculate margin based on leverage
    margin_required = position_value / leverage
    
    return margin_required

def format_price(price: float, instrument: str) -> str:
    """Format price according to instrument conventions"""
    
    if 'JPY' in instrument:
        # JPY pairs typically show 3 decimal places
        return f"{price:.3f}"
    else:
        # Other pairs typically show 5 decimal places
        return f"{price:.5f}"

def calculate_position_pnl(entry_price: float, current_price: float, units: float, direction: str) -> float:
    """Calculate P&L for a position"""
    
    if direction == 'Long':
        price_change = current_price - entry_price
    else:  # Short
        price_change = entry_price - current_price
    
    pnl = price_change * abs(units)
    return pnl