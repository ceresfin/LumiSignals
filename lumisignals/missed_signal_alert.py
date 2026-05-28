"""Periodic check for missed TV signals → Telegram alert.

Runs the 2n20 replay over the recent bar window, diffs against actual
INTENT_OPEN events, and fires a Telegram alert when a new miss appears.

Tracks alerted bar_times in Redis with a TTL so the same miss isn't
re-alerted on every loop iteration.

Designed to be called from the ibkr-sync main loop on a slow cadence
(every 5 min). Cheap when there's nothing to do (one Redis read + one
PostgREST call + one in-process replay).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

CFG_KEY = "risk:missed_signal_alert:config"
ALERTED_PREFIX = "risk:missed_signal_alert:alerted:"  # + bar_time iso

DEFAULT_CONFIG = {
    "enabled": True,
    "ticker": "MES",
    "strategy_id": "futures_2n20",
    "lookback_minutes": 30,        # how far back to look for misses
    "alerted_ttl_secs": 6 * 3600,  # remember we alerted on a bar_time for 6h
}


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def get_config() -> dict:
    raw = _rdb().get(CFG_KEY)
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(raw)
        return {**DEFAULT_CONFIG, **saved}
    except Exception:
        return dict(DEFAULT_CONFIG)


def set_config(updates: dict) -> dict:
    merged = {**get_config(), **(updates or {})}
    try:
        merged["lookback_minutes"] = max(5, int(merged.get("lookback_minutes", 30)))
    except (TypeError, ValueError):
        merged["lookback_minutes"] = 30
    merged["enabled"] = bool(merged.get("enabled", True))
    _rdb().set(CFG_KEY, json.dumps(merged))
    return merged


def _was_alerted(bar_time: str) -> bool:
    try:
        return _rdb().get(ALERTED_PREFIX + bar_time) is not None
    except Exception:
        return False


def _mark_alerted(bar_time: str, ttl_secs: int) -> None:
    try:
        _rdb().setex(ALERTED_PREFIX + bar_time, ttl_secs, "1")
    except Exception:
        pass


def check_and_alert() -> dict:
    """Pull recent bars, run replay, diff, alert on new misses.
    Returns a small status dict for the caller to log."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"checked": False, "reason": "disabled"}

    ticker = cfg["ticker"]
    strategy_id = cfg["strategy_id"]
    lookback = int(cfg["lookback_minutes"])
    ttl = int(cfg["alerted_ttl_secs"])

    # Load cached bars
    raw = _rdb().get(f"ibkr:bars:{ticker}:2m")
    if not raw:
        return {"checked": False, "reason": f"no cached bars for {ticker}"}
    cached = json.loads(raw)
    bars = cached.get("bars", []) or []
    if not bars:
        return {"checked": False, "reason": "empty bars"}

    # Replay over the full available window (VWAP needs prior context),
    # then filter signals to the lookback window. Run diff against the
    # diary's INTENT_OPEN events for the same window.
    from .strategy_replay import replay_2n20_signals, diff_against_diary
    from .diary import query_events

    now_utc = datetime.now(timezone.utc)
    since_dt = now_utc - timedelta(minutes=lookback)
    since_iso = since_dt.isoformat()

    all_signals = replay_2n20_signals(bars)
    in_window = [s for s in all_signals if s["bar_time"] >= since_iso]
    expected_entries = [s for s in in_window if s["direction"] in ("BUY", "SELL")]

    actual = query_events(strategy_id=strategy_id, ticker=ticker,
                          since=since_iso, limit=2000)
    actual_entries = [a for a in actual if a.get("state") == "INTENT_OPEN"]

    diff = diff_against_diary(expected_entries, actual_entries)
    missed = diff.get("missed", [])

    # Skip the most recent bar from alerting — it may still be within the
    # delivery slack window (TV's webhook hasn't arrived yet). Anything
    # older than 3 minutes (bar_secs + slack + buffer) is safe to alert on.
    safe_cutoff = (now_utc - timedelta(seconds=210)).isoformat()
    alertable = [m for m in missed if m["bar_time"] <= safe_cutoff]

    new_alerts: list = []
    for m in alertable:
        bar_time = m["bar_time"]
        if _was_alerted(bar_time):
            continue
        new_alerts.append(m)
        _mark_alerted(bar_time, ttl)

    if not new_alerts:
        return {"checked": True, "missed_total": len(missed),
                "missed_alertable": len(alertable), "new_alerts": 0}

    # Fire Telegram — one alert covering all new misses in this pass.
    try:
        from .ibkr_sync_cpapi import _send_telegram_alert
        lines = []
        for m in new_alerts[:5]:
            bt = m["bar_time"][:19].replace("T", " ")
            lines.append(f"• {bt} UTC: {m['direction']} {ticker} "
                         f"@ close {m['close']} (vwap {m['vwap']})")
        body = (f"Pine expected {len(new_alerts)} signal(s) we never received:\n"
                + "\n".join(lines)
                + ("\n…" if len(new_alerts) > 5 else "")
                + "\n\nLikely TV → server webhook delivery failure.")
        _send_telegram_alert("🚨 Missed TV signal(s) detected", body)
    except Exception as e:
        logger.warning("missed_signal_alert: telegram send failed: %s", e)

    logger.warning("missed_signal_alert: alerted on %d new miss(es)", len(new_alerts))
    return {"checked": True, "missed_total": len(missed),
            "missed_alertable": len(alertable), "new_alerts": len(new_alerts)}
