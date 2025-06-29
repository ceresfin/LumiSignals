import os
import json
import logging
import sys
from datetime import datetime
from pyairtable import Api
from oandapyV20 import API
from oandapyV20.endpoints.transactions import TransactionIDRange
from oandapyV20.endpoints.trades import OpenTrades

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import project config
from config.oanda_config import API_KEY, ACCOUNT_ID
from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
from src.airtable_utils import log_to_airtable

# Set up logging
LOG_FILE = os.path.join(os.path.dirname(__file__), "../logs/sync.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filemode='a'
)

# Airtable client
api = Api(AIRTABLE_API_TOKEN)
table = api.table(BASE_ID, TABLE_NAME)

# Store the last synced transaction ID
SYNC_FILE = os.path.join(os.path.dirname(__file__), "../data/last_sync.json")

def load_last_transaction_id():
    if os.path.exists(SYNC_FILE):
        with open(SYNC_FILE, "r") as f:
            try:
                return json.load(f).get("last_transaction_id", "1")
            except json.JSONDecodeError:
                return "1"
    return "1"

def save_last_transaction_id(last_id):
    with open(SYNC_FILE, "w") as f:
        json.dump({"last_transaction_id": last_id}, f)

def fetch_new_transactions():
    client = API(access_token=API_KEY, environment="practice")
    last_id = load_last_transaction_id()

    try:
        r = TransactionIDRange(accountID=ACCOUNT_ID, params={"from": str(int(last_id) + 1), "to": "99999999"})
        client.request(r)
    except Exception as e:
        logging.error(f"❌ Failed to fetch transactions: {e}")
        return

    new_transactions = r.response.get("transactions", [])
    if not new_transactions:
        logging.info("✅ No new transactions.")
        return

    for tx in new_transactions:
        if tx["type"] == "ORDER_FILL":
            trade_id = tx["id"]
            existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
            if existing:
                logging.warning(f"⚠️ Duplicate Fill ID {trade_id} — skipping")
                continue

            record = {
                "OANDA Order ID": tx["orderID"],
                "Instrument": tx["instrument"],
                "Order Type": tx.get("reason", "UNKNOWN"),
                "Direction": "Long" if int(tx["units"]) > 0 else "Short",
                "Units": abs(int(tx["units"])),
                "Filled Price": float(tx["price"]),
                "Execution Time": tx["time"],
                "Order Status": "Filled",
                "Fill ID": trade_id,
                "Realized P/L ($)": float(tx.get("pl", 0.0)),
                "Account Balance After": float(tx.get("accountBalance", 0.0)),
                "Spread Cost": float(tx.get("halfSpreadCost", 0.0)),
                "Reason": tx.get("reason", "ORDER_FILL")
            }

            try:
                response = table.create(record)
                logging.info(f"✅ Airtable record created: {response['id']}")
            except Exception as e:
                logging.error(f"❌ Failed to create Airtable record: {e}")

    # Save latest transaction ID
    latest_id = r.response.get("lastTransactionID", last_id)
    save_last_transaction_id(latest_id)
    logging.info(f"✅ Saved last transaction ID: {latest_id}")

def fetch_open_trades():
    logging.info("📡 Fetching open trades from OANDA...")
    client = API(access_token=API_KEY, environment="practice")

    try:
        r = OpenTrades(accountID=ACCOUNT_ID)
        client.request(r)
        open_trades = r.response.get("trades", [])
        logging.info(f"📘 {len(open_trades)} open trades retrieved.")
    except Exception as e:
        logging.error(f"❌ Failed to fetch open trades: {e}")
        return

    for trade in open_trades:
        trade_id = trade["id"]
        instrument = trade["instrument"]
        entry_price = float(trade["price"])
        units = int(trade["currentUnits"])
        unrealized_pl = float(trade.get("unrealizedPL", 0.0))
        realized_pl = float(trade.get("realizedPL", 0.0))
        trade_state = trade.get("state", "OPEN")

        existing = table.first(formula=f"{{Fill ID}} = '{trade_id}'")
        if existing:
            record_id = existing["id"]
            fields_to_update = {
                "Unrealized P/L ($)": unrealized_pl,
                "Trade State": trade_state,
                "Current Price": float(trade.get("price")),
                "Realized P/L ($)": realized_pl,
                "Order Status": "Open"
            }
            table.update(record_id, fields_to_update)
            logging.info(f"✅ Updated Fill ID {trade_id} with live P&L: {unrealized_pl}")
        else:
            logging.warning(f"⚠️ No Airtable match found for Fill ID {trade_id}")

if __name__ == "__main__":
    fetch_new_transactions()
    fetch_open_trades()
