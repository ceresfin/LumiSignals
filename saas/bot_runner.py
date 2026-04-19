"""Standalone bot runner — runs outside gunicorn as its own process.

Checks the database for users with bot_active=True and runs their bots.
Stores watchlist data in Redis so the web app can read it.
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))

import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot_runner")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
)

rdb = redis.from_url(REDIS_URL)


def get_active_users():
    """Query database for users with bot_active=True."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, email, oanda_account_id, oanda_api_key, oanda_environment,
               massive_api_key, trading_timeframe, min_score, min_risk_reward,
               stock_atr_multiplier, dry_run,
               scalp_risk_mode, scalp_risk_value, scalp_daily_budget,
               intraday_risk_mode, intraday_risk_value, intraday_daily_budget,
               swing_risk_mode, swing_risk_value, swing_daily_budget,
               lumitrade_api_key,
               options_auto_trade, options_auto_spread_type, options_trigger_tf, options_min_verdict,
               options_max_risk_per_spread, options_max_contracts,
               options_max_total_risk, options_spread_width,
               options_min_credit_pct, options_max_spreads
        FROM users WHERE bot_active = true AND oanda_api_key IS NOT NULL
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def publish_watchlist(user_id, zones):
    """Store combined watchlist in Redis."""
    rdb.setex(f"watchlist:{user_id}", 600, json.dumps(zones))


def publish_watchlist_model(user_id, model_name, zones):
    """Store per-model watchlist in Redis."""
    rdb.setex(f"watchlist:{user_id}:{model_name}", 600, json.dumps(zones))
    # Also update combined
    all_zones = []
    for mn in ["scalp", "intraday", "swing"]:
        raw = rdb.get(f"watchlist:{user_id}:{mn}")
        if raw:
            all_zones.extend(json.loads(raw))
    rdb.setex(f"watchlist:{user_id}", 600, json.dumps(all_zones))


def publish_log(user_id, entries):
    """Store log entries in Redis."""
    rdb.setex(f"botlog:{user_id}", 600, json.dumps(entries[-100:]))


def _auto_trade_options(user_data, signal, extra_meta, model_name, log, alert_pass, email):
    """Analyze and queue options spread when a stock signal fires."""
    from lumisignals.polygon_options import analyze_spreads_polygon
    from lumisignals.ibkr_client import calculate_spread_contracts, OptionsRiskConfig

    user_id = user_data["id"]
    symbol = signal.symbol
    zone_type = (extra_meta or {}).get("zone_type", "demand" if signal.action == "BUY" else "supply")
    zone_price = (extra_meta or {}).get("zone_price", signal.entry)
    spread_pref = user_data.get("options_auto_spread_type") or "credit"
    min_verdict = user_data.get("options_min_verdict") or "good"
    allowed_verdicts = ["GOOD"] if min_verdict == "good" else ["GOOD", "FAIR"]

    massive_key = user_data.get("massive_api_key") or os.environ.get("MASSIVE_API_KEY", "")
    if not massive_key:
        log(f"[{model_name.upper()}] OPTIONS: No Polygon API key — skipping")
        return

    log(f"[{model_name.upper()}] OPTIONS: Analyzing {symbol} ({zone_type} zone @ {zone_price:.2f})")

    # Run Polygon analysis
    result = analyze_spreads_polygon(massive_key, symbol, zone_type, zone_price, signal.entry)

    if result.get("error"):
        log(f"[{model_name.upper()}] OPTIONS: Analysis error — {result['error']}")
        return

    # Build risk config from user settings
    risk_config = OptionsRiskConfig(
        max_risk_per_spread=float(user_data.get("options_max_risk_per_spread") or 200),
        max_contracts=int(user_data.get("options_max_contracts") or 5),
        max_total_risk=float(user_data.get("options_max_total_risk") or 2000),
        spread_width=float(user_data.get("options_spread_width") or 5),
        min_credit_pct=float(user_data.get("options_min_credit_pct") or 25),
        max_spreads=int(user_data.get("options_max_spreads") or 10),
    )

    orders_queued = []

    # Process credit spread
    credit = result.get("credit_spread")
    if credit and spread_pref in ("credit", "both"):
        if credit.get("verdict") in allowed_verdicts:
            is_credit = credit["net_credit"] > 0
            premium = credit["net_credit"] if is_credit else credit["net_debit"]
            width = credit["width"]

            sizing = calculate_spread_contracts(
                spread_width=width, credit_or_debit=premium,
                is_credit=is_credit, risk_config=risk_config,
            )

            if sizing["contracts"] > 0:
                order = {
                    "ticker": symbol,
                    "spread_type": credit["type"],
                    "buy_strike": credit["long_strike"],
                    "sell_strike": credit["short_strike"],
                    "right": "C" if "Call" in credit["option_type"] else "P",
                    "expiration": credit["expiration"],
                    "quantity": sizing["contracts"],
                    "limit_price": premium,
                }
                # Queue in Redis for IB sync script
                import uuid
                order_id = str(uuid.uuid4())[:8]
                order["order_id"] = order_id
                order["user_id"] = user_id
                order["status"] = "queued"
                order["auto"] = True
                rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
                orders_queued.append(f"{credit['type']} {sizing['contracts']}x @ ${premium:.2f}")
                log(f"[{model_name.upper()}] OPTIONS QUEUED: {credit['type']} {symbol} SELL {credit['short_strike']} / BUY {credit['long_strike']} x{sizing['contracts']} @ ${premium:.2f} (risk ${sizing['total_risk']:.0f})")
            else:
                log(f"[{model_name.upper()}] OPTIONS SKIP: {credit['type']} — {sizing.get('reason', 'sizing rejected')}")
        else:
            log(f"[{model_name.upper()}] OPTIONS SKIP: {credit['type']} — verdict: {credit.get('verdict')}")

    # Process debit spread
    debit = result.get("debit_spread")
    if debit and spread_pref in ("debit", "both"):
        if debit.get("verdict") in allowed_verdicts:
            is_credit = False
            premium = debit["net_debit"]
            width = debit["width"]

            sizing = calculate_spread_contracts(
                spread_width=width, credit_or_debit=premium,
                is_credit=False, risk_config=risk_config,
            )

            if sizing["contracts"] > 0:
                order = {
                    "ticker": symbol,
                    "spread_type": debit["type"],
                    "buy_strike": debit["long_strike"],
                    "sell_strike": debit["short_strike"],
                    "right": "C" if "Call" in debit["option_type"] else "P",
                    "expiration": debit["expiration"],
                    "quantity": sizing["contracts"],
                    "limit_price": premium,
                }
                import uuid
                order_id = str(uuid.uuid4())[:8]
                order["order_id"] = order_id
                order["user_id"] = user_id
                order["status"] = "queued"
                order["auto"] = True
                rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
                orders_queued.append(f"{debit['type']} {sizing['contracts']}x @ ${premium:.2f}")
                log(f"[{model_name.upper()}] OPTIONS QUEUED: {debit['type']} {symbol} BUY {debit['long_strike']} / SELL {debit['short_strike']} x{sizing['contracts']} @ ${premium:.2f} (risk ${sizing['total_risk']:.0f})")
            else:
                log(f"[{model_name.upper()}] OPTIONS SKIP: {debit['type']} — {sizing.get('reason', 'sizing rejected')}")
        else:
            log(f"[{model_name.upper()}] OPTIONS SKIP: {debit['type']} — verdict: {debit.get('verdict')}")

    # Alert on queued orders
    if orders_queued and alert_pass:
        from lumisignals.alerts import send_alert, AlertType
        send_alert(
            AlertType.TRADE_OPENED,
            f"Options queued: {symbol}",
            f"Stock signal triggered auto-options analysis. Orders queued for IB:\n" + "\n".join(orders_queued),
            details={
                "Symbol": symbol,
                "Zone": f"{zone_type} @ {zone_price:.2f}",
                "Signal": f"{signal.action} @ {signal.entry:.2f}",
                "Orders": ", ".join(orders_queued),
            },
            to_email=email, smtp_pass=alert_pass,
        )


def run_bot_for_user(user_data, stop_check):
    """Run the three-phase signal engine for a user."""
    from lumisignals.oanda_client import OandaClient
    from lumisignals.snr_filter import SNRClient
    from lumisignals.levels_strategy import LevelsStrategy, get_watchlist_snapshot
    from lumisignals.massive_client import MassiveClient, DEFAULT_TICKERS
    from lumisignals.signal_log import SignalLog

    user_id = user_data["id"]
    email = user_data["email"]
    log_entries = []

    def log(msg):
        from datetime import datetime, timezone, timedelta
        et = datetime.now(timezone.utc) + timedelta(hours=-4)
        entry = f"{et.strftime('%I:%M:%S %p')} {msg}"
        log_entries.append(entry)
        if len(log_entries) > 200:
            del log_entries[:100]
        publish_log(user_id, log_entries)
        logger.info("[user:%s] %s", email, msg)

    log("Bot starting...")

    oanda = OandaClient(
        account_id=user_data["oanda_account_id"],
        api_key=user_data["oanda_api_key"],
        environment=user_data.get("oanda_environment") or "practice",
    )

    if not user_data.get("dry_run", True):
        if not oanda.validate_connection():
            log("Could not connect to Oanda — check credentials")
            return
        log("Connected to Oanda")
    else:
        log("Dry-run mode — skipping Oanda validation")

    snr_base_url = "https://app.lumitrade.ai/api/v1"
    snr_api_key = user_data.get("lumitrade_api_key") or os.environ.get("LUMITRADE_API_KEY", "")
    snr = SNRClient(base_url=snr_base_url, api_key=snr_api_key)

    massive = None
    stock_tickers = []
    massive_key = user_data.get("massive_api_key") or os.environ.get("MASSIVE_API_KEY", "")
    if massive_key:
        massive = MassiveClient(api_key=massive_key)
        stock_tickers = list(DEFAULT_TICKERS)
        log(f"Massive connected — scanning {len(stock_tickers)} stock/crypto tickers")

    signal_log = SignalLog(path=f"/opt/lumisignals/signal_log_user_{user_id}.json")

    def on_signal(signal, extra_meta=None):
        log(f"SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
        log_entry = {
            "action": signal.action, "symbol": signal.symbol,
            "entry": signal.entry, "stop": signal.stop, "target": signal.target,
            "risk_reward": signal.risk_reward,
        }
        if extra_meta:
            log_entry.update(extra_meta)
        signal_log.record(f"{signal.symbol}_{int(time.time())}", log_entry)

    from lumisignals.levels_strategy import SCALP_MODEL, INTRADAY_MODEL, SWING_MODEL, ALL_MODELS
    from lumisignals.risk_budget import record_loss, is_budget_exceeded
    from lumisignals.alerts import alert_signal, alert_trade_opened, alert_budget_hit

    alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")

    import threading

    def get_risk_config(user_data, model_name, model_cfg):
        """Build risk config dict from user settings, falling back to ModelConfig defaults."""
        mode = user_data.get(f"{model_name}_risk_mode") or "percent"
        value = user_data.get(f"{model_name}_risk_value")
        if value is None:
            value = model_cfg.risk_percent
        config = {"max_open_positions": 999}
        if mode == "fixed":
            config["risk_percent"] = 0
            config["risk_dollar"] = float(value)
        else:
            config["risk_percent"] = float(value)
            config["risk_dollar"] = 0.0
        return config

    # Create all three model strategies
    models = {}
    for model_cfg in [SCALP_MODEL, INTRADAY_MODEL, SWING_MODEL]:
        def make_signal_handler(model_name, _model_cfg=model_cfg):
            risk_cfg = get_risk_config(user_data, model_name, _model_cfg)
            daily_budget = float(user_data.get(f"{model_name}_daily_budget") or 0)
            risk_mode = user_data.get(f"{model_name}_risk_mode") or "percent"
            risk_val = risk_cfg.get("risk_dollar") if risk_mode == "fixed" else risk_cfg.get("risk_percent")
            log(f"[{model_name.upper()}] Risk: {risk_mode} {'$' if risk_mode == 'fixed' else ''}{risk_val}{'%' if risk_mode == 'percent' else ''} | Daily budget: {'$' + str(daily_budget) if daily_budget > 0 else 'unlimited'}")

            def handler(signal, extra_meta=None):
                log(f"[{model_name.upper()}] SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
                log_entry = {
                    "action": signal.action, "symbol": signal.symbol,
                    "entry": signal.entry, "stop": signal.stop, "target": signal.target,
                    "risk_reward": signal.risk_reward,
                    "strategy_id": "htf_levels", "model": model_name,
                }
                if extra_meta:
                    log_entry.update(extra_meta)
                signal_log.record(f"{model_name}_{signal.symbol}_{int(time.time())}", log_entry)

                # Email alert for every signal
                if alert_pass:
                    try:
                        alert_signal(
                            model=model_name, action=signal.action, symbol=signal.symbol,
                            entry=signal.entry, risk_reward=signal.risk_reward,
                            score=extra_meta.get("bias_score", 0) if extra_meta else 0,
                            stop=signal.stop, target=signal.target,
                            zone_type=extra_meta.get("zone_type", "") if extra_meta else "",
                            zone_timeframe=extra_meta.get("zone_timeframe", "") if extra_meta else "",
                            trigger_pattern=extra_meta.get("trigger_pattern", "") if extra_meta else "",
                            to_email=email, smtp_pass=alert_pass,
                        )
                    except Exception as e:
                        logger.debug("Alert error: %s", e)

                # --- Auto-trade options for stock signals ---
                is_stock = extra_meta and extra_meta.get("is_stock")
                auto_trade = user_data.get("options_auto_trade", False)
                if is_stock and auto_trade and model_name == "swing":
                    try:
                        _auto_trade_options(
                            user_data, signal, extra_meta, model_name,
                            log, alert_pass, email,
                        )
                    except Exception as e:
                        log(f"[{model_name.upper()}] OPTIONS AUTO-TRADE ERROR: {e}")
                        logger.error("Options auto-trade error: %s", e)

                if not user_data.get("dry_run", True):
                    # Check daily budget before placing order
                    if daily_budget > 0 and is_budget_exceeded(user_id, model_name, daily_budget):
                        log(f"[{model_name.upper()}] SKIPPED — daily loss budget ${daily_budget:.0f} exceeded")
                        if alert_pass:
                            try:
                                from lumisignals.risk_budget import get_daily_loss
                                spent = get_daily_loss(user_id, model_name)
                                alert_budget_hit(model_name, daily_budget, spent, to_email=email, smtp_pass=alert_pass)
                            except Exception:
                                pass
                        return

                    from lumisignals.order_manager import OrderManager
                    om = OrderManager(client=oanda, risk_config=risk_cfg, dry_run=False)
                    result = om.execute_signal(signal)
                    if result.success:
                        log(f"[{model_name.upper()}] ORDER PLACED: {result.order_id}")
                        # Email alert for trade placed
                        if alert_pass:
                            try:
                                alert_trade_opened(
                                    model=model_name, action=signal.action, symbol=signal.symbol,
                                    units=result.details.get("units", 0) if result.details else 0,
                                    entry=signal.entry, order_id=result.order_id,
                                    risk_amount=risk_cfg.get("risk_dollar") or (result.details.get("balance", 0) * risk_cfg.get("risk_percent", 0) / 100) if result.details else 0,
                                    to_email=email, smtp_pass=alert_pass,
                                )
                            except Exception as e:
                                logger.debug("Trade alert error: %s", e)
                        # Record risk amount against daily budget
                        risk_amt = risk_cfg.get("risk_dollar") or 0
                        if risk_amt <= 0 and result.details:
                            bal = result.details.get("balance", 0)
                            risk_amt = bal * (risk_cfg.get("risk_percent", 0) / 100)
                        if risk_amt > 0:
                            record_loss(user_id, model_name, risk_amt)
                        # Also record under Oanda order ID for trade enrichment
                        signal_log.record(result.order_id, log_entry)
                        try:
                            signal_log.record(str(int(result.order_id) + 1), log_entry)
                        except (ValueError, TypeError):
                            pass
                    else:
                        log(f"[{model_name.upper()}] ORDER FAILED: {result.error}")
            return handler

        strategy = LevelsStrategy(
            oanda_client=oanda, snr_client=snr,
            trade_builder_url=snr_base_url, api_key=snr_api_key,
            model=model_cfg,
            massive_client=massive, stock_tickers=stock_tickers,
            stock_atr_multiplier=user_data.get("stock_atr_multiplier") or 0.5,
            on_signal=make_signal_handler(model_cfg.name),
        )
        models[model_cfg.name] = strategy
        log(f"[{model_cfg.name.upper()}] Configured — zones: {model_cfg.zone_tfs}, trigger: {model_cfg.trigger_tf}, bias: {model_cfg.bias_tf}")

    # Patch each strategy's watchlist refresh to publish to Redis per model
    for model_name, strategy in models.items():
        original = strategy._refresh_watchlist
        mn = model_name  # capture for closure

        def make_patched(orig, name):
            def patched(pairs=None):
                orig(pairs)
                zones = get_watchlist_snapshot(name)
                publish_watchlist_model(user_id, name, zones)
                log(f"[{name.upper()}] Watchlist: {len(zones)} zones")
            return patched

        strategy._refresh_watchlist = make_patched(original, mn)

    # Create stock options model with custom trigger TF (if different from swing's daily)
    options_trigger_tf = user_data.get("options_trigger_tf") or "4h"
    if user_data.get("options_auto_trade") and options_trigger_tf != "1d" and massive:
        from lumisignals.levels_strategy import ModelConfig
        from copy import copy

        stock_options_model = ModelConfig(
            name="swing_options",
            trigger_tf=options_trigger_tf,
            zone_tfs=["1w", "1mo"],
            bias_tf="1mo",
            bias_candle_tfs=["1w", "1mo"],
            risk_percent=1.0,
            zone_tolerance_pct={"1w": 0.006, "1mo": 0.009},
            min_score=50,
            min_risk_reward=1.5,
            watchlist_interval=300,
        )

        # This model only scans stocks — no forex
        stock_options_strategy = LevelsStrategy(
            oanda_client=oanda, snr_client=snr,
            trade_builder_url=snr_base_url, api_key=snr_api_key,
            model=stock_options_model,
            massive_client=massive, stock_tickers=stock_tickers,
            stock_atr_multiplier=user_data.get("stock_atr_multiplier") or 0.5,
            on_signal=make_signal_handler("swing_options"),
        )
        # Override watchlist refresh to skip forex — only scan stocks
        original_refresh = stock_options_strategy._refresh_watchlist
        def stock_only_refresh(pairs=None):
            original_refresh(pairs=[])  # empty forex list — only stocks via Massive
        stock_options_strategy._refresh_watchlist = stock_only_refresh
        models["swing_options"] = stock_options_strategy

        # Patch watchlist refresh
        original = stock_options_strategy._refresh_watchlist
        def make_patched_opts(orig):
            def patched(pairs=None):
                orig(pairs)
                zones = get_watchlist_snapshot("swing_options")
                publish_watchlist_model(user_id, "swing_options", zones)
                log(f"[SWING_OPTIONS] Watchlist: {len(zones)} zones")
            return patched
        stock_options_strategy._refresh_watchlist = make_patched_opts(original)

        log(f"[SWING_OPTIONS] Configured — zones: {stock_options_model.zone_tfs}, trigger: {options_trigger_tf}, stocks only")
        log(f"All 4 models running — SCALP (15m) + INTRADAY (1h) + SWING (daily) + SWING_OPTIONS ({options_trigger_tf})")
    else:
        log("All 3 models running — SCALP (15m) + INTRADAY (1h) + SWING (daily)")

    # Run all models in a unified loop
    tick = 0
    while True:
        # Check if user deactivated
        if tick > 0 and tick % 10 == 0:
            if stop_check(user_id):
                log("Bot stopped by user")
                break

        for model_name, strategy in models.items():
            ticks_per_wl = max(1, strategy.watchlist_interval // 30)

            if tick % ticks_per_wl == 0:
                try:
                    strategy._refresh_watchlist()
                except Exception as e:
                    logger.debug("[%s] Watchlist error: %s", model_name, e)

            try:
                strategy._monitor_zones()
            except Exception as e:
                logger.debug("[%s] Monitor error: %s", model_name, e)

            try:
                strategy._check_triggers()
            except Exception as e:
                logger.debug("[%s] Trigger error: %s", model_name, e)

            strategy._watchlist = [z for z in strategy._watchlist if z.status != "triggered"]

            # Publish current watchlist to Redis every cycle
            zones = get_watchlist_snapshot(model_name)
            publish_watchlist_model(user_id, model_name, zones)

        tick += 1
        time.sleep(30)

    log("Bot stopped")


def check_user_inactive(user_id):
    """Check if user deactivated their bot."""
    import psycopg2
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT bot_active FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        conn.close()
        return not (row and row[0])
    except Exception:
        return False


def main():
    """Main loop — check for active users and run their bots."""
    import threading

    logger.info("Bot runner starting — checking for active users every 30s")
    active_threads = {}  # user_id → thread

    while True:
        try:
            users = get_active_users()
            active_ids = {u["id"] for u in users}

            # Start bots for new active users
            for user in users:
                uid = user["id"]
                if uid not in active_threads or not active_threads[uid].is_alive():
                    logger.info("Starting bot for user %s (%s)", uid, user["email"])
                    t = threading.Thread(
                        target=run_bot_for_user,
                        args=(user, check_user_inactive),
                        daemon=True,
                        name=f"bot-{uid}",
                    )
                    t.start()
                    active_threads[uid] = t

            # Clean up threads for deactivated users
            for uid in list(active_threads.keys()):
                if uid not in active_ids:
                    logger.info("User %s deactivated — bot will stop", uid)
                    active_threads.pop(uid, None)

        except Exception as e:
            logger.error("Bot runner error: %s", e)

        time.sleep(30)


if __name__ == "__main__":
    main()
