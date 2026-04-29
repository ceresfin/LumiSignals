"""Bot worker manager — runs per-user bot instances in background threads."""

import logging
import threading
import time
from typing import Dict

logger = logging.getLogger(__name__)

# Per-user bot state: {user_id: {"thread": Thread, "stop_event": Event, "watchlist": list}}
_workers: Dict[int, dict] = {}
_lock = threading.Lock()


def start_bot_for_user(user) -> bool:
    """Start the signal engine for a user.

    Args:
        user: User model instance with broker credentials and settings.

    Returns:
        True if started successfully.
    """
    with _lock:
        if user.id in _workers and _workers[user.id]["thread"].is_alive():
            logger.info("Bot already running for user %s", user.email)
            return True

    # Snapshot user data — ORM objects can't cross thread boundaries
    user_data = {
        "id": user.id,
        "email": user.email,
        "oanda_account_id": user.oanda_account_id,
        "oanda_api_key": user.oanda_api_key,
        "oanda_environment": user.oanda_environment,
        "massive_api_key": user.massive_api_key,
        "trading_timeframe": user.trading_timeframe,
        "min_score": user.min_score,
        "min_risk_reward": user.min_risk_reward,
        "stock_atr_multiplier": user.stock_atr_multiplier,
        "dry_run": user.dry_run,
        "futures_stop_loss": user.futures_stop_loss,
        "futures_contracts": user.futures_contracts,
    }

    stop_event = threading.Event()
    watchlist_store = {"zones": [], "log": []}

    def run():
        try:
            _run_bot(user_data, stop_event, watchlist_store)
        except Exception as e:
            logger.error("Bot crashed for user %s: %s", user_data["email"], e)
            watchlist_store["log"].append(f"Bot crashed: {e}")

    thread = threading.Thread(target=run, daemon=True, name=f"bot-{user.id}")
    thread.start()

    with _lock:
        _workers[user.id] = {
            "thread": thread,
            "stop_event": stop_event,
            "watchlist": watchlist_store,
        }

    logger.info("Bot started for user %s", user.email)
    return True


def stop_bot_for_user(user_id: int) -> bool:
    """Stop the bot for a user."""
    with _lock:
        worker = _workers.get(user_id)
        if not worker:
            return False

    worker["stop_event"].set()
    worker["thread"].join(timeout=10)

    with _lock:
        _workers.pop(user_id, None)

    logger.info("Bot stopped for user %d", user_id)
    return True


def get_user_watchlist(user_id: int) -> list:
    """Get the current watchlist for a user."""
    with _lock:
        worker = _workers.get(user_id)
        if not worker:
            return []
        return list(worker["watchlist"].get("zones", []))


def get_user_log(user_id: int, limit: int = 50) -> list:
    """Get recent log entries for a user."""
    with _lock:
        worker = _workers.get(user_id)
        if not worker:
            return []
        return list(worker["watchlist"].get("log", []))[-limit:]


def is_bot_running(user_id: int) -> bool:
    """Check if bot is running for a user."""
    with _lock:
        worker = _workers.get(user_id)
        if not worker:
            return False
        return worker["thread"].is_alive()


def _run_bot(user, stop_event, store):
    """Run the three-phase signal engine for a user.

    Args:
        user: dict with user data (not ORM object).
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from lumisignals.oanda_client import OandaClient
    from lumisignals.snr_filter import SNRClient
    from lumisignals.levels_strategy import LevelsStrategy
    from lumisignals.massive_client import MassiveClient, DEFAULT_TICKERS
    from lumisignals.signal_log import SignalLog

    email = user["email"]
    user_id = user["id"]

    def log(msg):
        entry = f"{time.strftime('%H:%M:%S')} {msg}"
        store["log"].append(entry)
        if len(store["log"]) > 200:
            store["log"] = store["log"][-100:]
        logger.info("[user:%s] %s", email, msg)

    log("Bot starting...")

    # Initialize Oanda client
    oanda = OandaClient(
        account_id=user["oanda_account_id"],
        api_key=user["oanda_api_key"],
        environment=user.get("oanda_environment") or "practice",
    )

    # Validate connection
    if not user.get("dry_run", True):
        if not oanda.validate_connection():
            log("Could not connect to Oanda — check credentials")
            return
        log("Connected to Oanda")
    else:
        log("Dry-run mode — skipping Oanda validation")

    # Initialize SNR client
    snr_base_url = "https://app.lumitrade.ai/api/v1"
    snr_api_key = os.environ.get("LUMITRADE_API_KEY", "")
    snr = SNRClient(base_url=snr_base_url, api_key=snr_api_key)

    # Initialize Massive client for stocks/crypto
    massive = None
    stock_tickers = []
    massive_key = user.get("massive_api_key") or os.environ.get("MASSIVE_API_KEY", "")
    if massive_key:
        massive = MassiveClient(api_key=massive_key)
        stock_tickers = list(DEFAULT_TICKERS)
        log(f"Massive connected — scanning {len(stock_tickers)} stock/crypto tickers")

    # Signal handler
    signal_log = SignalLog(path=f"signal_log_user_{user_id}.json")

    def on_signal(signal, extra_meta=None):
        log(f"SIGNAL: {signal.action} {signal.symbol} @ {signal.entry:.5f} | R:R {signal.risk_reward:.1f}")
        log_entry = {
            "action": signal.action,
            "symbol": signal.symbol,
            "entry": signal.entry,
            "stop": signal.stop,
            "target": signal.target,
            "risk_reward": signal.risk_reward,
        }
        if extra_meta:
            log_entry.update(extra_meta)
        signal_log.record(f"{signal.symbol}_{int(time.time())}", log_entry)

        if not user.get("dry_run", True):
            from lumisignals.order_manager import OrderManager
            om = OrderManager(client=oanda, risk_config={"risk_percent": 1.0}, dry_run=False)
            result = om.execute_signal(signal)
            if result.success:
                log(f"ORDER PLACED: {result.order_id}")
            else:
                log(f"ORDER FAILED: {result.error}")

    trading_tf = user.get("trading_timeframe") or "1d"
    min_score = user.get("min_score") or 50
    min_rr = user.get("min_risk_reward") or 1.5
    stock_atr = user.get("stock_atr_multiplier") or 0.5

    # Create strategy
    strategy = LevelsStrategy(
        oanda_client=oanda,
        snr_client=snr,
        trade_builder_url=snr_base_url,
        api_key=snr_api_key,
        min_score=min_score,
        atr_stop_multiplier=1.0,
        trading_timeframe=trading_tf,
        min_risk_reward=min_rr,
        watchlist_interval=300,
        monitor_interval=30,
        on_signal=on_signal,
        massive_client=massive,
        stock_tickers=stock_tickers,
        stock_atr_multiplier=stock_atr,
    )

    log(f"Strategy configured — TF: {trading_tf}, min score: {min_score}, min R:R: {min_rr}")

    # Override watchlist publish to store in user's state
    original_refresh = strategy._refresh_watchlist

    def patched_refresh(pairs=None):
        original_refresh(pairs)
        # Serialize watchlist for the web API
        from lumisignals.levels_strategy import get_watchlist_snapshot
        store["zones"] = get_watchlist_snapshot()
        fx_count = sum(1 for z in store["zones"] if not z.get("is_stock"))
        stock_count = len(store["zones"]) - fx_count
        log(f"Watchlist: {len(store['zones'])} zones ({fx_count} forex, {stock_count} stocks/crypto)")

    strategy._refresh_watchlist = patched_refresh

    # Run the bot
    log("Bot running — scanning...")
    strategy.run(stop_event=stop_event)
    log("Bot stopped")
