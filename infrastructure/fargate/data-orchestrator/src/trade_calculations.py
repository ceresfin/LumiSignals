"""
Trade Calculation Utilities for Fargate Data Orchestrator
Handles pip calculations, P&L analysis, and risk calculations for real OANDA trades
"""

import logging
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def calculate_pips_moved(entry_price: float, current_price: float, instrument: str, direction: str) -> float:
    """
    Calculate how many pips a trade has moved since entry
    Returns positive for profitable moves, negative for losing moves
    """
    if not current_price or not entry_price:
        return 0.0
        
    # Pip values for different instrument types
    pip_values = {
        # Major pairs (4 decimal places)
        'EUR_USD': 0.0001, 'GBP_USD': 0.0001, 'USD_CHF': 0.0001, 'USD_CAD': 0.0001,
        'AUD_USD': 0.0001, 'NZD_USD': 0.0001, 'EUR_GBP': 0.0001, 'EUR_CHF': 0.0001,
        'GBP_CHF': 0.0001, 'EUR_CAD': 0.0001, 'GBP_CAD': 0.0001, 'AUD_CAD': 0.0001,
        'EUR_AUD': 0.0001, 'GBP_AUD': 0.0001, 'EUR_NZD': 0.0001, 'GBP_NZD': 0.0001,
        'AUD_NZD': 0.0001, 'CAD_CHF': 0.0001, 'AUD_CHF': 0.0001, 'NZD_CHF': 0.0001,
        
        # Yen pairs (2 decimal places)
        'USD_JPY': 0.01, 'EUR_JPY': 0.01, 'GBP_JPY': 0.01, 'CHF_JPY': 0.01,
        'CAD_JPY': 0.01, 'AUD_JPY': 0.01, 'NZD_JPY': 0.01
    }
    
    pip_value = pip_values.get(instrument, 0.0001)  # Default to 4 decimal places
    price_difference = current_price - entry_price
    
    # For short positions, flip the sign
    if direction.lower() in ['short', 'sell']:
        price_difference = -price_difference
    
    pips_moved = price_difference / pip_value
    return round(pips_moved, 1)


def calculate_risk_reward_ratio(entry_price: float, take_profit_price: Optional[float], 
                               stop_loss_price: Optional[float], direction: str) -> Optional[float]:
    """
    Calculate the Risk:Reward ratio for a trade
    Returns the ratio or None if not enough data
    """
    if not take_profit_price or not stop_loss_price:
        return None
    
    if direction.lower() in ['long', 'buy']:
        # Long position
        potential_profit = abs(take_profit_price - entry_price)
        potential_loss = abs(entry_price - stop_loss_price)
    else:
        # Short position
        potential_profit = abs(entry_price - take_profit_price)
        potential_loss = abs(stop_loss_price - entry_price)
    
    if potential_loss == 0:
        return None
    
    risk_reward_ratio = potential_profit / potential_loss
    return round(risk_reward_ratio, 2)


def extract_order_price(order_data: Optional[Dict[str, Any]]) -> Optional[float]:
    """
    Extract price from OANDA order data (takeProfitOrder or stopLossOrder)
    """
    if not order_data:
        return None
    
    price_str = order_data.get('price')
    if not price_str:
        return None
    
    try:
        return float(price_str)
    except (ValueError, TypeError):
        return None


def enhance_trade_with_calculations(trade_data: Dict[str, Any], current_price: float) -> Dict[str, Any]:
    """
    Enhance OANDA trade data with comprehensive calculations
    This is the main function called by the Data Orchestrator
    """
    enhanced_trade = trade_data.copy()
    
    # Extract basic trade info
    instrument = trade_data.get('instrument', '')
    entry_price = float(trade_data.get('price', 0))
    current_units = float(trade_data.get('currentUnits', 0))
    direction = 'Long' if current_units > 0 else 'Short'
    
    # Extract Target and Stop Loss prices
    take_profit_order = trade_data.get('takeProfitOrder')
    stop_loss_order = trade_data.get('stopLossOrder')
    
    take_profit_price = extract_order_price(take_profit_order)
    stop_loss_price = extract_order_price(stop_loss_order)
    
    # Calculate pips moved since entry
    pips_moved = calculate_pips_moved(entry_price, current_price, instrument, direction)
    
    # Calculate Risk:Reward ratio
    risk_reward_ratio = calculate_risk_reward_ratio(
        entry_price, take_profit_price, stop_loss_price, direction
    )
    
    # Calculate distance to entry (always positive)
    distance_to_entry = abs(pips_moved)
    
    # Add enhanced fields to trade data
    enhanced_trade.update({
        'direction': direction,
        'current_price': current_price,
        'take_profit_price': take_profit_price,
        'stop_loss_price': stop_loss_price,
        'pips_moved': pips_moved,
        'distance_to_entry': distance_to_entry,
        'risk_reward_ratio': risk_reward_ratio,
        'enhanced_timestamp': datetime.now().isoformat()
    })
    
    logger.debug(f"Enhanced trade {trade_data.get('id')}: "
                f"{instrument} {direction} {abs(current_units)} units, "
                f"Entry: {entry_price}, Current: {current_price}, "
                f"Pips: {pips_moved}, R:R: {risk_reward_ratio}")
    
    return enhanced_trade


def calculate_trade_duration(open_time_str: str) -> Dict[str, Any]:
    """
    Calculate trade duration in days, hours, minutes
    """
    from datetime import datetime, timezone
    
    try:
        # Parse OANDA time format
        open_time = datetime.fromisoformat(open_time_str.replace('Z', '+00:00'))
        current_time = datetime.now(timezone.utc)
        
        duration = current_time - open_time
        total_seconds = int(duration.total_seconds())
        
        days = total_seconds // (24 * 3600)
        hours = (total_seconds % (24 * 3600)) // 3600
        minutes = (total_seconds % 3600) // 60
        
        # Format duration string
        if days > 0:
            duration_str = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            duration_str = f"{hours}h {minutes}m"
        else:
            duration_str = f"{minutes}m"
        
        return {
            'duration_seconds': total_seconds,
            'duration_string': duration_str,
            'days': days,
            'hours': hours,
            'minutes': minutes
        }
        
    except Exception as e:
        logger.error(f"Failed to calculate trade duration: {e}")
        return {
            'duration_seconds': 0,
            'duration_string': '0m',
            'days': 0,
            'hours': 0,
            'minutes': 0
        }