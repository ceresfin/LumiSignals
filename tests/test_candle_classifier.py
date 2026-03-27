"""Tests for candle_classifier — pattern detection and multi-TF scoring."""

from lumisignals.candle_classifier import (
    CandleData, classify_candle, score_multi_timeframe,
)


class TestClassifyCandle:
    def test_bullish_marubozu(self):
        candle = CandleData(open=1.0800, high=1.0900, low=1.0798, close=1.0898)
        result = classify_candle(candle)
        assert result.direction == "bullish"
        assert "Marubozu" in result.pattern
        assert result.strength >= 0.8

    def test_bearish_marubozu(self):
        candle = CandleData(open=1.0900, high=1.0902, low=1.0800, close=1.0802)
        result = classify_candle(candle)
        assert result.direction == "bearish"
        assert "Marubozu" in result.pattern

    def test_hammer(self):
        # Small green body at top, long lower wick
        candle = CandleData(open=1.0870, high=1.0880, low=1.0800, close=1.0878)
        result = classify_candle(candle)
        assert result.direction == "bullish"
        assert result.pattern == "Hammer"

    def test_shooting_star(self):
        # Small red body at bottom, long upper wick
        candle = CandleData(open=1.0840, high=1.0900, low=1.0830, close=1.0832)
        result = classify_candle(candle)
        assert result.direction == "bearish"
        assert result.pattern == "Shooting Star"

    def test_doji(self):
        candle = CandleData(open=1.0850, high=1.0870, low=1.0830, close=1.0851)
        result = classify_candle(candle)
        assert result.pattern == "Doji" or "Doji" in result.pattern
        assert result.strength <= 0.6

    def test_dragonfly_doji(self):
        candle = CandleData(open=1.0850, high=1.0852, low=1.0800, close=1.0851)
        result = classify_candle(candle)
        assert result.pattern == "Dragonfly Doji"
        assert result.direction == "bullish"

    def test_bullish_engulfing(self):
        prev = CandleData(open=1.0860, high=1.0865, low=1.0830, close=1.0835)  # red
        curr = CandleData(open=1.0830, high=1.0875, low=1.0828, close=1.0870)  # big green
        result = classify_candle(curr, prev)
        # TA-Lib may classify differently than basic; just verify direction
        assert result.direction == "bullish"

    def test_bearish_engulfing(self):
        prev = CandleData(open=1.0830, high=1.0860, low=1.0825, close=1.0855)  # green
        curr = CandleData(open=1.0860, high=1.0865, low=1.0815, close=1.0820)  # big red
        result = classify_candle(curr, prev)
        assert result.direction == "bearish"

    def test_no_range(self):
        candle = CandleData(open=1.0850, high=1.0850, low=1.0850, close=1.0850)
        result = classify_candle(candle)
        assert result.direction == "neutral"
        assert result.pattern == "No Range"

    def test_bullish_belt_hold(self):
        candle = CandleData(open=1.0800, high=1.0880, low=1.0790, close=1.0870)
        result = classify_candle(candle)
        assert result.direction == "bullish"
        assert result.pattern == "Bullish Belt Hold"

    def test_bearish_belt_hold(self):
        candle = CandleData(open=1.0880, high=1.0890, low=1.0800, close=1.0810)
        result = classify_candle(candle)
        assert result.direction == "bearish"
        assert result.pattern == "Bearish Belt Hold"


class TestScoreMultiTimeframe:
    def test_all_bullish(self):
        candles = {
            "1mo": CandleData(open=1.08, high=1.10, low=1.079, close=1.095),
            "1w": CandleData(open=1.08, high=1.095, low=1.079, close=1.092),
            "1d": CandleData(open=1.08, high=1.092, low=1.079, close=1.090),
        }
        result = score_multi_timeframe(candles)
        assert result["long_score"] == 3
        assert result["direction"] == "bullish"
        assert result["confidence"] == 1.0

    def test_all_bearish(self):
        candles = {
            "1mo": CandleData(open=1.09, high=1.10, low=1.07, close=1.08),
            "1w": CandleData(open=1.09, high=1.095, low=1.08, close=1.085),
            "1d": CandleData(open=1.09, high=1.091, low=1.085, close=1.086),
        }
        result = score_multi_timeframe(candles)
        assert result["short_score"] == 3
        assert result["direction"] == "bearish"

    def test_mixed_monthly_bullish(self):
        candles = {
            "1mo": CandleData(open=1.08, high=1.10, low=1.07, close=1.09),  # bullish
            "1w": CandleData(open=1.09, high=1.095, low=1.08, close=1.085),  # bearish
            "1d": CandleData(open=1.09, high=1.091, low=1.085, close=1.086),  # bearish
        }
        result = score_multi_timeframe(candles)
        assert result["long_score"] == 1
        assert result["short_score"] == 2
        assert result["direction"] == "bearish"

    def test_2_of_3_bullish(self):
        candles = {
            "1mo": CandleData(open=1.08, high=1.10, low=1.079, close=1.095),  # bullish
            "1w": CandleData(open=1.08, high=1.095, low=1.079, close=1.092),  # bullish
            "1d": CandleData(open=1.09, high=1.092, low=1.075, close=1.078),  # bearish
        }
        result = score_multi_timeframe(candles)
        assert result["long_score"] == 2
        assert result["direction"] == "bullish"

    def test_summary_includes_patterns(self):
        candles = {
            "1mo": CandleData(open=1.08, high=1.10, low=1.079, close=1.099),
            "1w": CandleData(open=1.08, high=1.09, low=1.079, close=1.089),
        }
        result = score_multi_timeframe(candles)
        assert "Monthly:" in result["summary"]
        assert "Weekly:" in result["summary"]
