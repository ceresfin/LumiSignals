"""Front-side options-debit-spread setup analyzer for the dashboard panel.

Implements the user-described "front side entry" logic:

  1. Trend on three timeframes: Monthly, Weekly, Daily.
  2. Setup direction = where Monthly + Weekly agree.
     Both agree     → momentum = Strong
     One disagrees  → momentum = Weak (still triggers, biased to Monthly)
     Both SIDE      → no setup
  3. Daily must be COUNTER-moving against the M+W direction (i.e.,
     a pullback in the higher-TF trend). No counter-move → no setup
     (skip with "no pullback yet").
  4. Trigger level = nearest monthly level the daily counter-move is
     approaching. Long setup: nearest demand level BELOW current price.
     Short setup: nearest supply level ABOVE current price.
  5. Vehicle: options debit spread (default) — or stock shares (when
     user toggles).
       - Long setup  → call debit spread (long lower-K call + short higher-K call)
       - Short setup → put debit spread  (long higher-K put  + short lower-K put)
       - Long-leg strike picked at the target delta (default 0.30).
       - Width: 10 points default; fall back to 15 if 10-wide net debit
         exceeds 30% of width (poor R:R).
       - Contracts = floor(max_risk_usd / max_loss_per_spread).
  6. Mode determines DTE target:
       SCALP    = 0    (same-day expiry)
       INTRADAY = 3-4  (this-week weekly)
       SWING    = 10-12 (next-week or two-week weekly)

This module is INTENTIONALLY conservative: it returns
`skip_reason != None` whenever any precondition isn't cleanly met,
rather than producing a half-baked setup. The panel should display
"no clean trade right now — <reason>" in those cases.

Thresholds marked TUNING are best-effort defaults from the user's
verbal description; refine after seeing live behavior.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── MODE CONFIG ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class _ModeCfg:
    name: str
    dte_target: int          # ideal days-to-expiration for the option
    dte_min: int             # acceptable range to find a real expiration
    dte_max: int
    width_default: int       # default spread width in points
    width_fallback: int


MODE_CONFIG = {
    "scalp":    _ModeCfg("scalp",    0,  0,  2,  10, 15),
    "intraday": _ModeCfg("intraday", 4,  2,  6,  10, 15),
    "swing":    _ModeCfg("swing",    11, 7,  14, 10, 15),
}


# ─── TUNING THRESHOLDS ───────────────────────────────────────────────
# All marked TUNING — adjust after seeing live behavior.

TARGET_DELTA = 0.30                # TUNING: long-leg strike delta target
TRIGGER_PROXIMITY_PCT = 0.03       # TUNING: skip if price > 3% from level
DEBIT_RATIO_FALLBACK = 0.30        # TUNING: if net_debit/width > 30%, try wider
ADX_STRONG_TREND_THRESHOLD = 25    # TUNING: ADX >= this on M or W = Strong
DAILY_COUNTER_BARS = 5             # TUNING: look at last 5 daily bars for counter-move

# Polygon serves index data under the "I:" prefix (cash indexes like
# SPX, NDX, RUT, VIX, DJI). Plain SPY/QQQ/IWM (ETFs) use the regular
# ticker. Schwab's /chains endpoint takes the bare underlying symbol
# either way, so this translation only applies to the Polygon bars call.
_POLYGON_INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI"}


def _polygon_ticker(ticker: str) -> str:
    """Translate to Polygon's I:-prefixed symbol for cash indexes."""
    if ticker.upper() in _POLYGON_INDEX_SYMBOLS:
        return f"I:{ticker.upper()}"
    return ticker


# ─── PUBLIC API ──────────────────────────────────────────────────────

def compute_setup(ticker: str, mode: str,
                  max_risk_usd: float = 200.0,
                  api_key: Optional[str] = None) -> dict:
    """Compute a front-side trade setup for `ticker` in `mode`.

    Args:
        ticker: SPX / SPY / QQQ / IWM / NDX.
        mode:   "scalp" | "intraday" | "swing"
        max_risk_usd: User's stop_loss_usd setting (from
            user_strategy_settings). Used to size contracts/shares.
        api_key: Polygon (Massive) API key. Falls back to MASSIVE_API_KEY env.

    Returns:
        Setup dict with keys: ticker, mode, direction, skip_reason,
        momentum, trends, trigger_level, underlying_price, vehicle,
        options{...}, shares{...}, warnings, computed_at.
    """
    api_key = api_key or os.environ.get("MASSIVE_API_KEY", "")
    if not api_key:
        return _skip(ticker, mode, "MASSIVE_API_KEY not configured")
    if mode not in MODE_CONFIG:
        return _skip(ticker, mode, f"unknown mode {mode!r}")

    cfg = MODE_CONFIG[mode]

    try:
        from .massive_client import MassiveClient
        massive = MassiveClient(api_key=api_key)
    except Exception as e:
        return _skip(ticker, mode, f"massive client init failed: {e}")

    # 1. Pull bars on all three timeframes.
    # Indexes need the "I:" prefix on Polygon; ETFs/stocks use the
    # bare ticker. _polygon_ticker handles that translation.
    # Monthly bar count = 36 (3 years) so N=15 swing-structure pivot
    # detection has enough data; with 12 bars we'd never find pivots.
    poly_t = _polygon_ticker(ticker)
    try:
        monthly = massive.get_candles(poly_t, "1mo", count=36) or []
        weekly = massive.get_candles(poly_t, "1w", count=104) or []
        daily = massive.get_candles(poly_t, "1d", count=200) or []
    except Exception as e:
        return _skip(ticker, mode, f"bar fetch failed: {e}")

    if len(monthly) < 18 or len(weekly) < 32 or len(daily) < 20:
        return _skip(ticker, mode,
                     f"insufficient bars (m={len(monthly)}, w={len(weekly)}, d={len(daily)})")

    current_price = daily[-1].close
    if current_price <= 0:
        return _skip(ticker, mode, "no current price")

    # 2. Trend assessment on all three timeframes.
    trends, strengths = _trends(monthly, weekly, daily, ticker)

    # 3. Direction + momentum from M+W weighting.
    direction_dir, momentum, skip = _resolve_direction(trends, strengths)
    if skip:
        return _skip(ticker, mode, skip,
                     trends=trends, underlying_price=current_price)

    # 4. Daily counter-move required.
    expected_counter = "DOWN" if direction_dir == "UP" else "UP"
    if trends["daily"] != expected_counter:
        return _skip(ticker, mode,
                     f"daily not counter-moving ({trends['daily']}); no pullback entry yet",
                     trends=trends, underlying_price=current_price)

    # 5. Trigger level from nearest monthly zone.
    trigger_level, level_skip = _pick_trigger_level(
        monthly, current_price, direction_dir
    )
    if level_skip:
        return _skip(ticker, mode, level_skip,
                     trends=trends, underlying_price=current_price)

    # Translate direction to BUY/SELL + spread_type.
    if direction_dir == "UP":
        direction = "BUY"
        spread_type = "call_debit"
    else:
        direction = "SELL"
        spread_type = "put_debit"

    # 6. Options spread spec (default vehicle).
    options_spec, opt_warn = _pick_options_spread(
        api_key, ticker, current_price, cfg, direction, spread_type, max_risk_usd
    )

    # 7. Shares plan (alternative vehicle if user toggles).
    shares_spec = _pick_shares_plan(
        daily, current_price, trigger_level, direction, max_risk_usd
    )

    warnings = []
    if opt_warn:
        warnings.append(opt_warn)

    return {
        "ticker": ticker,
        "mode": mode,
        "direction": direction,
        "skip_reason": None,
        "momentum": momentum,
        "trends": trends,
        "trigger_level": round(trigger_level, 2),
        "underlying_price": round(current_price, 2),
        "vehicle": "options",
        "options": options_spec,
        "shares": shares_spec,
        "warnings": warnings,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── INTERNALS ───────────────────────────────────────────────────────

def _trends(monthly, weekly, daily, ticker: str) -> Tuple[dict, dict]:
    """Trend direction on M / W / D.

    Uses calculate_structure_direction (N=15 Dow-Theory swing pivots)
    for monthly + weekly — same approach the FX H1 Zone Scalp strategy
    uses on its trend TF. Matches the user's trader-intuition of
    "higher highs + higher lows = UP", and avoids ADX's susceptibility
    to single-bar volatility spikes that pull +DI/-DI the wrong way.

    The N=15 detector needs 2N+2 = 32 bars to find the two pivots
    required for an HH-vs-HL comparison. Monthly fetch is bumped to
    36 bars (3 years) to support this; weekly to 104 (2 years).

    Daily counter-move is a different question — "is there a pullback
    RIGHT NOW?" — and a 5-bar swing-structure check isn't meaningful.
    Use a simple last-close vs N-bars-back close-price comparison,
    with a noise threshold of 0.3 × ATR(5) to avoid SIDE-flapping on
    barely-moved bars."""
    from .untouched_levels import calculate_structure_direction

    m_dir, m_str = calculate_structure_direction(monthly, n=15)
    w_dir, w_str = calculate_structure_direction(weekly, n=15)

    d_dir, d_str = _daily_counter_direction(daily)

    return ({"monthly": m_dir, "weekly": w_dir, "daily": d_dir},
            {"monthly": m_str, "weekly": w_str, "daily": d_str})


def _daily_counter_direction(daily) -> Tuple[str, float]:
    """Short-term daily direction for the counter-move check.

    Compares the most recent close to the close DAILY_COUNTER_BARS
    bars ago. Returns "UP", "DOWN", or "SIDE" + a confidence proxy
    (price-change as a fraction of recent ATR, clipped to 0-100).

    The noise threshold (0.3 × ATR-5) prevents the analyzer from
    flapping SIDE↔UP↔DOWN on flat days. If the move is smaller than
    that buffer, we call it SIDE."""
    if len(daily) < DAILY_COUNTER_BARS + 2:
        return "SIDE", 0.0
    recent = daily[-DAILY_COUNTER_BARS - 1:]
    # ATR-5 for noise floor
    atrs = []
    for i in range(1, len(recent)):
        c, p = recent[i], recent[i - 1]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        atrs.append(tr)
    atr = sum(atrs) / len(atrs) if atrs else 0
    noise_floor = atr * 0.3

    change = daily[-1].close - daily[-DAILY_COUNTER_BARS].close
    if abs(change) < noise_floor:
        return "SIDE", 0.0
    strength = min(100.0, abs(change) / max(atr, 1e-9) * 33.0)
    return ("UP" if change > 0 else "DOWN"), strength


def _resolve_direction(trends: dict, strengths: dict):
    """Apply the M+W weighting rule from the user's description.

    Returns (direction_dir, momentum_label, skip_reason).
    direction_dir is "UP" or "DOWN"; momentum is "Strong" or "Weak";
    skip_reason is None on success or a string on skip."""
    m, w = trends["monthly"], trends["weekly"]
    if m == "SIDE" and w == "SIDE":
        return None, None, "both monthly and weekly are sideways; no directional bias"
    if m != "SIDE" and w != "SIDE" and m == w:
        # Both agree
        return m, "Strong", None
    if m != "SIDE" and w == "SIDE":
        return m, "Weak", None
    if w != "SIDE" and m == "SIDE":
        return w, "Weak", None
    # M and W both have direction but disagree — bias to M
    if m != w:
        return m, "Weak", None
    return None, None, "trend resolution failed"


def _pick_trigger_level(monthly_candles, current_price: float,
                        direction_dir: str) -> Tuple[Optional[float], Optional[str]]:
    """Find the nearest untouched monthly level on the side that aligns
    with a front-side entry.

    For UP direction (long setup): nearest DEMAND below current.
    For DOWN direction (short setup): nearest SUPPLY above current.

    Returns (level, None) on success or (None, skip_reason) on skip
    (no level found, or price too far from any level).
    """
    from .untouched_levels import find_untouched_levels
    highs = [c.high for c in monthly_candles[::-1]]  # most recent first
    lows = [c.low for c in monthly_candles[::-1]]
    sup1, sup2, dem1, dem2 = find_untouched_levels(highs, lows, current_price, lookback=12)

    if direction_dir == "UP":
        # Long — want nearest demand BELOW current price
        candidates = [d for d in (dem1, dem2) if d is not None and d < current_price]
        if not candidates:
            return None, "no monthly demand level below current price"
        level = max(candidates)
        proximity = (current_price - level) / current_price
    else:
        # Short — want nearest supply ABOVE current price
        candidates = [s for s in (sup1, sup2) if s is not None and s > current_price]
        if not candidates:
            return None, "no monthly supply level above current price"
        level = min(candidates)
        proximity = (level - current_price) / current_price

    if proximity > TRIGGER_PROXIMITY_PCT:
        return None, (f"price {proximity*100:.1f}% from trigger level; "
                      f"wait for closer approach (threshold {TRIGGER_PROXIMITY_PCT*100:.0f}%)")
    return level, None


def _pick_options_spread(api_key: str, ticker: str, underlying_price: float,
                         cfg: _ModeCfg, direction: str, spread_type: str,
                         max_risk_usd: float) -> Tuple[dict, Optional[str]]:
    """Build the options debit-spread spec via Schwab /chains.

    Schwab is the chosen options-pricing source for the dashboard until
    Tastytrade is funded (per user direction). Schwab returns greeks
    (delta + IV) in the chain response, so we can pick the long leg by
    actual delta rather than OTM-distance heuristics.

    Long leg picked at target delta (TARGET_DELTA = 0.30). Width
    starts at cfg.width_default; falls back to cfg.width_fallback if
    the initial debit/width ratio exceeds DEBIT_RATIO_FALLBACK.

    Returns (spec_dict, warning_or_None). api_key is unused (kept for
    signature compatibility with the prior Polygon path).
    """
    chain, err = _fetch_schwab_chain(ticker, cfg, spread_type)
    if err:
        return _empty_options_spec(cfg, err), err
    if not chain:
        return _empty_options_spec(cfg, "empty chain"), \
               "Schwab returned no options data"

    # Pick the expiration nearest cfg.dte_target from those returned.
    expiries = sorted({c["expiry"] for c in chain})
    today = datetime.now(timezone.utc).date()
    def _dte_of(e):
        try:
            return (datetime.strptime(e, "%Y-%m-%d").date() - today).days
        except Exception:
            return -1
    in_range = [(e, _dte_of(e)) for e in expiries
                if cfg.dte_min <= _dte_of(e) <= cfg.dte_max]
    if in_range:
        expiry = min(in_range, key=lambda ed: abs(ed[1] - cfg.dte_target))[0]
    else:
        # Fall back to the closest expiry overall, even if outside the window.
        expiry = min(((e, _dte_of(e)) for e in expiries),
                     key=lambda ed: abs(ed[1] - cfg.dte_target))[0]

    in_expiry = [c for c in chain if c["expiry"] == expiry]
    if not in_expiry:
        return _empty_options_spec(cfg, f"no contracts at expiry {expiry}"), \
               "Schwab chain missing target expiry"

    # Pick long strike: closest |delta| to TARGET_DELTA. Schwab returns
    # signed delta (positive for calls, negative for puts) — abs() it.
    by_delta = [(c, abs(c["delta"])) for c in in_expiry if c["delta"] != 0]
    if not by_delta:
        # Greeks present but all zero (rare — usually a Schwab data hiccup).
        # Fall back to OTM heuristic so we at least produce a spec.
        if spread_type == "call_debit":
            long_strike = round(underlying_price * 1.005 / 5) * 5
        else:
            long_strike = round(underlying_price * 0.995 / 5) * 5
        warning = "Schwab chain returned zero deltas; used OTM heuristic"
    else:
        best = min(by_delta, key=lambda cd: abs(cd[1] - TARGET_DELTA))
        long_strike = best[0]["strike"]
        warning = None

    # Pick short strike: long ± width on the trend-OTM direction.
    # Call debit: short HIGHER (further OTM up) so short_strike > long_strike.
    # Put  debit: short LOWER  (further OTM down) so short_strike < long_strike.
    def _build(width):
        ss = long_strike + width if spread_type == "call_debit" else long_strike - width
        long_row = next((c for c in in_expiry if c["strike"] == long_strike), None)
        short_row = next((c for c in in_expiry if c["strike"] == ss), None)
        net_debit = None
        if long_row and short_row:
            long_ask = long_row.get("ask", 0)
            short_bid = short_row.get("bid", 0)
            if long_ask > 0 and short_bid > 0:
                net_debit = round(long_ask - short_bid, 2)
        return ss, net_debit, long_row, short_row

    short_strike, net_debit, long_row, short_row = _build(cfg.width_default)
    width = cfg.width_default

    if net_debit and net_debit / cfg.width_default > DEBIT_RATIO_FALLBACK:
        ss2, nd2, lr2, sr2 = _build(cfg.width_fallback)
        if nd2 is not None:
            short_strike, net_debit = ss2, nd2
            long_row, short_row = lr2, sr2
            width = cfg.width_fallback

    max_loss = (net_debit or 0) * 100
    max_profit = ((width - (net_debit or 0)) * 100) if net_debit else None
    contracts = int(max_risk_usd // max_loss) if max_loss > 0 else 0
    contracts_reason = None
    if contracts < 1:
        contracts_reason = (
            f"max_risk ${max_risk_usd:.0f} too small for "
            f"${max_loss:.0f} debit per spread"
            if max_loss > 0 else "net debit unknown — cannot size"
        )

    spec = {
        "expiry": expiry,
        "dte_target": cfg.dte_target,
        "right": "call" if spread_type == "call_debit" else "put",
        "long_strike": float(long_strike),
        "short_strike": float(short_strike),
        "long_delta": long_row.get("delta") if long_row else None,
        "short_delta": short_row.get("delta") if short_row else None,
        "spread_type": spread_type,
        "width_points": width,
        "net_debit_estimate": net_debit,
        "max_loss_per_spread": round(max_loss, 2) if net_debit else None,
        "max_profit_per_spread": round(max_profit, 2) if max_profit is not None else None,
        "contracts": contracts,
        "contracts_reason": contracts_reason,
        # Underlying price at the moment of breakeven at expiry.
        # Call debit: breakeven = long_strike + net_debit
        # Put  debit: breakeven = long_strike - net_debit
        "breakeven": _breakeven(long_strike, net_debit, spread_type),
    }
    return spec, warning


def _fetch_schwab_chain(ticker: str, cfg: _ModeCfg,
                        spread_type: str) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Pull the options chain from Schwab for the ticker + DTE window.

    Returns (chain, error). chain is a flat list of dicts:
        [{expiry, strike, delta, bid, ask, oi, iv}, ...]
    error is None on success or a short string on skip.

    Reuses the SchwabMarketData class that's been on main for months
    (also used by lumisignals/options_analyzer.py at saas/app.py:1050+).
    """
    try:
        from .schwab_client import SchwabAuth, SchwabMarketData
    except Exception as e:
        return None, f"Schwab client import failed: {e}"

    client_id = os.environ.get("SCHWAB_CLIENT_ID", "")
    client_secret = os.environ.get("SCHWAB_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None, "SCHWAB_CLIENT_ID/SECRET not set"

    token_file = os.environ.get("SCHWAB_TOKEN_FILE",
                                 "/opt/lumisignals/schwab_tokens.json")
    auth = SchwabAuth(client_id, client_secret, token_file=token_file)
    if not auth.is_authenticated:
        return None, "Schwab not authenticated — run schwab_auth.py"

    md = SchwabMarketData(auth)
    today = datetime.now(timezone.utc).date()
    from_date = (today + timedelta(days=cfg.dte_min)).strftime("%Y-%m-%d")
    to_date = (today + timedelta(days=cfg.dte_max)).strftime("%Y-%m-%d")

    contract_type = "CALL" if spread_type == "call_debit" else "PUT"

    try:
        resp = md._request("/chains", params={
            "symbol": ticker,
            "contractType": contract_type,
            "strikeCount": 40,
            "range": "ALL",
            "fromDate": from_date,
            "toDate": to_date,
        })
    except Exception as e:
        return None, f"Schwab /chains call failed: {e}"

    if not isinstance(resp, dict):
        return None, "Schwab /chains returned non-dict"

    # Schwab response shape: callExpDateMap (or putExpDateMap) =
    # {"YYYY-MM-DD:DTE": {"strike_str": [{opt_data}]}}
    map_key = "callExpDateMap" if contract_type == "CALL" else "putExpDateMap"
    exp_map = resp.get(map_key) or {}
    flat = []
    for exp_str, strikes in exp_map.items():
        exp_date = exp_str.split(":")[0]
        for strike_str, opt_list in strikes.items():
            opt = opt_list[0] if isinstance(opt_list, list) else opt_list
            try:
                flat.append({
                    "expiry": exp_date,
                    "strike": float(strike_str),
                    "delta": float(opt.get("delta") or 0),
                    "bid": float(opt.get("bid") or 0),
                    "ask": float(opt.get("ask") or 0),
                    "iv": float(opt.get("volatility") or 0),
                    "oi": int(opt.get("openInterest") or 0),
                })
            except (TypeError, ValueError):
                continue
    return flat, None


def _pick_shares_plan(daily_candles, current_price: float,
                      trigger_level: float, direction: str,
                      max_risk_usd: float) -> dict:
    """Compute an alternative ETF-shares plan in case the user toggles
    'Trade as: shares' instead of options.

    Entry: current price (or trigger level on a limit basis).
    Stop:  one ATR beyond the trigger level (counter-trend side).
    Target: next opposite level (placeholder for v1 — uses 2:1 R:R if
            no clear opposite level available).
    Shares: floor(max_risk / abs(entry - stop)).
    """
    # Simple ATR-14 on the daily bars.
    atrs = []
    for i in range(1, min(15, len(daily_candles))):
        c = daily_candles[-i]
        p = daily_candles[-(i + 1)]
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        atrs.append(tr)
    atr = sum(atrs) / len(atrs) if atrs else 0
    stop_buffer = atr  # TUNING: 1x ATR beyond the trigger

    if direction == "BUY":
        entry = current_price
        stop = trigger_level - stop_buffer
        target = entry + 2 * (entry - stop)   # 2:1 R:R placeholder
    else:
        entry = current_price
        stop = trigger_level + stop_buffer
        target = entry - 2 * (stop - entry)

    risk_per_share = abs(entry - stop)
    qty = int(max_risk_usd // risk_per_share) if risk_per_share > 0 else 0
    qty_reason = None if qty >= 1 else (
        f"stop ${risk_per_share:.2f} wide, ${max_risk_usd:.0f} max risk → 0 shares"
    )

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "qty": qty,
        "qty_reason": qty_reason,
        "risk_per_share": round(risk_per_share, 2),
    }


# ─── SMALL HELPERS ───────────────────────────────────────────────────

def _breakeven(long_strike: float, net_debit: Optional[float],
               spread_type: str) -> Optional[float]:
    if net_debit is None:
        return None
    if spread_type == "call_debit":
        return round(long_strike + net_debit, 2)
    return round(long_strike - net_debit, 2)


def _empty_options_spec(cfg: _ModeCfg, reason: str) -> dict:
    return {
        "expiry": None, "dte_target": cfg.dte_target,
        "right": None,
        "long_strike": None, "short_strike": None,
        "spread_type": None, "width_points": cfg.width_default,
        "net_debit_estimate": None,
        "max_loss_per_spread": None,
        "max_profit_per_spread": None,
        "contracts": 0,
        "contracts_reason": reason,
        "breakeven": None,
    }


def _skip(ticker: str, mode: str, reason: str, **extras) -> dict:
    base = {
        "ticker": ticker,
        "mode": mode,
        "direction": None,
        "skip_reason": reason,
        "momentum": None,
        "trends": extras.get("trends"),
        "trigger_level": None,
        "underlying_price": extras.get("underlying_price"),
        "vehicle": None,
        "options": None,
        "shares": None,
        "warnings": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    return base
