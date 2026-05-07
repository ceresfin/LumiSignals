"""IB Gateway sync — polls positions and account data, pushes to LumiSignals server.

Runs as the `lumisignals-sync` systemd service on the production server, talking
to a Dockerized IB Gateway on the same host (`ib-gateway` container, port 4002).
Pushes data every ~10s; throttled MES bar pushes every 60s.
"""

import json
import logging
import os
import sys
import time
from typing import Optional

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
SYNC_INTERVAL = 10


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
    # First, build a map of permId → execution details from recent fills
    perm_id_map = {}
    for fill in ib.fills():
        if fill.execution.permId:
            perm_id_map[fill.execution.permId] = {
                "symbol": fill.contract.symbol,
                "perm_id": fill.execution.permId,
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
            "aux_price": o.auxPrice,  # Stop price for STP orders
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
                for lookup_id in [o.orderId, o.permId]:
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
                if not order_entry.get("model") and c.symbol:
                    try:
                        resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/order/search",
                            params={"ticker": c.symbol, "sell_strike": sell_strike or 0, "buy_strike": buy_strike or 0},
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
            if c.symbol and sell_strike and buy_strike:
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/order/search",
                        params={"ticker": c.symbol, "sell_strike": sell_strike, "buy_strike": buy_strike},
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
            if not order_entry.get("model") and c.symbol:
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/signal-lookup/{c.symbol}",
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


# --- MES real-time streaming bars ---
# Replaces the polling-based historical fetch with a live 5-second-bar subscription.
# We aggregate 5-sec → 2-min in memory; when a 2-min bar closes we push immediately.
# This eliminates the IB historical-data settlement delay (which was producing
# partial bars with lagging OHLC and missed signals).

_mes_realtime_subscription = None  # ib_insync RealTimeBarList
_mes_completed_bars: list = []     # list of finalized 2-min bars (warm + streamed)
_mes_current_bucket: Optional[dict] = None  # in-progress 2-min bucket
_mes_front_label: str = ""


def _bucket_start_for(dt) -> "datetime":
    """Round a datetime down to its 2-min bucket boundary."""
    return dt.replace(second=0, microsecond=0,
                      minute=(dt.minute // 2) * 2)


def _push_completed_bars_to_server():
    """Push the current finalized-bars list to the server."""
    try:
        requests.post(
            f"{SERVER_URL}/api/ibkr/futures-bars/MES",
            json={"bars": _mes_completed_bars, "front_month": _mes_front_label},
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=10,
        )
    except Exception as e:
        logger.warning("MES bar push failed: %s", e)


def _on_real_time_bar(bars, has_new_bar):
    """Callback fired by ib_insync when a new 5-sec bar arrives.

    Aggregates into 2-min buckets. When a bucket rolls over, the just-completed
    2-min bar is appended to history and pushed to the server immediately —
    no settlement waiting, no partial-bar evaluation by the strategy.
    """
    global _mes_current_bucket, _mes_completed_bars
    if not has_new_bar or not bars:
        return
    bar = bars[-1]
    bar_time = bar.time
    if hasattr(bar_time, "timestamp"):
        # datetime — make sure it's tz-aware in UTC
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
    else:
        try:
            bar_time = datetime.fromtimestamp(float(bar_time), tz=timezone.utc)
        except Exception:
            return
    bucket_start = _bucket_start_for(bar_time)

    if _mes_current_bucket is None or _mes_current_bucket["start"] != bucket_start:
        # Bucket boundary crossed — finalize previous bucket if it exists
        if _mes_current_bucket is not None:
            done = _mes_current_bucket
            _mes_completed_bars.append({
                "open": done["open"],
                "high": done["high"],
                "low": done["low"],
                "close": done["close"],
                "volume": done["volume"],
                # Keep ISO format with timezone so server-side parsing matches
                # the historical-warm-up format.
                "time": done["start"].isoformat(),
            })
            if len(_mes_completed_bars) > 1500:
                _mes_completed_bars = _mes_completed_bars[-1500:]
            logger.info("MES 2-min bar closed: %s O=%.2f H=%.2f L=%.2f C=%.2f V=%d",
                        done["start"].strftime("%H:%M"),
                        done["open"], done["high"], done["low"], done["close"],
                        done["volume"])
            _push_completed_bars_to_server()
        _mes_current_bucket = {
            "start": bucket_start,
            "open": float(bar.open_),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(bar.volume) if bar.volume else 0,
        }
    else:
        _mes_current_bucket["high"] = max(_mes_current_bucket["high"], float(bar.high))
        _mes_current_bucket["low"] = min(_mes_current_bucket["low"], float(bar.low))
        _mes_current_bucket["close"] = float(bar.close)
        if bar.volume:
            _mes_current_bucket["volume"] += int(bar.volume)


def _setup_mes_realtime_stream(ib, ticker: str = "MES"):
    """Subscribe to MES real-time bars. Idempotent — safe to call after reconnect.

    Warms `_mes_completed_bars` with last 24h of historical 2-min bars so the
    strategy has enough history for its 18:00-ET-anchored VWAP, then attaches
    the streaming callback for live aggregation going forward.
    """
    global _mes_realtime_subscription, _mes_completed_bars, _mes_front_label, _mes_current_bucket
    if _mes_realtime_subscription is not None:
        return
    try:
        from ib_insync import Future
        contract = Future(ticker, exchange="CME")
        candidates = ib.reqContractDetails(contract)
        if not candidates:
            logger.warning("MES streaming setup: no contract details")
            return
        candidates.sort(key=lambda c: c.contract.lastTradeDateOrContractMonth)
        front = candidates[0].contract
        _mes_front_label = f"{front.symbol}{front.lastTradeDateOrContractMonth[:6]}"

        # Warm history (one-time, on connect)
        hist = ib.reqHistoricalData(
            front, endDateTime='', durationStr='86400 S',
            barSizeSetting='2 mins', whatToShow='TRADES',
            useRTH=False, formatDate=1,
        )
        warmed = []
        for b in hist:
            try:
                warmed.append({
                    "open": float(b.open), "high": float(b.high),
                    "low": float(b.low), "close": float(b.close),
                    "volume": int(b.volume) if b.volume else 0,
                    "time": str(b.date),
                })
            except Exception:
                continue
        _mes_completed_bars = warmed
        _mes_current_bucket = None
        logger.info("MES history warmed: %d 2-min bars (front: %s)",
                    len(warmed), _mes_front_label)
        _push_completed_bars_to_server()

        # Subscribe to live 5-sec bars
        sub = ib.reqRealTimeBars(front, 5, 'TRADES', False)
        sub.updateEvent += _on_real_time_bar
        _mes_realtime_subscription = sub
        logger.info("MES real-time stream active (5-sec bars → 2-min aggregation)")
    except Exception as e:
        logger.error("MES real-time setup failed: %s", e)


def _teardown_mes_realtime_stream(ib):
    """Cancel the real-time subscription. Called before reconnect cycles."""
    global _mes_realtime_subscription, _mes_current_bucket
    if _mes_realtime_subscription is not None:
        try:
            ib.cancelRealTimeBars(_mes_realtime_subscription)
        except Exception:
            pass
        _mes_realtime_subscription = None
    _mes_current_bucket = None


# --- Polling fallback (used when real-time streaming isn't subscribed) ---
_last_mes_poll_push = 0.0
MES_POLL_INTERVAL = 30  # seconds; every 30s pull last 24h of historical 2-min bars


def _push_mes_bars_polling(ib, ticker: str = "MES"):
    """Polling fallback: pull historical 2-min MES bars from IB and push to server.

    Used when the account lacks real-time market data permissions. Has 30-60s of
    settlement delay on the latest bar — the strategy compensates by reading
    bars[-2] (the just-closed bar) rather than bars[-1] (still-finalizing).
    """
    global _last_mes_poll_push
    now = time.time()
    if now - _last_mes_poll_push < MES_POLL_INTERVAL:
        return
    _last_mes_poll_push = now
    try:
        from ib_insync import Future
        contract = Future(ticker, exchange="CME")
        candidates = ib.reqContractDetails(contract)
        if not candidates:
            return
        candidates.sort(key=lambda c: c.contract.lastTradeDateOrContractMonth)
        front = candidates[0].contract
        front_label = f"{front.symbol}{front.lastTradeDateOrContractMonth[:6]}"
        bars = ib.reqHistoricalData(
            front, endDateTime='', durationStr='86400 S',
            barSizeSetting='2 mins', whatToShow='TRADES',
            useRTH=False, formatDate=1,
        )
        if not bars:
            return
        candles = []
        for b in bars:
            try:
                candles.append({
                    "open": float(b.open), "high": float(b.high),
                    "low": float(b.low), "close": float(b.close),
                    "volume": int(b.volume) if b.volume else 0,
                    "time": str(b.date),
                })
            except Exception:
                continue
        try:
            requests.post(
                f"{SERVER_URL}/api/ibkr/futures-bars/{ticker}",
                json={"bars": candles, "front_month": front_label},
                headers={"X-Sync-Key": SYNC_KEY}, timeout=10,
            )
        except Exception as e:
            logger.warning("MES poll push failed: %s", e)
    except Exception as e:
        logger.warning("MES poll fetch failed: %s", e)


def _place_futures_stop(ib, contract, ticker, action, contracts, sl_price,
                         fill_price, sl_dollars, entry_perm_id, strategy_name):
    """Place a GTC stop on IB and mirror it to Redis so the Trades page can show it.

    `outsideRth=True` is critical for futures: without it, the stop is dormant
    during overnight Globex session (MES trades 23/5 but RTH is only 9:30-16:00 ET).
    A trade taken at 6 AM ET with an RTH-only stop will sit unprotected through
    the entire pre-market session — exactly what bit us on Apr 29 (entry 7173,
    SL trigger 7168.25, but stop didn't activate until RTH open at 9:30 ET by
    which time price was at 7154 → fill at 7163.50, $49 loss vs intended $25).
    """
    try:
        from ib_insync import StopOrder
        sl_order = StopOrder(action, contracts, sl_price)
        sl_order.tif = "GTC"
        sl_order.outsideRth = True
        sl_trade = ib.placeOrder(contract, sl_order)
        ib.sleep(1)
        logger.info("Stop loss: %s %s @ %.2f (entry %.2f, risk $%.0f)",
                    action, ticker, sl_price, fill_price, sl_dollars)
        try:
            from datetime import datetime as _sdt, timezone as _stz
            sl_perm = sl_trade.order.permId
            direction_label = "STOP_LONG" if action == "SELL" else "STOP_SHORT"
            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                json={
                    "order_id": f"futures_stop_{sl_perm}",
                    "perm_id": sl_perm,
                    "entry_perm_id": entry_perm_id,
                    "ticker": ticker,
                    "type": "futures",
                    "direction": direction_label,
                    "stop_price": round(sl_price, 2),
                    "entry_price": round(fill_price, 2),
                    "contracts": contracts,
                    "strategy": strategy_name,
                    "status": "Submitted",
                    "queued_at": _sdt.now(_stz.utc).isoformat(),
                },
                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
        except Exception:
            pass
    except Exception as e:
        logger.error("Failed to place stop loss: %s", e)


# Snapshot of open futures positions from the previous sync tick — used by
# _detect_closed_futures to spot positions that closed at the broker (e.g. SL stop fired)
# without an explicit CLOSE_LONG/CLOSE_SHORT signal from the strategy.
_prev_futures_positions: dict = {}


def _detect_closed_futures(ib):
    """Detect futures positions that closed since last tick and record a closed trade.

    Handles the case where the IB-side stop fires (or the position is closed manually).
    The explicit CLOSE_LONG/CLOSE_SHORT path also writes a closed-trade record; server-side
    dedup on close_exec_id keeps both paths idempotent.
    """
    global _prev_futures_positions

    current = {}
    for item in ib.portfolio():
        try:
            if item.contract.secType != 'FUT':
                continue
            qty = int(item.position)
            if qty == 0:
                continue
            sym = item.contract.symbol
            direction = "LONG" if qty > 0 else "SHORT"
            current[(sym, direction)] = {
                "quantity": abs(qty),
                "avg_cost": float(item.averageCost),
                "multiplier": float(item.contract.multiplier or 5),
            }
        except Exception:
            continue

    # Closures: keys present in prev but missing in current
    closed_keys = set(_prev_futures_positions.keys()) - set(current.keys())
    for key in closed_keys:
        sym, direction = key
        prev = _prev_futures_positions[key]

        # Find the most recent matching exit fill (LONG closes via SLD, SHORT via BOT)
        exit_side = 'SLD' if direction == 'LONG' else 'BOT'
        exit_fill = None
        try:
            fills_sorted = sorted(ib.fills(), key=lambda f: str(f.execution.time), reverse=True)
        except Exception:
            fills_sorted = list(ib.fills())
        for fill in fills_sorted:
            try:
                c = fill.contract
                e = fill.execution
                if c.secType == 'FUT' and c.symbol == sym and e.side == exit_side:
                    exit_fill = fill
                    break
            except Exception:
                continue
        if not exit_fill:
            # Track retry count — give up after 30 retries (~5 min at 10s intervals)
            retry_count = prev.get("_close_retries", 0) + 1
            prev["_close_retries"] = retry_count
            if retry_count <= 30:
                logger.info("Position closed but no exit fill found: %s %s — retry %d/30", sym, direction, retry_count)
                current[key] = prev
                continue
            else:
                # Give up — mark entry as closed without fill data, clean up
                logger.warning("Giving up on exit fill for %s %s after 30 retries — marking closed", sym, direction)
                entry_dir = "BUY" if direction == "LONG" else "SELL"
                try:
                    requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                        json={"order_id": f"futures_entry_{sym}_{entry_dir}", "status": "closed"},
                        headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                except Exception:
                    pass
                # Clean up any futures_entry_ keys for this symbol
                try:
                    import redis as _rdb
                    rdb = _rdb.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    for fk in rdb.scan_iter(f"ibkr:order:futures_entry_*"):
                        raw = rdb.get(fk)
                        if raw:
                            fd = json.loads(raw)
                            if fd.get("ticker") == sym and fd.get("direction") == entry_dir:
                                rdb.delete(fk)
                                logger.info("Cleaned stale futures entry: %s", fk)
                except Exception:
                    pass
                continue

        multiplier = prev["multiplier"]
        # Use stored fill price from entry tracking if available, else derive from avg_cost
        entry_price = prev.get("entry_fill_price", 0)
        if not entry_price:
            entry_price = prev["avg_cost"] / multiplier if multiplier else 0
        exit_price = float(exit_fill.execution.price)
        # Get IB's actual execution time (not sync detection time)
        ib_exit_time = str(exit_fill.execution.time) if exit_fill.execution.time else ""
        contracts = prev["quantity"]
        if direction == 'LONG':
            pnl = (exit_price - entry_price) * contracts * multiplier
        else:
            pnl = (entry_price - exit_price) * contracts * multiplier

        # Look up entry strategy + opened_at; mark entry record closed
        entry_dir = "BUY" if direction == "LONG" else "SELL"
        opened_at = ""
        strategy = ""
        try:
            entry_resp = requests.get(
                f"{SERVER_URL}/api/ibkr/futures-entry/{sym}/{entry_dir}",
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=5,
            )
            if entry_resp.status_code == 200:
                d = entry_resp.json()
                opened_at = d.get("opened_at", "")
                strategy = (d.get("strategy", "") or "").replace("_exit", "")
                if d.get("order_id"):
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                            json={"order_id": d["order_id"], "status": "closed"},
                            headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                    except Exception:
                        pass
        except Exception:
            pass

        close_perm_id = getattr(exit_fill.execution, "permId", 0)
        # If a Redis stop record exists for this permId, this was a SL fill.
        close_reason = "Stop loss" if close_perm_id else "Closed at broker"

        from datetime import datetime as _dt, timezone as _tz
        # Use IB execution time if available, else fall back to current time
        if ib_exit_time:
            try:
                closed_at = _dt.fromisoformat(str(ib_exit_time).replace("Z", "+00:00")).isoformat()
            except Exception:
                closed_at = _dt.now(_tz.utc).isoformat()
        else:
            closed_at = _dt.now(_tz.utc).isoformat()

        closed_trade = {
            "symbol": sym,
            "type": "futures",
            "direction": direction,
            "contracts": contracts,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "realized_pnl": round(pnl, 2),
            "strategy": strategy,
            "close_reason": close_reason,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "close_exec_id": str(close_perm_id) if close_perm_id else "",
        }
        try:
            requests.post(f"{SERVER_URL}/api/ibkr/closed-trade",
                          json=closed_trade, headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
            logger.info("Auto-detected close: %s %s entry=%.2f exit=%.2f P&L=$%.2f reason=%s",
                        sym, direction, entry_price, exit_price, pnl, close_reason)
            # Write closed trade + remove position directly to Supabase
            try:
                from lumisignals.supabase_client import record_closed_trade, notify_trade_closed, get_client
                supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                if supabase_uid:
                    record_closed_trade(supabase_uid, {
                        "id": str(close_perm_id or ""),
                        "broker": "ib",
                        "asset_type": "futures",
                        "instrument": sym,
                        "direction": direction,
                        "contracts": prev["quantity"],
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "realized_pl": round(pnl, 2),
                        "strategy": entry_strategy,
                        "close_reason": close_reason,
                        "won": pnl > 0,
                        "opened_at": opened_at,
                        "closed_at": closed_at,
                    })
                    notify_trade_closed(supabase_uid, sym, direction, round(pnl, 2), 0, close_reason)
                    sb = get_client()
                    if sb:
                        sb.table("positions").delete().eq(
                            "user_id", supabase_uid
                        ).eq("broker", "ib").eq("instrument", sym).execute()
            except Exception:
                pass
        except Exception:
            pass

        # Mark the linked stop record as Filled (no-op if it was an explicit close)
        if close_perm_id:
            try:
                requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                    json={"order_id": f"futures_stop_{close_perm_id}", "status": "Filled"},
                    headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
            except Exception:
                pass

    _prev_futures_positions = current


def _cancel_futures_stop(ib, ticker):
    """Cancel any open GTC stop on this futures ticker and mark Redis record cancelled.

    Called before closing a position so the stop and the close don't both hit IB.
    """
    try:
        for ot in list(ib.openTrades()):
            try:
                if (ot.contract.symbol == ticker and ot.contract.secType == 'FUT'
                        and getattr(ot.order, 'orderType', '') == 'STP'):
                    sl_perm = ot.order.permId
                    ib.cancelOrder(ot.order)
                    logger.info("Cancelled stop loss %s permId=%s", ticker, sl_perm)
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                            json={"order_id": f"futures_stop_{sl_perm}", "status": "Cancelled"},
                            headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                    except Exception:
                        pass
            except Exception:
                continue
    except Exception as e:
        logger.warning("Failed to cancel stop loss for %s: %s", ticker, e)


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

                # Per-strategy position awareness
                # Check if this strategy already has an active entry for this ticker.
                # Uses the most recent entry record only (not cumulative count).
                import redis as _rdb_pos
                rdb_pos = _rdb_pos.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

                has_active_long = False
                has_active_short = False
                for fk in rdb_pos.scan_iter("ibkr:order:futures_entry_*"):
                    raw_fe = rdb_pos.get(fk)
                    if raw_fe:
                        fe = json.loads(raw_fe)
                        if fe.get("ticker") == ticker and fe.get("strategy") == strategy_name and fe.get("status") == "entry":
                            if fe.get("direction") == "BUY":
                                has_active_long = True
                            elif fe.get("direction") == "SELL":
                                has_active_short = True

                # Also check total broker position for CLOSE orders
                ib.sleep(1)
                broker_pos = 0
                for item in ib.portfolio():
                    if item.contract.symbol == ticker and item.contract.secType == 'FUT':
                        broker_pos = int(item.position)
                        break
                if broker_pos == 0:
                    for pos in ib.positions():
                        if pos.contract.symbol == ticker and pos.contract.secType == 'FUT':
                            broker_pos = int(pos.position)
                            break

                logger.info("Position check: %s strategy=%s has_long=%s has_short=%s broker_pos=%d (direction=%s)",
                            ticker, strategy_name, has_active_long, has_active_short, broker_pos, direction)

                skip = False

                # ORB reversal: BUY while short (or SELL while long) = reverse position
                # Double the contracts: 1 to close existing + 1 to open new direction
                is_reversal = order.get("reversal", False)
                if direction == "BUY" and broker_pos < 0 and (is_reversal or "fakeout" in strategy_name):
                    reversal_qty = abs(broker_pos) + contracts
                    logger.info("ORB REVERSAL: %s BUY while short %d — sending %d contracts (close %d + open %d)",
                                ticker, broker_pos, reversal_qty, abs(broker_pos), contracts)
                    contracts = reversal_qty
                elif direction == "SELL" and broker_pos > 0 and (is_reversal or "fakeout" in strategy_name):
                    reversal_qty = abs(broker_pos) + contracts
                    logger.info("ORB REVERSAL: %s SELL while long %d — sending %d contracts (close %d + open %d)",
                                ticker, broker_pos, reversal_qty, broker_pos, contracts)
                    contracts = reversal_qty

                if direction == "BUY" and has_active_long:
                    logger.info("SKIP %s BUY — %s already has active long", ticker, strategy_name)
                    skip = True
                elif direction == "SELL" and has_active_short:
                    logger.info("SKIP %s SELL — %s already has active short", ticker, strategy_name)
                    skip = True
                elif direction == "CLOSE_LONG" and broker_pos <= 0:
                    logger.info("SKIP %s CLOSE_LONG — not long at broker (pos=%d)", ticker, broker_pos)
                    skip = True
                elif direction == "CLOSE_SHORT" and broker_pos >= 0:
                    logger.info("SKIP %s CLOSE_SHORT — not short at broker (pos=%d)", ticker, broker_pos)
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
                    from ib_insync import Future, MarketOrder as MktOrder

                    # Resolve front-month futures contract
                    contract = Future(ticker, exchange="CME")
                    candidates = ib.reqContractDetails(contract)
                    if candidates:
                        # Pick the nearest expiration (front month)
                        candidates.sort(key=lambda c: c.contract.lastTradeDateOrContractMonth)
                        contract = candidates[0].contract
                        logger.info("Resolved %s to %s exp %s", ticker, contract.localSymbol, contract.lastTradeDateOrContractMonth)
                    else:
                        raise ValueError(f"No futures contract found for {ticker}")

                    # Get futures stop loss setting from server
                    sl_dollars = 25.0  # default
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

                    # MES = $5/point, ES = $50/point
                    multiplier = float(contract.multiplier or 5)
                    # Use webhook stop_price if provided (ORB sends exact levels)
                    webhook_stop = order.get("stop_price")
                    sl_points = sl_dollars / multiplier

                    if direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                        # Record entry price before closing — prefer stored fill price
                        entry_price = 0
                        entry_qty = 0
                        for item in ib.portfolio():
                            if item.contract.symbol == ticker and item.contract.secType == 'FUT':
                                entry_price = item.averageCost / multiplier  # fallback
                                entry_qty = abs(int(item.position))
                                break

                        # Cancel the bracket stop first so it doesn't fight the close.
                        _cancel_futures_stop(ib, ticker)
                        close_action = "SELL" if direction == "CLOSE_LONG" else "BUY"
                        close_ord = MktOrder(close_action, contracts)
                        close_ord.tif = "GTC"
                        close_ord.outsideRth = True
                        trade = ib.placeOrder(contract, close_ord)
                        ib.sleep(3)

                        # Record closed trade
                        exit_price = trade.orderStatus.avgFillPrice or 0
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
                                    # Mark ALL matching entries as closed (not just this one)
                                    try:
                                        import redis as _rdb_close_entry
                                        rdb_ce = _rdb_close_entry.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                                        for fk in rdb_ce.scan_iter("ibkr:order:futures_entry_*"):
                                            raw_fe = rdb_ce.get(fk)
                                            if raw_fe:
                                                fe = json.loads(raw_fe)
                                                if (fe.get("ticker") == ticker and
                                                    fe.get("strategy") == entry_strategy and
                                                    fe.get("status") == "entry"):
                                                    fe["status"] = "closed"
                                                    rdb_ce.setex(fk, 3600, json.dumps(fe))
                                                    logger.info("Marked entry closed: %s", fk)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            if not opened_at:
                                opened_at = order.get("queued_at", "")

                            # Use stored fill price from entry if available
                            if entry_data and entry_data.get("entry_price"):
                                stored_entry = float(entry_data["entry_price"])
                                if stored_entry > 0:
                                    entry_price = stored_entry

                            # Use IB execution time, not sync detection time
                            ib_fill_time = ""
                            if trade.fills:
                                try:
                                    ib_fill_time = str(trade.fills[-1].execution.time)
                                except Exception:
                                    pass
                            if ib_fill_time:
                                try:
                                    closed_at = _dt.fromisoformat(
                                        ib_fill_time.replace("Z", "+00:00")
                                    ).isoformat()
                                except Exception:
                                    closed_at = _dt.now(_tz.utc).isoformat()
                            else:
                                closed_at = _dt.now(_tz.utc).isoformat()

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
                                "closed_at": closed_at,
                                "close_exec_id": str(getattr(trade.order, "permId", "") or ""),
                            }
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/closed-trade",
                                              json=closed_trade, headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                            except Exception:
                                pass
                            logger.info("Closed %s %s: entry=%.2f exit=%.2f P&L=$%.2f", ticker, direction, entry_price, exit_price, pnl)

                            # Remove position from Supabase
                            try:
                                from lumisignals.supabase_client import remove_position
                                supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                                if supabase_uid:
                                    # Remove all futures positions for this ticker
                                    from lumisignals.supabase_client import get_client
                                    sb = get_client()
                                    if sb:
                                        sb.table("positions").delete().eq(
                                            "user_id", supabase_uid
                                        ).eq("broker", "ib").eq("instrument", ticker).execute()
                            except Exception:
                                pass
                    elif direction == "BUY":
                        buy_ord = MktOrder("BUY", contracts)
                        buy_ord.tif = "GTC"
                        buy_ord.outsideRth = True  # MES trades 23/5; allow fills outside RTH
                        trade = ib.placeOrder(contract, buy_ord)
                        ib.sleep(2)
                        if trade.orderStatus.status in ("Filled", "PreSubmitted", "Submitted"):
                            fill_price = trade.orderStatus.avgFillPrice or 0
                            if fill_price > 0:
                                if webhook_stop:
                                    sl_price = float(webhook_stop)
                                    sl_dollars = abs(fill_price - sl_price) * multiplier
                                else:
                                    sl_price = fill_price - sl_points
                                _place_futures_stop(ib, contract, ticker, "SELL", contracts,
                                                    sl_price, fill_price, sl_dollars,
                                                    trade.order.permId, strategy_name)
                    elif direction == "SELL":
                        sell_ord = MktOrder("SELL", contracts)
                        sell_ord.tif = "GTC"
                        sell_ord.outsideRth = True
                        trade = ib.placeOrder(contract, sell_ord)
                        ib.sleep(2)
                        if trade.orderStatus.status in ("Filled", "PreSubmitted", "Submitted"):
                            fill_price = trade.orderStatus.avgFillPrice or 0
                            if fill_price > 0:
                                if webhook_stop:
                                    sl_price = float(webhook_stop)
                                    sl_dollars = abs(fill_price - sl_price) * multiplier
                                else:
                                    sl_price = fill_price + sl_points
                                _place_futures_stop(ib, contract, ticker, "BUY", contracts,
                                                    sl_price, fill_price, sl_dollars,
                                                    trade.order.permId, strategy_name)
                    else:
                        logger.error("Unknown futures direction: %s", direction)
                        continue

                    ib.sleep(2)
                    from datetime import datetime as _dt2, timezone as _tz2
                    perm_id = trade.order.permId
                    # Use IB execution time for opened_at
                    ib_entry_time = ""
                    if trade.fills:
                        try:
                            ib_entry_time = str(trade.fills[-1].execution.time)
                        except Exception:
                            pass
                    if ib_entry_time:
                        try:
                            now_iso = _dt2.fromisoformat(
                                ib_entry_time.replace("Z", "+00:00")
                            ).isoformat()
                        except Exception:
                            now_iso = _dt2.now(_tz2.utc).isoformat()
                    else:
                        now_iso = _dt2.now(_tz2.utc).isoformat()

                    result = {
                        "order_id": order_id,
                        "ib_order_id": trade.order.orderId,
                        "perm_id": perm_id,
                        "status": trade.orderStatus.status,
                        "ticker": ticker,
                        "direction": direction,
                        "type": "futures",
                    }
                    logger.info("Futures order placed: %s %s — %s (permId=%s)", direction, ticker, trade.orderStatus.status, perm_id)

                    # Store entry details for BUY/SELL (not CLOSE) using permId as unique key
                    if direction in ("BUY", "SELL"):
                        fill_price = trade.orderStatus.avgFillPrice or 0
                        try:
                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                json={
                                    "order_id": f"futures_entry_{perm_id}",
                                    "ticker": ticker,
                                    "direction": direction,
                                    "contracts": contracts,
                                    "perm_id": perm_id,
                                    "opened_at": now_iso,
                                    "strategy": strategy_name,
                                    "status": "entry",
                                    "type": "futures",
                                    "entry_price": fill_price,
                                },
                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                        except Exception:
                            pass

                        # Write position to Supabase (for mobile app)
                        try:
                            from lumisignals.supabase_client import upsert_position
                            supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                            if supabase_uid:
                                upsert_position(supabase_uid, {
                                    "id": str(perm_id),
                                    "broker": "ib",
                                    "instrument": ticker,
                                    "asset_type": "futures",
                                    "direction": direction,
                                    "contracts": contracts,
                                    "entry_price": fill_price,
                                    "strategy": strategy_name,
                                    "model": strategy_name,
                                    "opened_at": now_iso,
                                })
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

                # Wait a moment for permId to be assigned
                ib.sleep(1)
                perm_id = trade.order.permId

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


def _connect(ib: IB) -> bool:
    """Connect or reconnect to IB Gateway. Returns True on success."""
    import random
    if ib.isConnected():
        return True
    try:
        cid = random.randint(20, 99)
        ib.connect(IB_HOST, IB_PORT, clientId=cid, timeout=15)
        logger.info("Connected to IB Gateway (clientId %d)", cid)
        ib.reqMarketDataType(3)
        # Store auth time for the IB session timer on the dashboard
        try:
            import redis as _rdb
            from datetime import datetime as _dtc, timezone as _tzc
            rdb = _rdb.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
            rdb.set("ib:auth_time", _dtc.now(_tzc.utc).isoformat())
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error("IB connect failed: %s", e)
        return False


DISCONNECT_ALERT_AFTER = 120   # seconds disconnected before sending email alert
DISCONNECT_ALERT_COOLDOWN = 1800  # don't re-alert more often than every 30 min


def _alert_disconnected(disconnected_seconds: float):
    """Email the user that IB Gateway has been disconnected. Used when re-auth is needed."""
    try:
        from lumisignals.alerts import send_alert, AlertType
        alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
        if not alert_pass:
            return
        send_alert(
            AlertType.TOKEN_EXPIRY,
            "IB Gateway disconnected — log in to resume trading",
            f"The bot's IB Gateway connection has been down for {int(disconnected_seconds/60)} minutes "
            f"and is failing to reconnect. This usually means the IB session expired (every ~24h) "
            f"and needs you to log in again.\n\n"
            f"Open in any browser: https://bot.lumitrade.ai/ib-vnc/vnc_lite.html\n\n"
            f"Once you log in, the bot will resume trading automatically. "
            f"While disconnected, no new futures trades are placed and existing positions are not monitored.",
            details={"Reconnect URL": "https://bot.lumitrade.ai/ib-vnc/vnc_lite.html"},
            smtp_pass=alert_pass,
        )
        logger.info("Sent disconnect alert email")
    except Exception as e:
        logger.warning("Failed to send disconnect alert: %s", e)


def main():
    logger.info("IB Sync starting — connecting to IB Gateway at %s:%s", IB_HOST, IB_PORT)

    ib = IB()
    consecutive_failures = 0
    disconnected_since: Optional[float] = None
    last_alert_at: float = 0.0

    while True:
        # Auto-reconnect if disconnected
        if not ib.isConnected():
            if disconnected_since is None:
                disconnected_since = time.time()
            disconnected_for = time.time() - disconnected_since

            # Email alert if we've been down past the threshold (cooldowned)
            if disconnected_for > DISCONNECT_ALERT_AFTER and \
               (time.time() - last_alert_at) > DISCONNECT_ALERT_COOLDOWN:
                _alert_disconnected(disconnected_for)
                last_alert_at = time.time()

            if consecutive_failures > 0:
                wait = min(consecutive_failures * 10, 60)
                logger.info("Reconnecting in %ds... (attempt %d, down %.0fs)",
                            wait, consecutive_failures, disconnected_for)
                time.sleep(wait)
            if not _connect(ib):
                consecutive_failures += 1
                if consecutive_failures == 1:
                    logger.error("IB Gateway not reachable — will keep retrying")
                continue

            consecutive_failures = 0
            disconnected_since = None
            logger.info("Connected to IB Gateway — syncing every %ds to %s", SYNC_INTERVAL, SERVER_URL)
            # NOTE: Real-time streaming (reqRealTimeBars) requires a paid CME market
            # data subscription which this account doesn't have. Using polling fallback.
            # Uncomment _setup_mes_realtime_stream(ib) once subscription is in place.

        try:
            ib.sleep(1)  # let ib_insync process events (including the realtime-bar callback)
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

            # Detect futures positions that closed at the broker (stop fired, manual close, etc.)
            _detect_closed_futures(ib)

            # MES bars: real-time streaming requires a paid CME market data subscription
            # which this account doesn't have (Error 420: No market data permissions).
            # Falling back to historical polling — runs every 30s on the regular tick.
            _push_mes_bars_polling(ib)

            # Monitor open spreads for TP/SL/time stop
            if data.get("spreads"):
                monitor_spreads(ib, data["spreads"])

            consecutive_failures = 0

        except Exception as e:
            logger.error("Sync error: %s", e)
            # Check if it's a connection error
            if not ib.isConnected():
                logger.warning("Connection lost — will auto-reconnect")
                _teardown_mes_realtime_stream(ib)
                try:
                    ib.disconnect()
                except Exception:
                    pass

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
