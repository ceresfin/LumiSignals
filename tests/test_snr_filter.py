"""Tests for snr_filter — timeframe mapping and confluence detection."""

from lumisignals.snr_filter import get_relevant_timeframes, check_snr_confluence


class TestGetRelevantTimeframes:
    def test_5m_trader(self):
        primary, alerts = get_relevant_timeframes("5m")
        assert "15m" in primary
        assert "30m" in primary
        assert "1h" in primary
        assert "1mo" in alerts
        assert "1w" in alerts
        assert "1d" in alerts

    def test_15m_trader(self):
        primary, alerts = get_relevant_timeframes("15m")
        assert "30m" in primary
        assert "1h" in primary
        assert "1mo" in alerts
        assert "1w" in alerts
        assert "1d" in alerts

    def test_30m_trader(self):
        primary, alerts = get_relevant_timeframes("30m")
        assert "1h" in primary
        assert "4h" in primary
        assert "1d" in alerts

    def test_1h_trader(self):
        primary, alerts = get_relevant_timeframes("1h")
        assert "4h" in primary
        assert "1mo" in alerts
        assert "1w" in alerts
        assert "1d" in alerts

    def test_4h_trader(self):
        primary, alerts = get_relevant_timeframes("4h")
        assert primary == []  # all relevant levels are alert levels
        assert "1mo" in alerts
        assert "1w" in alerts
        assert "1d" in alerts

    def test_daily_trader(self):
        primary, alerts = get_relevant_timeframes("1d")
        assert primary == []
        assert "1mo" in alerts
        assert "1w" in alerts

    def test_alias_1H(self):
        primary, alerts = get_relevant_timeframes("1H")
        assert "4h" in primary

    def test_alias_daily(self):
        primary, alerts = get_relevant_timeframes("daily")
        assert "1mo" in alerts
        assert "1w" in alerts

    def test_alert_levels_always_include_monthly_weekly_daily(self):
        """For any sub-daily timeframe, alerts must include monthly, weekly, daily."""
        for tf in ["5m", "15m", "30m", "1h", "4h"]:
            _, alerts = get_relevant_timeframes(tf)
            assert "1mo" in alerts, f"monthly missing for {tf}"
            assert "1w" in alerts, f"weekly missing for {tf}"
            assert "1d" in alerts, f"daily missing for {tf}"


class TestCheckSNRConfluence:
    def test_buy_entry_at_support(self):
        """BUY signal with entry near daily support = alert confluence."""
        snr_data = {
            "1d": {"ticker": "EURUSD", "support_price": 1.0850, "resistance_price": 1.0950},
        }
        result = check_snr_confluence(
            entry=1.0851, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=["4h"], alert_tfs=["1d", "1w", "1mo"],
        )
        assert result["has_alert_confluence"]
        assert result["grade"] == "A"
        assert len(result["alert_matches"]) >= 1
        assert result["alert_matches"][0]["role"] == "entry_at_demand"

    def test_buy_target_at_resistance(self):
        """BUY signal with target near weekly resistance."""
        snr_data = {
            "1w": {"ticker": "EURUSD", "support_price": 1.0700, "resistance_price": 1.0952},
        }
        result = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=["4h"], alert_tfs=["1d", "1w", "1mo"],
        )
        assert result["has_alert_confluence"]
        assert any(m["role"] == "target_at_supply" for m in result["alert_matches"])

    def test_sell_entry_at_resistance(self):
        """SELL signal with entry near resistance."""
        snr_data = {
            "4h": {"ticker": "GBPUSD", "support_price": 1.2550, "resistance_price": 1.2650},
        }
        result = check_snr_confluence(
            entry=1.2651, stop=1.2700, target=1.2550, action="SELL",
            snr_data=snr_data, primary_tfs=["4h"], alert_tfs=["1d", "1w", "1mo"],
        )
        assert result["has_primary_confluence"]
        assert result["grade"] == "B"

    def test_grade_a_plus(self):
        """Both primary and alert confluence = A+."""
        snr_data = {
            "4h": {"ticker": "EURUSD", "support_price": 1.0850, "resistance_price": 1.1000},
            "1w": {"ticker": "EURUSD", "support_price": 1.0849, "resistance_price": 1.1100},
        }
        result = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=["4h"], alert_tfs=["1d", "1w", "1mo"],
        )
        assert result["grade"] == "A+"

    def test_no_confluence(self):
        """Signal far from all S/R levels = grade C."""
        snr_data = {
            "1d": {"ticker": "EURUSD", "support_price": 1.0500, "resistance_price": 1.1200},
        }
        result = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=["4h"], alert_tfs=["1d", "1w", "1mo"],
        )
        assert not result["has_primary_confluence"]
        assert not result["has_alert_confluence"]
        assert result["grade"] == "C"

    def test_empty_snr_data(self):
        result = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data={}, primary_tfs=["4h"], alert_tfs=["1d"],
        )
        assert result["grade"] == "C"

    def test_custom_tolerance(self):
        """Tight tolerance should miss levels that wider tolerance catches."""
        snr_data = {
            "1d": {"ticker": "EURUSD", "support_price": 1.0830, "resistance_price": 1.1000},
        }
        # 0.2% of 1.085 = 0.00217 — support at 1.083 is 0.002 away, within tolerance
        wide = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=[], alert_tfs=["1d"],
            tolerance_pct=0.002,
        )
        # 0.05% of 1.085 = 0.000542 — too tight
        tight = check_snr_confluence(
            entry=1.0850, stop=1.0800, target=1.0950, action="BUY",
            snr_data=snr_data, primary_tfs=[], alert_tfs=["1d"],
            tolerance_pct=0.0005,
        )
        assert wide["has_alert_confluence"]
        assert not tight["has_alert_confluence"]
