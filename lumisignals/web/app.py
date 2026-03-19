"""LumiSignals Web UI — local dashboard for configuring and monitoring the bot."""

import json
import logging
import os
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, render_template, request, jsonify, redirect, url_for

from ..bot import LumiSignalsBot, load_config
from ..oanda_client import OandaClient
from ..snr_filter import get_relevant_timeframes

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
CONFIG_EXAMPLE_PATH = "config.example.yaml"


def create_web_app():
    """Create the Flask web UI application."""
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.urandom(24)

    # Shared state
    state = {
        "bot": None,
        "bot_thread": None,
        "running": False,
        "log_entries": [],
        "signals_processed": 0,
        "orders_placed": 0,
        "orders_skipped": 0,
        "last_signal_time": None,
    }

    # Custom log handler to capture logs for the UI
    class WebLogHandler(logging.Handler):
        def emit(self, record):
            entry = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": record.levelname,
                "message": self.format(record),
            }
            state["log_entries"].append(entry)
            # Keep last 200 entries
            if len(state["log_entries"]) > 200:
                state["log_entries"] = state["log_entries"][-200:]

            # Track stats from log messages
            msg = record.getMessage()
            if "Processing signal:" in msg:
                state["signals_processed"] += 1
                state["last_signal_time"] = datetime.now().strftime("%H:%M:%S")
            elif "Order placed" in msg or "Would place order" in msg:
                state["orders_placed"] += 1
            elif "Skipping" in msg and "grade" in msg:
                state["orders_skipped"] += 1

    web_handler = WebLogHandler()
    web_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))

    def _get_config():
        """Load current config or return empty dict."""
        try:
            return load_config(CONFIG_PATH)
        except FileNotFoundError:
            return {}

    def _has_config():
        return Path(CONFIG_PATH).exists()

    # --- Routes ---

    @app.route("/")
    def index():
        if not _has_config():
            return redirect(url_for("setup"))
        config = _get_config()
        sig_cfg = config.get("signals", {})
        primary_tfs, alert_tfs = get_relevant_timeframes(
            sig_cfg.get("trading_timeframe", "1h")
        )
        return render_template(
            "dashboard.html",
            config=config,
            state=state,
            primary_tfs=primary_tfs,
            alert_tfs=alert_tfs,
        )

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if request.method == "POST":
            config = {
                "oanda": {
                    "account_id": request.form["oanda_account_id"].strip(),
                    "api_key": request.form["oanda_api_key"].strip(),
                    "environment": request.form["oanda_environment"],
                },
                "signals": {
                    "mode": request.form["signal_mode"],
                    "strategy": request.form["strategy"],
                    "api_url": request.form.get("api_url", "").strip()
                        or "https://app.lumitrade.ai/api/v1/partners/technical-analysis/top-tickers/",
                    "api_key": request.form.get("signal_api_key", "").strip(),
                    "poll_interval_seconds": int(request.form.get("poll_interval", 60)),
                    "market_filter": request.form.get("market_filter", "fx"),
                    "min_reward_risk": float(request.form.get("min_rr", 1.5)),
                    "trading_timeframe": request.form.get("trading_timeframe", "1h"),
                    "webhook_port": int(request.form.get("webhook_port", 8080)),
                    "webhook_secret": request.form.get("webhook_secret", ""),
                    "mock_file": "test_signals.json",
                },
                "snr": {
                    "min_grade": request.form.get("min_grade", "B"),
                    "tolerance_pct": float(request.form.get("tolerance_pct", 0.002)),
                    "market_type": request.form.get("snr_market_type", "forex"),
                },
                "risk": {
                    "risk_percent": float(request.form.get("risk_percent", 1.0)),
                    "max_position_units": int(request.form.get("max_units", 100000)),
                    "max_open_positions": int(request.form.get("max_positions", 5)),
                },
                "bot": {
                    "dry_run": "dry_run" in request.form,
                    "log_level": "INFO",
                },
            }
            with open(CONFIG_PATH, "w") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            return redirect(url_for("index"))

        existing = _get_config() if _has_config() else {}
        return render_template("setup.html", config=existing)

    @app.route("/api/test-connection", methods=["POST"])
    def test_connection():
        data = request.get_json()
        try:
            client = OandaClient(
                account_id=data["account_id"],
                api_key=data["api_key"],
                environment=data.get("environment", "practice"),
            )
            account_info = client.get_account()
            balance = account_info["account"]["balance"]
            currency = account_info["account"].get("currency", "USD")
            return jsonify({
                "success": True,
                "balance": balance,
                "currency": currency,
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    @app.route("/api/start", methods=["POST"])
    def start_bot():
        if state["running"]:
            return jsonify({"error": "Bot is already running"})

        config = _get_config()
        if not config:
            return jsonify({"error": "No config found. Complete setup first."})

        # Attach web log handler
        root_logger = logging.getLogger("lumisignals")
        root_logger.addHandler(web_handler)
        root_logger.setLevel(logging.INFO)

        # Reset stats
        state["signals_processed"] = 0
        state["orders_placed"] = 0
        state["orders_skipped"] = 0
        state["last_signal_time"] = None
        state["log_entries"] = []

        try:
            dry_run = request.get_json().get("dry_run", config.get("bot", {}).get("dry_run", False))
            bot = LumiSignalsBot(config=config, dry_run=dry_run)
            state["bot"] = bot
            state["running"] = True

            def run():
                try:
                    bot.start()
                except Exception as e:
                    logger.error("Bot crashed: %s", e)
                finally:
                    state["running"] = False

            t = threading.Thread(target=run, daemon=True)
            t.start()
            state["bot_thread"] = t

            mode_label = "DRY RUN" if dry_run else "LIVE"
            return jsonify({"success": True, "message": f"Bot started ({mode_label})"})
        except Exception as e:
            state["running"] = False
            return jsonify({"error": str(e)})

    @app.route("/api/stop", methods=["POST"])
    def stop_bot():
        if not state["running"]:
            return jsonify({"error": "Bot is not running"})

        if state["bot"]:
            state["bot"]._stop_event.set()
        state["running"] = False
        return jsonify({"success": True, "message": "Bot stopped"})

    @app.route("/api/status")
    def status():
        config = _get_config() if _has_config() else {}
        return jsonify({
            "running": state["running"],
            "dry_run": config.get("bot", {}).get("dry_run", False),
            "strategy": config.get("signals", {}).get("strategy", ""),
            "signals_processed": state["signals_processed"],
            "orders_placed": state["orders_placed"],
            "orders_skipped": state["orders_skipped"],
            "last_signal_time": state["last_signal_time"],
            "log_count": len(state["log_entries"]),
        })

    @app.route("/api/logs")
    def logs():
        since = int(request.args.get("since", 0))
        return jsonify(state["log_entries"][since:])

    return app
