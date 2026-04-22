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

    # Positions with market values and P&L
    positions = []
    portfolio_items = ib.portfolio()
    for item in portfolio_items:
        c = item.contract
        entry = {
            "symbol": c.symbol,
            "sec_type": c.secType,
            "quantity": float(item.position),
            "avg_cost": item.averageCost,
            "market_price": item.marketPrice,
            "market_value": item.marketValue,
            "unrealized_pnl": item.unrealizedPNL,
            "realized_pnl": item.realizedPNL,
            "con_id": c.conId,
        }
        if c.secType == "OPT":
            entry["expiration"] = c.lastTradeDateOrContractMonth
            entry["strike"] = c.strike
            entry["right"] = c.right
            entry["multiplier"] = int(c.multiplier or 100)
        positions.append(entry)
    # Fallback to ib.positions() if portfolio is empty
    if not positions:
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
                entry["right"] = c.right
                entry["multiplier"] = int(c.multiplier or 100)
            positions.append(entry)

    # Group option positions into spreads
    spreads = _detect_spreads(positions)

    # Enrich spreads with signal metadata from stored order details
    for spread in spreads:
        try:
            # Search order details by ticker + strikes
            for key_suffix in ["done", "details"]:
                resp = requests.get(
                    f"{SERVER_URL}/api/ibkr/order/search",
                    params={"ticker": spread["symbol"], "sell_strike": spread.get("short_strike", 0), "buy_strike": spread.get("long_strike", 0)},
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=5,
                )
                if resp.status_code == 200:
                    details = resp.json()
                    if details.get("model"):
                        spread["model"] = details.get("model", "")
                        spread["strategy"] = details.get("strategy", "")
                        spread["trigger_pattern"] = details.get("trigger_pattern", "")
                        spread["bias_score"] = details.get("bias_score", 0)
                        spread["zone_type"] = details.get("zone_type", "")
                        spread["zone_timeframe"] = details.get("zone_timeframe", "")
                        spread["verdict"] = details.get("verdict", "")
                        spread["opened_at"] = details.get("queued_at", "")
                        break
        except Exception:
            pass

    # Open orders — resolve combo legs to get strike/expiration details
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
            "time": str(trade.log[0].time) if trade.log else "",
        }
        if c.secType == "BAG":
            # Combo order (spread) — resolve leg details
            legs = []
            sell_strike = 0
            buy_strike = 0
            expiration = ""
            right = ""
            for leg in c.comboLegs:
                leg_info = {"con_id": leg.conId, "action": leg.action, "ratio": leg.ratio}
                # Resolve contract details using Option contract
                try:
                    from ib_insync import Option as IBOption
                    leg_contract = IBOption(conId=leg.conId)
                    ib.qualifyContracts(leg_contract)
                    leg_info["strike"] = leg_contract.strike
                    leg_info["expiration"] = leg_contract.lastTradeDateOrContractMonth
                    leg_info["right"] = leg_contract.right
                    if leg.action == "SELL":
                        sell_strike = leg_info["strike"]
                    else:
                        buy_strike = leg_info["strike"]
                    if not expiration:
                        expiration = leg_info["expiration"]
                    if not right:
                        right = leg_info["right"]
                except Exception:
                    pass
                legs.append(leg_info)
            # If leg resolution failed, look up stored order details from server
            if not right:
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/order/details/{o.orderId}",
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        details = resp.json()
                        if details.get("right"):
                            right = details["right"]
                            sell_strike = float(details.get("sell_strike", sell_strike))
                            buy_strike = float(details.get("buy_strike", buy_strike))
                            expiration = details.get("expiration", expiration)
                            order_entry["spread_type"] = details.get("spread_type", "")
                            order_entry["is_credit"] = details.get("is_credit", False)
                            order_entry["model"] = details.get("model", "")
                            order_entry["trigger_pattern"] = details.get("trigger_pattern", "")
                            order_entry["bias_score"] = details.get("bias_score", 0)
                            order_entry["zone_type"] = details.get("zone_type", "")
                            order_entry["zone_timeframe"] = details.get("zone_timeframe", "")
                            order_entry["verdict"] = details.get("verdict", "")
                except Exception:
                    pass
            order_entry["legs"] = legs
            order_entry["sec_type"] = "SPREAD"
            order_entry["sell_strike"] = sell_strike
            order_entry["buy_strike"] = buy_strike
            order_entry["expiration"] = expiration
            order_entry["right"] = right
            # Determine spread type from leg structure
            # Credit spread: sell the more expensive (closer to money) option
            # For calls: sell lower strike = bear call credit
            # For puts: sell higher strike = bull put credit
            width = abs(sell_strike - buy_strike) if sell_strike and buy_strike else 0
            premium = abs(o.lmtPrice)
            if right == "C":
                if sell_strike < buy_strike:
                    order_entry["spread_type"] = "Bear Call Credit"
                    order_entry["direction"] = "SELL"
                else:
                    order_entry["spread_type"] = "Bull Call Debit"
                    order_entry["direction"] = "BUY"
            elif right == "P":
                if sell_strike > buy_strike:
                    order_entry["spread_type"] = "Bull Put Credit"
                    order_entry["direction"] = "BUY"
                else:
                    order_entry["spread_type"] = "Bear Put Debit"
                    order_entry["direction"] = "SELL"
            else:
                order_entry["spread_type"] = "Spread"
                order_entry["direction"] = ""
            is_credit = "Credit" in order_entry["spread_type"]
            order_entry["width"] = width
            order_entry["net_premium"] = premium
            order_entry["is_credit"] = is_credit
            if is_credit:
                order_entry["max_profit"] = round(premium * 100, 2)
                order_entry["max_risk"] = round((width - premium) * 100, 2) if width else 0
            else:
                order_entry["max_risk"] = round(premium * 100, 2)
                order_entry["max_profit"] = round((width - premium) * 100, 2) if width else 0
            order_entry["risk_reward"] = round(order_entry["max_profit"] / order_entry["max_risk"], 2) if order_entry["max_risk"] > 0 else 0
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
    """Group option positions into vertical spreads.

    Handles multiple spreads on the same symbol by pairing each short leg
    with the nearest long leg at a different strike, matching quantities.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for pos in positions:
        if pos["sec_type"] == "OPT":
            key = (pos["symbol"], pos["expiration"], pos["right"])
            groups[key].append(pos)

    spreads = []
    for (symbol, expiration, right), legs in groups.items():
        # Separate into long and short legs
        longs = [l for l in legs if l["quantity"] > 0]
        shorts = [l for l in legs if l["quantity"] < 0]

        # Sort by strike
        longs.sort(key=lambda x: x["strike"])
        shorts.sort(key=lambda x: x["strike"])

        # Pair each short leg with the nearest long leg
        used_longs = set()
        for short_leg in shorts:
            # Find closest long leg by strike that hasn't been fully used
            best_long = None
            best_dist = float("inf")
            for i, long_leg in enumerate(longs):
                if i in used_longs:
                    continue
                dist = abs(long_leg["strike"] - short_leg["strike"])
                if dist > 0 and dist < best_dist:
                    best_long = long_leg
                    best_long_idx = i
                    best_dist = dist

            if best_long:
                used_longs.add(best_long_idx)
                # Determine quantity (use the smaller of the two)
                qty = min(abs(short_leg["quantity"]), abs(best_long["quantity"]))
                width = abs(best_long["strike"] - short_leg["strike"])

                # Determine spread type
                if right == "P":
                    if short_leg["strike"] > best_long["strike"]:
                        spread_type = "Put Credit Spread"
                    else:
                        spread_type = "Put Debit Spread"
                else:
                    if short_leg["strike"] < best_long["strike"]:
                        spread_type = "Call Credit Spread"
                    else:
                        spread_type = "Call Debit Spread"

                net_cost = (best_long["avg_cost"] - short_leg["avg_cost"]) * qty / qty if qty else 0

                # P&L
                long_pnl = (best_long.get("unrealized_pnl", 0) or 0)
                short_pnl = (short_leg.get("unrealized_pnl", 0) or 0)
                # Scale P&L if quantities don't match exactly
                if abs(best_long["quantity"]) != qty:
                    long_pnl = long_pnl * qty / abs(best_long["quantity"])
                if abs(short_leg["quantity"]) != qty:
                    short_pnl = short_pnl * qty / abs(short_leg["quantity"])
                spread_pnl = round(long_pnl + short_pnl, 2)

                long_mkt = (best_long.get("market_value", 0) or 0)
                short_mkt = (short_leg.get("market_value", 0) or 0)
                if abs(best_long["quantity"]) != qty:
                    long_mkt = long_mkt * qty / abs(best_long["quantity"])
                if abs(short_leg["quantity"]) != qty:
                    short_mkt = short_mkt * qty / abs(short_leg["quantity"])
                current_value = round(long_mkt + short_mkt, 2)

                spreads.append({
                    "symbol": symbol,
                    "expiration": expiration,
                    "right": right,
                    "spread_type": spread_type,
                    "long_strike": best_long["strike"],
                    "short_strike": short_leg["strike"],
                    "quantity": qty,
                    "width": width,
                    "net_cost": round(net_cost, 2),
                    "max_risk": round((width * 100) - abs(net_cost), 2) if "Credit" in spread_type else round(abs(net_cost), 2),
                    "max_profit": round(abs(net_cost), 2) if "Credit" in spread_type else round((width * 100) - abs(net_cost), 2),
                    "unrealized_pnl": spread_pnl,
                    "current_value": current_value,
                })
            else:
                # Unpaired short leg
                spreads.append(_single_leg_entry(symbol, expiration, right, short_leg))

        # Any unpaired long legs
        for i, long_leg in enumerate(longs):
            if i not in used_longs:
                spreads.append(_single_leg_entry(symbol, expiration, right, long_leg))

    return spreads


def _single_leg_entry(symbol, expiration, right, leg):
    """Create a spread entry for an unpaired single option leg."""
    direction = "Long" if leg["quantity"] > 0 else "Short"
    opt_type = "Call" if right == "C" else "Put"
    return {
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
        "unrealized_pnl": round(leg.get("unrealized_pnl", 0) or 0, 2),
        "current_value": round(leg.get("market_value", 0) or 0, 2),
    }


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
                    "sell_strike": sell_strike,
                    "buy_strike": buy_strike,
                    "right": right,
                    "expiration": expiration,
                    "quantity": quantity,
                    "limit_price": limit_price,
                    "is_credit": is_credit,
                    "message": f"Order placed: {trade.orderStatus.status}",
                    # Pass through signal metadata
                    "model": order.get("model", ""),
                    "strategy": order.get("strategy", ""),
                    "zone_type": order.get("zone_type", ""),
                    "zone_price": order.get("zone_price", 0),
                    "trigger_pattern": order.get("trigger_pattern", ""),
                    "bias_score": order.get("bias_score", 0),
                    "zone_timeframe": order.get("zone_timeframe", ""),
                    "verdict": order.get("verdict", ""),
                    "width": order.get("width", 0),
                    "max_risk": order.get("max_risk", 0),
                    "max_profit": order.get("max_profit", 0),
                    "risk_reward": order.get("risk_reward", 0),
                }
                # Update order status on server
                try:
                    requests.post(
                        f"{SERVER_URL}/api/ibkr/order/update",
                        json=result,
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=10,
                    )
                except Exception:
                    pass
                logger.info("Order placed: %s — %s", ticker, trade.orderStatus.status)

            except Exception as e:
                result = {
                    "order_id": order_id,
                    "status": "failed",
                    "ticker": ticker,
                    "error": str(e),
                    "message": f"Order failed: {e}",
                }
                logger.error("Order failed for %s: %s", ticker, e)

            # Update order status on server
            try:
                requests.post(
                    f"{SERVER_URL}/api/ibkr/order/update",
                    json=result,
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=10,
                )
            except Exception:
                pass

    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.error("Order check error: %s", e)
        import traceback
        traceback.print_exc()


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


def monitor_spreads(ib: IB, spreads: list):
    """Monitor open spreads and auto-close when TP/SL/time stop is hit."""
    if not spreads:
        return

    # Fetch exit rules from server
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/exit-rules",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return
        rules = resp.json()
    except Exception:
        return

    credit_tp_pct = rules.get("credit_tp_pct", 50)
    credit_sl_pct = rules.get("credit_sl_pct", 100)
    debit_tp_pct = rules.get("debit_tp_pct", 75)
    debit_sl_pct = rules.get("debit_sl_pct", 50)
    time_stop_dte = rules.get("time_stop_dte", 7)

    from datetime import datetime, timezone

    for spread in spreads:
        symbol = spread["symbol"]
        spread_type = spread.get("spread_type", "")
        is_credit = "Credit" in spread_type
        net_cost = abs(spread.get("net_cost", 0))
        pnl = spread.get("unrealized_pnl", 0)
        expiration = spread.get("expiration", "")
        quantity = spread.get("quantity", 0)

        if not net_cost or not expiration or not quantity:
            continue

        # Calculate DTE
        try:
            exp_date = datetime.strptime(expiration, "%Y%m%d").date()
            dte = (exp_date - datetime.now().date()).days
        except Exception:
            dte = 999

        close_reason = None
        close_price = None  # limit price for closing order

        if is_credit:
            # Credit spread: net_cost is the credit received (positive)
            credit_received = net_cost  # per contract, in dollars (e.g. $34.40 for 1 contract)
            credit_per_contract = credit_received / quantity if quantity else credit_received

            # TP: close when we can buy back at (100 - tp_pct)% of credit
            # e.g. 50% TP on $0.50 credit = buy back at $0.25
            tp_threshold = credit_per_contract * (1 - credit_tp_pct / 100)
            # Current value: credit_received + pnl (pnl negative = spread moved against us)
            current_value = credit_received + pnl

            if pnl > 0 and pnl >= credit_received * (credit_tp_pct / 100):
                close_reason = f"TAKE PROFIT — captured {credit_tp_pct}% of credit (P&L: ${pnl:+.2f})"

            # SL: close when loss exceeds X% of credit
            elif pnl < 0 and abs(pnl) >= credit_received * (credit_sl_pct / 100):
                close_reason = f"STOP LOSS — loss exceeded {credit_sl_pct}% of credit (P&L: ${pnl:+.2f})"

        else:
            # Debit spread: net_cost is what we paid (positive)
            debit_paid = net_cost

            # TP: close when gain >= tp_pct% of debit paid
            if pnl > 0 and pnl >= debit_paid * (debit_tp_pct / 100):
                close_reason = f"TAKE PROFIT — {debit_tp_pct}% gain (P&L: ${pnl:+.2f})"

            # SL: close when loss >= sl_pct% of debit paid
            elif pnl < 0 and abs(pnl) >= debit_paid * (debit_sl_pct / 100):
                close_reason = f"STOP LOSS — {debit_sl_pct}% loss (P&L: ${pnl:+.2f})"

        # Time stop
        if not close_reason and dte <= time_stop_dte:
            close_reason = f"TIME STOP — {dte} DTE remaining (limit: {time_stop_dte})"

        if close_reason:
            logger.info("CLOSING %s %s: %s", symbol, spread_type, close_reason)
            try:
                _close_spread(ib, spread, close_reason)
            except Exception as e:
                logger.error("Failed to close %s spread: %s", symbol, e)


def _close_spread(ib: IB, spread: dict, reason: str):
    """Close an open spread by placing an opposite market order."""
    from ib_insync import Option, ComboLeg, Contract, MarketOrder

    symbol = spread["symbol"]
    expiration = spread.get("expiration", "")
    right = spread.get("right", "")
    long_strike = spread.get("long_strike", 0)
    short_strike = spread.get("short_strike", 0)
    quantity = int(spread.get("quantity", 0))

    if not all([symbol, expiration, right, long_strike, short_strike, quantity]):
        logger.error("Missing data to close spread: %s", spread)
        return

    # Build closing combo — reverse the legs
    long_contract = Option(symbol, expiration, long_strike, right, "SMART")
    short_contract = Option(symbol, expiration, short_strike, right, "SMART")
    ib.qualifyContracts(long_contract, short_contract)

    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = "SMART"

    # Close: SELL the long leg, BUY the short leg
    leg1 = ComboLeg()
    leg1.conId = long_contract.conId
    leg1.ratio = 1
    leg1.action = "SELL"
    leg1.exchange = "SMART"

    leg2 = ComboLeg()
    leg2.conId = short_contract.conId
    leg2.ratio = 1
    leg2.action = "BUY"
    leg2.exchange = "SMART"

    combo.comboLegs = [leg1, leg2]

    order = MarketOrder("BUY", quantity)
    order.tif = "DAY"

    trade = ib.placeOrder(combo, order)
    ib.sleep(3)

    logger.info("Close order for %s: status=%s reason=%s", symbol, trade.orderStatus.status, reason)

    # Send alert
    try:
        from lumisignals.alerts import send_alert, AlertType
        alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
        if alert_pass:
            send_alert(
                AlertType.TRADE_CLOSED,
                f"{symbol} spread closed — {reason}",
                f"Auto-closed {spread.get('spread_type', '')} on {symbol}",
                details={
                    "Symbol": symbol,
                    "Spread": spread.get("spread_type", ""),
                    "P&L": f"${spread.get('unrealized_pnl', 0):+.2f}",
                    "Reason": reason,
                },
                smtp_pass=alert_pass,
            )
    except Exception:
        pass

    # Record closed trade on server
    try:
        from datetime import datetime, timezone
        closed_trade = {
            "symbol": symbol,
            "spread_type": spread.get("spread_type", ""),
            "long_strike": spread.get("long_strike", 0),
            "short_strike": spread.get("short_strike", 0),
            "right": spread.get("right", ""),
            "expiration": expiration,
            "quantity": quantity,
            "entry_cost": spread.get("net_cost", 0),
            "realized_pnl": spread.get("unrealized_pnl", 0),
            "close_reason": reason,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "model": spread.get("model", ""),
            "strategy": spread.get("strategy", ""),
            "trigger_pattern": spread.get("trigger_pattern", ""),
            "bias_score": spread.get("bias_score", 0),
            "zone_type": spread.get("zone_type", ""),
            "zone_timeframe": spread.get("zone_timeframe", ""),
            "opened_at": spread.get("opened_at", ""),
        }
        requests.post(
            f"{SERVER_URL}/api/ibkr/closed-trade",
            json=closed_trade,
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=10,
        )
    except Exception:
        pass


def main():
    logger.info("IB Sync starting — connecting to IB Gateway at %s:%s", IB_HOST, IB_PORT)

    ib = IB()
    try:
        import random
        cid = random.randint(20, 99)
        ib.connect(IB_HOST, IB_PORT, clientId=cid)
        logger.info("Using clientId %d", cid)
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

            # Monitor open spreads for TP/SL/time stop
            if data.get("spreads"):
                monitor_spreads(ib, data["spreads"])

        except Exception as e:
            logger.error("Sync error: %s", e)

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
