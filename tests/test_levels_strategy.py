"""Tests for levels_strategy — three-phase institutional top-down pipeline."""

import threading
import time
from unittest.mock import MagicMock, patch

from lumisignals.candle_classifier import CandleData, CandleClassification
from lumisignals.levels_strategy import (
    LevelsStrategy, ZoneEntry, TriggerResult,
    DEMAND_PATTERNS, SUPPLY_PATTERNS, OANDA_GRANULARITY,
)


def _make_strategy(**overrides):
    """Create a LevelsStrategy with mocked dependencies."""
    from lumisignals.levels_strategy import ModelConfig
    oanda = MagicMock()
    snr = MagicMock()
    # Default test model uses daily zones (like old behavior)
    test_model = ModelConfig(
        name="test",
        trigger_tf="5m",
        zone_tfs=["1d", "1w", "1mo"],
        bias_tf="1d",
        bias_candle_tfs=["1d", "1w", "1mo"],
        risk_percent=1.0,
        zone_tolerance_pct={"1d": 0.003, "1w": 0.006, "1mo": 0.009},
        min_score=overrides.pop("min_score", 50),
        min_risk_reward=overrides.pop("min_risk_reward", 1.5),
        atr_stop_multiplier=overrides.pop("atr_stop_multiplier", 1.0),
        watchlist_interval=overrides.pop("watchlist_interval", 300),
        monitor_interval=overrides.pop("monitor_interval", 30),
    )
    defaults = dict(
        oanda_client=oanda,
        snr_client=snr,
        trade_builder_url="https://app.lumitrade.ai/api/v1",
        api_key="test_key",
        model=test_model,
        on_signal=MagicMock(),
    )
    defaults.update(overrides)
    return LevelsStrategy(**defaults)


def _make_zone(**overrides):
    """Create a ZoneEntry with sensible defaults."""
    defaults = dict(
        instrument="EUR_USD",
        zone_timeframe="1d",
        zone_type="demand",
        zone_price=1.08000,
        bias_score=73.0,
        trends={"Monthly": "bullish", "Weekly": "bullish", "Daily": "bearish"},
        candle_summary="Monthly: Hammer (bullish) | Weekly: Engulfing (bullish)",
        atr=0.00823,
        status="watching",
    )
    defaults.update(overrides)
    return ZoneEntry(**defaults)


# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

class TestConstants:
    def test_oanda_granularity_has_ltf(self):
        assert "5m" in OANDA_GRANULARITY
        assert "15m" in OANDA_GRANULARITY
        assert "30m" in OANDA_GRANULARITY
        assert OANDA_GRANULARITY["5m"] == "M5"

    def test_demand_patterns_are_bullish(self):
        assert "CDLHAMMER" in DEMAND_PATTERNS
        assert "CDLENGULFING" in DEMAND_PATTERNS
        assert "CDLMORNINGSTAR" in DEMAND_PATTERNS
        assert "CDLSHOOTINGSTAR" not in DEMAND_PATTERNS

    def test_supply_patterns_are_bearish(self):
        assert "CDLSHOOTINGSTAR" in SUPPLY_PATTERNS
        assert "CDLEVENINGSTAR" in SUPPLY_PATTERNS
        assert "CDLHAMMER" not in SUPPLY_PATTERNS

    def test_shared_patterns_in_both(self):
        # Engulfing and Harami can be bullish or bearish
        assert "CDLENGULFING" in DEMAND_PATTERNS
        assert "CDLENGULFING" in SUPPLY_PATTERNS
        assert "CDLHARAMI" in DEMAND_PATTERNS
        assert "CDLHARAMI" in SUPPLY_PATTERNS


# ------------------------------------------------------------------
# ZoneEntry dataclass
# ------------------------------------------------------------------

class TestZoneEntry:
    def test_demand_sets_buy(self):
        z = _make_zone(zone_type="demand")
        assert z.trade_direction == "BUY"

    def test_supply_sets_sell(self):
        z = _make_zone(zone_type="supply")
        assert z.trade_direction == "SELL"

    def test_default_status_is_watching(self):
        z = _make_zone()
        assert z.status == "watching"
        assert z.visit_count == 0


# ------------------------------------------------------------------
# Phase 2: Zone Monitor
# ------------------------------------------------------------------

class TestMonitorZones:
    def test_activate_zone_when_price_within_tolerance(self):
        strat = _make_strategy()
        zone = _make_zone(zone_price=1.08000, status="watching")
        strat._watchlist = [zone]

        # Price is very close to zone (within 0.15% activation tolerance)
        strat._batch_get_prices = MagicMock(return_value={"EUR_USD": 1.08010})

        strat._monitor_zones()
        assert zone.status == "activated"
        assert zone.activated_at > 0

    def test_stay_watching_when_price_far(self):
        strat = _make_strategy()
        zone = _make_zone(zone_price=1.08000, status="watching")
        strat._watchlist = [zone]

        # Price is far from zone
        strat._batch_get_prices = MagicMock(return_value={"EUR_USD": 1.09000})

        strat._monitor_zones()
        assert zone.status == "watching"

    def test_deactivate_when_price_moves_away(self):
        strat = _make_strategy()
        zone = _make_zone(zone_price=1.08000, status="activated")
        zone.activated_at = time.time()
        strat._watchlist = [zone]

        # Price moved well beyond outer tolerance (0.3%)
        strat._batch_get_prices = MagicMock(return_value={"EUR_USD": 1.09000})

        strat._monitor_zones()
        assert zone.status == "watching"
        assert zone.visit_count == 1

    def test_timeout_deactivates_zone(self):
        strat = _make_strategy(zone_timeout=100)
        zone = _make_zone(zone_price=1.08000, status="activated")
        zone.activated_at = time.time() - 200  # Activated 200s ago, timeout is 100s
        strat._watchlist = [zone]

        # Price still near zone
        strat._batch_get_prices = MagicMock(return_value={"EUR_USD": 1.08010})

        strat._monitor_zones()
        assert zone.status == "watching"
        assert zone.visit_count == 1

    def test_empty_watchlist_is_noop(self):
        strat = _make_strategy()
        strat._watchlist = []
        strat._monitor_zones()  # Should not raise


# ------------------------------------------------------------------
# Phase 3: Execution Trigger
# ------------------------------------------------------------------

class TestCheckTriggers:
    def test_no_activated_zones_is_noop(self):
        strat = _make_strategy()
        strat._watchlist = [_make_zone(status="watching")]
        strat._check_triggers()  # Should not raise or call anything

    @patch("lumisignals.levels_strategy.classify_for_zone")
    def test_trigger_fires_on_matching_pattern(self, mock_classify):
        strat = _make_strategy()
        zone = _make_zone(zone_type="demand", status="activated", bias_score=73)
        zone.activated_at = time.time()
        strat._watchlist = [zone]

        # Mock candle data
        candles = [
            CandleData(1.0790, 1.0800, 1.0785, 1.0795),
            CandleData(1.0795, 1.0810, 1.0790, 1.0805),
            CandleData(1.0805, 1.0815, 1.0800, 1.0812),
        ]
        strat._get_candles = MagicMock(return_value=candles)

        # Mock classification — bullish pattern at demand zone
        mock_classify.return_value = CandleClassification(
            direction="bullish", pattern="Hammer", strength=0.8,
            body_pct=0.3, upper_wick_pct=0.1, lower_wick_pct=0.6,
        )

        # Mock target finding — must give R:R >= 1.5
        # Entry ~1.0812, stop ~1.07177, risk ~0.00943, need reward >= 0.01415
        strat._find_target = MagicMock(return_value=1.10000)

        strat._check_triggers()

        assert zone.status == "triggered"
        assert strat.on_signal.called

    @patch("lumisignals.levels_strategy.classify_for_zone")
    def test_no_trigger_when_pattern_direction_wrong(self, mock_classify):
        strat = _make_strategy()
        zone = _make_zone(zone_type="demand", status="activated")
        zone.activated_at = time.time()
        strat._watchlist = [zone]

        candles = [
            CandleData(1.0790, 1.0800, 1.0785, 1.0795),
            CandleData(1.0795, 1.0810, 1.0790, 1.0805),
            CandleData(1.0805, 1.0815, 1.0800, 1.0812),
        ]
        strat._get_candles = MagicMock(return_value=candles)

        # Bearish pattern at a demand zone — should NOT trigger
        mock_classify.return_value = CandleClassification(
            direction="bearish", pattern="Shooting Star", strength=0.8,
            body_pct=0.3, upper_wick_pct=0.6, lower_wick_pct=0.1,
        )

        strat._check_triggers()
        assert zone.status == "activated"  # Not triggered
        assert not strat.on_signal.called

    @patch("lumisignals.levels_strategy.classify_for_zone")
    def test_no_trigger_when_no_pattern(self, mock_classify):
        strat = _make_strategy()
        zone = _make_zone(zone_type="supply", status="activated")
        zone.activated_at = time.time()
        strat._watchlist = [zone]

        candles = [
            CandleData(1.0790, 1.0800, 1.0785, 1.0795),
            CandleData(1.0795, 1.0810, 1.0790, 1.0805),
            CandleData(1.0805, 1.0815, 1.0800, 1.0812),
        ]
        strat._get_candles = MagicMock(return_value=candles)
        mock_classify.return_value = None  # No matching pattern

        strat._check_triggers()
        assert zone.status == "activated"
        assert not strat.on_signal.called

    @patch("lumisignals.levels_strategy.classify_for_zone")
    def test_reject_low_rr(self, mock_classify):
        strat = _make_strategy(min_risk_reward=2.0)
        zone = _make_zone(zone_type="demand", status="activated", atr=0.01)
        zone.activated_at = time.time()
        strat._watchlist = [zone]

        candles = [
            CandleData(1.0790, 1.0800, 1.0785, 1.0795),
            CandleData(1.0795, 1.0810, 1.0790, 1.0805),
            CandleData(1.0805, 1.0815, 1.0800, 1.0812),
        ]
        strat._get_candles = MagicMock(return_value=candles)
        mock_classify.return_value = CandleClassification(
            direction="bullish", pattern="Hammer", strength=0.8,
            body_pct=0.3, upper_wick_pct=0.1, lower_wick_pct=0.6,
        )

        # Target very close to entry — bad R:R
        strat._find_target = MagicMock(return_value=1.0815)

        strat._check_triggers()
        assert zone.status == "activated"  # Not triggered due to low R:R
        assert not strat.on_signal.called


# ------------------------------------------------------------------
# Signal metadata
# ------------------------------------------------------------------

class TestFireTrigger:
    def test_signal_metadata_has_trigger_fields(self):
        strat = _make_strategy()
        zone = _make_zone(
            zone_type="demand", bias_score=73.3,
            trends={"Monthly": "bullish", "Weekly": "bullish", "Daily": "bearish"},
        )
        trigger = TriggerResult(
            zone=zone,
            trigger_timeframe="5m",
            trigger_pattern="Bullish Engulfing",
            trigger_direction="bullish",
            entry=1.08120,
            stop=1.07177,
            target=1.09500,
            risk_reward=1.46,
        )

        strat._fire_trigger(trigger)

        assert strat.on_signal.called
        call_args = strat.on_signal.call_args
        signal = call_args[0][0]
        meta = call_args[1]["extra_meta"]

        assert signal.action == "BUY"
        assert signal.entry == 1.08120
        assert meta["strategy"] == "levels-test"
        assert meta["trigger_timeframe"] == "5m"
        assert meta["trigger_pattern"] == "Bullish Engulfing"
        assert meta["zone_timeframe"] == "Daily"
        assert meta["zone_type"] == "demand"
        assert meta["bias_score"] == 73.3
        assert "zone_visit_count" in meta

    def test_dedup_prevents_double_fire(self):
        strat = _make_strategy()
        zone = _make_zone()
        trigger = TriggerResult(
            zone=zone, trigger_timeframe="5m", trigger_pattern="Hammer",
            trigger_direction="bullish", entry=1.081, stop=1.071,
            target=1.095, risk_reward=1.4,
        )

        strat._fire_trigger(trigger)
        assert strat.on_signal.call_count == 1

        # Second fire with same zone — should be deduped
        zone2 = _make_zone()
        trigger2 = TriggerResult(
            zone=zone2, trigger_timeframe="5m", trigger_pattern="Hammer",
            trigger_direction="bullish", entry=1.081, stop=1.071,
            target=1.095, risk_reward=1.4,
        )
        strat._fire_trigger(trigger2)
        assert strat.on_signal.call_count == 1  # Still 1


# ------------------------------------------------------------------
# Phase 1: Watchlist (integration-level with mocks)
# ------------------------------------------------------------------

class TestRefreshWatchlist:
    def test_builds_watchlist_from_snr_levels(self):
        strat = _make_strategy(min_score=0)  # Low threshold to allow any zone

        # Mock price
        strat._get_current_price = MagicMock(return_value=1.08050)

        # Mock SNR levels
        strat.snr_client.get_snr_levels.return_value = {
            "1d": {"support_price": 1.08000, "resistance_price": 1.09500},
            "1w": {"support_price": 1.07500, "resistance_price": 1.10000},
            "1mo": {"support_price": 1.06000, "resistance_price": 1.12000},
        }

        # Mock Trade Builder
        strat._get_trade_builder_data = MagicMock(return_value={
            "atr": 0.00823,
            "trends": {"Monthly": "bullish", "Weekly": "bullish", "Daily": "bullish"},
        })

        # Mock candles
        candle_series = [
            CandleData(1.078, 1.085, 1.076, 1.083),
            CandleData(1.083, 1.090, 1.081, 1.088),
            CandleData(1.088, 1.092, 1.085, 1.090),
        ]
        strat._get_candles = MagicMock(return_value=candle_series)

        strat._refresh_watchlist(pairs=["EUR_USD"])

        # Should have at least the daily demand zone (price near 1.08000)
        assert len(strat._watchlist) > 0
        demand_zones = [z for z in strat._watchlist if z.zone_type == "demand"]
        assert len(demand_zones) > 0
        assert demand_zones[0].instrument == "EUR_USD"
        assert demand_zones[0].atr == 0.00823

    def test_preserves_activated_state_on_refresh(self):
        strat = _make_strategy(min_score=0)

        # Seed an activated zone
        old_zone = _make_zone(status="activated", visit_count=2)
        old_zone.activated_at = 12345.0
        strat._watchlist = [old_zone]

        # Mock everything to rebuild the same zone
        strat._get_current_price = MagicMock(return_value=1.08050)
        strat.snr_client.get_snr_levels.return_value = {
            "1d": {"support_price": 1.08000, "resistance_price": 1.09500},
        }
        strat._get_trade_builder_data = MagicMock(return_value={
            "atr": 0.00823,
            "trends": {"Monthly": "bullish", "Weekly": "bullish", "Daily": "bullish"},
        })
        candles = [
            CandleData(1.078, 1.085, 1.076, 1.083),
            CandleData(1.083, 1.090, 1.081, 1.088),
            CandleData(1.088, 1.092, 1.085, 1.090),
        ]
        strat._get_candles = MagicMock(return_value=candles)

        strat._refresh_watchlist(pairs=["EUR_USD"])

        matching = [z for z in strat._watchlist
                    if z.zone_type == "demand" and z.zone_timeframe == "1d"]
        assert len(matching) > 0
        assert matching[0].status == "activated"
        assert matching[0].visit_count == 2
        assert matching[0].activated_at == 12345.0

    def test_skips_zones_below_min_score(self):
        strat = _make_strategy(min_score=90)

        strat._get_current_price = MagicMock(return_value=1.08050)
        strat.snr_client.get_snr_levels.return_value = {
            "1d": {"support_price": 1.08000, "resistance_price": 1.09500},
        }
        # Only 1/3 trends agree — score will be ~20 + candle component
        strat._get_trade_builder_data = MagicMock(return_value={
            "atr": 0.00823,
            "trends": {"Monthly": "bearish", "Weekly": "bearish", "Daily": "bullish"},
        })
        candles = [
            CandleData(1.078, 1.085, 1.076, 1.083),
            CandleData(1.083, 1.090, 1.081, 1.088),
            CandleData(1.088, 1.092, 1.085, 1.090),
        ]
        strat._get_candles = MagicMock(return_value=candles)

        strat._refresh_watchlist(pairs=["EUR_USD"])

        # With score threshold at 90, demand zones (BUY) should be filtered out
        # because only 1/3 trends are bullish
        demand_zones = [z for z in strat._watchlist if z.zone_type == "demand"]
        assert len(demand_zones) == 0


# ------------------------------------------------------------------
# Run loop
# ------------------------------------------------------------------

class TestRunLoop:
    def test_run_calls_all_phases(self):
        strat = _make_strategy(watchlist_interval=30, monitor_interval=30)
        strat._refresh_watchlist = MagicMock()
        strat._monitor_zones = MagicMock()
        strat._check_triggers = MagicMock()

        stop = threading.Event()

        # Set the stop event after the first wait() call
        original_wait = stop.wait

        def stop_after_first(timeout=None):
            stop.set()
            return True

        stop.wait = stop_after_first

        strat.run(stop_event=stop)

        strat._refresh_watchlist.assert_called_once()
        strat._monitor_zones.assert_called_once()
        strat._check_triggers.assert_called_once()

    def test_watchlist_only_refreshes_on_interval(self):
        strat = _make_strategy(watchlist_interval=90, monitor_interval=30)
        strat._refresh_watchlist = MagicMock()
        strat._monitor_zones = MagicMock()
        strat._check_triggers = MagicMock()

        # ticks_per_watchlist = 90 // 30 = 3
        # So watchlist refreshes on tick 0, 3, 6, ...
        tick_count = 0
        stop = threading.Event()

        def stop_after_ticks(timeout=None):
            nonlocal tick_count
            tick_count += 1
            if tick_count >= 4:
                stop.set()
            return stop.is_set()

        stop.wait = stop_after_ticks

        strat.run(stop_event=stop)

        # Phase 1 should refresh on tick 0 and tick 3 = 2 times
        assert strat._refresh_watchlist.call_count == 2
        # Phase 2+3 called every tick; stop fires after tick 3's wait, so 4 ticks run
        assert strat._monitor_zones.call_count == 4


# ------------------------------------------------------------------
# classify_for_zone (candle_classifier)
# ------------------------------------------------------------------

class TestClassifyForZone:
    def test_returns_none_without_talib(self):
        from lumisignals.candle_classifier import classify_for_zone, HAS_TALIB
        candles = [
            CandleData(1.08, 1.085, 1.078, 1.083),
            CandleData(1.083, 1.09, 1.081, 1.088),
        ]
        if not HAS_TALIB:
            result = classify_for_zone(candles, "demand")
            assert result is None

    def test_returns_none_for_too_few_candles(self):
        from lumisignals.candle_classifier import classify_for_zone
        candles = [CandleData(1.08, 1.085, 1.078, 1.083)]
        result = classify_for_zone(candles, "demand")
        assert result is None
