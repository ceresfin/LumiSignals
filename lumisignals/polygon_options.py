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

    def get_stock_price(self, ticker: str) -> float:
        """Get current/last stock price."""
        data = self._request(f"/v2/aggs/ticker/{ticker}/prev")
        results = data.get("results", [])
        if results:
            return results[0].get("c", 0)  # close price
        return 0


def analyze_spreads_polygon(api_key: str, ticker: str, zone_type: str,
                            zone_price: float, current_price: float) -> dict:
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

        # Date range: 14-60 DTE
        today = datetime.now().date()
        min_exp = (today + timedelta(days=14)).strftime("%Y-%m-%d")
        max_exp = (today + timedelta(days=60)).strftime("%Y-%m-%d")

        # Strike range: within 10% of current price
        strike_range = current_price * 0.10
        strike_gte = current_price - strike_range
        strike_lte = current_price + strike_range

        # Get option contracts from reference data (free tier)
        # First get contracts to find available expirations and strikes
        contracts = client.get_option_contracts(
            ticker, min_exp, max_exp,
            strike_gte=strike_gte, strike_lte=strike_lte,
            limit=250,
        )

        if not contracts:
            result["error"] = "No option contracts found"
            return result

        # Build a lookup of available contracts by (exp, strike, type)
        contract_map = {}
        for c in contracts:
            exp = c.get("expiration_date", "")
            strike = c.get("strike_price", 0)
            ctype = c.get("contract_type", "").lower()
            poly_ticker = c.get("ticker", "")
            if exp and strike and ctype in ("call", "put"):
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                right = "C" if ctype == "call" else "P"
                contract_map[(exp, strike, right)] = {
                    "poly_ticker": poly_ticker,
                    "strike": strike,
                    "expiration": exp.replace("-", ""),
                    "dte": dte,
                    "right": right,
                }

        # Find available expirations
        exp_set = {}
        for (exp, strike, right), info in contract_map.items():
            if exp not in exp_set:
                exp_set[exp] = info["dte"]

        exp_list = [(exp.replace("-", ""), dte) for exp, dte in exp_set.items()]
        if not exp_list:
            result["error"] = "No valid expirations found"
            return result

        credit_exp = _best_exp_poly(exp_list, 30, 45)
        debit_exp = _best_exp_poly(exp_list, 14, 30)

        # Get strikes for the chosen expirations, filtered to $5 increments for expensive stocks
        all_strikes = sorted(set(s for (e, s, r) in contract_map.keys()))
        if current_price > 50:
            all_strikes = [s for s in all_strikes if s % 5 == 0]

        # Determine which specific contracts we need (max ~8 contracts for 2 spreads × 2 legs)
        needed_contracts = []

        if zone_type == "supply":
            # Bear Call Credit: sell call near current, buy call above
            sell_strikes = sorted([s for s in all_strikes if s >= current_price])[:2]
            for ss in sell_strikes:
                buy_strikes = sorted([s for s in all_strikes if s > ss])[:2]
                for bs in buy_strikes:
                    exp_raw = credit_exp[0][:4] + "-" + credit_exp[0][4:6] + "-" + credit_exp[0][6:]
                    if (exp_raw, ss, "C") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, ss, "C")])
                    if (exp_raw, bs, "C") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, bs, "C")])
            # Bear Put Debit: buy put near current, sell put below
            buy_strikes = sorted([s for s in all_strikes if s <= current_price], reverse=True)[:2]
            for bs in buy_strikes:
                sell_strikes2 = sorted([s for s in all_strikes if s < bs], reverse=True)[:2]
                for ss in sell_strikes2:
                    exp_raw = debit_exp[0][:4] + "-" + debit_exp[0][4:6] + "-" + debit_exp[0][6:]
                    if (exp_raw, bs, "P") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, bs, "P")])
                    if (exp_raw, ss, "P") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, ss, "P")])
        else:
            # Bull Put Credit: sell put near current, buy put below
            sell_strikes = sorted([s for s in all_strikes if s <= current_price], reverse=True)[:2]
            for ss in sell_strikes:
                buy_strikes = sorted([s for s in all_strikes if s < ss], reverse=True)[:2]
                for bs in buy_strikes:
                    exp_raw = credit_exp[0][:4] + "-" + credit_exp[0][4:6] + "-" + credit_exp[0][6:]
                    if (exp_raw, ss, "P") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, ss, "P")])
                    if (exp_raw, bs, "P") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, bs, "P")])
            # Bull Call Debit: buy call near current, sell call above
            buy_strikes = sorted([s for s in all_strikes if s >= current_price])[:2]
            for bs in buy_strikes:
                sell_strikes2 = sorted([s for s in all_strikes if s > bs])[:2]
                for ss in sell_strikes2:
                    exp_raw = debit_exp[0][:4] + "-" + debit_exp[0][4:6] + "-" + debit_exp[0][6:]
                    if (exp_raw, bs, "C") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, bs, "C")])
                    if (exp_raw, ss, "C") in contract_map:
                        needed_contracts.append(contract_map[(exp_raw, ss, "C")])

        # Deduplicate
        seen = set()
        unique_contracts = []
        for c in needed_contracts:
            key = c["poly_ticker"]
            if key not in seen:
                seen.add(key)
                unique_contracts.append(c)

        # Fetch prev close for only the needed contracts (with rate limiting)
        import time
        options = []
        for i, c in enumerate(unique_contracts):
            if i > 0 and i % 4 == 0:
                time.sleep(12)  # Rate limit: 5 req/min on free tier
            prev = client.get_option_prev_close(c["poly_ticker"])
            if not prev:
                continue
            close = prev.get("c", 0)
            if not close or close <= 0:
                continue
            c["bid"] = round(close * 0.97, 2)
            c["ask"] = round(close * 1.03, 2)
            c["mid"] = close
            c["delta"] = 0
            c["iv"] = 0
            c["oi"] = 0
            options.append(c)

        if not options:
            result["error"] = "No options data in 14-60 DTE range"
            return result

        # Filter to $5-wide strikes for high-priced stocks
        if current_price > 50:
            options = [o for o in options if o["strike"] % 5 == 0]

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

        credit_exp = _best_exp_poly(exp_list, 30, 45)
        debit_exp = _best_exp_poly(exp_list, 14, 30)

        # Analyze based on zone type
        credit_options = exps.get(credit_exp[0], {}).get("options", [])
        debit_options = exps.get(debit_exp[0], {}).get("options", [])

        if zone_type == "supply":
            credit = _find_bear_call_credit_poly(credit_options, credit_exp, zone_price, current_price)
            debit = _find_bear_put_debit_poly(debit_options, debit_exp, zone_price, current_price)
        else:
            credit = _find_bull_put_credit_poly(credit_options, credit_exp, zone_price, current_price)
            debit = _find_bull_call_debit_poly(debit_options, debit_exp, zone_price, current_price)

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
        if rr >= 1.5:
            verdict, reason = "GOOD", f"{rr:.1f}:1 reward-to-risk"
        elif rr >= 1.0:
            verdict, reason = "FAIR", f"{rr:.1f}:1 reward-to-risk"
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


def _find_bear_call_credit_poly(options, exp_info, zone_price, current_price):
    exp, dte = exp_info
    sells = _find_opts(options, "C", current_price, "above")
    for short_opt in sells[:3]:
        buys = [o for o in options if o["right"] == "C" and o["strike"] > short_opt["strike"]]
        buys.sort(key=lambda o: o["strike"])
        for long_opt in buys[:2]:
            if long_opt["strike"] - short_opt["strike"] >= 2.5:
                result = _build_spread_poly("Bear Call Credit", short_opt, long_opt, True)
                if result:
                    return result
    return None


def _find_bull_put_credit_poly(options, exp_info, zone_price, current_price):
    exp, dte = exp_info
    sells = _find_opts(options, "P", current_price, "below")
    for short_opt in sells[:3]:
        buys = [o for o in options if o["right"] == "P" and o["strike"] < short_opt["strike"]]
        buys.sort(key=lambda o: -o["strike"])
        for long_opt in buys[:2]:
            if short_opt["strike"] - long_opt["strike"] >= 2.5:
                result = _build_spread_poly("Bull Put Credit", short_opt, long_opt, True)
                if result:
                    return result
    return None


def _find_bear_put_debit_poly(options, exp_info, zone_price, current_price):
    exp, dte = exp_info
    buys = _find_opts(options, "P", current_price, "below")
    for long_opt in buys[:3]:
        sells = [o for o in options if o["right"] == "P" and o["strike"] < long_opt["strike"]]
        sells.sort(key=lambda o: -o["strike"])
        for short_opt in sells[:2]:
            if long_opt["strike"] - short_opt["strike"] >= 2.5:
                result = _build_spread_poly("Bear Put Debit", short_opt, long_opt, False)
                if result:
                    return result
    return None


def _find_bull_call_debit_poly(options, exp_info, zone_price, current_price):
    exp, dte = exp_info
    buys = _find_opts(options, "C", current_price, "above")
    for long_opt in buys[:3]:
        sells = [o for o in options if o["right"] == "C" and o["strike"] > long_opt["strike"]]
        sells.sort(key=lambda o: o["strike"])
        for short_opt in sells[:2]:
            if short_opt["strike"] - long_opt["strike"] >= 2.5:
                result = _build_spread_poly("Bull Call Debit", short_opt, long_opt, False)
                if result:
                    return result
    return None
