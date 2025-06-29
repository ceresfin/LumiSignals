#!/usr/bin/env python3
"""
Trading Analytics Calculator
Calculates performance metrics in Python and updates Airtable
Run separately from sync_all.py for clean separation of concerns
"""

import os
import sys
import logging
from datetime import datetime

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("Starting Trading Analytics Calculator...")
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
LOG_FILE = os.path.join(log_dir, "analytics.log")

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
    """Safely parse datetime string"""
    if not time_str:
        return None
    try:
        # Handle different datetime formats
        if 'T' in time_str:
            return datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            # Handle date-only format from Airtable
            return datetime.strptime(time_str[:19], '%Y-%m-%d %H:%M')
    except:
        return None

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

def calculate_position_size_percent(risk_amount, account_balance):
    """Calculate position size as percentage of account"""
    if not account_balance or account_balance == 0:
        return 0
    
    try:
        return round((risk_amount / account_balance) * 100, 2)
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

def calculate_days_held(order_time, execution_time):
    """Calculate days held"""
    start_dt = safe_datetime_parse(order_time)
    end_dt = safe_datetime_parse(execution_time)
    
    if not start_dt or not end_dt:
        return 0
    
    try:
        days_held = (end_dt - start_dt).total_seconds() / (24 * 3600)
        return round(days_held, 2)
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

def calculate_fill_rate(order_status):
    """Calculate fill rate for analytics"""
    status_mapping = {
        "Filled": "Filled",
        "Cancelled": "Cancelled", 
        "Pending": "Pending",
        "Expired": "Expired"
    }
    return status_mapping.get(order_status, "Unknown")

def get_writable_fields():
    """
    Return only the field names that can be written to (not computed/formula fields)
    Using new "Calculated" field names to avoid conflicts with formula fields
    """
    # New calculated fields that are regular Number/Text fields
    writable_fields = [
        "R:R Ratio Calculated",              # New Number field
        "ROI Calculated",                     # New Number field  
        "Risk Amount Calculated",             # New Number field
        "Position Size % Calculated",         # New Number field
        "Risk Per Trade % Calculated",        # New Number field
        "Pips Gained/Lost Calculated",       # New Number field
        "Days Held Calculated",              # New Number field
        "Trade Result Calculated",           # New Single Select field
        "Fill Rate Calculated",              # New Single Select field
    ]
    return writable_fields

def calculate_all_metrics(record_fields):
    """Calculate all performance metrics for a single record"""
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
    
    # Calculate ALL metrics and map to new "Calculated" field names
    calculated = {}
    
    # R:R Ratio → R:R Ratio Calculated
    calculated['R:R Ratio Calculated'] = calculate_rr_ratio(entry_price, stop_loss, target_price, direction)
    
    # Risk Amount → Risk Amount Calculated
    risk_amount = calculate_risk_amount(entry_price, stop_loss, units, direction)
    calculated['Risk Amount Calculated'] = risk_amount
    
    # Position Size % → Position Size % Calculated
    calculated['Position Size % Calculated'] = calculate_position_size_percent(risk_amount, account_balance_before)
    
    # Risk Per Trade % → Risk Per Trade % Calculated
    calculated['Risk Per Trade % Calculated'] = calculated['Position Size % Calculated']
    
    # ROI % → ROI Calculated
    calculated['ROI Calculated'] = calculate_roi_percent(realized_pl, risk_amount)
    
    # Pips Gained/Lost → Pips Gained/Lost Calculated
    calculated['Pips Gained/Lost Calculated'] = calculate_pips(entry_price, exit_price, direction, instrument)
    
    # Days Held → Days Held Calculated
    calculated['Days Held Calculated'] = calculate_days_held(order_time, execution_time)
    
    # Trade Result → Trade Result Calculated
    calculated['Trade Result Calculated'] = determine_trade_result(realized_pl, exit_price)
    
    # Fill Rate → Fill Rate Calculated
    calculated['Fill Rate Calculated'] = calculate_fill_rate(order_status)
    
    # Filter to only writable fields
    writable_fields = get_writable_fields()
    writable_calculated = {k: v for k, v in calculated.items() if k in writable_fields}
    
    # Log calculated values for debugging
    logger.info(f"Calculated metrics for record: {writable_calculated}")
    
    return writable_calculated

def process_all_records():
    """Process all records and update with calculated metrics"""
    logger.info("Starting analytics calculation for all records...")
    
    try:
        # Get all records
        records = table.all()
        logger.info(f"Retrieved {len(records)} records for analysis")
        
        if not records:
            logger.info("No records found to process")
            return True
        
        updated_count = 0
        error_count = 0
        
        for record in records:
            try:
                record_id = record['id']
                fields = record['fields']
                order_id = fields.get('OANDA Order ID', 'Unknown')
                
                logger.info(f"Processing record {order_id} (ID: {record_id})")
                
                # Calculate all metrics
                calculated_metrics = calculate_all_metrics(fields)
                
                # Only update if we have calculated values
                if calculated_metrics:
                    # Filter out any None or empty values
                    update_fields = {k: v for k, v in calculated_metrics.items() 
                                   if v is not None and v != ''}
                    
                    if update_fields:
                        table.update(record_id, update_fields)
                        logger.info(f"Updated record {order_id} with calculated metrics: {list(update_fields.keys())}")
                        updated_count += 1
                    else:
                        logger.info(f"No metrics to update for record {order_id}")
                
            except Exception as e:
                logger.error(f"Error processing record {record.get('id', 'unknown')}: {e}")
                error_count += 1
                continue
        
        logger.info(f"Analytics calculation completed. Updated: {updated_count}, Errors: {error_count}")
        return error_count == 0
        
    except Exception as e:
        logger.error(f"Error in process_all_records: {e}")
        return False

def generate_summary_stats():
    """Generate summary statistics"""
    logger.info("Generating summary statistics...")
    
    try:
        records = table.all()
        if not records:
            logger.info("No records for summary statistics")
            return
        
        # Initialize counters
        total_orders = len(records)
        filled_orders = 0
        cancelled_orders = 0
        pending_orders = 0
        wins = 0
        losses = 0
        breakevens = 0
        total_pl = 0
        total_risk = 0
        
        for record in records:
            fields = record['fields']
            
            # Order status counts
            status = fields.get('Order Status', '')
            if status == 'Filled':
                filled_orders += 1
            elif status == 'Cancelled':
                cancelled_orders += 1
            elif status == 'Pending':
                pending_orders += 1
            
            # Trade results
            result = fields.get('Trade Result', '')
            if result == 'Win':
                wins += 1
            elif result == 'Loss':
                losses += 1
            elif result == 'Breakeven':
                breakevens += 1
            
            # P/L and risk totals
            total_pl += safe_float(fields.get('Realized PL'))
            total_risk += safe_float(fields.get('Risk Amount'))
        
        # Calculate percentages
        completed_orders = filled_orders + cancelled_orders
        hit_rate = (filled_orders / completed_orders * 100) if completed_orders > 0 else 0
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        
        # Log summary
        logger.info("=" * 50)
        logger.info("TRADING ANALYTICS SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Total Orders: {total_orders}")
        logger.info(f"Filled: {filled_orders} | Cancelled: {cancelled_orders} | Pending: {pending_orders}")
        logger.info(f"Hit Rate: {hit_rate:.1f}% ({filled_orders}/{completed_orders})")
        logger.info(f"Trade Results: {wins} Wins | {losses} Losses | {breakevens} Breakevens")
        logger.info(f"Win Rate: {win_rate:.1f}% ({wins}/{wins + losses})")
        logger.info(f"Total P/L: ${total_pl:.2f}")
        logger.info(f"Total Risk: ${total_risk:.2f}")
        if total_risk > 0:
            logger.info(f"Risk-Adjusted Return: {(total_pl / total_risk * 100):.1f}%")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"Error generating summary statistics: {e}")

def main():
    """Main execution function"""
    logger.info("Starting Trading Analytics Calculator...")
    
    success = True
    
    try:
        # Process all records with calculations
        if not process_all_records():
            success = False
            logger.error("Failed to process all records")
        
        # Generate summary statistics
        generate_summary_stats()
        
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        success = False
    
    if success:
        logger.info("Analytics calculation completed successfully!")
    else:
        logger.error("Analytics calculation completed with errors")
    
    return success

if __name__ == "__main__":
    main()