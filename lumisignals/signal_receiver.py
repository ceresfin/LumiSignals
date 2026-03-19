"""Signal intake — polling, webhook, and mock modes."""

import json
import logging
import time
from pathlib import Path
from typing import Callable, Union

import requests

from .models import Signal

logger = logging.getLogger(__name__)


def _parse_signal(data: dict) -> Signal:
    """Parse a JSON dict into a Signal object.

    Supports both the legacy webhook format and the LumiTrade Partner API
    top-tickers format (ticker/stoploss/reward_risk_ratio fields).
    """
    # Resolve field names — Partner API uses "ticker"/"stoploss"/"reward_risk_ratio"
    symbol = data.get("symbol", data.get("ticker", ""))
    stop = float(data.get("stop", data.get("stoploss", 0)))
    rr = float(data.get("rr", data.get("risk_reward", data.get("reward_risk_ratio", 0))))
    entry = float(data.get("entry", 0))
    target = float(data.get("target", 0))

    # If action is missing, infer from entry vs stop
    action = data.get("action", "")
    if not action and entry > 0 and stop > 0:
        action = "BUY" if stop < entry else "SELL"

    return Signal(
        action=action,
        symbol=symbol,
        entry=entry,
        stop=stop,
        target=target,
        timeframe=data.get("timeframe", data.get("frequency", "")),
        risk_reward=rr,
        target_num=int(data.get("target_num", 1)),
        signal_version=data.get("signal_version", "Fib1"),
        duration=data.get("duration", ""),
        momentum=data.get("momentum", ""),
    )


# ---------------------------------------------------------------------------
# Polling mode
# ---------------------------------------------------------------------------

def _extract_signals_from_response(payload: Union[dict, list], market_filter: str = "") -> list:
    """Extract signal dicts from various API response formats.

    Handles:
    - Plain list of signals
    - {"signals": [...]}
    - LumiTrade Partner API: {"data": {"fx": [...], "equity": [...], ...}}
    """
    if isinstance(payload, list):
        return payload

    # LumiTrade Partner API top-tickers format
    # Response may be {"data": {"success": true, "data": {"fx": [...], ...}}}
    data = payload.get("data")
    if isinstance(data, dict):
        # Handle double-nested data from Partner API
        inner = data.get("data", data)
        if isinstance(inner, dict):
            signals = []
            for market, items in inner.items():
                if market in ("success", "message"):
                    continue
                if market_filter and market != market_filter:
                    continue
                if isinstance(items, list):
                    signals.extend(items)
            if signals:
                return signals

    # Generic formats
    return payload.get("signals", [])


def run_polling(api_url: str, api_key: str, interval: int, on_signal: Callable[[Signal], None],
                stop_event=None, market_filter: str = "", min_rr: float = 0):
    """Poll an API endpoint for new signals.

    Args:
        api_url: URL to poll for signals.
        api_key: API key sent as Authorization header.
        interval: Seconds between polls.
        on_signal: Callback invoked for each new signal.
        stop_event: threading.Event — set to stop the loop.
        market_filter: Only process signals from this market (e.g. "fx"). Empty = all.
        min_rr: Minimum reward/risk ratio to accept. 0 = no filter.
    """
    logger.info("Polling %s every %ds", api_url, interval)
    seen_ids: set[str] = set()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    while stop_event is None or not stop_event.is_set():
        try:
            resp = requests.get(api_url, headers=headers, timeout=30)
            resp.raise_for_status()
            payload = resp.json()

            signals = _extract_signals_from_response(payload, market_filter)
            for item in signals:
                sig_id = item.get("id", json.dumps(item, sort_keys=True))
                if sig_id not in seen_ids:
                    seen_ids.add(sig_id)
                    signal = _parse_signal(item)
                    if min_rr and signal.risk_reward < min_rr:
                        logger.debug("Skipping %s %s — R:R %.1f below minimum %.1f",
                                     signal.action, signal.symbol, signal.risk_reward, min_rr)
                        continue
                    logger.info("New signal via polling: %s %s", signal.action, signal.symbol)
                    on_signal(signal)
        except Exception as e:
            logger.error("Polling error: %s", e)

        if stop_event is not None:
            stop_event.wait(interval)
        else:
            time.sleep(interval)


# ---------------------------------------------------------------------------
# Webhook mode
# ---------------------------------------------------------------------------

def create_webhook_app(on_signal: Callable[[Signal], None], webhook_secret: str = None):
    """Create a Flask app that receives webhook signals.

    Args:
        on_signal: Callback invoked for each received signal.
        webhook_secret: Optional secret to validate incoming requests.

    Returns:
        A Flask application.
    """
    from flask import Flask, request, jsonify

    app = Flask("lumisignals_webhook")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"})

    @app.route("/webhook", methods=["POST"])
    def webhook():
        payload = request.get_json(force=True)

        if webhook_secret and payload.get("secret") != webhook_secret:
            return jsonify({"error": "Unauthorized"}), 401

        try:
            signal = _parse_signal(payload)
            errors = signal.validate()
            if errors:
                return jsonify({"error": "; ".join(errors)}), 400

            logger.info("New signal via webhook: %s %s", signal.action, signal.symbol)
            on_signal(signal)
            return jsonify({"received": True, "action": signal.action, "symbol": signal.symbol})
        except Exception as e:
            logger.error("Webhook processing error: %s", e)
            return jsonify({"error": str(e)}), 500

    return app


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

def run_mock(mock_file: str, on_signal: Callable[[Signal], None]):
    """Read signals from a local JSON file and process them.

    Args:
        mock_file: Path to a JSON file containing a list of signal objects.
        on_signal: Callback invoked for each signal.
    """
    path = Path(mock_file)
    if not path.exists():
        logger.error("Mock file not found: %s", mock_file)
        return

    data = json.loads(path.read_text())
    signals = data if isinstance(data, list) else data.get("signals", [data])

    logger.info("Loaded %d signal(s) from %s", len(signals), mock_file)
    for item in signals:
        signal = _parse_signal(item)
        logger.info("Mock signal: %s %s @ %s", signal.action, signal.symbol, signal.entry)
        on_signal(signal)
