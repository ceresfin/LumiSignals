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
    try:
        monthly = massive.get_candles(ticker, "1mo", count=12) or []
        weekly = massive.get_candles(ticker, "1w", count=52) or []
        daily = massive.get_candles(ticker, "1d", count=200) or []
    except Exception as e:
        return _skip(ticker, mode, f"bar fetch failed: {e}")

    if len(monthly) < 6 or len(weekly) < 8 or len(daily) < 20:
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
    """Run calculate_trend_direction on each timeframe.
    Daily is only the recent slice (last DAILY_COUNTER_BARS bars) so
    we're measuring the current pullback/rally, not the multi-month
    direction."""
    from .untouched_levels import calculate_trend_direction
    m_dir, m_str = calculate_trend_direction(monthly, ticker)
    w_dir, w_str = calculate_trend_direction(weekly, ticker)
    d_dir, d_str = calculate_trend_direction(daily[-DAILY_COUNTER_BARS:], ticker)
    return ({"monthly": m_dir, "weekly": w_dir, "daily": d_dir},
            {"monthly": m_str, "weekly": w_str, "daily": d_str})


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
    """Build the options debit-spread spec.

    Long leg picked at target delta (TARGET_DELTA = 0.30). Width
    starts at cfg.width_default; falls back to cfg.width_fallback if
    the initial debit/width ratio exceeds DEBIT_RATIO_FALLBACK.

    Returns (spec_dict, warning_or_None).
    """
    from .polygon_options import PolygonOptionsClient
    pc = PolygonOptionsClient(api_key=api_key)

    # Fetch chain for ticker in the mode's DTE window.
    today = datetime.now(timezone.utc).date()
    exp_gte = (today + timedelta(days=cfg.dte_min)).strftime("%Y-%m-%d")
    exp_lte = (today + timedelta(days=cfg.dte_max)).strftime("%Y-%m-%d")

    right = "call" if spread_type == "call_debit" else "put"

    try:
        snaps = pc.get_option_snapshots(ticker, exp_gte=exp_gte, exp_lte=exp_lte) or []
    except Exception as e:
        return _empty_options_spec(cfg, f"options chain fetch failed: {e}"), \
               "options chain unavailable"

    # Filter by right + reasonable proximity to current price (within 10%)
    candidates = [s for s in snaps
                  if (s.get("contract_type") or s.get("right") or "").lower().startswith(right[0])
                  and abs((s.get("strike") or 0) - underlying_price) / underlying_price < 0.10]
    if not candidates:
        return _empty_options_spec(cfg, "no chain candidates"), \
               f"no {right} strikes within 10% of price"

    # Pick long-leg strike: closest to TARGET_DELTA. Snapshot delta
    # may live under different keys depending on Polygon plan; try a
    # few common locations.
    def _delta_of(snap):
        for path in (("greeks", "delta"), ("delta",), ("details", "delta")):
            v = snap
            for k in path:
                if isinstance(v, dict):
                    v = v.get(k)
                else:
                    v = None
                    break
            if isinstance(v, (int, float)):
                return abs(v)
        return None

    with_delta = [(s, _delta_of(s)) for s in candidates]
    with_delta = [(s, d) for s, d in with_delta if d is not None]
    if not with_delta:
        # Fall back to OTM-by-strike-distance heuristic.
        # For calls: long_strike = round(underlying * 1.005 / 5) * 5 (~0.5% OTM, 5-pt grid).
        # For puts: long_strike = round(underlying * 0.995 / 5) * 5.
        # (Refinement opportunity later — pull greeks from Schwab once cherry-picked.)
        if right == "call":
            long_strike = round(underlying_price * 1.005 / 5) * 5
        else:
            long_strike = round(underlying_price * 0.995 / 5) * 5
        warning = "delta unavailable on chain; used OTM heuristic for long strike"
    else:
        # Sort by closeness to TARGET_DELTA and pick the best.
        best = min(with_delta, key=lambda sd: abs(sd[1] - TARGET_DELTA))
        long_strike = float(best[0].get("strike"))
        warning = None

    # Pick short-leg strike: long ± width on the trend direction.
    # Call debit: short higher (further OTM) so short_strike > long_strike.
    # Put debit: short lower (further OTM) so short_strike < long_strike.
    def _build(width):
        ss = long_strike + width if spread_type == "call_debit" else long_strike - width
        # Find the actual snapshot for short_strike to get a debit estimate
        short_snap = next((s for s in candidates if float(s.get("strike") or 0) == ss), None)
        long_snap = next((s for s in candidates if float(s.get("strike") or 0) == long_strike), None)
        net_debit = None
        if long_snap and short_snap:
            long_ask = _quote_ask(long_snap)
            short_bid = _quote_bid(short_snap)
            if long_ask and short_bid:
                net_debit = round(long_ask - short_bid, 2)
        return ss, net_debit

    short_strike, net_debit = _build(cfg.width_default)
    width = cfg.width_default

    if net_debit and net_debit / cfg.width_default > DEBIT_RATIO_FALLBACK:
        ss2, nd2 = _build(cfg.width_fallback)
        if nd2 is not None:
            short_strike, net_debit, width = ss2, nd2, cfg.width_fallback

    # Pick expiry (first available in window, closest to dte_target).
    expiry = _pick_nearest_expiry(snaps, cfg)

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
        "right": right,
        "long_strike": float(long_strike),
        "short_strike": float(short_strike),
        "spread_type": spread_type,
        "width_points": width,
        "net_debit_estimate": net_debit,
        "max_loss_per_spread": round(max_loss, 2) if net_debit else None,
        "max_profit_per_spread": round(max_profit, 2) if max_profit is not None else None,
        "contracts": contracts,
        "contracts_reason": contracts_reason,
        # Underlying price at the moment of breakeven at expiry.
        # For call debit:  breakeven = long_strike + net_debit
        # For put debit:   breakeven = long_strike - net_debit
        "breakeven": _breakeven(long_strike, net_debit, spread_type),
    }
    return spec, warning


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

def _quote_bid(snap) -> Optional[float]:
    for path in (("last_quote", "bid"), ("bid",), ("details", "bid")):
        v = snap
        for k in path:
            if isinstance(v, dict):
                v = v.get(k)
            else:
                v = None; break
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _quote_ask(snap) -> Optional[float]:
    for path in (("last_quote", "ask"), ("ask",), ("details", "ask")):
        v = snap
        for k in path:
            if isinstance(v, dict):
                v = v.get(k)
            else:
                v = None; break
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _pick_nearest_expiry(snaps, cfg: _ModeCfg) -> Optional[str]:
    exps = set()
    for s in snaps:
        e = (s.get("details") or {}).get("expiration_date") or s.get("expiration_date")
        if e:
            exps.add(e)
    if not exps:
        return None
    today = datetime.now(timezone.utc).date()
    def _dte(e):
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            return (d - today).days
        except Exception:
            return -1
    valid = [(e, _dte(e)) for e in exps]
    in_range = [(e, d) for e, d in valid if cfg.dte_min <= d <= cfg.dte_max]
    if in_range:
        # Closest to target
        return min(in_range, key=lambda ed: abs(ed[1] - cfg.dte_target))[0]
    # Fall back to closest overall
    return min(valid, key=lambda ed: abs(ed[1] - cfg.dte_target))[0] if valid else None


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
