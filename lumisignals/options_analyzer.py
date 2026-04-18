"""Options spread analyzer — finds best credit/debit spreads at S/R zones."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SpreadLeg:
    """One leg of an options spread."""
    strike: float
    option_type: str     # "CALL" or "PUT"
    action: str          # "SELL" or "BUY"
    bid: float
    ask: float
    delta: float
    iv: float
    open_interest: int
    expiration: str


@dataclass
class SpreadAnalysis:
    """Analysis result for a vertical spread."""
    spread_type: str          # "Bear Call Credit", "Bull Put Credit", "Bear Put Debit", "Bull Call Debit"
    short_leg: SpreadLeg      # The leg we sell
    long_leg: SpreadLeg       # The leg we buy
    net_credit: float         # Positive for credit spreads
    net_debit: float          # Positive for debit spreads
    max_profit: float
    max_loss: float
    risk_reward: float        # max_profit / max_loss
    breakeven: float
    width: float              # Distance between strikes
    expiration: str
    days_to_expiry: int
    iv_rank: str              # "low", "medium", "high"
    verdict: str              # "GOOD", "FAIR", "SKIP"
    reason: str               # Why it's good/bad


def analyze_spreads_at_zone(schwab_md, ticker: str, zone_type: str,
                             zone_price: float, current_price: float,
                             trends: dict = None) -> dict:
    """Analyze best credit and debit spreads for a stock at an S/R zone.

    Args:
        schwab_md: SchwabMarketData client
        ticker: Stock symbol (e.g. "SPY")
        zone_type: "supply" or "demand"
        zone_price: The S/R level price
        current_price: Current stock price
        trends: {"Monthly": "bearish", "Weekly": "bearish", ...}

    Returns:
        Dict with "credit_spread" and "debit_spread" SpreadAnalysis objects.
    """
    result = {"credit_spread": None, "debit_spread": None, "error": None}

    try:
        # Find optimal expiration: 2-6 weeks out for credit, 4-8 weeks for debit
        chain_data = schwab_md._request("/chains", params={
            "symbol": ticker,
            "contractType": "ALL",
            "strikeCount": 20,
            "range": "ALL",
            "fromDate": (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"),
            "toDate": (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"),
        })

        if not chain_data or chain_data.get("status") == "FAILED":
            result["error"] = "No options data available"
            return result

        underlying_price = chain_data.get("underlyingPrice", current_price)
        overall_iv = chain_data.get("volatility", 0)

        call_map = chain_data.get("callExpDateMap", {})
        put_map = chain_data.get("putExpDateMap", {})

        if zone_type == "supply":
            # At supply zone (bearish expectation):
            # Credit: Bear Call Credit Spread (sell call, buy higher call)
            # Debit:  Bear Put Debit Spread (buy put, sell lower put)
            credit = _find_best_bear_call_credit(call_map, zone_price, underlying_price, overall_iv)
            debit = _find_best_bear_put_debit(put_map, zone_price, underlying_price, overall_iv)
        else:
            # At demand zone (bullish expectation):
            # Credit: Bull Put Credit Spread (sell put, buy lower put)
            # Debit:  Bull Call Debit Spread (buy call, sell higher call)
            credit = _find_best_bull_put_credit(put_map, zone_price, underlying_price, overall_iv)
            debit = _find_best_bull_call_debit(call_map, zone_price, underlying_price, overall_iv)

        result["credit_spread"] = credit
        result["debit_spread"] = debit

    except Exception as e:
        logger.error("Options analysis error for %s: %s", ticker, e)
        result["error"] = str(e)

    return result


def _parse_options(exp_date_map: dict) -> List[Tuple[str, float, dict]]:
    """Parse Schwab options chain into flat list of (expiration, strike, option_data)."""
    options = []
    for exp_str, strikes in exp_date_map.items():
        exp_date = exp_str.split(":")[0]  # "2026-04-18:9" → "2026-04-18"
        for strike_str, opt_list in strikes.items():
            opt = opt_list[0] if isinstance(opt_list, list) else opt_list
            strike = float(strike_str)
            options.append((exp_date, strike, opt))
    return options


def _days_to_expiry(exp_date: str) -> int:
    try:
        exp = datetime.strptime(exp_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (exp - datetime.now(timezone.utc)).days)
    except ValueError:
        return 0


def _iv_rank(iv: float) -> str:
    if iv < 20:
        return "low"
    elif iv < 40:
        return "medium"
    else:
        return "high"


def _make_leg(strike, opt, option_type, action, exp_date) -> SpreadLeg:
    return SpreadLeg(
        strike=strike,
        option_type=option_type,
        action=action,
        bid=float(opt.get("bid", 0)),
        ask=float(opt.get("ask", 0)),
        delta=float(opt.get("delta", 0)),
        iv=float(opt.get("volatility", 0)),
        open_interest=int(opt.get("openInterest", 0)),
        expiration=exp_date,
    )


def _score_spread(spread: SpreadAnalysis) -> float:
    """Score a spread — higher is better."""
    score = 0
    if spread.risk_reward > 0:
        score += spread.risk_reward * 30
    if spread.days_to_expiry >= 14:
        score += 10
    if spread.short_leg.open_interest > 100:
        score += 5
    if spread.long_leg.open_interest > 100:
        score += 5
    return score


# ------------------------------------------------------------------
# Bear Call Credit Spread (at supply zones)
# Sell call near zone, buy call 1-2 strikes higher
# ------------------------------------------------------------------

def _find_best_bear_call_credit(call_map, zone_price, price, overall_iv) -> Optional[SpreadAnalysis]:
    options = _parse_options(call_map)
    if not options:
        return None

    # Group by expiration
    by_exp = {}
    for exp, strike, opt in options:
        by_exp.setdefault(exp, []).append((strike, opt))

    best = None
    best_score = -1

    for exp, strikes_list in by_exp.items():
        strikes_list.sort(key=lambda x: x[0])
        dte = _days_to_expiry(exp)
        if dte < 25 or dte > 40:
            continue

        for i, (sell_strike, sell_opt) in enumerate(strikes_list):
            # Sell call at or just above zone price
            if sell_strike < zone_price * 0.98:
                continue
            if sell_strike > zone_price * 1.03:
                break

            sell_bid = float(sell_opt.get("bid", 0))
            if sell_bid <= 0.05:
                continue

            # Buy call 1-2 strikes higher
            for j in range(i + 1, min(i + 3, len(strikes_list))):
                buy_strike, buy_opt = strikes_list[j]
                buy_ask = float(buy_opt.get("ask", 0))

                net_credit = round(sell_bid - buy_ask, 2)
                if net_credit <= 0.05:
                    continue

                width = round(buy_strike - sell_strike, 2)
                max_loss = round((width - net_credit) * 100, 2)
                max_profit = round(net_credit * 100, 2)
                rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

                iv = float(sell_opt.get("volatility", overall_iv))
                ivr = _iv_rank(iv)

                # Verdict
                if rr >= 0.3 and ivr != "low" and net_credit >= 0.10:
                    verdict = "GOOD" if rr >= 0.5 else "FAIR"
                    reason = f"${net_credit:.2f} credit, {dte}d, IV {ivr}"
                elif ivr == "low":
                    verdict = "SKIP"
                    reason = f"IV too low ({iv:.0f}%) — thin premium"
                else:
                    verdict = "SKIP"
                    reason = f"R:R {rr:.2f} too low" if rr < 0.3 else f"Credit ${net_credit:.2f} too thin"

                spread = SpreadAnalysis(
                    spread_type="Bear Call Credit",
                    short_leg=_make_leg(sell_strike, sell_opt, "CALL", "SELL", exp),
                    long_leg=_make_leg(buy_strike, buy_opt, "CALL", "BUY", exp),
                    net_credit=net_credit,
                    net_debit=0,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    risk_reward=rr,
                    breakeven=round(sell_strike + net_credit, 2),
                    width=width,
                    expiration=exp,
                    days_to_expiry=dte,
                    iv_rank=ivr,
                    verdict=verdict,
                    reason=reason,
                )

                s = _score_spread(spread)
                if s > best_score:
                    best_score = s
                    best = spread

    return best


# ------------------------------------------------------------------
# Bull Put Credit Spread (at demand zones)
# Sell put near zone, buy put 1-2 strikes lower
# ------------------------------------------------------------------

def _find_best_bull_put_credit(put_map, zone_price, price, overall_iv) -> Optional[SpreadAnalysis]:
    options = _parse_options(put_map)
    if not options:
        return None

    by_exp = {}
    for exp, strike, opt in options:
        by_exp.setdefault(exp, []).append((strike, opt))

    best = None
    best_score = -1

    for exp, strikes_list in by_exp.items():
        strikes_list.sort(key=lambda x: x[0])
        dte = _days_to_expiry(exp)
        if dte < 25 or dte > 40:
            continue

        for i, (sell_strike, sell_opt) in enumerate(strikes_list):
            # Sell put at or just below zone price
            if sell_strike > zone_price * 1.02:
                continue
            if sell_strike < zone_price * 0.97:
                continue

            sell_bid = float(sell_opt.get("bid", 0))
            if sell_bid <= 0.05:
                continue

            # Buy put 1-2 strikes lower
            for j in range(i - 1, max(i - 3, -1), -1):
                if j < 0:
                    break
                buy_strike, buy_opt = strikes_list[j]
                buy_ask = float(buy_opt.get("ask", 0))

                net_credit = round(sell_bid - buy_ask, 2)
                if net_credit <= 0.05:
                    continue

                width = round(sell_strike - buy_strike, 2)
                max_loss = round((width - net_credit) * 100, 2)
                max_profit = round(net_credit * 100, 2)
                rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

                iv = float(sell_opt.get("volatility", overall_iv))
                ivr = _iv_rank(iv)

                if rr >= 0.3 and ivr != "low" and net_credit >= 0.10:
                    verdict = "GOOD" if rr >= 0.5 else "FAIR"
                    reason = f"${net_credit:.2f} credit, {dte}d, IV {ivr}"
                elif ivr == "low":
                    verdict = "SKIP"
                    reason = f"IV too low ({iv:.0f}%) — thin premium"
                else:
                    verdict = "SKIP"
                    reason = f"R:R {rr:.2f} too low" if rr < 0.3 else f"Credit ${net_credit:.2f} too thin"

                spread = SpreadAnalysis(
                    spread_type="Bull Put Credit",
                    short_leg=_make_leg(sell_strike, sell_opt, "PUT", "SELL", exp),
                    long_leg=_make_leg(buy_strike, buy_opt, "PUT", "BUY", exp),
                    net_credit=net_credit,
                    net_debit=0,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    risk_reward=rr,
                    breakeven=round(sell_strike - net_credit, 2),
                    width=width,
                    expiration=exp,
                    days_to_expiry=dte,
                    iv_rank=ivr,
                    verdict=verdict,
                    reason=reason,
                )

                s = _score_spread(spread)
                if s > best_score:
                    best_score = s
                    best = spread

    return best


# ------------------------------------------------------------------
# Bear Put Debit Spread (at supply zones)
# Buy put near zone, sell put 1-2 strikes lower
# ------------------------------------------------------------------

def _find_best_bear_put_debit(put_map, zone_price, price, overall_iv) -> Optional[SpreadAnalysis]:
    options = _parse_options(put_map)
    if not options:
        return None

    by_exp = {}
    for exp, strike, opt in options:
        by_exp.setdefault(exp, []).append((strike, opt))

    best = None
    best_score = -1

    for exp, strikes_list in by_exp.items():
        strikes_list.sort(key=lambda x: x[0])
        dte = _days_to_expiry(exp)
        if dte < 25 or dte > 40:
            continue

        for i, (buy_strike, buy_opt) in enumerate(strikes_list):
            # Buy put near or at zone price
            if buy_strike < zone_price * 0.97:
                continue
            if buy_strike > zone_price * 1.03:
                break

            buy_ask = float(buy_opt.get("ask", 0))
            if buy_ask <= 0:
                continue

            # Sell put 1-2 strikes lower
            for j in range(i - 1, max(i - 3, -1), -1):
                if j < 0:
                    break
                sell_strike, sell_opt = strikes_list[j]
                sell_bid = float(sell_opt.get("bid", 0))

                net_debit = round(buy_ask - sell_bid, 2)
                if net_debit <= 0:
                    continue

                width = round(buy_strike - sell_strike, 2)
                max_profit = round((width - net_debit) * 100, 2)
                max_loss = round(net_debit * 100, 2)
                rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

                iv = float(buy_opt.get("volatility", overall_iv))
                ivr = _iv_rank(iv)

                if rr >= 1.0 and ivr != "high":
                    verdict = "GOOD" if rr >= 1.5 else "FAIR"
                    reason = f"${net_debit:.2f} debit, {dte}d, R:R {rr:.1f}"
                elif ivr == "high":
                    verdict = "SKIP"
                    reason = f"IV too high ({iv:.0f}%) — overpaying for premium"
                else:
                    verdict = "SKIP"
                    reason = f"R:R {rr:.2f} — need 1.0+"

                spread = SpreadAnalysis(
                    spread_type="Bear Put Debit",
                    short_leg=_make_leg(sell_strike, sell_opt, "PUT", "SELL", exp),
                    long_leg=_make_leg(buy_strike, buy_opt, "PUT", "BUY", exp),
                    net_credit=0,
                    net_debit=net_debit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    risk_reward=rr,
                    breakeven=round(buy_strike - net_debit, 2),
                    width=width,
                    expiration=exp,
                    days_to_expiry=dte,
                    iv_rank=ivr,
                    verdict=verdict,
                    reason=reason,
                )

                s = _score_spread(spread)
                if s > best_score:
                    best_score = s
                    best = spread

    return best


# ------------------------------------------------------------------
# Bull Call Debit Spread (at demand zones)
# Buy call near zone, sell call 1-2 strikes higher
# ------------------------------------------------------------------

def _find_best_bull_call_debit(call_map, zone_price, price, overall_iv) -> Optional[SpreadAnalysis]:
    options = _parse_options(call_map)
    if not options:
        return None

    by_exp = {}
    for exp, strike, opt in options:
        by_exp.setdefault(exp, []).append((strike, opt))

    best = None
    best_score = -1

    for exp, strikes_list in by_exp.items():
        strikes_list.sort(key=lambda x: x[0])
        dte = _days_to_expiry(exp)
        if dte < 25 or dte > 40:
            continue

        for i, (buy_strike, buy_opt) in enumerate(strikes_list):
            # Buy call near or at zone price
            if buy_strike < zone_price * 0.97:
                continue
            if buy_strike > zone_price * 1.03:
                break

            buy_ask = float(buy_opt.get("ask", 0))
            if buy_ask <= 0:
                continue

            # Sell call 1-2 strikes higher
            for j in range(i + 1, min(i + 3, len(strikes_list))):
                sell_strike, sell_opt = strikes_list[j]
                sell_bid = float(sell_opt.get("bid", 0))

                net_debit = round(buy_ask - sell_bid, 2)
                if net_debit <= 0:
                    continue

                width = round(sell_strike - buy_strike, 2)
                max_profit = round((width - net_debit) * 100, 2)
                max_loss = round(net_debit * 100, 2)
                rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

                iv = float(buy_opt.get("volatility", overall_iv))
                ivr = _iv_rank(iv)

                if rr >= 1.0 and ivr != "high":
                    verdict = "GOOD" if rr >= 1.5 else "FAIR"
                    reason = f"${net_debit:.2f} debit, {dte}d, R:R {rr:.1f}"
                elif ivr == "high":
                    verdict = "SKIP"
                    reason = f"IV too high ({iv:.0f}%) — overpaying for premium"
                else:
                    verdict = "SKIP"
                    reason = f"R:R {rr:.2f} — need 1.0+"

                spread = SpreadAnalysis(
                    spread_type="Bull Call Debit",
                    short_leg=_make_leg(sell_strike, sell_opt, "CALL", "SELL", exp),
                    long_leg=_make_leg(buy_strike, buy_opt, "CALL", "BUY", exp),
                    net_credit=0,
                    net_debit=net_debit,
                    max_profit=max_profit,
                    max_loss=max_loss,
                    risk_reward=rr,
                    breakeven=round(buy_strike + net_debit, 2),
                    width=width,
                    expiration=exp,
                    days_to_expiry=dte,
                    iv_rank=ivr,
                    verdict=verdict,
                    reason=reason,
                )

                s = _score_spread(spread)
                if s > best_score:
                    best_score = s
                    best = spread

    return best


def format_spread_for_display(spread: SpreadAnalysis) -> dict:
    """Convert a SpreadAnalysis to a JSON-serializable dict for the web UI."""
    if not spread:
        return None
    return {
        "type": spread.spread_type,
        "verdict": spread.verdict,
        "reason": spread.reason,
        "short_strike": spread.short_leg.strike,
        "long_strike": spread.long_leg.strike,
        "short_action": spread.short_leg.action,
        "long_action": spread.long_leg.action,
        "option_type": spread.short_leg.option_type,
        "net_credit": spread.net_credit,
        "net_debit": spread.net_debit,
        "max_profit": spread.max_profit,
        "max_loss": spread.max_loss,
        "risk_reward": spread.risk_reward,
        "breakeven": spread.breakeven,
        "width": spread.width,
        "expiration": spread.expiration,
        "days_to_expiry": spread.days_to_expiry,
        "iv_rank": spread.iv_rank,
        "short_iv": round(spread.short_leg.iv, 1),
        "short_delta": round(spread.short_leg.delta, 3),
        "short_oi": spread.short_leg.open_interest,
    }
