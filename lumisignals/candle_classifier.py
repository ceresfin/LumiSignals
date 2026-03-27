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
        # Pick the strongest pattern
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
