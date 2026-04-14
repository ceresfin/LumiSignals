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
    """Store watchlist in Redis so the web app can read it."""
    rdb.setex(f"watchlist:{user_id}", 600, json.dumps(zones))  # 10 min TTL


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

    trading_tf = user_data.get("trading_timeframe") or "1d"
    min_score = user_data.get("min_score") or 50
    min_rr = user_data.get("min_risk_reward") or 1.5
    stock_atr = user_data.get("stock_atr_multiplier") or 0.5

    import threading
    stop_event = threading.Event()

    strategy = LevelsStrategy(
        oanda_client=oanda, snr_client=snr,
        trade_builder_url=snr_base_url, api_key=snr_api_key,
        min_score=min_score, atr_stop_multiplier=1.0,
        trading_timeframe=trading_tf, min_risk_reward=min_rr,
        watchlist_interval=300, monitor_interval=30,
        on_signal=on_signal, massive_client=massive,
        stock_tickers=stock_tickers, stock_atr_multiplier=stock_atr,
    )

    log(f"Strategy configured — TF: {trading_tf}, min score: {min_score}, min R:R: {min_rr}")

    # Patch watchlist refresh to publish to Redis
    original_refresh = strategy._refresh_watchlist

    def patched_refresh(pairs=None):
        original_refresh(pairs)
        zones = get_watchlist_snapshot()
        publish_watchlist(user_id, zones)
        fx_count = sum(1 for z in zones if not z.get("is_stock"))
        stock_count = len(zones) - fx_count
        log(f"Watchlist: {len(zones)} zones ({fx_count} forex, {stock_count} stocks/crypto)")

    strategy._refresh_watchlist = patched_refresh

    log("Bot running — scanning...")

    # Run with periodic check if user deactivated
    ticks_per_watchlist = max(1, 300 // 30)
    tick = 0

    while not stop_event.is_set():
        # Check if user deactivated
        if tick > 0 and tick % 10 == 0:
            if stop_check(user_id):
                log("Bot stopped by user")
                break

        if tick % ticks_per_watchlist == 0:
            try:
                strategy._refresh_watchlist()
            except Exception as e:
                log(f"Watchlist error: {e}")

        try:
            strategy._monitor_zones()
        except Exception as e:
            logger.debug("Monitor error: %s", e)

        try:
            strategy._check_triggers()
        except Exception as e:
            logger.debug("Trigger error: %s", e)

        strategy._watchlist = [z for z in strategy._watchlist if z.status != "triggered"]
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
