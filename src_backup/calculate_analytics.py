#!/usr/bin/env python3
"""
Enhanced Trading Analytics Calculator
Adds missing field calculations and improves data handling
"""

import os
import sys
import logging
from datetime import datetime, timedelta

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("Starting Enhanced Trading Analytics Calculator...")
print(f"Current directory: {current_dir}")

# Config imports
try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    from pyairtable import Api
    print("SUCCESS: Imported Airtable config")
except ImportError as e:
    print(f"ERROR: Failed to import Airtable config: {e}")
    sys.exit(1)

# Airtable setup
try:
    airtable_api = Api(AIRTABLE_API_TOKEN)
    table = airtable_api.table(BASE_ID, TABLE_NAME)
    print("SUCCESS: Airtable connection established")
except Exception as e:
    print(f"ERROR: Failed to connect to Airtable: {e}")
    sys.exit(1)

# Logging setup
log_dir = os.path.join(parent_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
LOG_FILE = os.path.join(log_dir, "enhanced_analytics.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def safe_float(value, default=0.0):
    """Safely convert value to float"""
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_datetime_parse(time_str):
    """Enhanced datetime parsing with multiple format support"""
    if not time_str:
        return None
    try:
        # Handle different datetime formats
        if 'T' in time_str:
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        elif '/' in time_str:
            # Handle MM/DD/YYYY format
            return datetime.strptime(time_str, '%m/%d/%Y %H:%M:%S')
        else:
            # Handle standard format
            return datetime.strptime(time_str[:19], '%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Warning: Could not parse datetime '{time_str}': {e}")
        return None

def calculate_days_pending(order_time, execution_time):
    """
    Calculate days between order placement and execution
    This is for FILLED orders only
    """
    order_dt = safe_datetime_parse(order_time)
    exec_dt = safe_datetime_parse(execution_time)
    
    if not order_dt or not exec_dt:
        return 0.0
    
    try:
        days_pending = (exec_dt - order_dt).total_seconds() / (24 * 3600)
        return round(max(0, days_pending), 2)  # Ensure non-negative
    except:
        return 0.0

def calculate_fill_rate_status(order_status):
    """
    Map order status to fill rate categories
    """
    status_mapping = {
        "Filled": "Filled",
        "Cancelled": "Cancelled", 
        "Pending": "Pending",
        "Expired": "Expired",
        "Rejected": "Rejected"
    }
    return status_mapping.get(order_status, "Unknown")

def calculate_time_to_fill(order_time, execution_time):
    """
    Calculate human-readable time to fill
    """
    days_pending = calculate_days_pending(order_time, execution_time)
    
    if days_pending == 0:
        return "Same Day"
    elif days_pending < 1:
        hours = round(days_pending * 24, 1)
        return f"{hours}h"
    elif days_pending < 7:
        return f"{days_pending}d"
    else:
        weeks = round(days_pending / 7, 1)
        return f"{weeks}w"

def calculate_enhanced_position_size(risk_amount, entry_price, units, account_balance):
    """
    Enhanced position size calculation with fallbacks
    """
    if account_balance and account_balance > 0:
        # Primary method: risk amount / account balance
        return round((risk_amount / account_balance) * 100, 2)
    elif entry_price and units and entry_price > 0:
        # Fallback: notional value calculation
        notional_value = entry_price * abs(units)
        # Estimate account balance from notional (conservative assumption)
        estimated_balance = notional_value * 20  # Assume 20:1 leverage (more conservative)
        if estimated_balance > 0:
            return round((risk_amount / estimated_balance) * 100, 2)
        else:
            return 0.0
    else:
        return 0.0

def calculate_days_held_enhanced(order_time, execution_time, exit_price):
    """
    Enhanced days held calculation
    - For closed trades: order time to execution time
    - For open trades: order time to now
    """
    order_dt = safe_datetime_parse(order_time)
    
    if not order_dt:
        return 0.0
    
    # Determine end time
    if exit_price and exit_price > 0:
        # Trade is closed, use execution time
        end_dt = safe_datetime_parse(execution_time)
        if not end_dt:
            end_dt = datetime.now()
    else:
        # Trade is still open, use current time
        end_dt = datetime.now()
    
    try:
        days_held = (end_dt - order_dt).total_seconds() / (24 * 3600)
        return round(max(0, days_held), 2)
    except:
        return 0.0

def detect_missing_data_issues(record_fields):
    """
    Detect and report missing data that prevents calculations
    """
    issues = []
    order_status = record_fields.get('Order Status', '')
    
    # Check critical fields
    if not record_fields.get('Order Time'):
        issues.append("Missing Order Time")
    
    # Only require Account Balance Before for filled orders
    if order_status == 'Filled' and not record_fields.get('Account Balance Before'):
        issues.append("Missing Account Balance Before (Filled Order)")
    
    if not record_fields.get('Entry Price'):
        issues.append("Missing Entry Price")
    
    if not record_fields.get('Units'):
        issues.append("Missing Units")
    
    return issues

def calculate_all_metrics_enhanced(record_fields):
    """
    Enhanced calculation of all performance metrics
    """
    # Extract data safely
    entry_price = safe_float(record_fields.get('Entry Price'))
    exit_price = safe_float(record_fields.get('Exit Price'))
    stop_loss = safe_float(record_fields.get('Stop Loss'))
    target_price = safe_float(record_fields.get('Target Price'))
    units = safe_float(record_fields.get('Units'))
    direction = record_fields.get('Direction', '')
    instrument = record_fields.get('Instrument', '')
    realized_pl = safe_float(record_fields.get('Realized PL'))
    account_balance_before = safe_float(record_fields.get('Account Balance Before'))
    order_time = record_fields.get('Order Time', '')
    execution_time = record_fields.get('Execution Time', '')
    order_status = record_fields.get('Order Status', '')
    
    # Detect issues
    issues = detect_missing_data_issues(record_fields)
    if issues:
        print(f"⚠️  Data issues detected: {', '.join(issues)}")
    
    # Calculate metrics
    calculated = {}
    
    # R:R Ratio
    if entry_price and stop_loss and target_price:
        calculated['R:R Ratio Calculated'] = calculate_rr_ratio(entry_price, stop_loss, target_price, direction)
    
    # Risk Amount
    risk_amount = 0
    if entry_price and stop_loss and units:
        risk_amount = calculate_risk_amount(entry_price, stop_loss, units, direction)
        calculated['Risk Amount Calculated'] = risk_amount
    
    # Enhanced Position Size % - only calculate for filled orders with account balance
    if risk_amount > 0 and order_status == 'Filled' and account_balance_before > 0:
        calculated['Position Size % Calculated'] = calculate_enhanced_position_size(
            risk_amount, entry_price, units, account_balance_before
        )
        calculated['Risk Per Trade % Calculated'] = calculated['Position Size % Calculated']
    elif risk_amount > 0 and order_status != 'Filled':
        # For pending orders, use fallback calculation
        calculated['Position Size % Calculated'] = calculate_enhanced_position_size(
            risk_amount, entry_price, units, 0  # Will trigger fallback
        )
        calculated['Risk Per Trade % Calculated'] = calculated['Position Size % Calculated']
    
    # ROI %
    if risk_amount > 0:
        calculated['ROI Calculated'] = calculate_roi_percent(realized_pl, risk_amount)
    
    # Pips Gained/Lost
    if entry_price and exit_price:
        calculated['Pips Gained/Lost Calculated'] = calculate_pips(entry_price, exit_price, direction, instrument)
    
    # Enhanced Days Held
    if order_time:
        calculated['Days Held Calculated'] = calculate_days_held_enhanced(order_time, execution_time, exit_price)
    
    # Days Pending (for filled orders only)
    if order_status == 'Filled' and order_time and execution_time:
        calculated['Days Pending'] = calculate_days_pending(order_time, execution_time)
    
    # Fill Rate
    calculated['Fill Rate Calculated'] = calculate_fill_rate_status(order_status)
    
    # Time to Fill (for filled orders only) - Now using Text field
    if order_status == 'Filled' and order_time and execution_time:
        calculated['Time to Fill'] = calculate_time_to_fill(order_time, execution_time)
    
    # Trade Result
    calculated['Trade Result Calculated'] = determine_trade_result(realized_pl, exit_price)
    
    return calculated

def calculate_rr_ratio(entry_price, stop_loss, target_price, direction):
    """Calculate Risk:Reward ratio"""
    if not all([entry_price, stop_loss, target_price]) or entry_price == 0:
        return 0
    
    try:
        if direction == "Long":
            risk = entry_price - stop_loss
            reward = target_price - entry_price
        else:  # Short
            risk = stop_loss - entry_price
            reward = entry_price - target_price
        
        if risk > 0:
            return round(reward / risk, 2)
        else:
            return 0
    except:
        return 0

def calculate_risk_amount(entry_price, stop_loss, units, direction):
    """Calculate dollar risk amount"""
    if not all([entry_price, stop_loss, units]) or entry_price == 0:
        return 0
    
    try:
        if direction == "Long":
            risk_per_unit = entry_price - stop_loss
        else:  # Short
            risk_per_unit = stop_loss - entry_price
        
        return round(abs(risk_per_unit * units), 2)
    except:
        return 0

def calculate_roi_percent(realized_pl, risk_amount):
    """Calculate ROI percentage"""
    if not risk_amount or risk_amount == 0:
        return 0
    
    try:
        return round((realized_pl / risk_amount) * 100, 2)
    except:
        return 0

def calculate_pips(entry_price, exit_price, direction, instrument):
    """Calculate pips gained/lost"""
    if not all([entry_price, exit_price]) or entry_price == 0 or exit_price == 0:
        return 0
    
    try:
        # Determine pip multiplier based on instrument
        if any(pair in instrument.upper() for pair in ['JPY', 'HUF', 'KRW']):
            pip_multiplier = 100  # JPY pairs: 1 pip = 0.01
        else:
            pip_multiplier = 10000  # Most pairs: 1 pip = 0.0001
        
        if direction == "Long":
            pip_difference = (exit_price - entry_price) * pip_multiplier
        else:  # Short
            pip_difference = (entry_price - exit_price) * pip_multiplier
        
        return round(pip_difference, 1)
    except:
        return 0

def determine_trade_result(realized_pl, exit_price):
    """Determine trade result"""
    if exit_price == 0:  # Trade not closed
        return "Open"
    elif realized_pl > 0:
        return "Win"
    elif realized_pl < 0:
        return "Loss"
    else:
        return "Breakeven"

def main_enhanced():
    """
    Enhanced main function with better error handling and reporting
    """
    logger.info("Starting Enhanced Trading Analytics Calculator...")
    
    try:
        # Get all records
        records = table.all()
        logger.info(f"Retrieved {len(records)} records for enhanced analysis")
        
        if not records:
            logger.info("No records found to process")
            return True
        
        updated_count = 0
        error_count = 0
        data_issues_count = 0
        
        for record in records:
            try:
                record_id = record['id']
                fields = record['fields']
                order_id = fields.get('OANDA Order ID', 'Unknown')
                
                logger.info(f"Processing record {order_id} (ID: {record_id})")
                
                # Enhanced calculation with issue detection
                calculated_metrics = calculate_all_metrics_enhanced(fields)
                
                # Check for data quality issues
                issues = detect_missing_data_issues(fields)
                if issues:
                    data_issues_count += 1
                    logger.warning(f"Record {order_id} has data issues: {', '.join(issues)}")
                
                # Update record
                if calculated_metrics:
                    update_fields = {k: v for k, v in calculated_metrics.items() 
                                   if v is not None and v != ''}
                    
                    if update_fields:
                        table.update(record_id, update_fields)
                        logger.info(f"✅ Updated record {order_id} with: {list(update_fields.keys())}")
                        updated_count += 1
                    else:
                        logger.info(f"No metrics to update for record {order_id}")
                
            except Exception as e:
                logger.error(f"❌ Error processing record {record.get('id', 'unknown')}: {e}")
                error_count += 1
                continue
        
        # Enhanced reporting
        logger.info("=" * 60)
        logger.info("ENHANCED ANALYTICS SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Records: {len(records)}")
        logger.info(f"Successfully Updated: {updated_count}")
        logger.info(f"Records with Data Issues: {data_issues_count}")
        logger.info(f"Errors: {error_count}")
        logger.info("=" * 60)
        
        if data_issues_count > 0:
            logger.warning(f"💡 Consider reviewing {data_issues_count} records with data issues")
            logger.warning("   Common fixes:")
            logger.warning("   - Filled orders should have Account Balance Before populated")
            logger.warning("   - Verify Order Time and Execution Time formats")
            logger.warning("   - Check Entry Price and Units are present")
            logger.warning("   - Pending orders won't have account balance (this is normal)")
        
        logger.info("✨ Note: Position Size % calculated using fallback method for pending orders")
        logger.info("✨ Time to Fill now populates for filled orders")
        
        return error_count == 0
        
    except Exception as e:
        logger.error(f"Error in enhanced analytics: {e}")
        return False

if __name__ == "__main__":
    main_enhanced()