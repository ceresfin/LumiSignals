"""Trade tracker — pulls trade data from Oanda and merges with local signal metadata."""

import logging
from datetime import datetime, timezone
from typing import Optional

from .oanda_client import OandaClient
from .signal_log import get_signal_log

logger = logging.getLogger(__name__)


def _parse_oanda_time(time_str: str) -> Optional[str]:
    """Convert Oanda UNIX timestamp to human-readable format."""
    try:
        ts = float(time_str)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return time_str


def _pip_value(instrument: str) -> float:
    """Get pip value for an instrument."""
    if "JPY" in instrument:
        return 0.01
    return 0.0001


def _estimate_usd_pl(instrument: str, units: int, entry: float, target_price: float) -> float:
    """Estimate P&L in USD for a price move.

    Simplified: assumes account currency is USD.
    For XXX_USD pairs, P&L = units × (target - entry).
    For USD_XXX pairs, P&L = units × (target - entry) / target.
    For cross pairs, approximates using entry price.
    """
    if units == 0 or entry == 0:
        return 0.0
    distance = target_price - entry  # positive = price went up
    parts = instrument.split("_")
    if len(parts) != 2:
        return round(abs(units) * abs(distance), 2)

    base, quote = parts
    if quote == "USD":
        # EUR_USD, GBP_USD etc — P&L is directly in USD
        return round(abs(units) * distance, 2)
    elif base == "USD":
        # USD_JPY, USD_CAD etc — P&L needs conversion
        if target_price != 0:
            return round(abs(units) * distance / target_price, 2)
        return 0.0
    else:
        # Cross pairs (EUR_GBP, AUD_NZD) — rough approximation
        # P&L in quote currency, divide by entry as rough USD estimate
        if entry != 0:
            return round(abs(units) * distance / entry, 2)
        return 0.0


def _enrich_with_signal_data(entry: dict, order_id: str) -> dict:
    """Merge local signal log data into a trade/order entry."""
    sig = get_signal_log().get(order_id)
    if sig:
        entry["strategy"] = sig.get("strategy", "")
        entry["snr_grade"] = sig.get("snr_grade", "")
        entry["snr_summary"] = sig.get("snr_summary", "")
        entry["candle_score"] = sig.get("candle_score", "")
        entry["candle_summary"] = sig.get("candle_summary", "")
        entry["candle_details"] = sig.get("candle_details", [])
        entry["level_type"] = sig.get("level_type", "")
        entry["level_timeframe"] = sig.get("level_timeframe", "")
        entry["level_price"] = sig.get("level_price", "")
        entry["alert_matches"] = sig.get("alert_matches", [])
        entry["primary_matches"] = sig.get("primary_matches", [])
    else:
        entry["strategy"] = ""
        entry["snr_grade"] = ""
        entry["candle_summary"] = ""
        entry["candle_details"] = []
    return entry


def _get_current_prices(client: OandaClient, instruments: list) -> dict:
    """Fetch current mid prices for a list of instruments."""
    prices = {}
    if not instruments:
        return prices
    # Oanda accepts comma-separated instruments
    try:
        unique = list(set(instruments))
        # Batch in groups of 20
        for i in range(0, len(unique), 20):
            batch = unique[i:i+20]
            data = client._request(
                "GET",
                f"/v3/accounts/{client.account_id}/pricing?instruments={','.join(batch)}",
            )
            for p in data.get("prices", []):
                bid = float(p["bids"][0]["price"])
                ask = float(p["asks"][0]["price"])
                prices[p["instrument"]] = (bid + ask) / 2
    except Exception as e:
        logger.debug("Could not fetch prices: %s", e)
    return prices


def get_pending_orders(client: OandaClient) -> list:
    """Get all pending orders formatted for display."""
    try:
        data = client.get_orders()
        orders = data.get("orders", [])
    except Exception as e:
        logger.error("Failed to get orders: %s", e)
        return []

    # Fetch current prices for all instruments with pending orders
    instruments = [o.get("instrument", "") for o in orders if o.get("instrument")]
    current_prices = _get_current_prices(client, instruments)

    result = []
    for order in orders:
        instrument = order.get("instrument", "")
        units = int(float(order.get("units", 0)))
        direction = "BUY" if units > 0 else "SELL"
        entry = float(order.get("price", 0))
        sl = float(order.get("stopLossOnFill", {}).get("price", 0))
        tp = float(order.get("takeProfitOnFill", {}).get("price", 0))

        rr = 0
        if sl and entry and tp:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = round(reward / risk, 2) if risk > 0 else 0

        # Calculate potential profit/loss in USD
        potential_profit = abs(_estimate_usd_pl(instrument, abs(units), entry, tp)) if tp else 0
        potential_loss = abs(_estimate_usd_pl(instrument, abs(units), entry, sl)) if sl else 0

        # Calculate pips away from current price
        pip = _pip_value(instrument)
        cur_price = current_prices.get(instrument)
        pips_away = round(abs(entry - cur_price) / pip, 1) if cur_price else None

        order_entry = {
            "id": order.get("id", ""),
            "instrument": instrument,
            "direction": direction,
            "units": abs(units),
            "entry": entry,
            "current_price": round(cur_price, 5) if cur_price else None,
            "pips_away": pips_away,
            "stop_loss": sl,
            "take_profit": tp,
            "risk_reward": rr,
            "potential_profit": round(potential_profit, 2),
            "potential_loss": round(potential_loss, 2),
            "type": order.get("type", ""),
            "time": _parse_oanda_time(order.get("createTime", "")),
            "status": "PENDING",
        }
        result.append(_enrich_with_signal_data(order_entry, order.get("id", "")))

    return result


def get_open_trades(client: OandaClient) -> list:
    """Get all open trades with unrealized P&L."""
    try:
        data = client.get_trades(state="OPEN")
        trades = data.get("trades", [])
    except Exception as e:
        logger.error("Failed to get trades: %s", e)
        return []

    result = []
    for trade in trades:
        instrument = trade.get("instrument", "")
        units = int(float(trade.get("currentUnits", trade.get("initialUnits", 0))))
        direction = "BUY" if units > 0 else "SELL"
        entry = float(trade.get("price", 0))
        unrealized_pl = float(trade.get("unrealizedPL", 0))

        sl = float(trade.get("stopLossOrder", {}).get("price", 0)) if trade.get("stopLossOrder") else 0
        tp = float(trade.get("takeProfitOrder", {}).get("price", 0)) if trade.get("takeProfitOrder") else 0

        # Calculate pips P&L
        pip = _pip_value(instrument)
        current_price = entry + (unrealized_pl / abs(units)) if units != 0 else entry
        pips_pl = round((current_price - entry) / pip, 1) if direction == "BUY" else round((entry - current_price) / pip, 1)

        # Potential profit/loss from current price to TP/SL
        potential_profit = abs(_estimate_usd_pl(instrument, abs(units), current_price, tp)) if tp else 0
        potential_loss = abs(_estimate_usd_pl(instrument, abs(units), current_price, sl)) if sl else 0

        # Planned R:R from entry
        rr = 0
        if sl and tp and entry:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = round(reward / risk, 2) if risk > 0 else 0

        trade_entry = {
            "id": trade.get("id", ""),
            "instrument": instrument,
            "direction": direction,
            "units": abs(units),
            "entry": entry,
            "current_price": round(current_price, 5),
            "stop_loss": sl,
            "take_profit": tp,
            "risk_reward": rr,
            "unrealized_pl": round(unrealized_pl, 2),
            "pips": pips_pl,
            "potential_profit": round(potential_profit, 2),
            "potential_loss": round(potential_loss, 2),
            "time_opened": _parse_oanda_time(trade.get("openTime", "")),
            "status": "OPEN",
        }
        # Try matching by trade ID or the order that opened it
        open_id = trade.get("id", "")
        opening_order = trade.get("openingTransactionID", open_id)
        trade_entry = _enrich_with_signal_data(trade_entry, opening_order)
        if not trade_entry.get("strategy"):
            trade_entry = _enrich_with_signal_data(trade_entry, open_id)
        result.append(trade_entry)

    return result


def get_closed_trades(client: OandaClient, count: int = 50) -> list:
    """Get recently closed trades with realized P&L."""
    try:
        data = client.get_trades(state="CLOSED", count=count)
        trades = data.get("trades", [])
    except Exception as e:
        logger.error("Failed to get closed trades: %s", e)
        return []

    result = []
    for trade in trades:
        instrument = trade.get("instrument", "")
        units = int(float(trade.get("initialUnits", 0)))
        direction = "BUY" if units > 0 else "SELL"
        entry = float(trade.get("price", 0))
        realized_pl = float(trade.get("realizedPL", 0))
        close_price = float(trade.get("averageClosePrice", 0))

        # Calculate pips
        pip = _pip_value(instrument)
        if direction == "BUY":
            pips = round((close_price - entry) / pip, 1)
        else:
            pips = round((entry - close_price) / pip, 1)

        # Determine how it closed
        close_reason = "Manual"
        if trade.get("stopLossOrderID"):
            close_reason = "Stop Loss"
        elif trade.get("takeProfitOrderID"):
            close_reason = "Take Profit"

        # Duration
        open_time = _parse_oanda_time(trade.get("openTime", ""))
        close_time = _parse_oanda_time(trade.get("closeTime", ""))

        # Get planned SL/TP from signal log if available
        opening_order = trade.get("openingTransactionID", trade.get("id", ""))
        sig = get_signal_log().get(opening_order) or get_signal_log().get(trade.get("id", ""))
        planned_sl = sig.get("stop", 0) if sig else 0
        planned_tp = sig.get("target", 0) if sig else 0

        # Planned potential profit/loss (what was expected at entry)
        planned_profit = abs(_estimate_usd_pl(instrument, abs(units), entry, planned_tp)) if planned_tp else 0
        planned_loss = abs(_estimate_usd_pl(instrument, abs(units), entry, planned_sl)) if planned_sl else 0

        # Planned R:R from signal log
        planned_rr = 0
        if planned_sl and planned_tp and entry:
            risk = abs(entry - planned_sl)
            reward = abs(planned_tp - entry)
            planned_rr = round(reward / risk, 2) if risk > 0 else 0
        elif sig and sig.get("risk_reward"):
            planned_rr = round(float(sig["risk_reward"]), 2)

        # Achieved R:R (actual result vs planned risk)
        achieved_rr = 0
        if planned_sl and entry:
            planned_risk = abs(entry - planned_sl)
            actual_move = abs(close_price - entry)
            if planned_risk > 0:
                achieved_rr = round(actual_move / planned_risk, 2)
                if realized_pl < 0:
                    achieved_rr = -achieved_rr

        trade_entry = {
            "id": trade.get("id", ""),
            "instrument": instrument,
            "direction": direction,
            "units": abs(units),
            "entry": entry,
            "close_price": close_price,
            "stop_loss": planned_sl,
            "take_profit": planned_tp,
            "realized_pl": round(realized_pl, 2),
            "pips": pips,
            "planned_rr": planned_rr,
            "achieved_rr": achieved_rr,
            "planned_profit": round(planned_profit, 2),
            "planned_loss": round(planned_loss, 2),
            "close_reason": close_reason,
            "time_opened": open_time,
            "time_closed": close_time,
            "status": "CLOSED",
            "won": realized_pl > 0,
        }
        trade_entry = _enrich_with_signal_data(trade_entry, opening_order)
        if not trade_entry.get("strategy"):
            trade_entry = _enrich_with_signal_data(trade_entry, trade.get("id", ""))
        result.append(trade_entry)

    return result


def get_performance_stats(closed_trades: list) -> dict:
    """Calculate performance statistics from closed trades."""
    if not closed_trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "total_pl": 0,
            "total_pips": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "best_trade": None,
            "worst_trade": None,
            "avg_rr_achieved": 0,
            "by_pair": {},
            "by_direction": {"BUY": {"wins": 0, "losses": 0, "pl": 0}, "SELL": {"wins": 0, "losses": 0, "pl": 0}},
        }

    wins = [t for t in closed_trades if t["realized_pl"] > 0]
    losses = [t for t in closed_trades if t["realized_pl"] <= 0]

    total_pl = sum(t["realized_pl"] for t in closed_trades)
    total_pips = sum(t["pips"] for t in closed_trades)

    avg_win = sum(t["realized_pl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["realized_pl"] for t in losses) / len(losses) if losses else 0

    best = max(closed_trades, key=lambda t: t["realized_pl"]) if closed_trades else None
    worst = min(closed_trades, key=lambda t: t["realized_pl"]) if closed_trades else None

    # By pair
    by_pair = {}
    for t in closed_trades:
        pair = t["instrument"]
        if pair not in by_pair:
            by_pair[pair] = {"wins": 0, "losses": 0, "pl": 0, "pips": 0}
        by_pair[pair]["pl"] += t["realized_pl"]
        by_pair[pair]["pips"] += t["pips"]
        if t["realized_pl"] > 0:
            by_pair[pair]["wins"] += 1
        else:
            by_pair[pair]["losses"] += 1

    # By direction
    by_direction = {"BUY": {"wins": 0, "losses": 0, "pl": 0}, "SELL": {"wins": 0, "losses": 0, "pl": 0}}
    for t in closed_trades:
        d = t["direction"]
        by_direction[d]["pl"] += t["realized_pl"]
        if t["realized_pl"] > 0:
            by_direction[d]["wins"] += 1
        else:
            by_direction[d]["losses"] += 1

    # Average R:R
    rr_values = [t["achieved_rr"] for t in closed_trades if t.get("achieved_rr")]
    avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0
    avg_planned_rr_values = [t["planned_rr"] for t in closed_trades if t.get("planned_rr")]
    avg_planned_rr = round(sum(avg_planned_rr_values) / len(avg_planned_rr_values), 2) if avg_planned_rr_values else 0

    # By strategy
    by_strategy = {}
    for t in closed_trades:
        strat = t.get("strategy") or "unknown"
        if strat not in by_strategy:
            by_strategy[strat] = {"wins": 0, "losses": 0, "pl": 0, "pips": 0, "trades": 0, "rr_sum": 0, "rr_count": 0}
        by_strategy[strat]["trades"] += 1
        by_strategy[strat]["pl"] += t["realized_pl"]
        by_strategy[strat]["pips"] += t["pips"]
        if t.get("achieved_rr"):
            by_strategy[strat]["rr_sum"] += t["achieved_rr"]
            by_strategy[strat]["rr_count"] += 1
        if t["realized_pl"] > 0:
            by_strategy[strat]["wins"] += 1
        else:
            by_strategy[strat]["losses"] += 1
    # Calculate averages
    for strat, data in by_strategy.items():
        data["win_rate"] = round(data["wins"] / data["trades"] * 100, 1) if data["trades"] else 0
        data["avg_rr"] = round(data["rr_sum"] / data["rr_count"], 2) if data["rr_count"] else 0
        data["pl"] = round(data["pl"], 2)
        data["pips"] = round(data["pips"], 1)

    return {
        "total_trades": len(closed_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0,
        "total_pl": round(total_pl, 2),
        "total_pips": round(total_pips, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_planned_rr": avg_planned_rr,
        "avg_achieved_rr": avg_rr,
        "best_trade": best,
        "worst_trade": worst,
        "by_pair": by_pair,
        "by_direction": by_direction,
        "by_strategy": by_strategy,
    }
