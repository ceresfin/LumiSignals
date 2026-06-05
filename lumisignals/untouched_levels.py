"""Untouched Supply/Demand Level Calculator.

Replicates the TradingView HTF Strategy Scanner's findAll() logic in Python,
using Polygon candle data via MassiveClient. Finds S1/S2 (supply) and D1/D2
(demand) untouched levels for each timeframe.

An untouched high (supply) = a period's high that no subsequent period exceeded.
An untouched low (demand) = a period's low that no subsequent period breached.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Timeframes to scan, ordered highest to lowest
TIMEFRAMES = ["1mo", "1w", "1d", "4h", "1h"]
TF_LABELS = {"1mo": "M", "1w": "W", "1d": "D", "4h": "4H", "1h": "1H"}
TF_NAMES = {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily", "4h": "4-Hour", "1h": "Hourly"}

# ADX direction thresholds (matches Pine Script: +DMI > -DMI + 2)
ADX_BUFFER = 2


@dataclass
class LevelSet:
    """Supply and demand levels for one timeframe."""
    tf: str
    tf_label: str
    supply1: Optional[float] = None
    supply2: Optional[float] = None
    demand1: Optional[float] = None
    demand2: Optional[float] = None
    trend: str = "SIDE"  # UP, DOWN, SIDE
    adx: float = 0.0


def find_untouched_levels(highs: List[float], lows: List[float],
                          current_price: float, lookback: int = 10) -> Tuple[
                              Optional[float], Optional[float],
                              Optional[float], Optional[float]]:
    """Find S1, S2, D1, D2 from a list of period highs and lows.

    Args:
        highs: List of period highs, most recent first [current, prev1, prev2, ...]
        lows: List of period lows, most recent first
        current_price: Current market price (used as baseline)
        lookback: How many periods to look back

    Returns:
        (supply1, supply2, demand1, demand2)
    """
    if not highs or not lows:
        return None, None, None, None

    n = min(len(highs), len(lows), lookback + 1)

    # Use max of current period's high and current price as baseline
    max_h = max(highs[0], current_price)
    sup1, sup2 = None, None

    for i in range(1, n):
        if highs[i] > max_h:
            if sup1 is None:
                sup1 = highs[i]
            elif sup2 is None:
                sup2 = highs[i]
        max_h = max(max_h, highs[i])

    # Fallback: if no untouched supply above, use current period high
    if sup1 is None:
        sup1 = max(highs[0], current_price)

    # Use min of current period's low and current price as baseline
    min_l = min(lows[0], current_price)
    dem1, dem2 = None, None

    for i in range(1, n):
        if lows[i] < min_l:
            if dem1 is None:
                dem1 = lows[i]
            elif dem2 is None:
                dem2 = lows[i]
        min_l = min(min_l, lows[i])

    # Fallback: if no untouched demand below, use current period low
    if dem1 is None:
        dem1 = min(lows[0], current_price)

    return sup1, sup2, dem1, dem2


def find_step_levels(highs: List[float], lows: List[float],
                     lookback: int = 12) -> Tuple[
                         Optional[float], Optional[float],
                         Optional[float], Optional[float]]:
    """Untouched demand / supply, anchored on the in-progress bar.

    Baseline = in-progress bar's low (for demand) / high (for supply).
    Walk back through prior bars; each one whose low is BELOW the
    running-min becomes a demand level, each one whose high is ABOVE
    the running-max becomes a supply level. First two of each become
    D1/D2 and S1/S2.

    Args:
        highs: List of period highs, most-recent-first.
                highs[0] = current in-progress bar.
        lows:  Same convention as highs.
        lookback: how many prior bars to scan.

    Returns:
        (s1, s2, d1, d2) — any may be None if no qualifying bar exists.

    Per user spec 2026-06-02 for the Dashboard panel. Distinct from
    find_untouched_levels above, which mixes current_price (e.g. from a
    finer TF's close) into the baseline. This version uses ONLY the
    in-progress bar's own extreme, so an intra-bar dip from a finer TF
    doesn't invalidate a still-untouched higher-TF level.
    """
    n = min(len(highs), len(lows), lookback + 1)
    if n < 2:
        return None, None, None, None

    s1 = s2 = d1 = d2 = None

    max_h = highs[0]
    for i in range(1, n):
        if highs[i] > max_h:
            if s1 is None:
                s1 = highs[i]
            elif s2 is None:
                s2 = highs[i]
        max_h = max(max_h, highs[i])

    min_l = lows[0]
    for i in range(1, n):
        if lows[i] < min_l:
            if d1 is None:
                d1 = lows[i]
            elif d2 is None:
                d2 = lows[i]
        min_l = min(min_l, lows[i])

    return s1, s2, d1, d2


# Per-TF lookback depth — mirrors TF_LOOKBACK in scripts/htf_levels.py
# (the Python port of pinescripts/htf_strategy.pine). Deeper than the
# old fixed-12 window so each TF's untouched levels match what the Pine
# script draws on TradingView (and thus the compare page's TV column).
HTF_TF_LOOKBACK = {
    "Q":   60,  "3mo": 60,
    "M":   60,  "1mo": 60,
    "W":   100, "1w":  100,
    "D":   100, "1d":  100,
    "4H":  120, "4h":  120,
    "1H":  200, "1h":  200,
    "30M": 300, "30m": 300,
    "15M": 500, "15m": 500,
}


def find_htf_levels(highs: List[float], lows: List[float],
                    current_price: float, lookback: int = 10) -> Tuple[
                        Optional[float], Optional[float],
                        Optional[float], Optional[float]]:
    """Untouched S1/S2 + D1/D2 — pure-Python port of the Pine algorithm
    in pinescripts/htf_strategy.pine (and scripts/htf_levels.py
    compute_levels). Use this so the compare-page SRV column and the
    MTF trade setups match what TradingView draws.

    Args:
        highs/lows: most-recent-first lists (highs[0] = current bar).
        current_price: current bar's close (the supply "> close" filter
            and the post-find "drop supply at/below close" both use it).
        lookback: how many prior bars to scan (see HTF_TF_LOOKBACK).

    Differences from find_step_levels (the prior MTF logic):
      - Supply candidate must satisfy high[i] > running-max AND
        high[i] > close (not just > running-max).
      - No supply fallback: S1 stays None if no past peak qualifies.
      - Demand DOES fall back to the current bar's low if no past
        trough is lower.
      - Post-find defensive drop: any supply at or below close → None
        (kills a fake "supply at price").

    Returns (s1, s2, d1, d2) — any may be None.
    """
    n = min(len(highs), len(lows))
    if n < 2:
        return None, None, None, None
    scan = min(lookback, n - 1)
    close_now = current_price

    # Supply — seed running-max at the in-progress bar's high.
    max_h = highs[0]
    s1 = s2 = None
    for i in range(1, scan + 1):
        h_i = highs[i]
        if h_i > max_h and h_i > close_now:
            if s1 is None:
                s1 = h_i
            elif s2 is None:
                s2 = h_i
        max_h = max(max_h, h_i)

    # Demand — seed running-min at the in-progress bar's low.
    min_l = lows[0]
    d1 = d2 = None
    for i in range(1, scan + 1):
        l_i = lows[i]
        if l_i < min_l:
            if d1 is None:
                d1 = l_i
            elif d2 is None:
                d2 = l_i
        min_l = min(min_l, l_i)
    if d1 is None:
        d1 = lows[0]

    # Defensive: supply must sit above price.
    if s1 is not None and s1 <= close_now:
        s1 = None
    if s2 is not None and s2 <= close_now:
        s2 = None

    return s1, s2, d1, d2


def calculate_structure_direction(candles, n: int = 15,
                                  prefer_confirmed: bool = False) -> Tuple[str, float]:
    """Trend direction from swing pivot structure (Dow Theory).

    A bar is a swing HIGH if its high beats the N bars on each side; same
    for swing LOW. Compares the last two of each:

      UP   = Higher High AND Higher Low
      DOWN = Lower High  AND Lower Low
      SIDE = anything else (expanding range, coiling, or not enough pivots)

    Returns (direction, strength) where strength is a 0-100 confidence:
      100 = both highs and both lows agreed clearly
       50 = only one of (highs / lows) agrees
        0 = not enough pivots / fully mixed

    The last N bars can't be confirmed yet (a pivot needs N bars on its
    right). This is a real structural lag, not artificial.

    Args:
        candles: list of objects with .high/.low attributes, OR list of
                 dicts with 'high'/'low' keys, oldest-first.
        n: half-window for the pivot detector.

    Designed as a drop-in replacement for calculate_adx_direction for
    FX assets, where ADX's Wilder smoothing keeps single-bar volatility
    spikes (e.g. BoJ intervention candles) in memory for ~27 daily bars
    and pulls the +DI/-DI reading the wrong way.
    """
    def _h(b):
        return b["high"] if isinstance(b, dict) else b.high

    def _l(b):
        return b["low"] if isinstance(b, dict) else b.low

    if len(candles) < 2 * n + 2:
        return "SIDE", 0.0

    highs: List[Tuple[int, float]] = []
    lows: List[Tuple[int, float]] = []
    for i in range(n, len(candles) - n):
        h = _h(candles[i])
        l = _l(candles[i])
        if all(_h(candles[i - j]) < h and _h(candles[i + j]) < h for j in range(1, n + 1)):
            highs.append((i, h))
        if all(_l(candles[i - j]) > l and _l(candles[i + j]) > l for j in range(1, n + 1)):
            lows.append((i, l))

    # In strong unidirectional moves, pivots stop forming because each bar
    # has a worse extreme than the bar N back (the move dominates the
    # required N-bar lookback). The detector can get stuck on pre-trend
    # consolidation pivots and miss the entire move. Check for in-progress
    # structure breaks: if current price has decisively broken outside the
    # most recent confirmed pivot, that's a structure-in-progress signal.
    def _close(b):
        return b["close"] if isinstance(b, dict) else b.close
    last_close = _close(candles[-1])
    # Tolerance: must be beyond the prior pivot by enough that it isn't noise.
    # Use the average range of the recent bars as a noise floor.
    recent_ranges = [(_h(candles[i]) - _l(candles[i])) for i in range(max(0, len(candles) - 20), len(candles))]
    avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0.0
    break_buffer = max(avg_range * 0.5, 1e-9)

    in_progress_up = in_progress_down = False
    if highs and last_close > highs[-1][1] + break_buffer:
        in_progress_up = True
    if lows and last_close < lows[-1][1] - break_buffer:
        in_progress_down = True

    if len(highs) < 2 or len(lows) < 2:
        # Not enough confirmed pivots — fall back to in-progress reading only.
        if in_progress_up:
            return "UP", 75.0
        if in_progress_down:
            return "DOWN", 75.0
        return "SIDE", 0.0

    hh = highs[-1][1] > highs[-2][1]
    lh = highs[-1][1] < highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    ll = lows[-1][1] < lows[-2][1]

    # Strong move override: a confirmed HH+HL "uptrend" can become stale if
    # price has since broken below the latest swing low (a fresh LL in
    # progress that hasn't formed a new confirmed pivot yet — common in
    # strong trends where pivots can't form because every bar dominates
    # its N-bar lookback). Same logic mirrored for downtrends.
    #
    # UI callers (chart title arrows, watchlist badges) pass
    # prefer_confirmed=True to disable this flip — visually a chart that
    # still prints HH+HL or LH+LL doesn't read as "reversal in progress"
    # to a human eye, and showing the flipped value made the title arrow
    # disagree with the chart's own dashboard.
    if not prefer_confirmed:
        if hh and hl and in_progress_down:
            return "DOWN", 75.0
        if lh and ll and in_progress_up:
            return "UP", 75.0

    if hh and hl:
        return "UP", 100.0
    if lh and ll:
        return "DOWN", 100.0

    # Confirmed pivots disagree. Prefer the in-progress break if present;
    # otherwise return SIDE.
    if in_progress_down:
        return "DOWN", 75.0
    if in_progress_up:
        return "UP", 75.0

    # Partial agreement gets a 50 score so callers that want a soft signal
    # can use it; the strict UP/DOWN classifier still returns SIDE.
    return "SIDE", 50.0 if (hh or hl or lh or ll) else 0.0


def _is_fx_instrument(instrument: str) -> bool:
    """Heuristic: FX if instrument has the OANDA underscore form (USD_JPY)
    or is a 6-letter alpha symbol (USDJPY)."""
    if not instrument:
        return False
    s = instrument.upper().strip()
    if "_" in s:
        parts = s.split("_")
        return len(parts) == 2 and all(p.isalpha() and len(p) == 3 for p in parts)
    return len(s) == 6 and s.isalpha()


def calculate_trend_direction(candles, instrument: str = "",
                              adx_period: int = 14,
                              structure_n: int = 15,
                              prefer_confirmed: bool = False) -> Tuple[str, float]:
    """Asset-aware trend direction.

    FX → swing structure (N=15) because ADX's Wilder smoothing handles
         single-bar BoJ-style spikes badly and pollutes +DI/-DI for weeks.
    Everything else → +DI vs -DI ADX (the historical behavior).

    prefer_confirmed: when True, FX structure ignores the in-progress
    "break above last swing high / below last swing low" override that
    would otherwise flip a confirmed UP/DOWN reading. Use this for UI
    displays so the title/dashboard agree with the visible pivot
    structure. Strategy callers leave it False to keep the override.

    Returns (direction, value) where:
      - for FX: value is the structure confidence (0-100)
      - for non-FX: value is the ADX numeric reading (0-100ish)
    """
    if _is_fx_instrument(instrument):
        return calculate_structure_direction(candles, n=structure_n,
                                              prefer_confirmed=prefer_confirmed)
    return calculate_adx_direction(candles, period=adx_period)


def calculate_adx_direction(candles, period: int = 14) -> Tuple[str, float]:
    """Calculate ADX trend direction from candle data.

    Simplified ADX: uses +DI vs -DI to determine direction.

    Args:
        candles: List of CandleData, most recent last
        period: ADX period

    Returns:
        (direction, adx_value) where direction is "UP", "DOWN", or "SIDE"
    """
    if len(candles) < period + 2:
        return "SIDE", 0.0

    # Calculate +DM, -DM, TR
    plus_dm_list = []
    minus_dm_list = []
    tr_list = []

    for i in range(1, len(candles)):
        h = candles[i].high
        l = candles[i].low
        prev_h = candles[i - 1].high
        prev_l = candles[i - 1].low
        prev_c = candles[i - 1].close

        plus_dm = max(h - prev_h, 0) if (h - prev_h) > (prev_l - l) else 0
        minus_dm = max(prev_l - l, 0) if (prev_l - l) > (h - prev_h) else 0
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    if len(tr_list) < period:
        return "SIDE", 0.0

    # Wilder's smoothing (EMA-like)
    def wilder_smooth(values, period):
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1] / period + v)
        return smoothed

    smooth_plus_dm = wilder_smooth(plus_dm_list, period)
    smooth_minus_dm = wilder_smooth(minus_dm_list, period)
    smooth_tr = wilder_smooth(tr_list, period)

    if not smooth_tr or smooth_tr[-1] == 0:
        return "SIDE", 0.0

    plus_di = 100 * smooth_plus_dm[-1] / smooth_tr[-1]
    minus_di = 100 * smooth_minus_dm[-1] / smooth_tr[-1]

    # ADX from DX
    dx_list = []
    for i in range(len(smooth_plus_dm)):
        if smooth_tr[i] == 0:
            continue
        pdi = 100 * smooth_plus_dm[i] / smooth_tr[i]
        mdi = 100 * smooth_minus_dm[i] / smooth_tr[i]
        if pdi + mdi > 0:
            dx_list.append(100 * abs(pdi - mdi) / (pdi + mdi))

    if len(dx_list) < period:
        adx_value = 0.0
    else:
        adx_smooth = wilder_smooth(dx_list, period)
        adx_value = adx_smooth[-1] if adx_smooth else 0.0

    # Direction
    if plus_di > minus_di + ADX_BUFFER:
        direction = "UP"
    elif plus_di < minus_di - ADX_BUFFER:
        direction = "DOWN"
    else:
        direction = "SIDE"

    return direction, round(adx_value, 1)


def scan_ticker(massive_client, ticker: str, current_price: float = 0,
                timeframes: List[str] = None) -> Dict[str, LevelSet]:
    """Scan a single ticker for untouched S/R levels across all timeframes.

    Args:
        massive_client: MassiveClient instance
        ticker: Stock ticker (e.g. "SPY")
        current_price: Current price (if 0, uses latest candle close)
        timeframes: List of timeframes to scan (default: all)

    Returns:
        Dict keyed by TF label ("M", "W", "D", "4H", "1H") → LevelSet
    """
    if timeframes is None:
        timeframes = TIMEFRAMES

    results = {}

    for tf in timeframes:
        try:
            # Get enough candles for 10-bar lookback + ADX calculation
            count = 30 if tf in ("1mo", "1w") else 50
            candles = massive_client.get_candles(ticker, tf, count)

            if not candles:
                continue

            # Use current price or latest candle close
            price = current_price if current_price > 0 else candles[-1].close

            # Extract highs/lows, most recent first
            highs = [c.high for c in reversed(candles)]
            lows = [c.low for c in reversed(candles)]

            # Find untouched levels
            s1, s2, d1, d2 = find_untouched_levels(highs, lows, price, lookback=10)

            # Calculate ADX direction
            direction, adx_val = calculate_adx_direction(candles, period=14)

            label = TF_LABELS.get(tf, tf)
            results[label] = LevelSet(
                tf=tf,
                tf_label=label,
                supply1=round(s1, 2) if s1 else None,
                supply2=round(s2, 2) if s2 else None,
                demand1=round(d1, 2) if d1 else None,
                demand2=round(d2, 2) if d2 else None,
                trend=direction,
                adx=adx_val,
            )

        except Exception as e:
            logger.warning("Error scanning %s %s: %s", ticker, tf, e)
            continue

    return results


def scan_universe(massive_client, tickers: List[str],
                  swing_tickers: List[str] = None,
                  proximity_pct: float = 1.0) -> List[dict]:
    """Scan a list of tickers and find those near S/R levels.

    Args:
        massive_client: MassiveClient instance
        tickers: List of stock tickers
        proximity_pct: How close price must be to a level (% of price)

    Returns:
        List of setups sorted by score (best first), each containing:
        {ticker, price, level, level_type, tf, distance_pct, trend, adx, score}
    """
    setups = []

    for ticker in tickers:
        try:
            # Get current price
            candles_1d = massive_client.get_candles(ticker, "1d", 2)
            if not candles_1d:
                continue
            price = candles_1d[-1].close

            # Scan all timeframes
            levels = scan_ticker(massive_client, ticker, price)

            # Check proximity to each level
            for tf_label, lvl in levels.items():
                for level_type, level_price in [
                    ("D1", lvl.demand1), ("D2", lvl.demand2),
                    ("S1", lvl.supply1), ("S2", lvl.supply2),
                ]:
                    if level_price is None or level_price == 0:
                        continue

                    dist_pct = (price - level_price) / price * 100

                    # D1/D2: price should be above (positive dist, approaching from above)
                    # S1/S2: price should be below (negative dist, approaching from below)
                    is_demand = level_type.startswith("D")
                    is_supply = level_type.startswith("S")

                    if is_demand and 0 < dist_pct <= proximity_pct:
                        # Price is above demand, within proximity
                        pass
                    elif is_supply and -proximity_pct <= dist_pct < 0:
                        # Price is below supply, within proximity
                        pass
                    else:
                        continue

                    # Score: +1 per aligned HTF trend
                    direction = "BUY" if is_demand else "SELL"
                    score = 0

                    # Get trend from this TF and higher TFs
                    tf_order = ["1H", "4H", "D", "W", "M"]
                    tf_idx = tf_order.index(tf_label) if tf_label in tf_order else -1

                    for check_tf in tf_order[tf_idx:]:
                        check_lvl = levels.get(check_tf)
                        if check_lvl:
                            if direction == "BUY" and check_lvl.trend == "UP":
                                score += 1
                            elif direction == "SELL" and check_lvl.trend == "DOWN":
                                score += 1
                            # ADX strength bonus
                            if check_lvl.adx >= 25:
                                score += 1
                                break  # Only count ADX bonus once

                    setups.append({
                        "ticker": ticker,
                        "price": round(price, 2),
                        "level": round(level_price, 2),
                        "level_type": level_type,
                        "tf": tf_label,
                        "tf_name": TF_NAMES.get(lvl.tf, lvl.tf),
                        "distance_pct": round(dist_pct, 2),
                        "direction": direction,
                        "trend": lvl.trend,
                        "adx": lvl.adx,
                        "score": score,
                    })

        except Exception as e:
            logger.warning("Error scanning %s: %s", ticker, e)
            continue

    # Sort by score descending, then by TF descending (M > W > D > 4H > 1H), then distance
    tf_rank = {"M": 5, "W": 4, "D": 3, "4H": 2, "1H": 1}
    setups.sort(key=lambda s: (-s["score"], -tf_rank.get(s["tf"], 0), abs(s["distance_pct"])))
    return setups
