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
               stock_atr_multiplier, dry_run
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
    snr_api_key = os.environ.get("LUMITRADE_API_KEY", "")
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

    import threading

    # Create all three model strategies
    models = {}
    for model_cfg in [SCALP_MODEL, INTRADAY_MODEL, SWING_MODEL]:
        def make_signal_handler(model_name):
            def handler(signal, extra_meta=None):
                log(f"[{model_name.upper()}] SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
                log_entry = {
                    "action": signal.action, "symbol": signal.symbol,
                    "entry": signal.entry, "stop": signal.stop, "target": signal.target,
                    "risk_reward": signal.risk_reward, "model": model_name,
                }
                if extra_meta:
                    log_entry.update(extra_meta)
                signal_log.record(f"{model_name}_{signal.symbol}_{int(time.time())}", log_entry)

                if not user_data.get("dry_run", True):
                    from lumisignals.order_manager import OrderManager
                    risk_pct = model_cfg.risk_percent
                    om = OrderManager(client=oanda, risk_config={"risk_percent": risk_pct, "max_open_positions": 999}, dry_run=False)
                    result = om.execute_signal(signal)
                    if result.success:
                        log(f"[{model_name.upper()}] ORDER PLACED: {result.order_id}")
                        # Also record under Oanda order ID for trade enrichment
                        signal_log.record(result.order_id, log_entry)
                        # And order_id + 1 (Oanda fill creates next ID)
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
        log(f"[{model_cfg.name.upper()}] Configured — zones: {model_cfg.zone_tfs}, trigger: {model_cfg.trigger_tf}, bias: {model_cfg.bias_tf}, risk: {model_cfg.risk_percent}%")

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
