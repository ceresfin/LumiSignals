"""Options spread analyzer using Interactive Brokers data."""

import logging
from datetime import datetime, timedelta

from ib_insync import IB, Stock, Option

from .options_analyzer import SpreadLeg, SpreadAnalysis, format_spread_for_display

logger = logging.getLogger(__name__)


def is_market_closed() -> bool:
    """Check if US stock market is currently closed (weekend or outside hours).

    Returns True on Friday after 4pm ET through Monday 9:30am ET,
    and outside regular hours on weekdays.
    """
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    # ET = UTC-4 (EDT) or UTC-5 (EST). Use -4 for simplicity.
    et_offset = timedelta(hours=-4)
    now_et = now_utc + et_offset
    weekday = now_et.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_et.hour
    minute = now_et.minute

    # Saturday or Sunday
    if weekday >= 5:
        return True
    # Friday after 4pm
    if weekday == 4 and (hour > 16 or (hour == 16 and minute > 0)):
        return True
    # Monday before 9:30am
    if weekday == 0 and (hour < 9 or (hour == 9 and minute < 30)):
        return True
    # Weekday outside market hours
    if hour < 9 or (hour == 9 and minute < 30) or hour >= 16:
        return True
    return False


def get_data_mode() -> str:
    """Return 'live' or 'friday_close' depending on market state."""
    return "friday_close" if is_market_closed() else "live"


def analyze_spreads_ib(ib: IB, ticker: str, zone_type: str,
                       zone_price: float, current_price: float) -> dict:
    """Analyze best credit and debit spreads using IB market data.

    Args:
        ib: Connected IB instance
        ticker: Stock symbol (e.g. "AAPL")
        zone_type: "supply" or "demand"
        zone_price: The S/R level price
        current_price: Current stock price

    Returns:
        Dict with "credit_spread" and "debit_spread" formatted for display.
    """
    data_mode = get_data_mode()
    result = {"credit_spread": None, "debit_spread": None, "error": None, "data_mode": data_mode}

    try:
        # Get stock contract
        stock = Stock(ticker, "SMART", "USD")
        ib.qualifyContracts(stock)

        # Get current price if not provided
        if not current_price:
            ticker_data = ib.reqMktData(stock, "", False, False)
            ib.sleep(2)
            current_price = ticker_data.midpoint() or ticker_data.last or 0
            ib.cancelMktData(stock)
            if not current_price:
                result["error"] = f"Could not get price for {ticker}"
                return result

        # Get option chains
        chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        if not chains:
            result["error"] = "No options data available"
            return result

        # Find SMART exchange chain
        chain = None
        for c in chains:
            if c.exchange == "SMART":
                chain = c
                break
        if not chain:
            chain = chains[0]

        # Filter expirations: 14-60 days out
        today = datetime.now().date()
        valid_exps = []
        for exp_str in sorted(chain.expirations):
            exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
            dte = (exp_date - today).days
            if 14 <= dte <= 60:
                valid_exps.append((exp_str, dte))

        if not valid_exps:
            result["error"] = "No expirations in 14-60 DTE range"
            return result

        # Pick optimal expirations
        # Credit spreads: prefer 30-45 DTE
        credit_exp = _best_exp(valid_exps, 30, 45)
        # Debit spreads: prefer 14-30 DTE
        debit_exp = _best_exp(valid_exps, 14, 30)

        # Get available strikes near the zone
        # Filter to $5-wide strikes for high-priced stocks, $1 for cheaper ones
        all_strikes = sorted(chain.strikes)
        if current_price > 50:
            # Use only $5-increment strikes to avoid non-existent $2.50 strikes
            all_strikes = [s for s in all_strikes if s % 5 == 0]
        near_strikes = [s for s in all_strikes if abs(s - zone_price) <= current_price * 0.10]
        if len(near_strikes) < 4:
            near_strikes = [s for s in all_strikes if abs(s - zone_price) <= current_price * 0.20]

        if len(near_strikes) < 4:
            result["error"] = "Not enough strikes near zone price"
            return result

        # Analyze based on zone type
        if zone_type == "supply":
            # Price at resistance — expect reversal down
            # Credit: Bear Call Spread (sell call below zone, buy call above)
            credit = _find_bear_call_credit(ib, ticker, credit_exp, near_strikes, zone_price, current_price)
            # Debit: Bear Put Spread (buy put at/near money, sell put below)
            debit = _find_bear_put_debit(ib, ticker, debit_exp, near_strikes, zone_price, current_price)
        else:
            # Price at support — expect bounce up
            # Credit: Bull Put Spread (sell put above zone, buy put below)
            credit = _find_bull_put_credit(ib, ticker, credit_exp, near_strikes, zone_price, current_price)
            # Debit: Bull Call Spread (buy call at/near money, sell call above)
            debit = _find_bull_call_debit(ib, ticker, debit_exp, near_strikes, zone_price, current_price)

        result["credit_spread"] = format_spread_for_display(credit) if credit else None
        result["debit_spread"] = format_spread_for_display(debit) if debit else None

    except Exception as e:
        logger.error("IB options analysis error for %s: %s", ticker, e)
        result["error"] = str(e)

    return result


def _best_exp(exps: list, min_dte: int, max_dte: int) -> tuple:
    """Pick the best expiration within a DTE range."""
    in_range = [(e, d) for e, d in exps if min_dte <= d <= max_dte]
    if in_range:
        # Prefer middle of range
        target = (min_dte + max_dte) // 2
        return min(in_range, key=lambda x: abs(x[1] - target))
    # Fall back to closest available
    return min(exps, key=lambda x: abs(x[1] - (min_dte + max_dte) // 2))


def _get_option_data(ib: IB, ticker: str, exp: str, strike: float, right: str) -> dict:
    """Fetch bid/ask/greeks for a single option.

    During market hours uses live bid/ask. When market is closed,
    falls back to last/close price as both bid and ask estimate.
    """
    contract = Option(ticker, exp, strike, right, "SMART")
    try:
        ib.qualifyContracts(contract)
    except Exception:
        return None

    tk = ib.reqMktData(contract, "106", False, False)  # 106 = greeks

    # Wait up to 3 seconds for data, checking every 0.5s
    import math
    for _ in range(6):
        ib.sleep(0.5)
        has_bid = tk.bid is not None and not math.isnan(tk.bid) and tk.bid > 0
        has_ask = tk.ask is not None and not math.isnan(tk.ask) and tk.ask > 0
        has_last = tk.last is not None and not math.isnan(tk.last) and tk.last > 0
        has_close = tk.close is not None and not math.isnan(tk.close) and tk.close > 0
        if has_bid or has_last or has_close:
            break

    ib.cancelMktData(contract)

    bid = tk.bid if (tk.bid is not None and not math.isnan(tk.bid) and tk.bid > 0) else 0
    ask = tk.ask if (tk.ask is not None and not math.isnan(tk.ask) and tk.ask > 0) else 0

    # When market is closed, bid/ask may be 0 — use last/close price
    if not bid and not ask:
        last = tk.last if (tk.last is not None and not math.isnan(tk.last) and tk.last > 0) else 0
        close = tk.close if (tk.close is not None and not math.isnan(tk.close) and tk.close > 0) else 0
        fallback = last or close
        if fallback > 0:
            # Simulate a tight spread around last price
            bid = round(fallback * 0.97, 2)
            ask = round(fallback * 1.03, 2)

    if not bid and not ask:
        return None

    # Greeks from model
    greeks = tk.modelGreeks or tk.lastGreeks
    delta = abs(greeks.delta) if greeks and greeks.delta else 0
    iv = (greeks.impliedVol or 0) * 100 if greeks else 0

    return {
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2 if bid and ask else 0,
        "delta": delta,
        "iv": iv,
        "oi": getattr(tk, "openInterest", 0) or 0,
    }


def _build_spread(spread_type: str, short_data: dict, long_data: dict,
                   option_type: str, exp: str, dte: int, is_credit: bool) -> SpreadAnalysis:
    """Build a SpreadAnalysis from two legs of option data."""
    if not short_data or not long_data:
        return None
    if not short_data["bid"] or not long_data["ask"]:
        return None

    short_leg = SpreadLeg(
        strike=short_data["strike"],
        option_type=option_type,
        action="SELL",
        bid=short_data["bid"],
        ask=short_data["ask"],
        delta=short_data["delta"],
        iv=short_data["iv"],
        open_interest=short_data["oi"],
        expiration=exp,
    )
    long_leg = SpreadLeg(
        strike=long_data["strike"],
        option_type=option_type,
        action="BUY",
        bid=long_data["bid"],
        ask=long_data["ask"],
        delta=long_data["delta"],
        iv=long_data["iv"],
        open_interest=long_data["oi"],
        expiration=exp,
    )

    width = abs(short_data["strike"] - long_data["strike"])
    if width == 0:
        return None

    if is_credit:
        net_credit = round(short_data["bid"] - long_data["ask"], 2)
        if net_credit <= 0:
            return None
        net_debit = 0
        max_profit = net_credit * 100
        max_loss = (width - net_credit) * 100
        credit_pct = (net_credit / width) * 100
    else:
        net_debit = round(long_data["ask"] - short_data["bid"], 2)
        if net_debit <= 0:
            return None
        net_credit = 0
        max_profit = (width - net_debit) * 100
        max_loss = net_debit * 100
        credit_pct = 0

    rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

    # Breakeven
    if "Call" in spread_type:
        breakeven = short_data["strike"] + net_credit if is_credit else long_data["strike"] + net_debit
    else:
        breakeven = short_data["strike"] - net_credit if is_credit else long_data["strike"] - net_debit

    # Verdict
    if is_credit:
        if credit_pct >= 33 and rr >= 0.3:
            verdict, reason = "GOOD", f"{credit_pct:.0f}% credit collected, solid R:R"
        elif credit_pct >= 25:
            verdict, reason = "FAIR", f"{credit_pct:.0f}% credit, acceptable"
        else:
            verdict, reason = "SKIP", f"Only {credit_pct:.0f}% credit — too thin"
    else:
        if rr >= 1.5:
            verdict, reason = "GOOD", f"{rr:.1f}:1 reward-to-risk"
        elif rr >= 1.0:
            verdict, reason = "FAIR", f"{rr:.1f}:1 reward-to-risk"
        else:
            verdict, reason = "SKIP", f"Only {rr:.1f}:1 — risk outweighs reward"

    # IV rank (simplified — would need historical IV for real ranking)
    avg_iv = (short_data["iv"] + long_data["iv"]) / 2
    if avg_iv >= 40:
        iv_rank = "high"
    elif avg_iv >= 25:
        iv_rank = "medium"
    else:
        iv_rank = "low"

    return SpreadAnalysis(
        spread_type=spread_type,
        short_leg=short_leg,
        long_leg=long_leg,
        net_credit=net_credit,
        net_debit=net_debit,
        max_profit=max_profit,
        max_loss=max_loss,
        risk_reward=rr,
        breakeven=round(breakeven, 2),
        width=width,
        expiration=exp,
        days_to_expiry=dte,
        iv_rank=iv_rank,
        verdict=verdict,
        reason=reason,
    )


def _next_strike_up(strikes, from_strike, min_gap=1.0):
    """Find the next strike above from_strike with at least min_gap distance."""
    for s in strikes:
        if s > from_strike and s - from_strike >= min_gap:
            return s
    # Fall back to any strike above
    above = [s for s in strikes if s > from_strike]
    return above[0] if above else None


def _next_strike_down(strikes, from_strike, min_gap=1.0):
    """Find the next strike below from_strike with at least min_gap distance."""
    below = [s for s in sorted(strikes, reverse=True) if s < from_strike and from_strike - s >= min_gap]
    return below[0] if below else None


def _try_spread(ib, ticker, exp_info, sell_strike, buy_strike, right, spread_type, is_credit):
    """Try to build a spread, returning None if data isn't available."""
    if not sell_strike or not buy_strike:
        return None
    exp, dte = exp_info
    short = _get_option_data(ib, ticker, exp, sell_strike, right)
    long = _get_option_data(ib, ticker, exp, buy_strike, right)
    return _build_spread(spread_type, short, long, "CALL" if right == "C" else "PUT", exp, dte, is_credit=is_credit)


def _find_bear_call_credit(ib, ticker, exp_info, strikes, zone_price, current_price):
    """Bear Call Credit Spread at supply zone."""
    # Sell call at/just above current price, buy call higher
    sell_candidates = sorted([s for s in strikes if s >= current_price and s <= zone_price + 10])
    for sell_strike in sell_candidates[:3]:
        buy_strike = _next_strike_up(strikes, sell_strike, min_gap=1.0)
        result = _try_spread(ib, ticker, exp_info, sell_strike, buy_strike, "C", "Bear Call Credit", True)
        if result:
            return result
    return None


def _find_bull_put_credit(ib, ticker, exp_info, strikes, zone_price, current_price):
    """Bull Put Credit Spread at demand zone."""
    # Sell put at/just below current price, buy put lower
    sell_candidates = sorted([s for s in strikes if s <= current_price and s >= zone_price - 10], reverse=True)
    for sell_strike in sell_candidates[:3]:
        buy_strike = _next_strike_down(strikes, sell_strike, min_gap=1.0)
        result = _try_spread(ib, ticker, exp_info, sell_strike, buy_strike, "P", "Bull Put Credit", True)
        if result:
            return result
    return None


def _find_bear_put_debit(ib, ticker, exp_info, strikes, zone_price, current_price):
    """Bear Put Debit Spread at supply zone."""
    # Buy put at/near money, sell put below
    buy_candidates = sorted([s for s in strikes if current_price - 5 <= s <= current_price + 2], reverse=True)
    for buy_strike in buy_candidates[:3]:
        sell_strike = _next_strike_down(strikes, buy_strike, min_gap=1.0)
        result = _try_spread(ib, ticker, exp_info, sell_strike, buy_strike, "P", "Bear Put Debit", False)
        if result:
            return result
    return None


def _find_bull_call_debit(ib, ticker, exp_info, strikes, zone_price, current_price):
    """Bull Call Debit Spread at demand zone."""
    # Buy call at/near money, sell call above
    buy_candidates = sorted([s for s in strikes if current_price - 2 <= s <= current_price + 5])
    for buy_strike in buy_candidates[:3]:
        sell_strike = _next_strike_up(strikes, buy_strike, min_gap=1.0)
        result = _try_spread(ib, ticker, exp_info, sell_strike, buy_strike, "C", "Bull Call Debit", False)
        if result:
            return result
    return None
