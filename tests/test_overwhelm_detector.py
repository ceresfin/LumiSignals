"""Tests for the shared overwhelm detector.

Verifies that detect_overwhelm() produces the same results as the
original inline code in fx_scalp_2n20.py.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lumisignals.overwhelm_detector import (
    detect_overwhelm, detect_vwap_cross, calc_vwap_from_bars, parse_oanda_candles,
)


def make_bars(ohlc_list):
    """Helper: convert list of (o, h, l, c) tuples to bar dicts."""
    return [{"open": o, "high": h, "low": l, "close": c, "volume": 100} for o, h, l, c in ohlc_list]


def test_green_overwhelm():
    """Green candle body > previous red candle body + close above red's open."""
    bars = make_bars([
        # 10 filler bars (needed for avg body calc)
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        # Red candle: open=101, close=100 (body=1.0)
        (101, 101.5, 99.5, 100),
        # Green overwhelm: open=99.5, close=102 (body=2.5 > 1.0, close > 101)
        (99.5, 102.5, 99, 102),
    ])
    green, red = detect_overwhelm(bars)
    assert green == True, f"Expected green overwhelm, got {green}"
    assert red == False
    print("✓ test_green_overwhelm passed")


def test_red_overwhelm():
    """Red candle body > previous green candle body + close below green's open."""
    bars = make_bars([
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        # Green candle: open=100, close=101 (body=1.0)
        (100, 101.5, 99.5, 101),
        # Red overwhelm: open=101.5, close=99 (body=2.5 > 1.0, close < 100)
        (101.5, 102, 98.5, 99),
    ])
    green, red = detect_overwhelm(bars)
    assert green == False
    assert red == True, f"Expected red overwhelm, got {red}"
    print("✓ test_red_overwhelm passed")


def test_doji_rejected():
    """A doji (tiny body) should NOT trigger overwhelm even if > prev body."""
    bars = make_bars([
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        (100, 101, 99, 100.5),
        (100.5, 101.5, 99.5, 100),
        # Tiny red: body=0.01
        (100.01, 100.5, 99.5, 100),
        # "Green" doji: body=0.02, range=3.0 → body% = 0.7% < 30%
        (100, 101.5, 98.5, 100.02),
    ])
    green, red = detect_overwhelm(bars)
    assert green == False, "Doji should not trigger green overwhelm"
    assert red == False
    print("✓ test_doji_rejected passed")


def test_no_opposite_candle():
    """If no opposite candle in lookback, no overwhelm."""
    # All green bars — no red to overwhelm
    bars = make_bars([
        (100, 101, 99.5, 100.5),
        (100.5, 101.5, 100, 101),
        (101, 102, 100.5, 101.5),
        (101.5, 102.5, 101, 102),
        (102, 103, 101.5, 102.5),
        (102.5, 103.5, 102, 103),
        (103, 104, 102.5, 103.5),
        (103.5, 104.5, 103, 104),
        (104, 105, 103.5, 104.5),
        (104.5, 105.5, 104, 105),
        (105, 106, 104.5, 105.5),
        (105.5, 107, 105, 106.5),
    ])
    green, red = detect_overwhelm(bars)
    assert green == False, "No red candle to overwhelm"
    print("✓ test_no_opposite_candle passed")


def test_vwap_cross():
    """VWAP cross detection."""
    bars = [{"close": 100.5}, {"close": 99.5}]
    below, above = detect_vwap_cross(bars, 100.0)
    assert below == True, "Should detect cross below VWAP"
    assert above == False

    bars = [{"close": 99.5}, {"close": 100.5}]
    below, above = detect_vwap_cross(bars, 100.0)
    assert below == False
    assert above == True, "Should detect cross above VWAP"
    print("✓ test_vwap_cross passed")


def test_vwap_calculation():
    """VWAP from bars."""
    bars = [
        {"high": 101, "low": 99, "close": 100, "volume": 100},
        {"high": 102, "low": 100, "close": 101, "volume": 200},
    ]
    vwap = calc_vwap_from_bars(bars)
    # HLC3 bar1 = (101+99+100)/3 = 100.0, vol=100
    # HLC3 bar2 = (102+100+101)/3 = 101.0, vol=200
    # VWAP = (100*100 + 101*200) / (100+200) = 30200/300 = 100.667
    assert abs(vwap - 100.667) < 0.01, f"VWAP should be ~100.667, got {vwap}"
    print("✓ test_vwap_calculation passed")


def test_parse_oanda_candles():
    """Oanda candle parsing."""
    raw = [
        {"complete": True, "mid": {"o": "1.10", "h": "1.11", "l": "1.09", "c": "1.105"}, "volume": 500, "time": "123456"},
        {"complete": False, "mid": {"o": "1.105", "h": "1.11", "l": "1.10", "c": "1.108"}, "volume": 100, "time": "123457"},
    ]
    bars = parse_oanda_candles(raw)
    assert len(bars) == 1, "Should only include completed candles"
    assert bars[0]["open"] == 1.10
    assert bars[0]["close"] == 1.105
    print("✓ test_parse_oanda_candles passed")


if __name__ == "__main__":
    test_green_overwhelm()
    test_red_overwhelm()
    test_doji_rejected()
    test_no_opposite_candle()
    test_vwap_cross()
    test_vwap_calculation()
    test_parse_oanda_candles()
    print("\n✓ All tests passed!")
