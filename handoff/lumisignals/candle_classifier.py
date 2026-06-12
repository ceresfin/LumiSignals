"""Candlestick pattern classification using TA-Lib (61 patterns)."""

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import talib
    HAS_TALIB = True
except ImportError:
    HAS_TALIB = False
    logger.warning("TA-Lib not installed — using basic candle classification")


# Human-readable names for TA-Lib candlestick functions
PATTERN_NAMES = {
    "CDL2CROWS": "Two Crows",
    "CDL3BLACKCROWS": "Three Black Crows",
    "CDL3INSIDE": "Three Inside",
    "CDL3LINESTRIKE": "Three Line Strike",
    "CDL3OUTSIDE": "Three Outside",
    "CDL3STARSINSOUTH": "Three Stars In South",
    "CDL3WHITESOLDIERS": "Three White Soldiers",
    "CDLABANDONEDBABY": "Abandoned Baby",
    "CDLADVANCEBLOCK": "Advance Block",
    "CDLBELTHOLD": "Belt Hold",
    "CDLBREAKAWAY": "Breakaway",
    "CDLCLOSINGMARUBOZU": "Closing Marubozu",
    "CDLCONCEALBABYSWALL": "Concealing Baby Swallow",
    "CDLCOUNTERATTACK": "Counterattack",
    "CDLDARKCLOUDCOVER": "Dark Cloud Cover",
    "CDLDOJI": "Doji",
    "CDLDOJISTAR": "Doji Star",
    "CDLDRAGONFLYDOJI": "Dragonfly Doji",
    "CDLENGULFING": "Engulfing",
    "CDLEVENINGDOJISTAR": "Evening Doji Star",
    "CDLEVENINGSTAR": "Evening Star",
    "CDLGAPSIDESIDEWHITE": "Gap Side Side White",
    "CDLGRAVESTONEDOJI": "Gravestone Doji",
    "CDLHAMMER": "Hammer",
    "CDLHANGINGMAN": "Hanging Man",
    "CDLHARAMI": "Harami",
    "CDLHARAMICROSS": "Harami Cross",
    "CDLHIGHWAVE": "High Wave",
    "CDLHIKKAKE": "Hikkake",
    "CDLHIKKAKEMOD": "Modified Hikkake",
    "CDLHOMINGPIGEON": "Homing Pigeon",
    "CDLIDENTICAL3CROWS": "Identical Three Crows",
    "CDLINNECK": "In-Neck",
    "CDLINVERTEDHAMMER": "Inverted Hammer",
    "CDLKICKING": "Kicking",
    "CDLKICKINGBYLENGTH": "Kicking By Length",
    "CDLLADDERBOTTOM": "Ladder Bottom",
    "CDLLONGLEGGEDDOJI": "Long Legged Doji",
    "CDLLONGLINE": "Long Line",
    "CDLMARUBOZU": "Marubozu",
    "CDLMATCHINGLOW": "Matching Low",
    "CDLMATHOLD": "Mat Hold",
    "CDLMORNINGDOJISTAR": "Morning Doji Star",
    "CDLMORNINGSTAR": "Morning Star",
    "CDLONNECK": "On-Neck",
    "CDLPIERCING": "Piercing",
    "CDLRICKSHAWMAN": "Rickshaw Man",
    "CDLRISEFALL3METHODS": "Rise Fall Three Methods",
    "CDLSEPARATINGLINES": "Separating Lines",
    "CDLSHOOTINGSTAR": "Shooting Star",
    "CDLSHORTLINE": "Short Line",
    "CDLSPINNINGTOP": "Spinning Top",
    "CDLSTALLEDPATTERN": "Stalled Pattern",
    "CDLSTICKSANDWICH": "Stick Sandwich",
    "CDLTAKURI": "Takuri",
    "CDLTASUKIGAP": "Tasuki Gap",
    "CDLTHRUSTING": "Thrusting",
    "CDLTRISTAR": "Tri-Star",
    "CDLUNIQUE3RIVER": "Unique Three River",
    "CDLUPSIDEGAP2CROWS": "Upside Gap Two Crows",
    "CDLXSIDEGAP3METHODS": "Side Gap Three Methods",
}

# Patterns where positive result = bullish, negative = bearish
# Some patterns are inherently bullish or bearish
BEARISH_ONLY = {
    "CDL2CROWS", "CDL3BLACKCROWS", "CDLADVANCEBLOCK", "CDLDARKCLOUDCOVER",
    "CDLEVENINGDOJISTAR", "CDLEVENINGSTAR", "CDLGRAVESTONEDOJI",
    "CDLHANGINGMAN", "CDLIDENTICAL3CROWS", "CDLSHOOTINGSTAR",
    "CDLUPSIDEGAP2CROWS",
}
BULLISH_ONLY = {
    "CDL3WHITESOLDIERS", "CDLHAMMER", "CDLINVERTEDHAMMER",
    "CDLDRAGONFLYDOJI", "CDLLADDERBOTTOM", "CDLMORNINGDOJISTAR",
    "CDLMORNINGSTAR", "CDLPIERCING", "CDLTAKURI",
    "CDL3STARSINSOUTH", "CDLHOMINGPIGEON", "CDLMATCHINGLOW",
}

# Actionable formations — only these count for institutional bias scoring.
# Generic candle colors (White Candle, Black Candle) are NOT actionable.
ACTIONABLE_PATTERNS = {
    # Bullish reversals
    "Hammer", "Inverted Hammer", "Bullish Engulfing", "Engulfing",
    "Piercing", "Belt Hold", "Bullish Belt Hold", "Closing Marubozu", "Marubozu",
    "Bullish Marubozu", "Three White Soldiers", "Morning Star", "Morning Doji Star",
    "Dragonfly Doji", "Takuri", "Harami", "Harami Cross", "Three Inside",
    "Ladder Bottom", "Homing Pigeon", "Matching Low", "Three Stars In South",
    "Rise Fall Three Methods",
    # Bearish reversals
    "Shooting Star", "Bearish Engulfing", "Dark Cloud Cover",
    "Bearish Belt Hold", "Bearish Marubozu",
    "Three Black Crows", "Identical Three Crows", "Evening Star", "Evening Doji Star",
    "Gravestone Doji", "Hanging Man", "Two Crows", "Upside Gap Two Crows",
    "Advance Block",
    # Neutral but actionable
    "Doji", "Doji Star", "Long Legged Doji", "Tri-Star",
    "Abandoned Baby", "Breakaway", "Counterattack",
    "Kicking", "Kicking By Length", "Separating Lines",
    "Three Outside", "Three Line Strike",
}


@dataclass
class CandleData:
    """A single candlestick."""
    open: float
    high: float
    low: float
    close: float
    timestamp: str = ""


@dataclass
class CandleClassification:
    """Result of classifying a candlestick."""
    direction: str          # "bullish", "bearish", or "neutral"
    pattern: str            # e.g. "Hammer", "Shooting Star", "Doji"
    strength: float         # 0.0 to 1.0
    body_pct: float         # body size as % of total range
    upper_wick_pct: float   # upper wick as % of total range
    lower_wick_pct: float   # lower wick as % of total range


def _classify_talib(candles: List[CandleData]) -> CandleClassification:
    """Classify candlestick patterns using TA-Lib.

    Needs at least 3-5 candles for multi-candle patterns.
    Returns the strongest detected pattern for the last candle.
    """
    opens = np.array([c.open for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)

    last = candles[-1]
    total_range = last.high - last.low
    body = abs(last.close - last.open)

    if total_range > 0:
        body_pct = round(body / total_range, 3)
        if last.close >= last.open:
            upper_wick_pct = round((last.high - last.close) / total_range, 3)
            lower_wick_pct = round((last.open - last.low) / total_range, 3)
        else:
            upper_wick_pct = round((last.high - last.open) / total_range, 3)
            lower_wick_pct = round((last.close - last.low) / total_range, 3)
    else:
        body_pct = upper_wick_pct = lower_wick_pct = 0.0

    # Run all 61 pattern detectors
    detected = []
    cdl_funcs = [f for f in dir(talib) if f.startswith("CDL")]

    for func_name in cdl_funcs:
        try:
            func = getattr(talib, func_name)
            result = func(opens, highs, lows, closes)
            last_val = int(result[-1])
            if last_val != 0:
                name = PATTERN_NAMES.get(func_name, func_name.replace("CDL", ""))
                # TA-Lib returns +100 for bullish, -100 for bearish
                if last_val > 0:
                    direction = "bullish"
                else:
                    direction = "bearish"
                strength = abs(last_val) / 100.0
                detected.append((name, direction, strength, func_name))
        except Exception:
            pass

    if detected:
        # Pick the most specific pattern — prefer directional over generic
        # Higher priority = more specific/actionable
        _pattern_priority = {
            # Generic (low priority)
            "CDLDOJI": 1, "CDLSPINNINGTOP": 1, "CDLHIGHWAVE": 2,
            "CDLLONGLEGGEDDOJI": 2, "CDLSHORTLINE": 1, "CDLLONGLINE": 1,
            # Specific directional (high priority)
            "CDLDRAGONFLYDOJI": 10, "CDLGRAVESTONEDOJI": 10,
            "CDLHAMMER": 10, "CDLSHOOTINGSTAR": 10, "CDLHANGINGMAN": 10,
            "CDLINVERTEDHAMMER": 10, "CDLTAKURI": 10,
            "CDLENGULFING": 12, "CDLPIERCING": 11, "CDLDARKCLOUDCOVER": 11,
            "CDLMORNINGSTAR": 13, "CDLEVENINGSTAR": 13,
            "CDLMORNINGDOJISTAR": 13, "CDLEVENINGDOJISTAR": 13,
            "CDL3WHITESOLDIERS": 14, "CDL3BLACKCROWS": 14,
            "CDLHARAMI": 8, "CDLHARAMICROSS": 9, "CDL3INSIDE": 9,
            "CDL3OUTSIDE": 9, "CDLHIKKAKE": 5, "CDLHIKKAKEMOD": 6,
            "CDLBELTHOLD": 7, "CDLCLOSINGMARUBOZU": 7, "CDLMARUBOZU": 7,
            "CDLCOUNTERATTACK": 8, "CDLKICKING": 11,
            "CDLABANDONEDBABY": 13, "CDLTRISTAR": 10,
        }
        detected.sort(key=lambda x: (_pattern_priority.get(x[3], 5), x[2]), reverse=True)
        best = detected[0]
        return CandleClassification(
            direction=best[1],
            pattern=best[0],
            strength=best[2],
            body_pct=body_pct,
            upper_wick_pct=upper_wick_pct,
            lower_wick_pct=lower_wick_pct,
        )

    # No pattern detected — classify by candle color
    if last.close > last.open:
        return CandleClassification("bullish", "White Candle", 0.3, body_pct, upper_wick_pct, lower_wick_pct)
    elif last.close < last.open:
        return CandleClassification("bearish", "Black Candle", 0.3, body_pct, upper_wick_pct, lower_wick_pct)
    else:
        return CandleClassification("neutral", "Doji", 0.3, body_pct, upper_wick_pct, lower_wick_pct)


def _classify_basic(candle: CandleData, prev_candle: CandleData = None) -> CandleClassification:
    """Basic classification without TA-Lib — fallback."""
    o, h, l, c = candle.open, candle.high, candle.low, candle.close
    total_range = h - l

    if total_range == 0:
        return CandleClassification("neutral", "No Range", 0.0, 0, 0, 0)

    body = abs(c - o)
    body_pct = body / total_range

    if c >= o:
        upper_wick = h - c
        lower_wick = o - l
    else:
        upper_wick = h - o
        lower_wick = c - l

    upper_wick_pct = upper_wick / total_range
    lower_wick_pct = lower_wick / total_range
    is_green = c > o
    is_red = c < o

    if body_pct < 0.1:
        if lower_wick_pct > 0.6:
            pattern, direction, strength = "Dragonfly Doji", "bullish", 0.6
        elif upper_wick_pct > 0.6:
            pattern, direction, strength = "Gravestone Doji", "bearish", 0.6
        else:
            pattern, direction, strength = "Doji", "neutral", 0.3
    elif body_pct < 0.35 and lower_wick_pct > 0.55 and upper_wick_pct < 0.15:
        if is_green:
            pattern, direction, strength = "Hammer", "bullish", 0.8
        else:
            pattern, direction, strength = "Hanging Man", "bearish", 0.5
    elif body_pct < 0.35 and upper_wick_pct > 0.55 and lower_wick_pct < 0.15:
        if is_red:
            pattern, direction, strength = "Shooting Star", "bearish", 0.8
        else:
            pattern, direction, strength = "Inverted Hammer", "bullish", 0.5
    elif body_pct > 0.85:
        if is_green:
            pattern, direction, strength = "Bullish Marubozu", "bullish", 0.9
        else:
            pattern, direction, strength = "Bearish Marubozu", "bearish", 0.9
    elif body_pct > 0.6:
        if is_green:
            pattern, direction, strength = "Bullish Belt Hold", "bullish", 0.7
        else:
            pattern, direction, strength = "Bearish Belt Hold", "bearish", 0.7
    elif body_pct < 0.3 and upper_wick_pct > 0.25 and lower_wick_pct > 0.25:
        pattern, direction, strength = "Spinning Top", "neutral", 0.2
    else:
        if is_green:
            pattern, direction, strength = "White Candle", "bullish", 0.5
        elif is_red:
            pattern, direction, strength = "Black Candle", "bearish", 0.5
        else:
            pattern, direction, strength = "Doji", "neutral", 0.1

    # Two-candle: engulfing
    if prev_candle is not None:
        prev_body = abs(prev_candle.close - prev_candle.open)
        if (is_green and prev_candle.close < prev_candle.open
                and o <= prev_candle.close and c >= prev_candle.open and body > prev_body):
            pattern, direction, strength = "Bullish Engulfing", "bullish", 0.9
        elif (is_red and prev_candle.close > prev_candle.open
              and o >= prev_candle.close and c <= prev_candle.open and body > prev_body):
            pattern, direction, strength = "Bearish Engulfing", "bearish", 0.9

    return CandleClassification(direction, pattern, strength,
                                round(body_pct, 3), round(upper_wick_pct, 3), round(lower_wick_pct, 3))


def classify_candle(candle: CandleData, prev_candle: CandleData = None) -> CandleClassification:
    """Classify a candlestick pattern. Uses TA-Lib if available, basic fallback otherwise."""
    if HAS_TALIB and prev_candle:
        # TA-Lib needs arrays — build from available candles
        candles = [prev_candle, candle]
        return _classify_talib(candles)
    return _classify_basic(candle, prev_candle)


def classify_candle_series(candles: List[CandleData]) -> CandleClassification:
    """Classify the last candle in a series using TA-Lib (can detect multi-candle patterns).

    Pass 5+ candles for best results (Three White Soldiers, Morning Star, etc.)
    """
    if HAS_TALIB and len(candles) >= 2:
        return _classify_talib(candles)
    if len(candles) >= 2:
        return _classify_basic(candles[-1], candles[-2])
    return _classify_basic(candles[-1])


# Zone-trigger quality gates.  Without these, classify_for_zone fires
# on weak partial-match patterns and doji-shaped bars — meaning a 5m
# "Hanging Man" with a 5% body could trigger a SELL.  The April 17
# audit showed three HTF FX trades fired in 25 minutes; two of them
# were weak setups that would've been filtered out here.  The 2n20
# overwhelm path has equivalent guards (min_body_pct=30); this brings
# HTF Levels in line.
MIN_PATTERN_STRENGTH = 80     # TA-Lib returns 0-100; require a clean match
MIN_TRIGGER_BODY_PCT = 0.30   # Trigger bar's body must be ≥ 30% of range
                                # (reject doji-shaped reversals)


# Patterns valid at demand zones (bullish reversals)
DEMAND_PATTERN_FUNCS = {
    "CDLHAMMER", "CDLENGULFING", "CDLMORNINGSTAR", "CDLPIERCING",
    "CDL3WHITESOLDIERS", "CDLDRAGONFLYDOJI", "CDLTAKURI",
    "CDLHARAMI", "CDL3INSIDE", "CDLMORNINGDOJISTAR",
    "CDLINVERTEDHAMMER", "CDLHOMINGPIGEON", "CDLMATCHINGLOW",
    "CDL3STARSINSOUTH", "CDLLADDERBOTTOM",
}

# Patterns valid at supply zones (bearish reversals)
SUPPLY_PATTERN_FUNCS = {
    "CDLSHOOTINGSTAR", "CDLENGULFING", "CDLEVENINGSTAR", "CDLDARKCLOUDCOVER",
    "CDL3BLACKCROWS", "CDLGRAVESTONEDOJI", "CDLHANGINGMAN",
    "CDLHARAMI", "CDL3INSIDE", "CDLEVENINGDOJISTAR",
    "CDL2CROWS", "CDLIDENTICAL3CROWS", "CDLUPSIDEGAP2CROWS",
    "CDLADVANCEBLOCK",
}


def classify_for_zone(candles: List[CandleData], zone_type: str) -> Optional[CandleClassification]:
    """Classify candles, returning a result only if the pattern is valid for the zone type.

    Args:
        candles: List of CandleData (at least 3 for multi-candle patterns).
        zone_type: "demand" or "supply".

    Returns:
        CandleClassification if a zone-appropriate pattern is detected, else None.
    """
    if not HAS_TALIB or len(candles) < 2:
        return None

    allowed_funcs = DEMAND_PATTERN_FUNCS if zone_type == "demand" else SUPPLY_PATTERN_FUNCS
    expected_direction = "bullish" if zone_type == "demand" else "bearish"

    opens = np.array([c.open for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    closes = np.array([c.close for c in candles], dtype=float)

    last = candles[-1]
    total_range = last.high - last.low
    body = abs(last.close - last.open)

    if total_range > 0:
        body_pct = round(body / total_range, 3)
        if last.close >= last.open:
            upper_wick_pct = round((last.high - last.close) / total_range, 3)
            lower_wick_pct = round((last.open - last.low) / total_range, 3)
        else:
            upper_wick_pct = round((last.high - last.open) / total_range, 3)
            lower_wick_pct = round((last.close - last.low) / total_range, 3)
    else:
        body_pct = upper_wick_pct = lower_wick_pct = 0.0

    # Early reject: trigger bar must have a real body.  A doji-shaped
    # bar matching a "Harami" or "Hanging Man" carries thin evidence
    # of a real reversal, especially on 5m FX bars.
    if body_pct < MIN_TRIGGER_BODY_PCT:
        return None

    detected = []
    for func_name in allowed_funcs:
        try:
            func = getattr(talib, func_name, None)
            if func is None:
                continue
            result = func(opens, highs, lows, closes)
            last_val = int(result[-1])
            if last_val == 0:
                continue
            # Reject partial-match TA-Lib hits — anything below the
            # quality floor isn't a clean enough pattern to act on.
            if abs(last_val) < MIN_PATTERN_STRENGTH:
                continue
            direction = "bullish" if last_val > 0 else "bearish"
            if direction == expected_direction:
                name = PATTERN_NAMES.get(func_name, func_name.replace("CDL", ""))
                strength = abs(last_val) / 100.0
                detected.append((name, direction, strength))
        except Exception:
            pass

    if not detected:
        return None

    detected.sort(key=lambda x: x[2], reverse=True)
    best = detected[0]
    return CandleClassification(
        direction=best[1],
        pattern=best[0],
        strength=best[2],
        body_pct=body_pct,
        upper_wick_pct=upper_wick_pct,
        lower_wick_pct=lower_wick_pct,
    )


@dataclass
class TimeframeScore:
    """Direction score for a single timeframe."""
    timeframe: str
    direction: str
    pattern: str
    strength: float
    score: int           # +1 for bullish, -1 for bearish, 0 for neutral


def score_multi_timeframe(candles: dict, prev_candles: dict = None) -> dict:
    """Score direction alignment across multiple timeframes using candlestick patterns.

    Args:
        candles: Dict of {timeframe: CandleData} for the current candle.
        prev_candles: Dict of {timeframe: CandleData} for the previous candle.

    Returns:
        Dict with scores, direction, confidence, and summary.
    """
    scores = []

    for tf in ["1mo", "1w", "1d"]:
        candle = candles.get(tf)
        if candle is None:
            continue

        prev = prev_candles.get(tf) if prev_candles else None
        classification = classify_candle(candle, prev)

        if classification.direction == "bullish":
            sc = 1
        elif classification.direction == "bearish":
            sc = -1
        else:
            sc = 0

        scores.append(TimeframeScore(
            timeframe=tf,
            direction=classification.direction,
            pattern=classification.pattern,
            strength=classification.strength,
            score=sc,
        ))

    total = len(scores)
    long_score = sum(1 for s in scores if s.score > 0)
    short_score = sum(1 for s in scores if s.score < 0)

    if long_score > short_score:
        direction = "bullish"
        confidence = long_score / total if total else 0
    elif short_score > long_score:
        direction = "bearish"
        confidence = short_score / total if total else 0
    else:
        direction = "neutral"
        confidence = 0

    parts = []
    for s in scores:
        tf_label = {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily"}.get(s.timeframe, s.timeframe)
        parts.append(f"{tf_label}: {s.pattern} ({s.direction})")

    summary = " | ".join(parts) + f" → {direction} ({long_score}/{total})"

    return {
        "scores": scores,
        "long_score": long_score,
        "short_score": short_score,
        "total": total,
        "direction": direction,
        "confidence": confidence,
        "summary": summary,
    }
