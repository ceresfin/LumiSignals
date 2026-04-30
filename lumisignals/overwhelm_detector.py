"""Shared 2n20 Overwhelm Detection — used by both FX and Futures strategies.

This is the single source of truth for:
- Overwhelm detection (green overwhelms red, red overwhelms green)
- Body size filters (min body %, significant vs average)
- VWAP calculation
- VWAP cross detection

Same logic as the TradingView Pine Script 2n20.pine.
"""

from typing import List, Optional, Tuple

# Default parameters — match the Pine Script
DEFAULT_MIN_BODY_PCT = 30.0   # Body must be >= 30% of candle range
DEFAULT_AVG_BODY_MULT = 0.8   # Body must be >= 80% of 10-candle average
DEFAULT_LOOKBACK_BARS = 3     # Look back up to 3 bars for opposite candle


def detect_overwhelm(bars: list,
                     min_body_pct: float = DEFAULT_MIN_BODY_PCT,
                     avg_body_mult: float = DEFAULT_AVG_BODY_MULT,
                     lookback_bars: int = DEFAULT_LOOKBACK_BARS) -> Tuple[bool, bool]:
    """Detect green/red overwhelm patterns on OHLC bars.

    An overwhelm occurs when the current candle's body is larger than
    the most recent opposite-color candle's body, AND the current candle
    closes beyond that opposite candle's open.

    Args:
        bars: List of dicts with "open", "high", "low", "close" keys.
              Must have at least 12 bars. Most recent bar is bars[-1].
        min_body_pct: Minimum body size as % of candle range (filters dojis).
        avg_body_mult: Body must be >= this × 10-bar average body.
        lookback_bars: How many bars back to search for opposite candle.

    Returns:
        (green_overwhelm, red_overwhelm) — True if the pattern is detected.
    """
    if len(bars) < 12:
        return False, False

    curr = bars[-1]
    curr_close = curr["close"]
    curr_open = curr["open"]
    curr_high = curr["high"]
    curr_low = curr["low"]

    is_green = curr_close > curr_open
    is_red = curr_close < curr_open
    green_body = curr_close - curr_open if is_green else 0
    red_body = curr_open - curr_close if is_red else 0

    # Body size filter — reject dojis
    candle_range = curr_high - curr_low
    body_size = abs(curr_close - curr_open)
    body_pct = (body_size / candle_range * 100) if candle_range > 0 else 0
    has_real_body = body_pct >= min_body_pct

    # Significant body — must be meaningful relative to recent bars
    avg_body = sum(abs(b["close"] - b["open"]) for b in bars[-11:-1]) / 10
    is_significant = body_size >= avg_body * avg_body_mult

    if not has_real_body or not is_significant:
        return False, False

    # Find most recent RED candle within lookback (for green overwhelm)
    last_red_body = 0.0
    last_red_high = 0.0
    for i in range(2, min(2 + lookback_bars, len(bars))):
        b = bars[-i]
        if b["close"] < b["open"]:
            last_red_body = b["open"] - b["close"]
            last_red_high = b["open"]
            break

    # Find most recent GREEN candle within lookback (for red overwhelm)
    last_green_body = 0.0
    last_green_low = 0.0
    for i in range(2, min(2 + lookback_bars, len(bars))):
        b = bars[-i]
        if b["close"] > b["open"]:
            last_green_body = b["close"] - b["open"]
            last_green_low = b["open"]
            break

    green_overwhelm = (is_green and last_red_body > 0
                      and green_body > last_red_body
                      and curr_close > last_red_high)

    red_overwhelm = (is_red and last_green_body > 0
                    and red_body > last_green_body
                    and curr_close < last_green_low)

    return green_overwhelm, red_overwhelm


def detect_vwap_cross(bars: list, vwap: float) -> Tuple[bool, bool]:
    """Detect if price crossed VWAP on the most recent bar.

    Args:
        bars: At least 2 bars with "close" key.
        vwap: Current VWAP value.

    Returns:
        (crossed_below, crossed_above)
    """
    if len(bars) < 2 or vwap is None:
        return False, False

    close = bars[-1]["close"]
    prev_close = bars[-2]["close"]

    crossed_below = close < vwap and prev_close >= vwap
    crossed_above = close > vwap and prev_close <= vwap

    return crossed_below, crossed_above


def calc_vwap_from_bars(bars: list) -> Optional[float]:
    """Calculate VWAP from a list of OHLC bars with volume.

    Uses HLC3 (high + low + close) / 3 weighted by volume.

    Args:
        bars: List of dicts with "high", "low", "close", "volume" keys.

    Returns:
        VWAP value, or None if no data.
    """
    num = 0.0
    den = 0.0
    for b in bars:
        vol = max(int(b.get("volume", 1)), 1)
        hlc3 = (b["high"] + b["low"] + b["close"]) / 3
        num += hlc3 * vol
        den += vol
    return num / den if den > 0 else None


def parse_oanda_candles(candles: list) -> list:
    """Convert Oanda candle format to simple OHLCV dicts.

    Args:
        candles: Raw Oanda candle list from get_candles().

    Returns:
        List of {"open", "high", "low", "close", "volume", "time"} dicts.
        Only includes completed candles.
    """
    bars = []
    for c in candles:
        if not c.get("complete", True):
            continue
        mid = c.get("mid", {})
        bars.append({
            "open": float(mid.get("o", 0)),
            "high": float(mid.get("h", 0)),
            "low": float(mid.get("l", 0)),
            "close": float(mid.get("c", 0)),
            "volume": int(c.get("volume", 0)),
            "time": c.get("time", ""),
        })
    return bars
