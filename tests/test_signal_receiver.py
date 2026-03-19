"""Tests for signal_receiver — signal parsing and mock mode."""

import json
import tempfile
from pathlib import Path

from lumisignals.signal_receiver import _parse_signal, _extract_signals_from_response, run_mock


class TestParseSignal:
    def test_basic_signal(self):
        data = {
            "action": "BUY",
            "symbol": "EURUSD",
            "entry": 1.0850,
            "stop": 1.0800,
            "target": 1.0950,
            "timeframe": "15",
            "rr": 2.0,
        }
        sig = _parse_signal(data)
        assert sig.action == "BUY"
        assert sig.symbol == "EURUSD"
        assert sig.entry == 1.0850
        assert sig.stop == 1.0800
        assert sig.target == 1.0950
        assert sig.risk_reward == 2.0

    def test_normalizes_symbol(self):
        data = {"action": "sell", "symbol": "eur/usd", "entry": 1.0, "stop": 1.0, "target": 1.0}
        sig = _parse_signal(data)
        assert sig.action == "SELL"
        assert sig.symbol == "EURUSD"

    def test_risk_reward_alias(self):
        data = {"action": "BUY", "symbol": "GBPUSD", "entry": 1.0, "stop": 1.0, "target": 1.0, "risk_reward": 3.0}
        sig = _parse_signal(data)
        assert sig.risk_reward == 3.0

    def test_optional_fields_default(self):
        data = {"action": "BUY", "symbol": "AUDUSD", "entry": 0.65, "stop": 0.64, "target": 0.67}
        sig = _parse_signal(data)
        assert sig.timeframe == ""
        assert sig.signal_version == "Fib1"
        assert sig.target_num == 1

    def test_partner_api_format(self):
        """Test parsing LumiTrade Partner API top-tickers format."""
        data = {
            "ticker": "EURUSD",
            "entry": 1.0850,
            "target": 1.0950,
            "stoploss": 1.0800,
            "reward_risk_ratio": 2.0,
            "timeframe": "hourly",
            "market_type": "forex",
            "market_label": "fx",
        }
        sig = _parse_signal(data)
        assert sig.symbol == "EURUSD"
        assert sig.stop == 1.0800
        assert sig.risk_reward == 2.0
        assert sig.action == "BUY"  # inferred: stop < entry
        assert sig.timeframe == "hourly"

    def test_partner_api_sell_inferred(self):
        """Action inferred as SELL when stop > entry."""
        data = {"ticker": "GBPUSD", "entry": 1.265, "target": 1.255, "stoploss": 1.270}
        sig = _parse_signal(data)
        assert sig.action == "SELL"

    def test_validation_errors(self):
        data = {"action": "HOLD", "symbol": "", "entry": -1, "stop": 0, "target": 0}
        sig = _parse_signal(data)
        errors = sig.validate()
        assert len(errors) >= 3  # bad action, no symbol, bad prices


class TestExtractSignals:
    def test_plain_list(self):
        payload = [{"ticker": "SPY", "entry": 530}]
        result = _extract_signals_from_response(payload)
        assert len(result) == 1

    def test_partner_api_response(self):
        payload = {
            "success": True,
            "data": {
                "equity": [{"ticker": "SPY", "entry": 530}],
                "fx": [
                    {"ticker": "EURUSD", "entry": 1.085},
                    {"ticker": "GBPUSD", "entry": 1.265},
                ],
                "crypto": [],
                "futures": [],
            },
        }
        # No filter — returns all
        result = _extract_signals_from_response(payload)
        assert len(result) == 3

        # Filter to fx only
        result = _extract_signals_from_response(payload, market_filter="fx")
        assert len(result) == 2
        assert result[0]["ticker"] == "EURUSD"

    def test_generic_signals_key(self):
        payload = {"signals": [{"action": "BUY", "symbol": "EURUSD"}]}
        result = _extract_signals_from_response(payload)
        assert len(result) == 1


class TestRunMock:
    def test_processes_all_signals(self):
        signals_data = [
            {"action": "BUY", "symbol": "EURUSD", "entry": 1.085, "stop": 1.08, "target": 1.095},
            {"action": "SELL", "symbol": "GBPUSD", "entry": 1.265, "stop": 1.27, "target": 1.255},
        ]
        received = []

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(signals_data, f)
            f.flush()
            run_mock(f.name, lambda sig: received.append(sig))

        assert len(received) == 2
        assert received[0].action == "BUY"
        assert received[1].action == "SELL"

    def test_missing_file(self):
        received = []
        run_mock("/nonexistent/file.json", lambda sig: received.append(sig))
        assert len(received) == 0
