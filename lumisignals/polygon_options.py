"""Options spread analyzer using Polygon.io API — runs server-side, no IB needed."""

import logging
from datetime import datetime, timedelta

import requests

from .options_analyzer import SpreadLeg, SpreadAnalysis, format_spread_for_display

logger = logging.getLogger(__name__)

BASE_URL = "https://api.polygon.io"


class PolygonOptionsClient:
    """Polygon.io options data client."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def _request(self, endpoint: str, params: dict = None) -> dict:
        params = params or {}
        params["apiKey"] = self.api_key
        resp = self.session.get(f"{BASE_URL}{endpoint}", params=params, timeout=15)
        if not resp.ok:
            logger.error("Polygon options error: %s - %s", resp.status_code, resp.text[:200])
            return {}
        return resp.json()

    def get_option_contracts(self, ticker: str, exp_date_gte: str, exp_date_lte: str,
                             strike_gte: float = None, strike_lte: float = None,
                             contract_type: str = None, limit: int = 50) -> list:
        """Get available option contracts for a ticker."""
        params = {
            "underlying_ticker": ticker,
            "expiration_date.gte": exp_date_gte,
            "expiration_date.lte": exp_date_lte,
            "limit": limit,
            "sort": "expiration_date",
            "order": "asc",
        }
        if strike_gte:
            params["strike_price.gte"] = strike_gte
        if strike_lte:
            params["strike_price.lte"] = strike_lte
        if contract_type:
            params["contract_type"] = contract_type

        data = self._request("/v3/reference/options/contracts", params)
        return data.get("results", [])

    def get_option_prev_close(self, option_ticker: str) -> dict:
        """Get previous close for an option contract."""
        data = self._request(f"/v2/aggs/ticker/{option_ticker}/prev")
        results = data.get("results", [])
        return results[0] if results else {}

    def get_option_snapshots(self, underlying: str, exp_gte: str = None, exp_lte: str = None,
                             strike_gte: float = None, strike_lte: float = None,
                             limit: int = 250) -> list:
        """Get snapshots for options of an underlying — includes greeks, prices, OI."""
        params = {"limit": limit}
        if exp_gte:
            params["expiration_date.gte"] = exp_gte
        if exp_lte:
            params["expiration_date.lte"] = exp_lte
        if strike_gte:
            params["strike_price.gte"] = strike_gte
        if strike_lte:
            params["strike_price.lte"] = strike_lte
        data = self._request(f"/v3/snapshot/options/{underlying}", params)
        return data.get("results", [])

    def get_stock_price(self, ticker: str) -> float:
        """Get current/last stock price."""
        data = self._request(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results", [])
        if results:
            return results[0].get("c", 0)  # close price
        return 0


def analyze_spreads_polygon(api_key: str, ticker: str, zone_type: str,
                            zone_price: float, current_price: float,
                            max_risk_per_spread: float = 0, preferred_width: float = 5.0,
                            min_dte: int = 14, max_dte: int = 60,
                            atr: float = 0, score: int = 0) -> dict:
    """Analyze best credit and debit spreads using Polygon data.

    Same output format as analyze_spreads_ib for side-by-side comparison.
    """
    result = {"credit_spread": None, "debit_spread": None, "error": None, "data_source": "polygon"}

    client = PolygonOptionsClient(api_key)

    try:
        # Get current price if not provided
        if not current_price:
            current_price = client.get_stock_price(ticker)
            if not current_price:
                result["error"] = f"Could not get price for {ticker}"
                return result

        # Date range based on model
        today = datetime.now().date()
        min_exp = (today + timedelta(days=min_dte)).strftime("%Y-%m-%d")
        max_exp = (today + timedelta(days=max_dte)).strftime("%Y-%m-%d")

        # Strike range: within 10% of current price
        strike_range = current_price * 0.10
        strike_gte = current_price - strike_range
        strike_lte = current_price + strike_range

        # Get all option snapshots in one API call (requires options subscription)
        snapshots = client.get_option_snapshots(
            ticker, exp_gte=min_exp, exp_lte=max_exp,
            strike_gte=strike_gte, strike_lte=strike_lte,
            limit=250,
        )

        if not snapshots:
            result["error"] = "No options data available"
            return result

        # Parse snapshots into usable data
        options = []
        for snap in snapshots:
            details = snap.get("details", {})
            day = snap.get("day", {})
            greeks = snap.get("greeks", {})
            last_quote = snap.get("last_quote", {})

            exp_str = details.get("expiration_date", "")
            if not exp_str:
                continue

            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days

            strike = details.get("strike_price", 0)
            contract_type = details.get("contract_type", "").lower()
            if contract_type not in ("call", "put"):
                continue

            close = day.get("close", 0)
            bid = last_quote.get("bid", 0) or (round(close * 0.97, 2) if close else 0)
            ask = last_quote.get("ask", 0) or (round(close * 1.03, 2) if close else 0)

            if not bid and not ask and not close:
                continue

            if not bid:
                bid = round(close * 0.97, 2) if close else 0
            if not ask:
                ask = round(close * 1.03, 2) if close else 0

            iv_raw = snap.get("implied_volatility", 0) or 0

            options.append({
                "strike": strike,
                "expiration": exp_str.replace("-", ""),
                "dte": dte,
                "right": "C" if contract_type == "call" else "P",
                "bid": bid,
                "ask": ask,
                "mid": close or (bid + ask) / 2,
                "delta": abs(greeks.get("delta", 0)),
                "iv": round(iv_raw * 100, 1),
                "oi": snap.get("open_interest", 0),
            })

        if not options:
            result["error"] = "No options data in 14-60 DTE range"
            return result

        # Filter strikes to avoid illiquid $0.50 increments on expensive stocks
        # Only filter to $5 increments for stocks over $200 (AAPL, MSFT, etc.)
        # Stocks $50-$200: use $1 increments. Under $50: use all available.
        if current_price > 200:
            options = [o for o in options if o["strike"] % 5 == 0]
        elif current_price > 50:
            options = [o for o in options if o["strike"] % 1 == 0]

        # Group by expiration
        exps = {}
        for opt in options:
            exp = opt["expiration"]
            if exp not in exps:
                exps[exp] = {"dte": opt["dte"], "options": []}
            exps[exp]["options"].append(opt)

        # Pick optimal expirations
        exp_list = [(exp, data["dte"]) for exp, data in exps.items()]
        if not exp_list:
            result["error"] = "No valid expirations found"
            return result

        # Use same expiration for both credit and debit
        target_exp = _best_exp_poly(exp_list, min_dte, max_dte)

        # Analyze based on zone type — both use same expiration
        credit_options = exps.get(target_exp[0], {}).get("options", [])
        debit_options = credit_options  # same expiration

        # Auto-adjust width: try preferred, then narrower, to fit max_risk
        widths_to_try = [preferred_width]
        if preferred_width > 2.5:
            widths_to_try.append(2.5)
        if preferred_width > 1.0:
            widths_to_try.append(1.0)

        if zone_type == "supply":
            credit = _find_best_spread_width(credit_options, target_exp, zone_price, current_price,
                                             _find_bear_call_credit_poly, widths_to_try, max_risk_per_spread, is_credit=True)
            debit = _find_optimal_debit(debit_options, target_exp, zone_price, current_price,
                                        "Bear Put Debit", "P", "below", widths_to_try,
                                        atr=atr, score=score)
        else:
            credit = _find_best_spread_width(credit_options, target_exp, zone_price, current_price,
                                             _find_bull_put_credit_poly, widths_to_try, max_risk_per_spread, is_credit=True)
            debit = _find_optimal_debit(debit_options, target_exp, zone_price, current_price,
                                        "Bull Call Debit", "C", "above", widths_to_try,
                                        atr=atr, score=score)

        result["credit_spread"] = format_spread_for_display(credit) if credit else None
        result["debit_spread"] = format_spread_for_display(debit) if debit else None

    except Exception as e:
        logger.error("Polygon options analysis error for %s: %s", ticker, e)
        result["error"] = str(e)

    return result


def _best_exp_poly(exps, min_dte, max_dte):
    in_range = [(e, d) for e, d in exps if min_dte <= d <= max_dte]
    if in_range:
        target = (min_dte + max_dte) // 2
        return min(in_range, key=lambda x: abs(x[1] - target))
    return min(exps, key=lambda x: abs(x[1] - (min_dte + max_dte) // 2))


def _build_spread_poly(spread_type, short_opt, long_opt, is_credit):
    """Build SpreadAnalysis from two option data dicts."""
    if not short_opt or not long_opt:
        return None
    if not short_opt["bid"] or not long_opt["ask"]:
        return None

    option_type = "CALL" if short_opt["right"] == "C" else "PUT"
    exp = short_opt["expiration"]
    dte = short_opt["dte"]

    short_leg = SpreadLeg(
        strike=short_opt["strike"], option_type=option_type, action="SELL",
        bid=short_opt["bid"], ask=short_opt["ask"],
        delta=short_opt["delta"], iv=short_opt["iv"],
        open_interest=short_opt["oi"], expiration=exp,
    )
    long_leg = SpreadLeg(
        strike=long_opt["strike"], option_type=option_type, action="BUY",
        bid=long_opt["bid"], ask=long_opt["ask"],
        delta=long_opt["delta"], iv=long_opt["iv"],
        open_interest=long_opt["oi"], expiration=exp,
    )

    width = abs(short_opt["strike"] - long_opt["strike"])
    if width == 0:
        return None

    if is_credit:
        net_credit = round(short_opt["bid"] - long_opt["ask"], 2)
        if net_credit <= 0:
            return None
        net_debit = 0
        max_profit = net_credit * 100
        max_loss = (width - net_credit) * 100
        credit_pct = (net_credit / width) * 100
    else:
        net_debit = round(long_opt["ask"] - short_opt["bid"], 2)
        if net_debit <= 0:
            return None
        net_credit = 0
        max_profit = (width - net_debit) * 100
        max_loss = net_debit * 100
        credit_pct = 0

    rr = round(max_profit / max_loss, 2) if max_loss > 0 else 0

    if "Call" in spread_type:
        breakeven = short_opt["strike"] + net_credit if is_credit else long_opt["strike"] + net_debit
    else:
        breakeven = short_opt["strike"] - net_credit if is_credit else long_opt["strike"] - net_debit

    if is_credit:
        if credit_pct >= 33 and rr >= 0.3:
            verdict, reason = "GOOD", f"{credit_pct:.0f}% credit collected, solid R:R"
        elif credit_pct >= 25:
            verdict, reason = "FAIR", f"{credit_pct:.0f}% credit, acceptable"
        else:
            verdict, reason = "SKIP", f"Only {credit_pct:.0f}% credit — too thin"
    else:
        if rr >= 3.0:
            verdict, reason = "GOOD", f"{rr:.1f}:1 R:R — excellent setup"
        elif rr >= 2.0:
            verdict, reason = "GOOD", f"{rr:.1f}:1 R:R — solid setup"
        elif rr >= 1.5:
            verdict, reason = "FAIR", f"{rr:.1f}:1 R:R — acceptable"
        else:
            verdict, reason = "SKIP", f"Only {rr:.1f}:1 — risk outweighs reward"

    avg_iv = (short_opt["iv"] + long_opt["iv"]) / 2
    iv_rank = "high" if avg_iv >= 40 else ("medium" if avg_iv >= 25 else "low")

    return SpreadAnalysis(
        spread_type=spread_type, short_leg=short_leg, long_leg=long_leg,
        net_credit=net_credit, net_debit=net_debit,
        max_profit=max_profit, max_loss=max_loss,
        risk_reward=rr, breakeven=round(breakeven, 2),
        width=width, expiration=exp, days_to_expiry=dte,
        iv_rank=iv_rank, verdict=verdict, reason=reason,
    )


def _find_opts(options, right, near_strike, direction="above"):
    """Find options of a given type near a strike, sorted by proximity."""
    filtered = [o for o in options if o["right"] == right]
    if direction == "above":
        candidates = sorted([o for o in filtered if o["strike"] >= near_strike], key=lambda o: o["strike"])
    else:
        candidates = sorted([o for o in filtered if o["strike"] <= near_strike], key=lambda o: -o["strike"])
    return candidates


def _find_best_spread_width(options, exp_info, zone_price, current_price,
                            finder_fn, widths_to_try, max_risk, is_credit):
    """Try multiple spread widths, pick the widest one that fits max_risk."""
    for target_width in widths_to_try:
        spread = finder_fn(options, exp_info, zone_price, current_price, target_width)
        if spread:
            # Let calculate_spread_contracts handle risk limits — it will
            # size to 0 contracts if risk is too high for even 1 contract
            return spread
    return None


def _find_bear_call_credit_poly(options, exp_info, zone_price, current_price, target_width=1.0):
    exp, dte = exp_info
    sells = _find_opts(options, "C", current_price, "above")
    for short_opt in sells[:3]:
        buys = [o for o in options if o["right"] == "C" and o["strike"] > short_opt["strike"]]
        buys.sort(key=lambda o: o["strike"])
        for long_opt in buys[:3]:
            gap = long_opt["strike"] - short_opt["strike"]
            if abs(gap - target_width) < 0.01 or (gap >= target_width and gap <= target_width + 1):
                result = _build_spread_poly("Bear Call Credit", short_opt, long_opt, True)
                if result:
                    return result
    return None


def _find_bull_put_credit_poly(options, exp_info, zone_price, current_price, target_width=1.0):
    exp, dte = exp_info
    sells = _find_opts(options, "P", current_price, "below")
    for short_opt in sells[:3]:
        buys = [o for o in options if o["right"] == "P" and o["strike"] < short_opt["strike"]]
        buys.sort(key=lambda o: -o["strike"])
        for long_opt in buys[:3]:
            gap = short_opt["strike"] - long_opt["strike"]
            if abs(gap - target_width) < 0.01 or (gap >= target_width and gap <= target_width + 1):
                result = _build_spread_poly("Bull Put Credit", short_opt, long_opt, True)
                if result:
                    return result
    return None


def _find_optimal_debit(options, exp_info, zone_price, current_price,
                        spread_type, right, direction, widths_to_try,
                        atr=0, score=0, min_rr=2.0, min_delta=0.15):
    """Find optimal debit spread placement using ATR + IV for strike selection.

    Strategy:
    1. Calculate expected move from ATR (how far price can bounce from the level)
    2. Use IV expected move as a cap
    3. Place long strike at 40-60% of expected move from the level
    4. Score adjusts how far OTM we go (higher score = more conviction = further OTM ok)
    5. Filter by R:R >= 2:1 and delta >= 0.15

    For BUY at demand: bull call debit — long call OTM, short call further OTM
    For SELL at supply: bear put debit — long put OTM, short put further OTM
    """
    exp, dte = exp_info
    is_bullish = direction == "above"  # bull call debit vs bear put debit

    # Calculate expected bounce from the level
    if atr > 0:
        # ATR-based: stronger score = expect bigger bounce
        atr_multiplier = 1.0 + (score * 0.25)  # score 0=1x, 1=1.25x, 2=1.5x, 3=1.75x
        expected_bounce = atr * atr_multiplier
    else:
        # Fallback: use 2% of price
        expected_bounce = current_price * 0.02

    # IV expected move over the DTE period (1 std dev)
    # Get average IV from nearby options
    nearby = [o for o in options if o["right"] == right and abs(o["strike"] - current_price) < current_price * 0.05]
    if nearby:
        avg_iv_pct = sum(o["iv"] for o in nearby) / len(nearby)
    else:
        avg_iv_pct = 25  # default 25% IV

    iv_expected_move = current_price * (avg_iv_pct / 100) * (dte / 365) ** 0.5

    # Cap the expected bounce at 70% of IV expected move (52% probability zone)
    max_otm = min(expected_bounce, iv_expected_move * 0.7)

    # Place long strike at 40-60% of expected move from zone price
    # Higher score = place at 50-60% (more conviction), lower = 30-40% (closer to money)
    placement_pct = 0.3 + (score * 0.1)  # score 0=30%, 1=40%, 2=50%, 3=60%
    placement_pct = min(placement_pct, 0.6)

    if is_bullish:
        target_long_strike = zone_price + (max_otm * placement_pct)
    else:
        target_long_strike = zone_price - (max_otm * placement_pct)

    logger.info("Debit optimization for %s: ATR=%.1f, IV=%.0f%%, expected_bounce=%.1f, "
                "iv_move=%.1f, max_otm=%.1f, target_long=%.1f",
                spread_type, atr, avg_iv_pct, expected_bounce, iv_expected_move,
                max_otm, target_long_strike)

    # Find the best spread: try multiple strikes near our target, pick best R:R >= 2:1
    best_spread = None
    best_rr = 0

    # Get candidate long options near our target strike
    all_opts = sorted([o for o in options if o["right"] == right], key=lambda o: o["strike"])

    if is_bullish:
        long_candidates = [o for o in all_opts if o["strike"] >= current_price]
        # Sort by proximity to target strike
        long_candidates.sort(key=lambda o: abs(o["strike"] - target_long_strike))
    else:
        long_candidates = [o for o in all_opts if o["strike"] <= current_price]
        long_candidates.sort(key=lambda o: abs(o["strike"] - target_long_strike))

    for long_opt in long_candidates[:8]:
        # Skip if delta too low (too unlikely to hit)
        if long_opt["delta"] < min_delta:
            continue

        # Try each width
        for target_width in widths_to_try:
            if is_bullish:
                short_strike_target = long_opt["strike"] + target_width
                short_candidates = [o for o in all_opts if o["right"] == right
                                    and abs(o["strike"] - short_strike_target) <= target_width * 0.5 + 0.5
                                    and o["strike"] > long_opt["strike"]]
            else:
                short_strike_target = long_opt["strike"] - target_width
                short_candidates = [o for o in all_opts if o["right"] == right
                                    and abs(o["strike"] - short_strike_target) <= target_width * 0.5 + 0.5
                                    and o["strike"] < long_opt["strike"]]

            short_candidates.sort(key=lambda o: abs(o["strike"] - short_strike_target))

            for short_opt in short_candidates[:2]:
                spread = _build_spread_poly(spread_type, short_opt, long_opt, False)
                if spread and spread.risk_reward >= min_rr and spread.risk_reward > best_rr:
                    best_spread = spread
                    best_rr = spread.risk_reward

    # Fallback: if no ATR-optimized spread found, try the original near-money approach
    if not best_spread:
        for target_width in widths_to_try:
            if is_bullish:
                best_spread = _find_bull_call_debit_poly(options, exp_info, zone_price, current_price, target_width)
            else:
                best_spread = _find_bear_put_debit_poly(options, exp_info, zone_price, current_price, target_width)
            if best_spread:
                break

    return best_spread


def _find_bear_put_debit_poly(options, exp_info, zone_price, current_price, target_width=1.0):
    exp, dte = exp_info
    buys = _find_opts(options, "P", current_price, "below")
    for long_opt in buys[:3]:
        sells = [o for o in options if o["right"] == "P" and o["strike"] < long_opt["strike"]]
        sells.sort(key=lambda o: -o["strike"])
        for short_opt in sells[:3]:
            gap = long_opt["strike"] - short_opt["strike"]
            if abs(gap - target_width) < 0.01 or (gap >= target_width and gap <= target_width + 1):
                result = _build_spread_poly("Bear Put Debit", short_opt, long_opt, False)
                if result:
                    return result
    return None


def _find_bull_call_debit_poly(options, exp_info, zone_price, current_price, target_width=1.0):
    exp, dte = exp_info
    buys = _find_opts(options, "C", current_price, "above")
    for long_opt in buys[:3]:
        sells = [o for o in options if o["right"] == "C" and o["strike"] > long_opt["strike"]]
        sells.sort(key=lambda o: o["strike"])
        for short_opt in sells[:3]:
            gap = short_opt["strike"] - long_opt["strike"]
            if abs(gap - target_width) < 0.01 or (gap >= target_width and gap <= target_width + 1):
                result = _build_spread_poly("Bull Call Debit", short_opt, long_opt, False)
                if result:
                    return result
    return None
