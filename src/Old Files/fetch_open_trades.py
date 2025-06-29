import os
import sys
import json
import logging
from oandapyV20 import API
from oandapyV20.endpoints.trades import OpenTrades

# Add project root to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Config
from config.oanda_config import API_KEY, ACCOUNT_ID
from config.airtable_config import AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME
from src.airtable_utils import get_airtable_table

# Setup logging
LOG_FILE = os.path.join(os.path.dirname(__file__), "../logs/sync.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filemode="a"
)
logger = logging.getLogger(__name__)

def fetch_open_trades_to_airtable(api_key, account_id):
    logger.info("🔍 Fetching open trades for Airtable sync...")

    try:
        client = API(access_token=api_key, environment="practice")
        r = OpenTrades(accountID=account_id)
        client.request(r)

        open_trades = r.response.get("trades", [])
        logger.info(f"✅ {len(open_trades)} open trades retrieved.")

        table = get_airtable_table(AIRTABLE_API_TOKEN, BASE_ID, TABLE_NAME)

        for trade in open_trades:
            logger.info(json.dumps(trade, indent=2))  # Optional: log the full trade JSON

            trade_id = trade.get("id")
            instrument = trade.get("instrument")
            entry_price = float(trade.get("price", 0))
            units = int(trade.get("currentUnits", 0))
            unrealized_pl = float(trade.get("unrealizedPL", 0))
            trade_state = trade.get("state", "OPEN")
            initial_margin = float(trade.get("initialMarginRequired", 0))
            financing = float(trade.get("financing", 0))
            margin_used = float(trade.get("marginUsed", 0))

            # Extract Stop Loss and Take Profit from sub-orders
            stop_loss_price = None
            take_profit_price = None

            if "stopLossOrder" in trade:
                stop_loss_price = float(trade["stopLossOrder"].get("price", 0))

            if "takeProfitOrder" in trade:
                take_profit_price = float(trade["takeProfitOrder"].get("price", 0))

            # Check if record already exists
            existing = table.first(formula=f"{{OANDA Order ID}} = '{trade_id}'")
            fields = {
                "OANDA Order ID": trade_id,
                "Instrument": instrument,
                "Direction": "Long" if units > 0 else "Short",
                "Units": abs(units),
                "Entry Price": entry_price,
                "Unrealized P/L ($)": unrealized_pl,
                "Trade State": trade_state,
                "Initial Margin": initial_margin,
                "Financing": financing,
                "Margin Used": margin_used,
                "Stop Loss": stop_loss_price,
                "Target Price": take_profit_price,
                "Reason": "ORDER_FILL"
            }

            try:
                if existing:
                    table.update(existing["id"], fields)
                    logger.info(f"🔁 Updated trade ID {trade_id}")
                else:
                    table.create(fields)
                    logger.info(f"✅ Created new trade record ID {trade_id}")
            except Exception as e:
                logger.error(f"❌ Airtable sync error for trade ID {trade_id}: {e}")

    except Exception as e:
        logger.error(f"❌ Error fetching open trades: {e}")

if __name__ == "__main__":
    fetch_open_trades_to_airtable(API_KEY, ACCOUNT_ID)

