"""IB Client Portal API sync — polls positions and account data via REST.

Runs on the server alongside the CPAPI gateway (Docker).
No ib_insync or local IB Gateway needed.

    python3 -m lumisignals.ibkr_sync_cpapi

Pushes data every 10 seconds to the LumiSignals server API.
"""

import json
import logging
import os
import sys
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ibkr_sync")

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
SYNC_KEY = os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")
CPAPI_URL = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api")
SYNC_INTERVAL = 10


def sync_positions_to_supabase(positions: list):
    """Refresh entry_price + unrealized_pl on existing Supabase position rows
    for each open IB position. Matches by (user_id, broker='ib', instrument).

    The mobile app reads from the Supabase positions table directly, so without
    this update it sees only the snapshot taken when the order originally filled.
    The web app reads from Redis (via push_to_server), so it doesn't need this.
    """
    if not positions:
        return
    try:
        from .supabase_client import get_client
    except Exception as e:
        logger.debug("supabase_client unavailable: %s", e)
        return
    sb = get_client()
    if not sb:
        return
    user_id = os.environ.get("SUPABASE_USER_ID", "")
    if not user_id:
        return

    for pos in positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue
        sec_type = pos.get("sec_type", "")
        # Only refresh STK / FUT here; OPT positions are part of spreads,
        # which have their own sync path.
        if sec_type not in ("STK", "FUT"):
            continue
        multiplier = pos.get("multiplier") or 1
        avg_cost = pos.get("avg_cost") or 0
        # avg_cost is total ($/contract * multiplier); divide for per-unit price.
        entry_price = (avg_cost / multiplier) if multiplier else avg_cost
        update = {
            "entry_price": round(float(entry_price), 4),
            "unrealized_pl": round(float(pos.get("unrealized_pnl") or 0), 2),
            "contracts": int(abs(pos.get("quantity") or 0)),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        }
        try:
            sb.table("positions").update(update) \
                .eq("user_id", user_id) \
                .eq("broker", "ib") \
                .eq("instrument", symbol) \
                .execute()
        except Exception as e:
            logger.debug("supabase position refresh failed for %s: %s", symbol, e)


def collect_ib_data(client) -> dict:
    """Collect all relevant data from IB via Client Portal API."""

    # Account summary
    account = client.get_account_summary()

    # Positions with market values and P&L (CPAPI returns same shape)
    positions = client.get_positions()

    # Group option positions into spreads
    spreads = _detect_spreads(positions)

    # Enrich spreads with signal metadata from stored order details
    # Build a map from recent trades/fills
    perm_id_map = {}
    for fill in client.get_trades():
        perm_id = fill.get("order_ref", fill.get("execution_id", ""))
        if perm_id:
            perm_id_map[perm_id] = {
                "symbol": fill.get("symbol", ""),
                "perm_id": perm_id,
            }

    for spread in spreads:
        try:
            # Search by ticker + strikes
            resp = requests.get(
                f"{SERVER_URL}/api/ibkr/order/search",
                params={
                    "ticker": spread["symbol"],
                    "sell_strike": spread.get("short_strike", 0),
                    "buy_strike": spread.get("long_strike", 0),
                },
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=5,
            )
            if resp.status_code == 200:
                details = resp.json()
                if details.get("model") or details.get("perm_id"):
                    spread["perm_id"] = details.get("perm_id", "")
                    spread["order_id"] = details.get("order_id", "")
                    spread["model"] = details.get("model", "")
                    spread["strategy"] = details.get("strategy", "")
                    spread["trigger_pattern"] = details.get("trigger_pattern", "")
                    spread["bias_score"] = details.get("bias_score", 0)
                    spread["zone_type"] = details.get("zone_type", "")
                    spread["zone_timeframe"] = details.get("zone_timeframe", "")
                    spread["verdict"] = details.get("verdict", "")
                    spread["opened_at"] = details.get("queued_at", "")
                    # Override max_profit/risk with planned values from order
                    planned_profit = details.get("max_profit", 0)
                    planned_risk = details.get("max_risk", 0)
                    if planned_profit:
                        spread["max_profit"] = planned_profit
                    if planned_risk:
                        spread["max_risk"] = planned_risk
                    spread["risk_reward"] = details.get("risk_reward", 0)
        except Exception:
            pass
        # Signal log fallback if model still missing
        if not spread.get("model") and spread.get("symbol"):
            try:
                resp = requests.get(
                    f"{SERVER_URL}/api/ibkr/signal-lookup/{spread['symbol']}",
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=5,
                )
                if resp.status_code == 200:
                    sig = resp.json()
                    if sig.get("model"):
                        spread["model"] = sig["model"]
                        spread["trigger_pattern"] = sig.get("trigger_pattern", "")
                        spread["bias_score"] = sig.get("bias_score", 0)
                        spread["zone_type"] = sig.get("zone_type", "")
                        spread["zone_timeframe"] = sig.get("zone_timeframe", "")
                        spread["risk_reward"] = sig.get("risk_reward", 0)
            except Exception:
                pass

    # Open orders from CPAPI
    open_orders = []
    for order in client.get_open_orders():
        order_entry = {
            "order_id": order.get("orderId", 0),
            "symbol": order.get("ticker", ""),
            "sec_type": order.get("secType", "STK"),
            "action": order.get("side", ""),
            "quantity": float(order.get("totalSize", order.get("remainingQuantity", 0))),
            "order_type": order.get("orderType", ""),
            # CPAPI returns "" (empty string) for the price of a market order, so
            # the default kwarg doesn't help — `or 0` covers both None and "".
            "limit_price": float(order.get("price") or 0),
            "status": order.get("status", ""),
            "time": order.get("lastExecutionTime_r", ""),
        }
        if order.get("isCombo") or order.get("conidex", "").count(";;;") > 0:
            # Combo order (spread) — resolve leg details from conIds
            legs = []
            sell_strike = 0
            buy_strike = 0
            expiration = ""
            right = ""
            for leg in order.get("legs", []):
                leg_conid = leg.get("conid", 0)
                leg_info = {"con_id": leg_conid, "action": leg.get("side", ""), "ratio": leg.get("ratio", 1)}
                try:
                    info = client.get_contract_info(leg_conid)
                    if info and not info.get("error"):
                        leg_info["strike"] = float(info.get("strike", 0))
                        leg_info["expiration"] = str(info.get("maturityDate", "")).replace("-", "")
                        leg_info["right"] = info.get("right", "")
                        if leg.get("side") == "SELL":
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
                for lookup_id in [order.get("orderId"), order.get("permId")]:
                    if not lookup_id:
                        continue
                    try:
                        resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/order/details/{lookup_id}",
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
                                order_entry["limit_price"] = float(details.get("limit_price", 0))
                                order_entry["max_profit"] = float(details.get("max_profit", 0))
                                order_entry["max_risk"] = float(details.get("max_risk", 0))
                                order_entry["risk_reward"] = float(details.get("risk_reward", 0))
                                order_entry["signal_action"] = details.get("signal_action", "")
                                order_entry["queued_at"] = details.get("queued_at", "")
                                break
                    except Exception:
                        pass
                # Try searching by symbol + strikes
                if not order_entry.get("model") and order.get("ticker"):
                    try:
                        resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/order/search",
                            params={"ticker": order.get("ticker"), "sell_strike": sell_strike or 0, "buy_strike": buy_strike or 0},
                            headers={"X-Sync-Key": SYNC_KEY},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            details = resp.json()
                            if details.get("model"):
                                order_entry.update({
                                    "model": details.get("model", ""),
                                    "trigger_pattern": details.get("trigger_pattern", ""),
                                    "bias_score": details.get("bias_score", 0),
                                    "zone_type": details.get("zone_type", ""),
                                    "zone_timeframe": details.get("zone_timeframe", ""),
                                    "is_credit": details.get("is_credit", False),
                                    "limit_price": float(details.get("limit_price", 0)),
                                    "max_profit": float(details.get("max_profit", 0)),
                                    "max_risk": float(details.get("max_risk", 0)),
                                    "risk_reward": float(details.get("risk_reward", 0)),
                                    "signal_action": details.get("signal_action", ""),
                                    "queued_at": details.get("queued_at", ""),
                                    "right": details.get("right", ""),
                                    "sell_strike": float(details.get("sell_strike", 0)),
                                    "buy_strike": float(details.get("buy_strike", 0)),
                                    "expiration": details.get("expiration", ""),
                                    "spread_type": details.get("spread_type", ""),
                                })
                                right = details.get("right", "")
                                sell_strike = float(details.get("sell_strike", 0))
                                buy_strike = float(details.get("buy_strike", 0))
                                expiration = details.get("expiration", "")
                    except Exception:
                        pass
            order_entry["legs"] = legs
            # Try to enrich with stored order data by searching ticker + strikes
            if order.get("ticker") and sell_strike and buy_strike:
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/order/search",
                        params={"ticker": order.get("ticker"), "sell_strike": sell_strike, "buy_strike": buy_strike},
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        details = resp.json()
                        if details.get("limit_price"):
                            if not order_entry.get("limit_price") or order_entry["limit_price"] == 0:
                                order_entry["limit_price"] = float(details["limit_price"])
                                order_entry["net_premium"] = float(details["limit_price"])
                            if not order_entry.get("max_profit"):
                                order_entry["max_profit"] = float(details.get("max_profit", 0))
                            if not order_entry.get("max_risk") or order_entry["max_risk"] == 100:
                                order_entry["max_risk"] = float(details.get("max_risk", 0))
                            if not order_entry.get("risk_reward"):
                                order_entry["risk_reward"] = float(details.get("risk_reward", 0))
                            if not order_entry.get("is_credit") and details.get("is_credit") is not None:
                                order_entry["is_credit"] = details["is_credit"]
                            if not order_entry.get("model"):
                                order_entry["model"] = details.get("model", "")
                                order_entry["trigger_pattern"] = details.get("trigger_pattern", "")
                                order_entry["bias_score"] = details.get("bias_score", 0)
                                order_entry["zone_type"] = details.get("zone_type", "")
                                order_entry["zone_timeframe"] = details.get("zone_timeframe", "")
                                order_entry["signal_action"] = details.get("signal_action", "")
                                order_entry["queued_at"] = details.get("queued_at", "")
                except Exception:
                    pass
            # Fallback to signal log if model still missing
            if not order_entry.get("model") and order.get("ticker"):
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/signal-lookup/{order.get("ticker")}",
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        sig = resp.json()
                        if sig.get("model"):
                            order_entry["model"] = sig["model"]
                            order_entry["trigger_pattern"] = sig.get("trigger_pattern", "")
                            order_entry["bias_score"] = sig.get("bias_score", 0)
                            order_entry["zone_type"] = sig.get("zone_type", "")
                            order_entry["zone_timeframe"] = sig.get("zone_timeframe", "")
                            order_entry["signal_action"] = sig.get("signal_action", "")
                            order_entry["risk_reward"] = sig.get("risk_reward", 0)
                except Exception:
                    pass
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
            premium = abs(order_entry.get("limit_price") or 0)
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
        elif order.get("secType") == "OPT":
            # Single-leg option order — strike/right/expiration would need a
            # /iserver/contract/{conid}/info call. Skip enrichment for now;
            # the combo branch above handles the multi-leg spreads we care about.
            pass
        open_orders.append(order_entry)

    # Completed (filled) orders — recent trades from CPAPI
    filled_orders = []
    for fill in client.get_trades():
        entry = {
            "order_id": fill.get("order_ref", fill.get("execution_id", 0)),
            "symbol": fill.get("symbol", fill.get("ticker", "")),
            "sec_type": fill.get("sec_type", fill.get("secType", "STK")),
            "action": fill.get("side", ""),
            "quantity": float(fill.get("size", fill.get("shares", 0))),
            "price": float(fill.get("price", 0)),
            "time": fill.get("trade_time_r", fill.get("trade_time", "")),
        }
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


def check_analyze_requests(client):
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


def check_order_requests(client):
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

        # ─── FUTURES DEDUP: only keep the most recent order per ticker ───
        # For scalping, we only care about the latest signal. Older ones are stale.
        futures_orders = [o for o in orders if o.get("type") == "futures"]
        other_orders = [o for o in orders if o.get("type") != "futures"]
        if len(futures_orders) > 1:
            # Group by ticker, keep only the most recent
            by_ticker = {}
            for o in futures_orders:
                tk = o.get("ticker", "")
                existing = by_ticker.get(tk)
                if not existing or o.get("queued_at", "") > existing.get("queued_at", ""):
                    # Mark the older one as superseded
                    if existing:
                        try:
                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                json={"order_id": existing["order_id"], "status": "superseded"},
                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                        except Exception:
                            pass
                        logger.info("SKIP superseded %s %s — newer order exists", existing.get("direction"), tk)
                    by_ticker[tk] = o
                else:
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                            json={"order_id": o["order_id"], "status": "superseded"},
                            headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                    except Exception:
                        pass
                    logger.info("SKIP superseded %s %s — newer order exists", o.get("direction"), tk)
            futures_orders = list(by_ticker.values())

        orders = other_orders + futures_orders

        for order in orders:
            order_id = order["order_id"]
            ticker = order["ticker"]

            # ─── FUTURES ORDERS ───
            if order.get("type") == "futures":
                direction = order.get("direction", "")
                contracts = int(order.get("contracts", 1))
                strategy_name = order.get("strategy", "")

                # Skip stale orders (queued more than 5 minutes ago)
                queued_at = order.get("queued_at", "")
                if queued_at:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        queued_time = _dt.fromisoformat(queued_at.replace("Z", "+00:00"))
                        age_seconds = (_dt.now(_tz.utc) - queued_time).total_seconds()
                        if age_seconds > 300:
                            logger.info("SKIP stale %s %s — queued %.0fs ago", direction, ticker, age_seconds)
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                    json={"order_id": order_id, "status": "expired"},
                                    headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass

                logger.info("Futures order: %s %s %dx — %s", direction, ticker, contracts, strategy_name)

                # Position awareness — check current position before acting
                time.sleep(1)
                current_pos = 0
                for item in client.get_positions():
                    if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                        current_pos = int(item.get("quantity", 0))
                        break
                logger.info("Position check: %s pos=%d (direction=%s)", ticker, current_pos, direction)

                skip = False
                if direction == "BUY" and current_pos != 0:
                    logger.info("SKIP %s BUY — not flat (pos=%d)", ticker, current_pos)
                    skip = True
                elif direction == "SELL" and current_pos != 0:
                    logger.info("SKIP %s SELL — not flat (pos=%d)", ticker, current_pos)
                    skip = True
                elif direction == "CLOSE_LONG" and current_pos <= 0:
                    logger.info("SKIP %s CLOSE_LONG — not long (pos=%d)", ticker, current_pos)
                    skip = True
                elif direction == "CLOSE_SHORT" and current_pos >= 0:
                    logger.info("SKIP %s CLOSE_SHORT — not short (pos=%d)", ticker, current_pos)
                    skip = True

                if skip:
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                      json={"order_id": order_id, "status": "skipped", "ticker": ticker, "direction": direction},
                                      headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                    except Exception:
                        pass
                    continue

                try:
                    # Resolve front-month futures contract via CPAPI
                    fut_info = client.search_futures(ticker)
                    if not fut_info or not fut_info.get("conid"):
                        raise ValueError(f"No futures contract found for {ticker}")
                    fut_conid = fut_info["conid"]
                    multiplier = float(fut_info.get("multiplier", 5))
                    logger.info("Resolved %s to conid %s exp %s", ticker, fut_conid, fut_info.get("expiration", ""))

                    # Get futures stop loss setting from server
                    sl_dollars = 25.0
                    try:
                        sl_resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/exit-rules",
                            headers={"X-Sync-Key": SYNC_KEY},
                            timeout=5,
                        )
                        if sl_resp.status_code == 200:
                            sl_dollars = float(sl_resp.json().get("futures_stop_loss", 25))
                    except Exception:
                        pass

                    sl_points = sl_dollars / multiplier

                    if direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                        # Record entry price before closing
                        entry_price = 0
                        entry_qty = 0
                        for item in client.get_positions():
                            if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                                entry_price = item.get("avg_cost", 0) / multiplier
                                entry_qty = abs(int(item.get("quantity", 0)))
                                break

                        close_action = "SELL" if direction == "CLOSE_LONG" else "BUY"
                        order_payload = client.build_futures_order(fut_conid, close_action, contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)
                        time.sleep(3)

                        # Record closed trade — get fill price from trades
                        exit_price = 0
                        try:
                            fills = client.get_trades()
                            if fills:
                                exit_price = float(fills[-1].get("price", 0))
                        except Exception:
                            pass
                        if entry_price and exit_price:
                            if direction == "CLOSE_LONG":
                                pnl = (exit_price - entry_price) * contracts * multiplier
                            else:
                                pnl = (entry_price - exit_price) * contracts * multiplier
                            from datetime import datetime as _dt, timezone as _tz
                            # Use reason from webhook, or default
                            close_reason = order.get("reason", "")
                            if not close_reason:
                                close_reason = "Exit Long" if direction == "CLOSE_LONG" else "Exit Short"

                            # Use entry strategy name (strip _exit suffix)
                            entry_strategy = strategy_name.replace("_exit", "")

                            # Find opened_at from stored entry order (most recent for this ticker + direction)
                            entry_dir = "BUY" if direction == "CLOSE_LONG" else "SELL"
                            opened_at = ""
                            try:
                                entry_resp = requests.get(
                                    f"{SERVER_URL}/api/ibkr/futures-entry/{ticker}/{entry_dir}",
                                    headers={"X-Sync-Key": SYNC_KEY},
                                    timeout=5,
                                )
                                if entry_resp.status_code == 200:
                                    entry_data = entry_resp.json()
                                    opened_at = entry_data.get("opened_at", "")
                                    entry_strategy = entry_data.get("strategy", entry_strategy)
                                    # Mark this entry as closed so it's not reused
                                    if entry_data.get("order_id"):
                                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                            json={"order_id": entry_data["order_id"], "status": "closed"},
                                            headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                            except Exception:
                                pass
                            if not opened_at:
                                opened_at = order.get("queued_at", "")

                            closed_trade = {
                                "symbol": ticker,
                                "type": "futures",
                                "direction": "LONG" if direction == "CLOSE_LONG" else "SHORT",
                                "contracts": contracts,
                                "entry_price": round(entry_price, 2),
                                "exit_price": round(exit_price, 2),
                                "realized_pnl": round(pnl, 2),
                                "strategy": entry_strategy,
                                "close_reason": close_reason,
                                "opened_at": opened_at,
                                "closed_at": _dt.now(_tz.utc).isoformat(),
                            }
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/closed-trade",
                                              json=closed_trade, headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                            except Exception:
                                pass
                            logger.info("Closed %s %s: entry=%.2f exit=%.2f P&L=$%.2f", ticker, direction, entry_price, exit_price, pnl)
                    elif direction == "BUY":
                        order_payload = client.build_futures_order(fut_conid, "BUY", contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)
                        time.sleep(2)
                        # Place stop loss
                        try:
                            fills = client.get_trades()
                            fill_price = float(fills[-1].get("price", 0)) if fills else 0
                            if fill_price > 0:
                                sl_price = fill_price - sl_points
                                sl_payload = client.build_futures_order(fut_conid, "SELL", contracts, "STP", sl_price, tif="GTC")
                                client.place_order(sl_payload)
                                logger.info("Stop loss: SELL %s @ %.2f (entry %.2f, risk $%.0f)", ticker, sl_price, fill_price, sl_dollars)
                        except Exception as e:
                            logger.error("Failed to place stop loss: %s", e)
                    elif direction == "SELL":
                        order_payload = client.build_futures_order(fut_conid, "SELL", contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)
                        time.sleep(2)
                        # Place stop loss
                        try:
                            fills = client.get_trades()
                            fill_price = float(fills[-1].get("price", 0)) if fills else 0
                            if fill_price > 0:
                                sl_price = fill_price + sl_points
                                sl_payload = client.build_futures_order(fut_conid, "BUY", contracts, "STP", sl_price, tif="GTC")
                                client.place_order(sl_payload)
                                logger.info("Stop loss: BUY %s @ %.2f (entry %.2f, risk $%.0f)", ticker, sl_price, fill_price, sl_dollars)
                        except Exception as e:
                            logger.error("Failed to place stop loss: %s", e)
                    else:
                        logger.error("Unknown futures direction: %s", direction)
                        continue

                    time.sleep(2)
                    from datetime import datetime as _dt2, timezone as _tz2
                    # Extract order ID from CPAPI response
                    perm_id = ""
                    ib_order_id = 0
                    order_status = "Submitted"
                    if isinstance(trade_result, list) and trade_result:
                        first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                        ib_order_id = first.get("order_id", 0)
                        order_status = first.get("order_status", "Submitted")
                        perm_id = str(ib_order_id)
                    elif isinstance(trade_result, dict):
                        ib_order_id = trade_result.get("order_id", 0)
                        order_status = trade_result.get("order_status", "Submitted")
                        perm_id = str(ib_order_id)
                    now_iso = _dt2.now(_tz2.utc).isoformat()

                    result = {
                        "order_id": order_id,
                        "ib_order_id": ib_order_id,
                        "perm_id": perm_id,
                        "status": order_status,
                        "ticker": ticker,
                        "direction": direction,
                        "type": "futures",
                    }
                    logger.info("Futures order placed: %s %s — %s (id=%s)", direction, ticker, order_status, perm_id)

                    # Store entry details for BUY/SELL (not CLOSE) using order ID as unique key
                    if direction in ("BUY", "SELL"):
                        try:
                            # Get fill price from recent trades
                            entry_fill_price = 0
                            try:
                                fills = client.get_trades()
                                if fills:
                                    entry_fill_price = float(fills[-1].get("price", 0))
                            except Exception:
                                pass
                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                json={
                                    "order_id": f"futures_entry_{perm_id}",
                                    "ticker": ticker,
                                    "direction": direction,
                                    "perm_id": perm_id,
                                    "opened_at": now_iso,
                                    "strategy": strategy_name,
                                    "status": "entry",
                                    "type": "futures",
                                    "entry_price": entry_fill_price,
                                },
                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                        except Exception:
                            pass

                except Exception as e:
                    result = {
                        "order_id": order_id,
                        "status": "failed",
                        "ticker": ticker,
                        "error": str(e),
                    }
                    logger.error("Futures order failed: %s — %s", ticker, e)

                try:
                    requests.post(f"{SERVER_URL}/api/ibkr/order/update", json=result,
                                  headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                except Exception:
                    pass
                continue

            # ─── OPTIONS ORDERS ───
            spread_type = order.get("spread_type", "")
            buy_strike = float(order.get("buy_strike", 0))
            sell_strike = float(order.get("sell_strike", 0))
            right = order.get("right", "")
            expiration = order.get("expiration", "")
            quantity = int(order.get("quantity", 1))
            limit_price = float(order["limit_price"])

            is_credit = "Credit" in spread_type
            logger.info("Placing %s order: %s SELL %s / BUY %s %s exp %s x%d @ $%.2f (%s)",
                        spread_type, ticker, sell_strike, buy_strike, right, expiration, quantity, limit_price,
                        "credit" if is_credit else "debit")

            try:
                # Resolve option contract conIds via CPAPI
                buy_conid = client.search_option_contract(ticker, expiration, buy_strike, right)
                sell_conid = client.search_option_contract(ticker, expiration, sell_strike, right)

                if not buy_conid or not sell_conid:
                    raise ValueError(f"Could not find option contracts: buy={buy_strike} sell={sell_strike}")

                # Build and place combo order
                spread_payload = client.build_spread_order(
                    sell_conid, buy_conid, quantity, limit_price, is_credit, tif="GTC"
                )
                trade_result = client.place_order(spread_payload)
                time.sleep(3)

                # Extract order ID from CPAPI response
                perm_id = ""
                if isinstance(trade_result, list) and trade_result:
                    first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                    perm_id = str(first.get("order_id", ""))
                elif isinstance(trade_result, dict):
                    perm_id = str(trade_result.get("order_id", ""))

                result = {
                    "order_id": order_id,
                    "ib_order_id": trade.order.orderId,
                    "perm_id": perm_id,
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


def monitor_spreads(client, spreads: list):
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

    default_credit_tp = rules.get("credit_tp_pct", 50)
    default_credit_sl = rules.get("credit_sl_pct", 100)
    default_debit_tp = rules.get("debit_tp_pct", 75)
    default_debit_sl = rules.get("debit_sl_pct", 50)
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

        # Per-spread TP/SL overrides (from 0DTE webhook orders)
        spread_tp = spread.get("tp_pct")
        spread_sl = spread.get("sl_pct")
        spread_time_stop_min = spread.get("time_stop_min", 0)

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
            credit_received = net_cost
            tp_pct = spread_tp if spread_tp else default_credit_tp
            sl_pct = spread_sl if spread_sl else default_credit_sl

            if pnl > 0 and pnl >= credit_received * (tp_pct / 100):
                close_reason = f"TAKE PROFIT — captured {tp_pct}% of credit (P&L: ${pnl:+.2f})"
            elif pnl < 0 and abs(pnl) >= credit_received * (sl_pct / 100):
                close_reason = f"STOP LOSS — loss exceeded {sl_pct}% of credit (P&L: ${pnl:+.2f})"
        else:
            debit_paid = net_cost
            tp_pct = spread_tp if spread_tp else default_debit_tp
            sl_pct = spread_sl if spread_sl else default_debit_sl

            if pnl > 0 and pnl >= debit_paid * (tp_pct / 100):
                close_reason = f"TAKE PROFIT — {tp_pct}% gain (P&L: ${pnl:+.2f})"
            elif pnl < 0 and abs(pnl) >= debit_paid * (sl_pct / 100):
                close_reason = f"STOP LOSS — {sl_pct}% loss (P&L: ${pnl:+.2f})"

        # Minute-based time stop (for 0DTE scalps)
        if not close_reason and spread_time_stop_min > 0:
            opened_at = spread.get("opened_at", "")
            if opened_at:
                try:
                    opened_str = opened_at.replace("Z", "+00:00")
                    if "T" not in opened_str and " " in opened_str:
                        opened_str = opened_str.replace(" ", "T", 1)
                    opened_dt = datetime.fromisoformat(opened_str)
                    minutes_held = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 60
                    if minutes_held >= spread_time_stop_min:
                        close_reason = f"TIME STOP — held {int(minutes_held)} min (limit: {spread_time_stop_min} min)"
                except Exception:
                    pass

        # DTE-based time stop (for swing trades)
        if not close_reason and dte <= time_stop_dte:
            close_reason = f"TIME STOP — {dte} DTE remaining (limit: {time_stop_dte})"

        if close_reason:
            logger.info("CLOSING %s %s: %s", symbol, spread_type, close_reason)
            try:
                _close_spread(client, spread, close_reason)
            except Exception as e:
                logger.error("Failed to close %s spread: %s", symbol, e)


def _close_spread(client, spread: dict, reason: str):
    """Close an open spread by placing an opposite market order."""
    symbol = spread["symbol"]
    expiration = spread.get("expiration", "")
    right = spread.get("right", "")
    long_strike = spread.get("long_strike", 0)
    short_strike = spread.get("short_strike", 0)
    quantity = int(spread.get("quantity", 0))

    if not all([symbol, expiration, right, long_strike, short_strike, quantity]):
        logger.error("Missing data to close spread: %s", spread)
        return

    # Resolve conIds for the legs
    long_conid = client.search_option_contract(symbol, expiration, long_strike, right)
    short_conid = client.search_option_contract(symbol, expiration, short_strike, right)

    if not long_conid or not short_conid:
        logger.error("Could not resolve conIds for spread close: %s %s/%s", symbol, long_strike, short_strike)
        return

    # Build and place closing order (reverse legs)
    close_payload = client.build_close_spread_order(long_conid, short_conid, quantity)
    trade_result = client.place_order(close_payload)
    time.sleep(3)

    status = "Submitted"
    if isinstance(trade_result, list) and trade_result:
        status = trade_result[0].get("order_status", "Submitted") if isinstance(trade_result[0], dict) else "Submitted"
    logger.info("Close order for %s: status=%s reason=%s", symbol, status, reason)

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
            "perm_id": spread.get("perm_id", ""),
            "order_id": spread.get("order_id", ""),
            "symbol": symbol,
            "spread_type": spread.get("spread_type", ""),
            "long_strike": spread.get("long_strike", 0),
            "short_strike": spread.get("short_strike", 0),
            "right": spread.get("right", ""),
            "expiration": expiration,
            "quantity": quantity,
            "width": spread.get("width", 0),
            "entry_cost": spread.get("net_cost", 0),
            "realized_pnl": spread.get("unrealized_pnl", 0),
            "max_profit": spread.get("max_profit", 0),
            "max_risk": spread.get("max_risk", 0),
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
    logger.info("IB CPAPI Sync starting — connecting to %s", CPAPI_URL)

    from .ibkr_cpapi import CPAPIClient
    client = CPAPIClient(base_url=CPAPI_URL)

    try:
        client.ensure_session()
    except ConnectionError as e:
        logger.error("Failed to connect to CPAPI gateway: %s", e)
        logger.error("Make sure the CPAPI Docker container is running and authenticated")
        sys.exit(1)

    logger.info("Connected to CPAPI — syncing every %ds to %s", SYNC_INTERVAL, SERVER_URL)

    while True:
        try:
            # Keep session alive
            try:
                client.ensure_session()
            except ConnectionError:
                logger.error("CPAPI session expired — waiting for re-auth...")
                # Send alert
                try:
                    from lumisignals.alerts import send_alert, AlertType
                    alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                    if alert_pass:
                        send_alert(AlertType.SYSTEM_ERROR, "CPAPI Session Expired",
                                   "Manual browser login required. SSH tunnel and open https://localhost:5000",
                                   smtp_pass=alert_pass)
                except Exception:
                    pass
                time.sleep(60)
                continue

            data = collect_ib_data(client)

            acct = data["account"]
            n_pos = len(data["positions"])
            n_spreads = len(data["spreads"])
            n_orders = len(data["open_orders"])
            logger.info(
                "NAV: $%s | Positions: %d | Spreads: %d | Open orders: %d",
                f"{acct.get('NetLiquidation', 0):,.2f}", n_pos, n_spreads, n_orders,
            )

            push_to_server(data)

            # Refresh open IB positions in Supabase so the mobile app sees
            # live mark price and unrealized P&L (web app reads Redis; mobile
            # reads Supabase directly, so the rows would otherwise stay frozen
            # at order-placement-time values).
            sync_positions_to_supabase(data.get("positions", []))

            # Check for options analyze requests
            check_analyze_requests(client)

            # Check for pending orders to place
            check_order_requests(client)

            # Monitor open spreads for TP/SL/time stop
            if data.get("spreads"):
                monitor_spreads(client, data["spreads"])

        except Exception as e:
            logger.error("Sync error: %s", e)

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
