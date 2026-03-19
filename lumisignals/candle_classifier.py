"""Candlestick pattern classification from OHLC data."""

import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


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


def classify_candle(candle: CandleData, prev_candle: CandleData = None) -> CandleClassification:
    """Classify a single candlestick pattern.

    Args:
        candle: Current candle OHLC.
        prev_candle: Previous candle for two-candle patterns (engulfing).

    Returns:
        CandleClassification with pattern name, direction, and strength.
    """
    o, h, l, c = candle.open, candle.high, candle.low, candle.close
    total_range = h - l

    if total_range == 0:
        return CandleClassification(
            direction="neutral", pattern="No Range", strength=0.0,
            body_pct=0, upper_wick_pct=0, lower_wick_pct=0,
        )

    body = abs(c - o)
    body_pct = body / total_range

    if c >= o:  # Bullish candle
        upper_wick = h - c
        lower_wick = o - l
    else:  # Bearish candle
        upper_wick = h - o
        lower_wick = c - l

    upper_wick_pct = upper_wick / total_range
    lower_wick_pct = lower_wick / total_range

    is_green = c > o
    is_red = c < o

    # --- Pattern detection ---

    # Doji: very small body
    if body_pct < 0.1:
        if lower_wick_pct > 0.6:
            pattern = "Dragonfly Doji"
            direction = "bullish"
            strength = 0.6
        elif upper_wick_pct > 0.6:
            pattern = "Gravestone Doji"
            direction = "bearish"
            strength = 0.6
        else:
            pattern = "Doji"
            direction = "neutral"
            strength = 0.3
    # Hammer / Hanging Man: small body at top, long lower wick
    elif body_pct < 0.35 and lower_wick_pct > 0.55 and upper_wick_pct < 0.15:
        if is_green:
            pattern = "Hammer"
            direction = "bullish"
            strength = 0.8
        else:
            pattern = "Hanging Man"
            direction = "bearish"
            strength = 0.5
    # Inverted Hammer / Shooting Star: small body at bottom, long upper wick
    elif body_pct < 0.35 and upper_wick_pct > 0.55 and lower_wick_pct < 0.15:
        if is_red:
            pattern = "Shooting Star"
            direction = "bearish"
            strength = 0.8
        else:
            pattern = "Inverted Hammer"
            direction = "bullish"
            strength = 0.5
    # Marubozu: large body, minimal wicks
    elif body_pct > 0.85:
        if is_green:
            pattern = "Bullish Marubozu"
            direction = "bullish"
            strength = 0.9
        else:
            pattern = "Bearish Marubozu"
            direction = "bearish"
            strength = 0.9
    # Strong candle: large body, some wicks
    elif body_pct > 0.6:
        if is_green:
            pattern = "Strong Bullish"
            direction = "bullish"
            strength = 0.7
        else:
            pattern = "Strong Bearish"
            direction = "bearish"
            strength = 0.7
    # Spinning Top: small body, wicks on both sides
    elif body_pct < 0.3 and upper_wick_pct > 0.25 and lower_wick_pct > 0.25:
        pattern = "Spinning Top"
        direction = "neutral"
        strength = 0.2
    # Default: moderate candle
    else:
        if is_green:
            pattern = "Bullish"
            direction = "bullish"
            strength = 0.5
        elif is_red:
            pattern = "Bearish"
            direction = "bearish"
            strength = 0.5
        else:
            pattern = "Neutral"
            direction = "neutral"
            strength = 0.1

    # Two-candle patterns (engulfing)
    if prev_candle is not None:
        prev_body = abs(prev_candle.close - prev_candle.open)
        # Bullish Engulfing
        if (is_green and prev_candle.close < prev_candle.open
                and o <= prev_candle.close and c >= prev_candle.open
                and body > prev_body):
            pattern = "Bullish Engulfing"
            direction = "bullish"
            strength = 0.9
        # Bearish Engulfing
        elif (is_red and prev_candle.close > prev_candle.open
              and o >= prev_candle.close and c <= prev_candle.open
              and body > prev_body):
            pattern = "Bearish Engulfing"
            direction = "bearish"
            strength = 0.9

    return CandleClassification(
        direction=direction,
        pattern=pattern,
        strength=strength,
        body_pct=round(body_pct, 3),
        upper_wick_pct=round(upper_wick_pct, 3),
        lower_wick_pct=round(lower_wick_pct, 3),
    )


@dataclass
class TimeframeScore:
    """Direction score for a single timeframe."""
    timeframe: str
    direction: str       # "bullish", "bearish", "neutral"
    pattern: str         # candlestick pattern name
    strength: float
    score: int           # +1 for bullish, -1 for bearish, 0 for neutral


def score_multi_timeframe(candles: dict, prev_candles: dict = None) -> dict:
    """Score direction alignment across multiple timeframes using candlestick patterns.

    Args:
        candles: Dict of {timeframe: CandleData} for the current candle.
        prev_candles: Dict of {timeframe: CandleData} for the previous candle (for engulfing).

    Returns:
        {
            "scores": [TimeframeScore, ...],
            "long_score": int,   # count of bullish timeframes
            "short_score": int,  # count of bearish timeframes
            "total": int,        # total timeframes scored
            "direction": str,    # "bullish", "bearish", or "neutral"
            "confidence": float, # 0.0 to 1.0
            "summary": str,
        }
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

    # Build summary
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
