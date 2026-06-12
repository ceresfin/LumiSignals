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

from . import mtf_config

logger = logging.getLogger(__name__)


# ─── MODE CONFIG ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class _ModeCfg:
    name: str
    dte_target: int          # ideal days-to-expiration for the option
    dte_min: int             # acceptable range to find a real expiration
    dte_max: int
    width_default: int       # spread-width sanity-clamp ceiling (points)
    width_fallback: int      # wider clamp ceiling for index-priced names
    short_delta: float       # target |delta| for the short leg — sets the
                             # spread WIDTH, so it self-scales with price+IV


MODE_CONFIG = {
    #                          name        tgt min max  wd  wf  shortΔ
    "scalp":    _ModeCfg("scalp",    0,  0,  2,  10, 15, 0.20),
    "intraday": _ModeCfg("intraday", 4,  2,  6,  10, 15, 0.15),
    "swing":    _ModeCfg("swing",    11, 7,  14, 10, 15, 0.12),
}

# Per-mode timeframe stack — sourced from levels_strategy.TARGET_TFS_BY_MODEL.
# Ordered bottom-to-top (shortest first). The pattern across modes is
# uniform "Russian dolls": each mode shows trigger TF + 2 higher TFs.
#   SCALP    → 5m  / 15m / 1h
#   INTRADAY → 15m / 1h  / 4h
#   SWING    → 1d  / 1w  / 1mo
# Direction logic: the top-two TFs are the BIAS (weighted same as
# Monthly+Weekly were for swing); the bottom TF is the COUNTER-MOVE
# trigger ("Daily must pull back" generalizes to "bottom TF must
# counter-move against the bias").
MODE_TFS = {
    "scalp":    ["5m",  "15m", "1h"],
    "intraday": ["15m", "1h",  "4h"],
    "swing":    ["1d",  "1w",  "1mo"],
}

# Bar count per TF — enough for ADX(14) to be stable, with headroom.
# Intraday TFs need more bars (active hours only). Higher TFs need
# fewer total bars but more calendar history.
BAR_COUNT_PER_TF = {
    "5m":  300,   # ~2-3 trading days
    "15m": 200,   # ~6-7 trading days
    "1h":  200,   # ~30 trading days
    "4h":  200,   # ~3 months
    "1d":  200,   # ~10 months
    "1w":  104,   # 2 years
    "1mo": 65,    # ~5 years — covers the HTF_TF_LOOKBACK[M]=60 window
}

# Human-readable labels (matches TF_LABELS in levels_strategy.py).
TF_LABELS = {
    "5m":  "5M",  "15m": "15M", "1h":  "1H", "4h":  "4H",
    "1d":  "Daily", "1w":  "Weekly", "1mo": "Monthly",
}


# ─── TUNING THRESHOLDS ───────────────────────────────────────────────
# All marked TUNING — adjust after seeing live behavior.

TARGET_DELTA = 0.30                # TUNING: long-leg strike delta target
TRIGGER_PROXIMITY_PCT = 0.03       # TUNING: skip if price > 3% from level
# Long leg must be strictly OTM (never buy an ITM debit leg). Short leg is
# picked by cfg.short_delta so width self-scales with price+IV; this caps a
# pathologically wide spread on a stock (fraction of the underlying).
MAX_WIDTH_PCT = 0.10               # TUNING: cap spread width at 10% of price

# Shares-vehicle stop/target tuning (per user spec 2026-06-01):
#   - Entry  = HTF supply/demand level (the bars_top zone)
#   - Stop   = 2 × bottom-TF ATR beyond the entry level
#   - Target = next opposite zone on the same TF as entry; if none,
#              fall back to a per-mode R:R floor.
SHARES_ATR_STOP_MULT = 2.0
SHARES_RR_FLOOR = {"scalp": 1.5, "intraday": 2.0, "swing": 3.0}
DEBIT_RATIO_FALLBACK = 0.30        # TUNING: if net_debit/width > 30%, try wider
ADX_STRONG_TREND_THRESHOLD = 25    # TUNING: ADX >= this on M or W = Strong
DAILY_COUNTER_BARS = 5             # TUNING: look at last 5 daily bars for counter-move

# Polygon serves index data under the "I:" prefix (cash indexes like
# SPX, NDX, RUT, VIX, DJI). Plain SPY/QQQ/IWM (ETFs) use the regular
# ticker. Schwab's /chains endpoint takes the bare underlying symbol
# either way, so this translation only applies to the Polygon bars call.
_POLYGON_INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI", "XSP", "XND"}


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
        ticker: any US equity or ETF (SPY, QQQ, NVDA, TSLA, etc.) or
            cash index (SPX/NDX/RUT/VIX/DJI — Polygon I: prefix is
            applied automatically). Liquid weekly chains recommended.
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
        from .massive_client import get_shared_client
        # Process-wide singleton — the endpoint's zones panel hits the
        # same MassiveClient instance and reuses cached candles. Without
        # this we'd pull each TF from Polygon twice per /api/swing-setup
        # request (once here, once in the zones loop).
        massive = get_shared_client(api_key)
    except Exception as e:
        return _skip(ticker, mode, f"massive client init failed: {e}")

    # 1. Pull bars on the three timeframes for this mode.
    # Each mode has its own TF stack (Russian dolls — see MODE_TFS):
    #   SCALP    → 5m  /15m /1h
    #   INTRADAY → 15m /1h  /1d
    #   SWING    → 1d  /1w  /1mo
    # Ordered bottom-to-top. The top-two are the BIAS (M+W-style
    # weighted direction); the bottom is the COUNTER-MOVE trigger.
    tfs = MODE_TFS[mode]
    tf_bot, tf_mid, tf_top = tfs[0], tfs[1], tfs[2]
    poly_t = _polygon_ticker(ticker)
    try:
        bars_bot = massive.get_candles(poly_t, tf_bot,
                                       count=BAR_COUNT_PER_TF[tf_bot]) or []
        bars_mid = massive.get_candles(poly_t, tf_mid,
                                       count=BAR_COUNT_PER_TF[tf_mid]) or []
        bars_top = massive.get_candles(poly_t, tf_top,
                                       count=BAR_COUNT_PER_TF[tf_top]) or []
    except Exception as e:
        return _skip(ticker, mode, f"bar fetch failed: {e}")

    # Each TF needs at least enough bars for ADX(14) to be stable
    # (we use 30 as a safe floor — 14 warmup + 14 smoothing + slack).
    min_bars = 30
    if len(bars_bot) < min_bars or len(bars_mid) < min_bars or len(bars_top) < min_bars:
        return _skip(
            ticker, mode,
            f"insufficient bars ({tf_bot}={len(bars_bot)}, "
            f"{tf_mid}={len(bars_mid)}, {tf_top}={len(bars_top)})"
        )

    current_price = bars_bot[-1].close
    if current_price <= 0:
        return _skip(ticker, mode, "no current price")

    # 2. Trend assessment on all three timeframes via Pine ADX.
    trends, strengths = _trends_by_tf(bars_top, bars_mid, bars_bot,
                                       tf_top, tf_mid, tf_bot)

    # 3. Direction + momentum from top+mid weighting (the BIAS pair).
    direction_dir, momentum, skip = _resolve_bias_direction(
        trends[tf_top], trends[tf_mid]
    )
    if skip:
        return _skip(ticker, mode, skip,
                     trends=trends, underlying_price=current_price)

    # 4. Bottom TF counter-move check. When the bottom TF agrees with
    # the bias (no pullback yet), the trade is NOT tradeable but we
    # still want to show what the prospective setup looks like — the
    # user is watching the entry zone develop. Set a flag and continue;
    # the panel disables Open Trade based on `tradeable`.
    expected_counter = "DOWN" if direction_dir == "UP" else "UP"
    prospective_reason = None
    if trends[tf_bot] != expected_counter:
        prospective_reason = (
            f"{TF_LABELS.get(tf_bot, tf_bot)} not counter-moving "
            f"({trends[tf_bot]}); no pullback entry yet"
        )

    # 5. Trigger level from nearest untouched zone on the TOP TF
    # (the highest-TF level price is approaching). Proximity is checked
    # below — if level is far (> threshold), we still surface it for
    # prospective view but flag tradeable=False.
    # Deep per-TF lookback for the top TF so the trigger level matches
    # the Pine/TV levels (find_htf_levels). HTF_TF_LOOKBACK keys on both
    # interval ("1mo") and label ("M") forms.
    from .untouched_levels import HTF_TF_LOOKBACK
    top_lookback = HTF_TF_LOOKBACK.get(tf_top, 100)
    trigger_level, level_skip = _pick_trigger_level(
        bars_top, current_price, direction_dir, lookback=top_lookback
    )
    if level_skip and trigger_level is None:
        # Genuine no-level case (no zones found at all). Skip cleanly.
        return _skip(ticker, mode, level_skip,
                     trends=trends, underlying_price=current_price)

    # Proximity gate: if price is far from the entry zone, the trade
    # isn't tradeable now (limit at the zone wouldn't fill) — but we
    # still surface the level for prospective view. Distance is measured
    # in bottom-TF ATRs (5m scalp / 15m intraday / daily swing) so it
    # adapts to each symbol's volatility instead of a flat percentage.
    # Threshold is Settings-tunable (mtf_config.proximity_atr_mult).
    mtf_cfg = mtf_config.get_config()
    atr_bot = _atr14(bars_bot)
    bot_label = TF_LABELS.get(tf_bot, tf_bot)
    prox_mult = mtf_config.proximity_mult(mode, mtf_cfg)
    prox_dist = abs(current_price - trigger_level)
    prox_threshold = prox_mult * atr_bot

    # Swing only (for now): also watch 15m candles for a wick that pierced the
    # monthly zone and bounced back out the same session. The daily/weekly
    # close — and thus current_price — can miss that, so we'd skip a setup that
    # actually traded into the zone. A fresh 15m touch makes it actionable even
    # when price has left the zone.
    zone_watch = None
    if mode == "swing" and atr_bot > 0:
        _side = "BUY" if direction_dir == "UP" else "SELL"
        zone_watch = _zone_touch_15m(massive, poly_t, trigger_level,
                                     prox_threshold, _side,
                                     fresh_n=mtf_config.zone_fresh_15m(mtf_cfg))
    wick_triggered = bool(zone_watch and (zone_watch["in_zone_now"]
                                          or zone_watch["triggered"]))

    if (atr_bot > 0 and prox_dist > prox_threshold
            and not wick_triggered and prospective_reason is None):
        prospective_reason = (
            f"price {prox_dist / atr_bot:.1f}× {bot_label} ATR from trigger "
            f"level; wait for closer approach (threshold {prox_mult:.1f}× ATR)"
        )

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
    #   - Entry = trigger_level (the bars_top supply/demand zone)
    #   - Stop  = 3 × ATR(bars_bot) beyond the entry
    #   - Target = next opposite zone on bars_top, else per-mode R:R floor
    shares_spec = _pick_shares_plan(
        bars_bot, bars_top, current_price, trigger_level,
        direction, max_risk_usd, mode, lookback=top_lookback,
        stop_mult=mtf_config.stop_mult(mode, mtf_cfg),
        rr=mtf_config.rr_floor(mode, mtf_cfg),
    )
    # Attach the bottom-TF label so the panel can render "4.5× ATR(5M)"
    # under the Stop Loss row.
    shares_spec["atr_tf"] = TF_LABELS.get(tf_bot, tf_bot)

    warnings = []
    if opt_warn:
        warnings.append(opt_warn)

    # Stash the zones computed inside _pick_trigger_level so the
    # endpoint can merge them into zones_by_tf for the panel. Without
    # this the panel re-fetches bars and the trigger_level + panel D2
    # can disagree (observed 2026-06-02 for SCALP on SPY).
    top_zones = getattr(_pick_trigger_level, "last_zones", None) or {}

    return {
        "ticker": ticker,
        "mode": mode,
        "direction": direction,
        "skip_reason": prospective_reason,   # populated when counter-move pending
        "tradeable": prospective_reason is None,
        "momentum": momentum,
        "trends": trends,
        "trigger_level": round(trigger_level, 2),
        "underlying_price": round(current_price, 2),
        # 15m wick-into-zone watch (swing only for now); None otherwise.
        "zone_watch": zone_watch,
        "vehicle": "options",
        "options": options_spec,
        "shares": shares_spec,
        "warnings": warnings,
        # Used by the endpoint to align the top-TF row in zones_by_tf
        # with the chart's trigger_level — same call, same bars.
        "top_tf_key": tf_top,
        "top_zones": top_zones,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── INTERNALS ───────────────────────────────────────────────────────

def _trends_by_tf(bars_top, bars_mid, bars_bot,
                  tf_top: str, tf_mid: str, tf_bot: str) -> Tuple[dict, dict]:
    """Pine ADX direction on each of the mode's three timeframes.
    Returns trends + ADX strength values, both keyed by TF identifier
    (e.g. "1mo", "1w", "1d" for swing; "5m", "15m", "1h" for scalp).

    Pine ADX (ta.dmi(14, 14)) for all three TFs — same engine the
    user's TradingView dashboard uses. The COUNTER-MOVE check on the
    bottom TF intentionally uses Pine ADX here too (vs the older
    "5-bar close-change" approach) so the trend reads are consistent
    across all three timeframes."""
    top_dir, top_adx = _pine_adx_direction(bars_top, period=14)
    mid_dir, mid_adx = _pine_adx_direction(bars_mid, period=14)
    bot_dir, bot_adx = _pine_adx_direction(bars_bot, period=14)
    trends = {tf_top: top_dir, tf_mid: mid_dir, tf_bot: bot_dir}
    strengths = {tf_top: top_adx, tf_mid: mid_adx, tf_bot: bot_adx}
    return trends, strengths


def _resolve_bias_direction(top_dir: str, mid_dir: str):
    """Apply the M+W weighting rule, generalized to "top+mid" so it
    works for any mode.

    Returns (direction_dir, momentum_label, skip_reason).
      Both agree (non-SIDE) → Strong
      One SIDE, other has dir → Weak (other carries)
      Both have dir but disagree → bias to top, Weak
      Both SIDE → skip
    """
    if top_dir == "SIDE" and mid_dir == "SIDE":
        return None, None, "both higher timeframes are sideways; no directional bias"
    if top_dir != "SIDE" and mid_dir != "SIDE" and top_dir == mid_dir:
        return top_dir, "Strong", None
    if top_dir != "SIDE" and mid_dir == "SIDE":
        return top_dir, "Weak", None
    if mid_dir != "SIDE" and top_dir == "SIDE":
        return mid_dir, "Weak", None
    # Both have direction but disagree — top wins
    return top_dir, "Weak", None


def _pine_adx_dmi(candles, period: int = 14) -> Tuple[float, float, float]:
    """Compute (+DI, -DI, ADX) the same way Pine's ta.dmi(period, period)
    does. All three values are 0-100.

    Formula (per TradingView reference):
      TR    = max(high-low, |high-prev_close|, |low-prev_close|)
      +DM   = high - prev_high   IF (high-prev_high) > (prev_low-low) AND > 0
              else 0
      -DM   = prev_low - low     IF (prev_low-low) > (high-prev_high) AND > 0
              else 0

      Wilder RMA (period=N):
        initial = mean of first N values
        next    = (prev * (N-1) + current) / N

      +DI = 100 * rma(+DM, N) / rma(TR, N)
      -DI = 100 * rma(-DM, N) / rma(TR, N)
      DX  = 100 * |+DI - -DI| / (+DI + -DI)
      ADX = rma(DX, N)
    """
    n = period
    if len(candles) < 2 * n + 1:
        return 0.0, 0.0, 0.0

    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i].high, candles[i].low
        ph, pl, pc = candles[i - 1].high, candles[i - 1].low, candles[i - 1].close
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up_move, down_move = h - ph, pl - l
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    def _rma(values, n):
        """Wilder RMA: initial = simple mean of first N, then
        next = (prev*(N-1) + current) / N. Returns full series."""
        if len(values) < n:
            return []
        first = sum(values[:n]) / n
        out = [first]
        for v in values[n:]:
            out.append((out[-1] * (n - 1) + v) / n)
        return out

    atr = _rma(tr_list, n)
    plus_dm_s = _rma(plus_dm_list, n)
    minus_dm_s = _rma(minus_dm_list, n)
    if not atr or atr[-1] == 0:
        return 0.0, 0.0, 0.0

    plus_di_series = [100 * pdm / a if a > 0 else 0
                      for pdm, a in zip(plus_dm_s, atr)]
    minus_di_series = [100 * mdm / a if a > 0 else 0
                       for mdm, a in zip(minus_dm_s, atr)]

    dx_series = []
    for pdi, mdi in zip(plus_di_series, minus_di_series):
        denom = pdi + mdi
        if denom > 0:
            dx_series.append(100 * abs(pdi - mdi) / denom)
        else:
            dx_series.append(0.0)

    adx_series = _rma(dx_series, n)
    adx_val = adx_series[-1] if adx_series else 0.0
    return plus_di_series[-1], minus_di_series[-1], adx_val


def _pine_adx_direction(candles, period: int = 14,
                        buffer: float = 2.0) -> Tuple[str, float]:
    """Pine adx_dashboard.pine direction logic. Returns (direction, adx).

    direction = UP   if +DI > -DI + buffer
              = DOWN if +DI < -DI - buffer
              = SIDE otherwise
    adx       = 0-100 ADX value (drives the momentum label downstream)
    """
    plus_di, minus_di, adx = _pine_adx_dmi(candles, period=period)
    if plus_di > minus_di + buffer:
        return "UP", round(adx, 2)
    if plus_di < minus_di - buffer:
        return "DOWN", round(adx, 2)
    return "SIDE", round(adx, 2)


def adx_momentum_label(adx_value: float) -> str:
    """Pine adx_dashboard.pine momentum label by ADX strength."""
    if adx_value >= 50: return "Unusually Very Strong"
    if adx_value >= 30: return "Very Strong"
    if adx_value >= 25: return "Strong"
    if adx_value >= 20: return "Moderate"
    if adx_value >= 15: return "Weak"
    if adx_value >= 10: return "Very Weak"
    return "No to Very Weak"


def _pick_trigger_level(monthly_candles, current_price: float,
                        direction_dir: str,
                        lookback: int = 100) -> Tuple[Optional[float], Optional[str]]:
    """Find the nearest untouched monthly level on the side that aligns
    with a front-side entry.

    For UP direction (long setup): nearest DEMAND below current.
    For DOWN direction (short setup): nearest SUPPLY above current.

    Returns (level, None) on success or (None, skip_reason) on skip
    (no level found, or price too far from any level).
    """
    from .untouched_levels import find_htf_levels
    highs = [c.high for c in monthly_candles[::-1]]  # most recent first
    lows = [c.low for c in monthly_candles[::-1]]
    # Pine-matching level finder (find_htf_levels): supply must be above
    # close, no supply fallback, demand falls back to the current low.
    # Deep per-TF lookback so the MTF trigger level matches what the
    # Pine script draws on TradingView.
    sup1, sup2, dem1, dem2 = find_htf_levels(highs, lows, current_price, lookback=lookback)
    # Stash the full zone set on a function attribute so the caller can
    # reuse it for the zones-panel data — guarantees the chart's
    # trigger_level and the panel's D1/D2/S1/S2 come from the exact
    # same find_htf_levels call on the exact same bars.
    _pick_trigger_level.last_zones = {
        "supply": sup1, "supply2": sup2,
        "demand": dem1, "demand2": dem2,
    }

    # D1/S1 from find_step_levels are the most recent untouched
    # low/high going back from the in-progress bar. Level may sit above
    # OR below current_price (e.g. monthly D1 well below price during an
    # uptrend; hourly D1 can be slightly above when a wick has just
    # broken through) — caller decides whether to take the trade.
    if direction_dir == "UP":
        if dem1 is None:
            return None, "no untouched demand in lookback window"
        level = dem1
    else:
        if sup1 is None:
            return None, "no untouched supply in lookback window"
        level = sup1
    proximity = abs(current_price - level) / current_price

    # Note: previously this hard-skipped when proximity > 3%. For the
    # dashboard's prospective view we want to SHOW the level even when
    # it's far away (the user is watching the zone develop). The
    # tradeable flag is now toggled at the call site based on
    # proximity, but the level itself is always returned.
    return level, None


def _strike_increment(strikes) -> Optional[float]:
    """Median gap between adjacent strikes in a chain (5.0 for SPX, 0.5/1.0
    for cheaper names). Lets width/rounding scale per underlying instead of
    assuming SPX's 5-point grid. None if undeterminable."""
    uniq = sorted({s for s in strikes if s is not None})
    if len(uniq) < 2:
        return None
    diffs = sorted(round(b - a, 4) for a, b in zip(uniq, uniq[1:]) if b > a)
    return diffs[len(diffs) // 2] if diffs else None


def _chain_source() -> str:
    """Which options-chain feed to use: 'ib' (default) or 'schwab'. Runtime
    override via Redis key `options:chain_source`, else env
    OPTIONS_CHAIN_SOURCE, else 'ib'. (Mirrors the equity:orders_enabled
    Redis-flag pattern.)"""
    try:
        import redis as _redis
        rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        v = rdb.get("options:chain_source")
        if v:
            v = (v.decode() if isinstance(v, bytes) else str(v)).strip().lower()
            if v in ("ib", "schwab"):
                return v
    except Exception:
        pass
    return os.environ.get("OPTIONS_CHAIN_SOURCE", "ib").strip().lower()


def _call_chain_source(src, ticker, cfg, spread_type, underlying_price):
    """Fetch from one source. IB is sourced from the same IBeam gateway used
    for orders; Schwab is the legacy /chains path (kept intact)."""
    if src == "ib":
        try:
            from .ib_options_chain import fetch_ib_chain
            return fetch_ib_chain(ticker, cfg, spread_type, underlying_price)
        except Exception as e:
            return None, f"IB chain error: {e}"
    return _fetch_schwab_chain(ticker, cfg, spread_type)


def _fetch_chain(ticker, cfg, spread_type, underlying_price):
    """Source dispatcher with visible auto-fallback. Tries the selected
    source first; on error/empty falls back to the other and flags it.
    Returns (chain, error, used_source, fallback_warning)."""
    primary = _chain_source() if _chain_source() in ("ib", "schwab") else "ib"
    order = ["ib", "schwab"] if primary == "ib" else ["schwab", "ib"]
    last_err = None
    for i, src in enumerate(order):
        chain, err = _call_chain_source(src, ticker, cfg, spread_type, underlying_price)
        if chain and not err:
            fb = f"options chain via {src} (fallback from {order[0]})" if i else None
            return chain, None, src, fb
        last_err = err or f"{src} returned no options data"
    return None, last_err, primary, None


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
    chain, err, chain_source, fb_warn = _fetch_chain(
        ticker, cfg, spread_type, underlying_price)
    if err:
        return _empty_options_spec(cfg, err), err
    if not chain:
        return _empty_options_spec(cfg, "empty chain"), "no options data"

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

    is_call = spread_type == "call_debit"
    inc = _strike_increment([c["strike"] for c in in_expiry]) or 5.0

    def _is_otm(strike):
        # Long debit leg must be OUT of the money — never buy an ITM debit
        # (a 30Δ option is normally OTM; enforce it so a skewed chain can't
        # hand us an ITM long that exercises into stock at expiry).
        return strike > underlying_price if is_call else strike < underlying_price

    otm = [c for c in in_expiry if _is_otm(c["strike"])]

    # Long strike: OTM strike whose |delta| is closest to TARGET_DELTA.
    # Schwab returns signed delta (positive calls, negative puts) — abs() it.
    long_by_delta = [(c, abs(c["delta"])) for c in otm if c.get("delta")]
    if long_by_delta:
        long_strike = min(long_by_delta, key=lambda cd: abs(cd[1] - TARGET_DELTA))[0]["strike"]
        warning = None
    else:
        # No OTM greeks — side-correct OTM heuristic at the real increment.
        raw = underlying_price * (1.005 if is_call else 0.995)
        long_strike = round(raw / inc) * inc
        if is_call and long_strike <= underlying_price:
            long_strike += inc
        elif not is_call and long_strike >= underlying_price:
            long_strike -= inc
        warning = "Schwab chain returned zero deltas; used OTM heuristic"

    # Short strike: picked by cfg.short_delta so the WIDTH self-scales with
    # price + IV (small $ for cheap names, tens of points for SPX). Capped at
    # a fraction of the underlying so a thin chain can't produce a
    # pathologically wide spread (floor of 2 strike increments).
    max_width = max(inc * 2, MAX_WIDTH_PCT * underlying_price)

    def _further_otm(strike):
        return strike > long_strike if is_call else strike < long_strike

    def _pick_short(target_delta):
        cands = [c for c in otm if _further_otm(c["strike"])
                 and abs(c["strike"] - long_strike) <= max_width]
        with_d = [(c, abs(c["delta"])) for c in cands if c.get("delta")]
        if with_d:
            return min(with_d, key=lambda cd: abs(cd[1] - target_delta))[0]["strike"]
        if cands:   # no greeks — nearest valid strike beyond the long
            return min(cands, key=lambda c: abs(c["strike"] - long_strike))["strike"]
        return long_strike + inc if is_call else long_strike - inc

    def _build(short_strike):
        long_row = next((c for c in in_expiry if c["strike"] == long_strike), None)
        short_row = next((c for c in in_expiry if c["strike"] == short_strike), None)
        net_debit = None
        if long_row and short_row:
            long_ask = long_row.get("ask", 0)
            short_bid = short_row.get("bid", 0)
            if long_ask > 0 and short_bid > 0:
                net_debit = round(long_ask - short_bid, 2)
        return net_debit, long_row, short_row

    short_strike = _pick_short(cfg.short_delta)
    net_debit, long_row, short_row = _build(short_strike)
    width = abs(short_strike - long_strike)

    # Quality gate: if the debit eats > DEBIT_RATIO_FALLBACK of the width
    # (poor R:R), step the short one notch further OTM (lower delta) once.
    if net_debit and width and net_debit / width > DEBIT_RATIO_FALLBACK:
        ss2 = _pick_short(max(0.05, cfg.short_delta - 0.05))
        nd2, lr2, sr2 = _build(ss2)
        if nd2 is not None and ss2 != long_strike:
            short_strike, net_debit, long_row, short_row = ss2, nd2, lr2, sr2
            width = abs(short_strike - long_strike)
    if net_debit and width and net_debit / width > DEBIT_RATIO_FALLBACK:
        _rw = f"debit/width {net_debit / width:.0%} > {DEBIT_RATIO_FALLBACK:.0%}"
        warning = (warning + "; " + _rw) if warning else _rw

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
        # Which feed sourced this chain ("ib" / "schwab") — visible so a
        # fallback is never silent.
        "chain_source": chain_source,
        # Underlying price at the moment of breakeven at expiry.
        # Call debit: breakeven = long_strike + net_debit
        # Put  debit: breakeven = long_strike - net_debit
        "breakeven": _breakeven(long_strike, net_debit, spread_type),
    }
    # Surface a fallback ("used Schwab because IB failed") in the warning.
    if fb_warn:
        warning = f"{fb_warn}; {warning}" if warning else fb_warn
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


def _atr14(bars) -> float:
    """Simple 14-period ATR (mean of the last 14 true ranges) on `bars`.
    Used for both the shares stop and the entry proximity gate so they
    share one volatility measure for the bottom timeframe."""
    trs = []
    for i in range(1, min(15, len(bars))):
        c = bars[-i]
        p = bars[-(i + 1)]
        trs.append(max(c.high - c.low, abs(c.high - p.close),
                       abs(c.low - p.close)))
    return sum(trs) / len(trs) if trs else 0.0


# Default trailing 15m candles that count as a "fresh" touch (the setup just
# triggered) vs merely "touched in the window". ~1 RTH session. Settings-
# tunable via mtf_config.zone_fresh_15m.
_ZONE_FRESH_15M = 26


def _zone_touch_15m(massive, poly_t: str, level: float, half_width: float,
                    side: str, count: int = 300, fresh_n: int = _ZONE_FRESH_15M):
    """Scan recent 15m candles for a wick that pierced the entry zone band
    [level ± half_width]. The daily/weekly close can miss a fast wick-and-
    bounce, so we watch the finer TF: a 15m high/low inside the band is a
    touch even if price has since left the zone.

    side "BUY" → demand zone below, the LOW is the relevant wick; "SELL" →
    supply zone above, the HIGH. Returns a dict (or None if no 15m data).
    """
    try:
        candles = massive.get_candles(poly_t, "15m", count=count) or []
    except Exception as e:
        logger.debug("zone_touch 15m fetch failed for %s: %s", poly_t, e)
        return None
    if not candles:
        return None
    zlo, zhi = level - half_width, level + half_width
    # Directional touch: a demand zone (BUY) is pierced by the candle's LOW
    # reaching down into the band; a supply zone (SELL) by the HIGH poking up
    # into it. (A bare range-overlap would over-count — e.g. a high near a
    # demand level isn't a touch.)
    if side == "BUY":
        hits = [i for i, c in enumerate(candles) if zlo <= c.low <= zhi]
    else:
        hits = [i for i, c in enumerate(candles) if zlo <= c.high <= zhi]
    n = len(candles)
    last_i = hits[-1] if hits else None
    last_c = candles[last_i] if last_i is not None else None
    extreme = last_at = None
    if last_c is not None:
        extreme = last_c.low if side == "BUY" else last_c.high
        try:
            from datetime import datetime as _dt, timezone as _tz
            last_at = _dt.fromtimestamp(float(last_c.timestamp), _tz.utc).isoformat()
        except Exception:
            last_at = None
    return {
        "tf": "15m",
        "zone_low": round(zlo, 2),
        "zone_high": round(zhi, 2),
        "in_zone_now": bool(last_i is not None and last_i == n - 1),
        "touched": bool(hits),
        # Fresh = wicked in within the last fresh_n candles → "just triggered".
        "triggered": bool(last_i is not None and last_i >= n - fresh_n),
        "touch_count": len(hits),
        "last_touch_at": last_at,
        "last_touch_extreme": round(extreme, 2) if extreme is not None else None,
        "candles_scanned": n,
    }


def _pick_shares_plan(atr_bars, top_bars, current_price: float,
                      trigger_level: float, direction: str,
                      max_risk_usd: float, mode: str,
                      lookback: int = 100,
                      stop_mult: Optional[float] = None,
                      rr: Optional[float] = None) -> dict:
    """Compute the shares-vehicle plan.

    Spec (per user 2026-06-01):
      Entry  = trigger_level (the HTF supply/demand zone for the mode:
               hourly for scalp, daily for intraday, monthly for swing).
               Placed as a limit — the trade only fills if price pulls
               back into the level.
      Stop   = entry ± 3 × ATR(atr_bars), where atr_bars is the bottom
               TF: 5m for scalp, 15m for intraday, 1d for swing.
      Target = next OPPOSITE untouched zone on the same TF as the entry
               (top_bars). If none found, fall back to per-mode R:R
               floor (SHARES_RR_FLOOR).
      Shares = floor(max_risk_usd / risk_per_share).

    Args:
      atr_bars:     bottom-TF candles (drives stop width)
      top_bars:     entry-TF candles (drives target — same TF that
                    produced trigger_level)
      current_price: live price (for sanity / display only — entry
                    itself sits at trigger_level)
      trigger_level: the entry-side HTF zone
      direction:    "BUY" (long at demand) or "SELL" (short at supply)
      max_risk_usd: user cap from the panel input
      mode:         "scalp" | "intraday" | "swing" — selects R:R floor
    """
    # ATR-14 on the bottom-TF bars. Stop multiplier is Settings-tunable
    # (mtf_config.stop_atr_mult); falls back to the code default.
    if stop_mult is None:
        stop_mult = SHARES_ATR_STOP_MULT
    atr = _atr14(atr_bars)
    stop_buffer = stop_mult * atr

    entry = trigger_level
    if direction == "BUY":
        stop = entry - stop_buffer
    else:
        stop = entry + stop_buffer

    # Target: next opposite zone on the same TF as the entry.
    target = None
    target_source = None
    try:
        from .untouched_levels import find_htf_levels
        highs = [c.high for c in top_bars[::-1]]
        lows  = [c.low  for c in top_bars[::-1]]
        sup1, sup2, dem1, dem2 = find_htf_levels(
            highs, lows, current_price, lookback=lookback)
        if direction == "BUY":
            # Long at demand → target = nearest supply ABOVE entry
            candidates = [s for s in (sup1, sup2) if s is not None and s > entry]
            if candidates:
                target = min(candidates)
                target_source = "opposite_zone"
        else:
            # Short at supply → target = nearest demand BELOW entry
            candidates = [d for d in (dem1, dem2) if d is not None and d < entry]
            if candidates:
                target = max(candidates)
                target_source = "opposite_zone"
    except Exception:
        pass

    risk_per_share = abs(entry - stop)
    if target is None:
        # Fallback: per-mode R:R floor (no opposite zone visible).
        # Settings-tunable via mtf_config.rr_floor_<mode>.
        if rr is None:
            rr = SHARES_RR_FLOOR.get(mode, 2.0)
        if direction == "BUY":
            target = entry + rr * risk_per_share
        else:
            target = entry - rr * risk_per_share
        target_source = f"rr_floor_{rr}x"

    reward_per_share = abs(target - entry)
    rr_ratio = (reward_per_share / risk_per_share) if risk_per_share > 0 else None

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
        "reward_per_share": round(reward_per_share, 2),
        "rr_ratio": round(rr_ratio, 2) if rr_ratio else None,
        "target_source": target_source,
        "atr": round(atr, 4),
        "atr_multiplier": stop_mult,
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
        "tradeable": False,
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
