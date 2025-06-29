import os
import sys
import json
import logging
from datetime import datetime
from oandapyV20 import API
from oandapyV20.endpoints.transactions import TransactionIDRange
from oandapyV20.endpoints.trades import OpenTrades
from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.exceptions import V20Error
from pyairtable import Api

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(parent_dir)

print("Starting Oanda to Airtable sync...")
print(f"Current directory: {current_dir}")
print(f"Parent directory: {parent_dir}")

# Config imports with error handling
try:
    from config.oanda_config import API_KEY, ACCOUNT_ID
    print("SUCCESS: Imported Oanda config")
except ImportError as e:
    print(f"ERROR: Failed to import Oanda config: {e}")
    sys.exit(1)

try:
    from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
    print("SUCCESS: Imported Airtable config")
except ImportError as e:
    print(f"ERROR: Failed to import Airtable config: {e}")
    sys.exit(1)

# Airtable setup with error handling
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
LOG_FILE = os.path.join(log_dir, "sync.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Helpers ---
def load_last_transaction_id():
    """Load the last processed transaction ID from file"""
    sync_file = os.path.join(current_dir, "last_sync.json")
    try:
        with open(sync_file, "r") as f:
            data = json.load(f)
            return data.get("last_transaction_id", "0")
    except FileNotFoundError:
        logger.info("No last_sync.json found, starting from transaction ID 0")
        return "0"
    except json.JSONDecodeError:
        logger.warning("Corrupted last_sync.json, starting from transaction ID 0")
        return "0"

def save_last_transaction_id(tx_id):
    """Save the last processed transaction ID to file"""
    sync_file = os.path.join(current_dir, "last_sync.json")
    try:
        with open(sync_file, "w") as f:
            json.dump({
                "last_transaction_id": tx_id,
                "last_sync_time": datetime.now().isoformat()
            }, f, indent=2)
        logger.info(f"Saved last transaction ID: {tx_id}")
    except Exception as e:
        logger.error(f"Failed to save transaction ID: {e}")

def test_oanda_connection():
    """Test connection to Oanda API"""
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = AccountSummary(accountID=ACCOUNT_ID)
        client.request(r)
        account_data = r.response.get("account", {})
        balance = account_data.get("balance", "N/A")
        logger.info(f"Oanda connection successful. Account balance: {balance}")
        return True
    except Exception as e:
        logger.error(f"Oanda connection failed: {e}")
        return False

def test_airtable_connection():
    """Test connection to Airtable"""
    try:
        records = table.all(max_records=1)
        logger.info(f"Airtable connection successful. Table has records: {len(records) > 0}")
        return True
    except Exception as e:
        logger.error(f"Airtable connection failed: {e}")
        return False

# --- 1. Sync new fills ---
def sync_new_fills():
    """Sync new transaction fills from Oanda to Airtable"""
    logger.info("Starting sync of new fills...")
    
    if not test_oanda_connection():
        return False
    
    client = API(access_token=API_KEY, environment="practice")
    last_id = load_last_transaction_id()
    
    logger.info(f"Looking for transactions after ID: {last_id}")

    try:
        from_id = str(int(last_id) + 1)
        r = TransactionIDRange(
            accountID=ACCOUNT_ID, 
            params={"from": from_id, "to": "99999999"}
        )
        client.request(r)
        
        transactions = r.response.get("transactions", [])
        logger.info(f"Retrieved {len(transactions)} transactions")
        
        if not transactions:
            logger.info("No new transactions to sync.")
            return True
            
    except V20Error as e:
        if "INVALID_RANGE" in str(e) or "Invalid value" in str(e):
            logger.info("No new transactions to sync (invalid range).")
            return True
        else:
            logger.error(f"V20Error: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error getting transactions: {e}")
        return False

    # Process each transaction
    fills_processed = 0
    orders_processed = 0
    for tx in transactions:
        tx_type = tx.get("type")
        tx_id = tx.get("id")
        logger.info(f"Processing transaction {tx_id}: {tx_type}")
        
        # Add detailed logging for ORDER_CANCEL specifically
        if tx_type == "ORDER_CANCEL":
            logger.info(f"🔍 FOUND ORDER_CANCEL transaction {tx_id}")
            logger.info(f"🔍 Full transaction data: {json.dumps(tx, indent=2)}")
        
        if tx_type == "ORDER_FILL":
            try:
                if process_order_fill(tx):
                    fills_processed += 1
            except Exception as e:
                logger.error(f"Error processing fill {tx.get('id')}: {e}")
                continue
        elif tx_type == "LIMIT_ORDER":
            try:
                if process_limit_order(tx):
                    orders_processed += 1
            except Exception as e:
                logger.error(f"Error processing limit order {tx.get('id')}: {e}")
                continue
        elif tx_type == "ORDER_CANCEL":
            logger.info(f"🔍 About to call process_order_cancel for transaction {tx_id}")
            try:
                process_order_cancel(tx)
            except Exception as e:
                logger.error(f"Error processing order cancel {tx.get('id')}: {e}")
                continue
        elif tx_type == "TAKE_PROFIT_ORDER":
            try:
                process_take_profit_order(tx)
            except Exception as e:
                logger.error(f"Error processing take profit order {tx.get('id')}: {e}")
                continue
        elif tx_type == "STOP_LOSS_ORDER":
            try:
                process_stop_loss_order(tx)
            except Exception as e:
                logger.error(f"Error processing stop loss order {tx.get('id')}: {e}")
                continue

    # Save the latest transaction ID
    latest_id = r.response.get("lastTransactionID", last_id)
    save_last_transaction_id(latest_id)
    
    logger.info(f"Sync completed. Processed {fills_processed} fills and {orders_processed} orders. Latest transaction ID: {latest_id}")
    return True

def process_order_fill(tx):
    """Process a single ORDER_FILL transaction"""
    try:
        # OPEN TRADE
        if "tradeOpened" in tx:
            trade_id = tx["tradeOpened"]["tradeID"]
            order_id = tx["orderID"]
            
            # Check if this is filling an existing limit order
            try:
                existing_order = table.first(formula=f"{{OANDA Order ID}} = '{order_id}'")
            except Exception as e:
                logger.warning(f"Error checking for existing order: {e}")
                existing_order = None
            
            # Check if record already exists by Fill ID
            try:
                existing_fill = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
            except Exception as e:
                logger.warning(f"Error checking for existing fill record: {e}")
                existing_fill = None

            # Calculate days pending if this was a limit order
            order_time = tx.get("time")
            fill_time = tx.get("time")
            days_pending = 0
            
            if existing_order:
                order_placement_time = existing_order['fields'].get('Order Time', '')
                days_pending = calculate_days_between(order_placement_time, fill_time)

            # Map order type to match Airtable field values
            order_type_mapping = {
                "ORDER_FILL": "MARKET_ORDER",
                "LIMIT_ORDER": "LIMIT_ORDER", 
                "MARKET_ORDER": "MARKET_ORDER",
                "STOP_ORDER": "STOP_LOSS_ORDER",
            }
            
            raw_order_type = tx.get("reason", "ORDER_FILL")
            mapped_order_type = order_type_mapping.get(raw_order_type, "MARKET_ORDER")

            # Use safe values for Airtable fields (formula-friendly names)
            fields = {
                "Fill ID": trade_id,
                "OANDA Order ID": order_id,
                "Instrument": tx["instrument"],
                "Order Type": mapped_order_type,  # Use mapped value that matches Airtable options
                "Direction": "Long" if int(tx["units"]) > 0 else "Short",
                "Units": abs(int(tx["units"])),
                "Entry Price": float(tx["price"]),
                "Filled Price": float(tx["price"]),
                "Execution Time": tx.get("time"),
                "Order Time": existing_order['fields'].get('Order Time', tx.get("time")) if existing_order else tx.get("time"),
                "Order Status": "Filled",  # Use exact Airtable field value  # Key status for hit rate tracking
                "Realized PL": float(tx.get("pl", 0.0)),
                "Account Balance After": float(tx.get("accountBalance", 0.0)),
                "Account Balance Before": float(tx.get("accountBalance", 0.0)) - float(tx.get("pl", 0.0)),
                "Spread Cost": float(tx.get("halfSpreadCost", 0.0)),
                "Reason": tx.get("reason", "ORDER_FILL"),
                "Initial Margin Required": float(tx.get("tradeOpened", {}).get("initialMarginRequired", 0.0)),
                "Financing": float(tx.get("financing", 0.0)),
                "Margin Used": float(tx.get("tradeOpened", {}).get("initialMarginRequired", 0.0)),
                "Trade State": "Open",
                "Days Pending": days_pending,  # Track how long order was pending
                # REMOVED: "Fill Rate": "Filled"  # This is a computed field in Airtable
            }

            # Add Stop Loss and Target Price from original order if they exist
            if "stopLossOnFill" in tx:
                fields["Stop Loss"] = float(tx["stopLossOnFill"]["price"])
                logger.info(f"Found stop loss on fill: {tx['stopLossOnFill']['price']}")
            
            if "takeProfitOnFill" in tx:
                fields["Target Price"] = float(tx["takeProfitOnFill"]["price"])
                logger.info(f"Found take profit on fill: {tx['takeProfitOnFill']['price']}")

            logger.info(f"Creating/updating Airtable record for trade open: {trade_id}")
            logger.info(f"DEBUG - ORDER_FILL fields being sent to Airtable: {fields}")
            
            if existing_order and not existing_fill:
                # Update the existing pending order record with fill data
                try:
                    logger.info(f"DEBUG - Updating existing order {order_id} with fields: {fields}")
                    table.update(existing_order["id"], fields)
                    logger.info(f"Updated pending order {order_id} with fill data for trade {trade_id}")
                except Exception as e:
                    logger.error(f"Failed to update pending order: {e}")
                    return False
            elif not existing_fill:
                # Create new record (this was likely a market order, not a limit order)
                try:
                    logger.info(f"DEBUG - Creating new record with fields: {fields}")
                    result = table.create(fields)
                    logger.info(f"Created new record for trade {trade_id}: {result['id']}")
                except Exception as e:
                    logger.error(f"Failed to create record: {e}")
                    return False
            else:
                # Update existing fill record
                try:
                    logger.info(f"DEBUG - Updating existing fill {trade_id} with fields: {fields}")
                    table.update(existing_fill["id"], fields)
                    logger.info(f"Updated existing record for trade {trade_id}")
                except Exception as e:
                    logger.error(f"Failed to update record: {e}")
                    return False
            
            return True

        # CLOSE TRADE
        elif "tradesClosed" in tx and tx["tradesClosed"]:
            for closed_trade in tx["tradesClosed"]:
                trade_id = closed_trade["tradeID"]
                
                try:
                    existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
                except Exception as e:
                    logger.warning(f"Error finding record for closed trade: {e}")
                    continue

                if not existing:
                    logger.warning(f"No matching open trade found for closed trade {trade_id}")
                    continue

                fields = {
                    "Exit Price": float(tx["price"]),
                    "Realized PL": float(closed_trade.get("realizedPL", tx.get("pl", 0.0))),  # Removed special characters
                    "Account Balance After": float(tx.get("accountBalance", 0.0)),
                    "Reason": "MARKET_ORDER",  # Use allowed Airtable value for closes
                    "Trade State": "Closed",  # Use "Closed" instead of "CLOSED"
                    "Financing": float(tx.get("financing", 0.0))  # Removed special characters
                }

                logger.info(f"Updating record for trade close: {trade_id}")
                logger.info(f"DEBUG - TRADE_CLOSE fields being sent to Airtable: {fields}")
                try:
                    table.update(existing["id"], fields)
                    logger.info(f"Updated record for closed trade {trade_id}")
                except Exception as e:
                    logger.error(f"Failed to update closed trade: {e}")
            
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error in process_order_fill: {e}")
        return False

def process_take_profit_order(tx):
    """Process a TAKE_PROFIT_ORDER transaction"""
    try:
        trade_id = tx.get("tradeID")
        if not trade_id:
            logger.warning("No trade ID found in take profit order")
            return False
        
        # Find the existing trade record
        try:
            existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for take profit order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching trade found for take profit order on trade {trade_id}")
            return False
        
        # Update with take profit price
        fields = {
            "Target Price": float(tx.get("price", 0.0))
        }
        
        logger.info(f"DEBUG - TAKE_PROFIT fields being sent to Airtable: {fields}")
        table.update(existing["id"], fields)
        logger.info(f"Updated trade {trade_id} with take profit: {tx.get('price')}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_take_profit_order: {e}")
        return False

def process_stop_loss_order(tx):
    """Process a STOP_LOSS_ORDER transaction"""
    try:
        trade_id = tx.get("tradeID")
        if not trade_id:
            logger.warning("No trade ID found in stop loss order")
            return False
        
        # Find the existing trade record
        try:
            existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for stop loss order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching trade found for stop loss order on trade {trade_id}")
            return False
        
        # Update with stop loss price
        fields = {
            "Stop Loss": float(tx.get("price", 0.0))
        }
        
        logger.info(f"DEBUG - STOP_LOSS fields being sent to Airtable: {fields}")
        table.update(existing["id"], fields)
        logger.info(f"Updated trade {trade_id} with stop loss: {tx.get('price')}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_stop_loss_order: {e}")
        return False

def process_limit_order(tx):
    """Process a LIMIT_ORDER transaction (pending order)"""
    try:
        order_id = tx.get("id")
        instrument = tx.get("instrument")
        units = int(tx.get("units", 0))
        price = float(tx.get("price", 0))
        order_time = tx.get("time")
        
        # Check if record already exists
        try:
            existing = table.first(formula=f"{{OANDA Order ID}} = '{order_id}'")
        except Exception as e:
            logger.warning(f"Error checking for existing order record: {e}")
            existing = None
        
        if existing:
            logger.info(f"Order {order_id} already exists in Airtable")
            return False
        
        # Create record for pending limit order
        fields = {
            "OANDA Order ID": order_id,
            "Instrument": instrument,
            "Order Type": "LIMIT_ORDER",  # Use exact Airtable field value
            "Direction": "Long" if units > 0 else "Short",
            "Units": abs(units),
            "Entry Price": price,
            "Order Time": order_time,
            "Order Status": "Pending",  # For hit rate tracking - this field allows "Pending"
            "Trade State": "Open",  # Only "Open" or "Closed" allowed in this field
            "Reason": "LIMIT_ORDER",  # Use allowed Airtable value
            "Account Balance After": float(tx.get("accountBalance", 0.0)),
            "Days Pending": 0,  # Will be calculated later when filled/cancelled
        }
        
        # Debug logging
        logger.info(f"DEBUG - LIMIT_ORDER fields being sent to Airtable: {fields}")
        
        result = table.create(fields)
        logger.info(f"Created pending order record for order {order_id}: {result['id']}")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_limit_order: {e}")
        return False

def process_order_cancel(tx):
    """Process an ORDER_CANCEL transaction"""
    try:
        # Try different field names for cancelled order ID based on Oanda API structure
        cancelled_order_id = tx.get("cancelledOrderID") or tx.get("orderID") or tx.get("id")
        
        if not cancelled_order_id:
            logger.warning(f"No cancelled order ID found in cancel transaction: {list(tx.keys())}")
            return False
        
        # Find the existing order record
        try:
            existing = table.first(formula=f"{{OANDA Order ID}} = '{cancelled_order_id}'")
        except Exception as e:
            logger.warning(f"Error finding record for cancelled order: {e}")
            return False
        
        if not existing:
            logger.warning(f"No matching order found for cancelled order {cancelled_order_id}")
            return False
        
        # Calculate days pending
        order_time = existing['fields'].get('Order Time', '')
        cancel_time = tx.get('time', '')
        days_pending = calculate_days_between(order_time, cancel_time)
        
        # Update with cancellation info
        fields = {
            "Order Status": "Cancelled",  # Use exact Airtable field value
            "Trade State": "Closed",  # Use "Closed" instead of "Cancelled" for Trade State
            "Reason": tx.get("reason", "CANCELLED"),
            "Days Pending": days_pending,
            # Uncomment if you add this field to Airtable:
            # "Cancel Time": cancel_time
        }
        
        table.update(existing["id"], fields)
        logger.info(f"Updated order {cancelled_order_id} status to Cancelled (pending {days_pending} days)")
        return True
        
    except Exception as e:
        logger.error(f"Error in process_order_cancel: {e}")
        return False

def calculate_days_between(start_time, end_time):
    """Calculate days between two ISO timestamps"""
    try:
        if not start_time or not end_time:
            return 0
        
        from datetime import datetime
        start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        return (end - start).days
    except:
        return 0

# --- 2. Sync open trades ---
def sync_open_trades():
    """Update open trades with current P/L and margin info"""
    logger.info("Starting sync of open trades...")
    
    if not test_oanda_connection():
        return False
    
    try:
        client = API(access_token=API_KEY, environment="practice")
        r = OpenTrades(accountID=ACCOUNT_ID)
        client.request(r)
        open_trades = r.response.get("trades", [])
        logger.info(f"Retrieved {len(open_trades)} open trades")

        if not open_trades:
            logger.info("No open trades to sync")
            return True

        updated_count = 0
        for trade in open_trades:
            try:
                trade_id = trade["id"]
                
                # Find existing record
                existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
                if not existing:
                    logger.warning(f"No Airtable record found for open trade {trade_id}")
                    continue

                # Update fields
                fields = {
                    "Trade State": "Open",  # Consistent naming
                    "Unrealized PL": float(trade.get("unrealizedPL", 0.0)),  # Removed special characters
                    "Initial Margin Required": float(trade.get("initialMarginRequired", 0.0)),
                    "Margin Used": float(trade.get("marginUsed", 0.0)),  # Removed special characters
                    "Financing": float(trade.get("financing", 0.0)),  # Removed special characters
                }

                # Add stop loss and take profit if present
                if "takeProfitOrder" in trade:
                    fields["Target Price"] = float(trade["takeProfitOrder"].get("price", 0.0))
                if "stopLossOrder" in trade:
                    fields["Stop Loss"] = float(trade["stopLossOrder"].get("price", 0.0))

                logger.info(f"DEBUG - OPEN_TRADES fields being sent to Airtable: {fields}")
                table.update(existing["id"], fields)
                updated_count += 1
                logger.info(f"Updated open trade {trade_id}")
                
            except Exception as e:
                logger.error(f"Error updating trade {trade.get('id', 'unknown')}: {e}")
                continue

        logger.info(f"Updated {updated_count} open trades")
        return True
        
    except Exception as e:
        logger.error(f"Error in sync_open_trades: {e}")
        return False

# --- Main execution ---
def main():
    """Main execution function"""
    logger.info("Starting Oanda to Airtable sync...")
    
    # Test connections first
    logger.info("Testing connections...")
    if not test_airtable_connection():
        logger.error("Cannot proceed without Airtable connection")
        return False
    
    # Run syncs
    success = True
    
    try:
        # Sync new fills first
        if not sync_new_fills():
            success = False
            logger.error("Failed to sync new fills")
        
        # Then update open trades
        if not sync_open_trades():
            success = False
            logger.error("Failed to sync open trades")
            
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        success = False
    
    if success:
        logger.info("Sync completed successfully!")
    else:
        logger.error("Sync completed with errors")
    
    return success

if __name__ == "__main__":
    main()