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
from ..trade_tracker import get_pending_orders, get_open_trades, get_closed_trades, get_performance_stats
from ..snr_filter import get_relevant_timeframes

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
CONFIG_EXAMPLE_PATH = "config.example.yaml"


def create_web_app():
    """Create the Flask web UI application."""
    app = Flask(__name__, template_folder="templates")
    app.secret_key = os.urandom(24)

    @app.after_request
    def add_no_cache(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

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
                "levels": {
                    "min_score": int(request.form.get("levels_min_score", 50)),
                    "atr_stop_multiplier": float(request.form.get("levels_atr_stop", 1.0)),
                    "trading_timeframe": request.form.get("trading_timeframe", "1d"),
                    "zone_tolerance_daily": 0.003,
                    "zone_tolerance_weekly": 0.006,
                    "zone_tolerance_monthly": 0.009,
                    "watchlist_interval": 300,
                    "monitor_interval": 30,
                    "trigger_candle_count": 10,
                    "min_risk_reward": float(request.form.get("levels_min_rr", 1.5)),
                    "zone_timeout": 14400,
                },
                "massive": {
                    "api_key": _get_config().get("massive", {}).get("api_key", ""),
                    "stock_atr_multiplier": float(request.form.get("stock_atr_multiplier", 0.5)),
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
            req_data = request.get_json() or {}
            if "dry_run" in req_data:
                dry_run = req_data["dry_run"]
            else:
                dry_run = config.get("bot", {}).get("dry_run", False)
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
            "dry_run": state["bot"].dry_run if state["bot"] else config.get("bot", {}).get("dry_run", False),
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

    def _get_oanda_client():
        """Get an OandaClient from current config."""
        config = _get_config()
        if not config or "oanda" not in config:
            return None
        oanda_cfg = config["oanda"]
        return OandaClient(
            account_id=oanda_cfg["account_id"],
            api_key=oanda_cfg["api_key"],
            environment=oanda_cfg.get("environment", "practice"),
        )

    @app.route("/trades")
    def trades_page():
        if not _has_config():
            return redirect(url_for("setup"))
        return render_template("trades.html", config=_get_config())

    @app.route("/api/trades")
    def api_trades():
        client = _get_oanda_client()
        if not client:
            return jsonify({"error": "No Oanda config"}), 400

        pending = get_pending_orders(client)
        open_trades = get_open_trades(client)
        closed = get_closed_trades(client, count=50)
        stats = get_performance_stats(closed)

        # Get stock/crypto watchlist zones
        from ..levels_strategy import get_watchlist_snapshot
        watchlist = get_watchlist_snapshot()

        return jsonify({
            "watchlist": watchlist,
            "pending": pending,
            "open": open_trades,
            "closed": closed,
            "stats": stats,
        })

    @app.route("/api/options/<ticker>")
    def api_options(ticker):
        """Get options spread analysis for a stock in the watchlist."""
        config = _get_config()
        schwab_cfg = config.get("schwab", {})
        if not schwab_cfg.get("client_id"):
            return jsonify({"error": "No Schwab config"}), 400

        zone_type = request.args.get("zone_type", "supply")
        zone_price = float(request.args.get("zone_price", 0))
        current_price = float(request.args.get("current_price", 0))

        try:
            from ..schwab_client import SchwabAuth, SchwabMarketData
            from ..options_analyzer import analyze_spreads_at_zone, format_spread_for_display

            auth = SchwabAuth(
                client_id=schwab_cfg["client_id"],
                client_secret=schwab_cfg["client_secret"],
            )
            if not auth.get_valid_token():
                return jsonify({"error": "Schwab not authorized — run python3 schwab_auth.py"}), 401

            md = SchwabMarketData(auth)
            result = analyze_spreads_at_zone(md, ticker, zone_type, zone_price, current_price)

            return jsonify({
                "ticker": ticker,
                "zone_type": zone_type,
                "zone_price": zone_price,
                "credit_spread": format_spread_for_display(result["credit_spread"]),
                "debit_spread": format_spread_for_display(result["debit_spread"]),
                "error": result.get("error"),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app
