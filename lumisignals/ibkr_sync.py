"""IB Gateway sync — polls positions and account data, pushes to LumiSignals server.

Run locally while IB Gateway is open:
    python3 -m lumisignals.ibkr_sync

Pushes data every 30 seconds to the server API.
"""

import json
import logging
import os
import sys
import time

import requests
from ib_insync import IB, Stock, Option

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ibkr_sync")

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
SYNC_KEY = os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")
IB_HOST = os.environ.get("IB_HOST", "127.0.0.1")
IB_PORT = int(os.environ.get("IB_PORT", "4002"))
SYNC_INTERVAL = 30


def collect_ib_data(ib: IB) -> dict:
    """Collect all relevant data from IB Gateway."""

    # Account summary
    account = {}
    for item in ib.accountSummary():
        if item.tag in ("NetLiquidation", "TotalCashValue", "BuyingPower",
                        "GrossPositionValue", "UnrealizedPnL", "RealizedPnL",
                        "AvailableFunds", "InitMarginReq", "MaintMarginReq"):
            account[item.tag] = float(item.value)

    # Positions
    positions = []
    for pos in ib.positions():
        c = pos.contract
        entry = {
            "symbol": c.symbol,
            "sec_type": c.secType,
            "quantity": float(pos.position),
            "avg_cost": pos.avgCost,
            "con_id": c.conId,
        }
        if c.secType == "OPT":
            entry["expiration"] = c.lastTradeDateOrContractMonth
            entry["strike"] = c.strike
            entry["right"] = c.right  # C or P
            entry["multiplier"] = int(c.multiplier or 100)
        positions.append(entry)

    # Group option positions into spreads
    spreads = _detect_spreads(positions)

    # Open orders
    open_orders = []
    for trade in ib.openTrades():
        o = trade.order
        c = trade.contract
        order_entry = {
            "order_id": o.orderId,
            "symbol": c.symbol,
            "sec_type": c.secType,
            "action": o.action,
            "quantity": float(o.totalQuantity),
            "order_type": o.orderType,
            "limit_price": o.lmtPrice,
            "status": trade.orderStatus.status,
        }
        if c.secType == "BAG":
            # Combo order (spread)
            legs = []
            for leg in c.comboLegs:
                legs.append({
                    "con_id": leg.conId,
                    "action": leg.action,
                    "ratio": leg.ratio,
                })
            order_entry["legs"] = legs
            order_entry["sec_type"] = "SPREAD"
        elif c.secType == "OPT":
            order_entry["expiration"] = c.lastTradeDateOrContractMonth
            order_entry["strike"] = c.strike
            order_entry["right"] = c.right
        open_orders.append(order_entry)

    # Completed (filled) orders — recent trades
    filled_orders = []
    for fill in ib.fills():
        c = fill.contract
        e = fill.execution
        entry = {
            "order_id": e.orderId,
            "symbol": c.symbol,
            "sec_type": c.secType,
            "action": e.side,
            "quantity": float(e.shares),
            "price": e.price,
            "time": str(e.time),
        }
        if c.secType == "OPT":
            entry["expiration"] = c.lastTradeDateOrContractMonth
            entry["strike"] = c.strike
            entry["right"] = c.right
        filled_orders.append(entry)

    return {
        "account": account,
        "positions": positions,
        "spreads": spreads,
        "open_orders": open_orders,
        "filled_orders": filled_orders,
    }


def _detect_spreads(positions: list) -> list:
    """Group option positions into vertical spreads."""
    # Group by symbol + expiration + right
    from collections import defaultdict
    groups = defaultdict(list)
    for pos in positions:
        if pos["sec_type"] == "OPT":
            key = (pos["symbol"], pos["expiration"], pos["right"])
            groups[key].append(pos)

    spreads = []
    for (symbol, expiration, right), legs in groups.items():
        if len(legs) == 2:
            # Sort by strike
            legs.sort(key=lambda x: x["strike"])
            long_leg = next((l for l in legs if l["quantity"] > 0), None)
            short_leg = next((l for l in legs if l["quantity"] < 0), None)

            if long_leg and short_leg:
                width = abs(long_leg["strike"] - short_leg["strike"])
                # Determine spread type
                if right == "P":
                    if short_leg["strike"] > long_leg["strike"]:
                        spread_type = "Put Credit Spread"
                    else:
                        spread_type = "Put Debit Spread"
                else:
                    if short_leg["strike"] < long_leg["strike"]:
                        spread_type = "Call Credit Spread"
                    else:
                        spread_type = "Call Debit Spread"

                # Net cost = what we paid (debit) or received (credit)
                net_cost = (long_leg["avg_cost"] - short_leg["avg_cost"])

                spreads.append({
                    "symbol": symbol,
                    "expiration": expiration,
                    "right": right,
                    "spread_type": spread_type,
                    "long_strike": long_leg["strike"],
                    "short_strike": short_leg["strike"],
                    "quantity": abs(long_leg["quantity"]),
                    "width": width,
                    "net_cost": round(net_cost, 2),
                    "max_risk": round((width * 100) - abs(net_cost), 2) if "Credit" in spread_type else round(abs(net_cost), 2),
                    "max_profit": round(abs(net_cost), 2) if "Credit" in spread_type else round((width * 100) - abs(net_cost), 2),
                })
            else:
                # Naked option positions
                for leg in legs:
                    spreads.append({
                        "symbol": symbol,
                        "expiration": expiration,
                        "right": right,
                        "spread_type": "Long " + ("Call" if right == "C" else "Put") if leg["quantity"] > 0 else "Short " + ("Call" if right == "C" else "Put"),
                        "long_strike": leg["strike"] if leg["quantity"] > 0 else 0,
                        "short_strike": leg["strike"] if leg["quantity"] < 0 else 0,
                        "quantity": abs(leg["quantity"]),
                        "width": 0,
                        "net_cost": round(leg["avg_cost"], 2),
                        "max_risk": round(leg["avg_cost"], 2),
                        "max_profit": 0,
                    })
        else:
            # Single option leg (not a spread)
            for leg in legs:
                direction = "Long" if leg["quantity"] > 0 else "Short"
                opt_type = "Call" if right == "C" else "Put"
                spreads.append({
                    "symbol": symbol,
                    "expiration": expiration,
                    "right": right,
                    "spread_type": f"{direction} {opt_type}",
                    "long_strike": leg["strike"] if leg["quantity"] > 0 else 0,
                    "short_strike": leg["strike"] if leg["quantity"] < 0 else 0,
                    "quantity": abs(leg["quantity"]),
                    "width": 0,
                    "net_cost": round(leg["avg_cost"], 2),
                    "max_risk": round(leg["avg_cost"], 2),
                    "max_profit": 0,
                })

    return spreads


def check_analyze_requests(ib: IB):
    """Check Redis (via server) for pending options analyze requests."""
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/analyze/pending",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return

        requests_list = resp.json().get("requests", [])
        for req in requests_list:
            ticker = req["ticker"]
            zone_type = req.get("zone_type", "supply")
            zone_price = float(req.get("zone_price", 0))
            current_price = float(req.get("current_price", 0))
            request_id = req["request_id"]

            logger.info("Analyzing options for %s (%s zone @ %.2f)", ticker, zone_type, zone_price)

            from .ibkr_analyzer import analyze_spreads_ib
            result = analyze_spreads_ib(ib, ticker, zone_type, zone_price, current_price)
            result["request_id"] = request_id
            result["ticker"] = ticker

            # Push result back
            requests.post(
                f"{SERVER_URL}/api/ibkr/analyze/result",
                json=result,
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=10,
            )
            logger.info("Analysis complete for %s: credit=%s, debit=%s",
                         ticker,
                         result["credit_spread"]["verdict"] if result.get("credit_spread") else "none",
                         result["debit_spread"]["verdict"] if result.get("debit_spread") else "none")

    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.debug("Analyze check: %s", e)


def check_order_requests(ib: IB):
    """Check for pending spread orders to place on IB."""
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/orders/pending",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return

        orders = resp.json().get("orders", [])
        for order in orders:
            order_id = order["order_id"]
            ticker = order["ticker"]
            spread_type = order["spread_type"]
            buy_strike = float(order["buy_strike"])
            sell_strike = float(order["sell_strike"])
            right = order["right"]
            expiration = order["expiration"]
            quantity = int(order["quantity"])
            limit_price = float(order["limit_price"])

            is_credit = "Credit" in spread_type
            logger.info("Placing %s order: %s SELL %s / BUY %s %s exp %s x%d @ $%.2f (%s)",
                        spread_type, ticker, sell_strike, buy_strike, right, expiration, quantity, limit_price,
                        "credit" if is_credit else "debit")

            try:
                from ib_insync import Option, ComboLeg, Contract, LimitOrder

                buy_contract = Option(ticker, expiration, buy_strike, right, "SMART")
                sell_contract = Option(ticker, expiration, sell_strike, right, "SMART")
                ib.qualifyContracts(buy_contract, sell_contract)

                # Verify strikes are valid
                if not buy_contract.conId or not sell_contract.conId:
                    raise ValueError(f"Could not qualify contracts: buy={buy_strike} sell={sell_strike}")

                combo = Contract()
                combo.symbol = ticker
                combo.secType = "BAG"
                combo.currency = "USD"
                combo.exchange = "SMART"

                # For credit spreads: sell the expensive leg, buy the cheap leg
                # For debit spreads: buy the expensive leg, sell the cheap leg
                # IB combo: leg actions are absolute (BUY/SELL per leg)
                # Order action "BUY" with negative price = receive credit
                # Order action "BUY" with positive price = pay debit

                leg1 = ComboLeg()
                leg1.conId = sell_contract.conId
                leg1.ratio = 1
                leg1.action = "SELL"
                leg1.exchange = "SMART"

                leg2 = ComboLeg()
                leg2.conId = buy_contract.conId
                leg2.ratio = 1
                leg2.action = "BUY"
                leg2.exchange = "SMART"

                combo.comboLegs = [leg1, leg2]

                if is_credit:
                    # Credit spread: we receive premium
                    # IB: BUY the combo at negative price = receive credit
                    ib_order = LimitOrder("BUY", quantity, -limit_price)
                else:
                    # Debit spread: we pay premium
                    # IB: BUY the combo at positive price = pay debit
                    ib_order = LimitOrder("BUY", quantity, limit_price)

                ib_order.tif = "GTC"

                trade = ib.placeOrder(combo, ib_order)
                ib.sleep(2)

                result = {
                    "order_id": order_id,
                    "ib_order_id": trade.order.orderId,
                    "status": trade.orderStatus.status,
                    "ticker": ticker,
                    "spread_type": spread_type,
                    "message": f"Order placed: {trade.orderStatus.status}",
                }
                logger.info("Order placed: %s — %s", ticker, trade.orderStatus.status)

            except Exception as e:
                result = {
                    "order_id": order_id,
                    "status": "FAILED",
                    "ticker": ticker,
                    "error": str(e),
                    "message": f"Order failed: {e}",
                }
                logger.error("Order failed for %s: %s", ticker, e)

            # Push result back
            requests.post(
                f"{SERVER_URL}/api/ibkr/order/result",
                json=result,
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=10,
            )

    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.debug("Order check: %s", e)


def push_to_server(data: dict):
    """Push IB data to the LumiSignals server."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/api/ibkr/sync",
            json=data,
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.debug("Synced to server")
        else:
            logger.warning("Server returned %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("Failed to push to server: %s", e)


def main():
    logger.info("IB Sync starting — connecting to IB Gateway at %s:%s", IB_HOST, IB_PORT)

    ib = IB()
    try:
        ib.connect(IB_HOST, IB_PORT, clientId=10)
        ib.reqMarketDataType(3)  # delayed data
    except Exception as e:
        logger.error("Failed to connect to IB Gateway: %s", e)
        logger.error("Make sure IB Gateway is running and API connections are enabled")
        sys.exit(1)

    logger.info("Connected to IB Gateway — syncing every %ds to %s", SYNC_INTERVAL, SERVER_URL)

    while True:
        try:
            ib.sleep(1)  # let ib_insync process events
            data = collect_ib_data(ib)

            acct = data["account"]
            n_pos = len(data["positions"])
            n_spreads = len(data["spreads"])
            n_orders = len(data["open_orders"])
            logger.info(
                "NAV: $%s | Positions: %d | Spreads: %d | Open orders: %d",
                f"{acct.get('NetLiquidation', 0):,.2f}", n_pos, n_spreads, n_orders,
            )

            push_to_server(data)

            # Check for options analyze requests
            check_analyze_requests(ib)

            # Check for pending orders to place
            check_order_requests(ib)

        except Exception as e:
            logger.error("Sync error: %s", e)

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
