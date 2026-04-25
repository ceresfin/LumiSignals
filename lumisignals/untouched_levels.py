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
