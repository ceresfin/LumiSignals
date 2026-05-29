"""Runaway-guard for the futures webhook path.

Two related counters with Telegram-on-trip semantics:

  1. Max trades per day — caps total number of accepted BUY/SELL signals
     in a day. position_guard caps SIZE (contracts), this caps COUNT.
     Defense against Pine bugs / news-event whipsaw firing 20 signals
     in a choppy hour.

  2. Consecutive losses circuit breaker — pauses the strategy when N
     stops fire in a row without an intervening winner. Daily kill
     switch triggers at TOTAL loss; this triggers at STREAK regardless
     of running P&L (catastrophic-Monday-open scenario).

Both reset at the same daily boundary as the kill switch (9:30 AM ET
by default; configurable). State lives in Redis. Once tripped, the
gate stays tripped until the boundary OR a manual reset.

The webhook handler calls is_blocking_entry() — same pattern as the
kill switch.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

CFG_KEY = "risk:runaway_guard:config"
STATE_KEY = "risk:runaway_guard:state"

DEFAULT_CONFIG = {
    "enabled": True,
    "max_trades_per_day": 20,         # 0 = no cap
    "max_consecutive_losses": 3,      # 0 = no cap
    "reset_hour_et": 9,
    "reset_minute_et": 30,
}


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _et_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return timezone(timedelta(hours=-4))


def get_config() -> dict:
    raw = _rdb().get(CFG_KEY)
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        return {**DEFAULT_CONFIG, **json.loads(raw)}
    except Exception:
        return dict(DEFAULT_CONFIG)


def set_config(updates: dict) -> dict:
    merged = {**get_config(), **(updates or {})}
    for k, lo in (("max_trades_per_day", 0), ("max_consecutive_losses", 0),
                  ("reset_hour_et", 0), ("reset_minute_et", 0)):
        try:
            merged[k] = max(lo, int(merged.get(k, DEFAULT_CONFIG[k])))
        except (TypeError, ValueError):
            merged[k] = DEFAULT_CONFIG[k]
    merged["reset_hour_et"] = merged["reset_hour_et"] % 24
    merged["reset_minute_et"] = merged["reset_minute_et"] % 60
    merged["enabled"] = bool(merged.get("enabled", True))
    _rdb().set(CFG_KEY, json.dumps(merged))
    return merged


def _current_boundary_utc() -> datetime:
    cfg = get_config()
    et = _et_tz()
    now_et = datetime.now(timezone.utc).astimezone(et)
    boundary = now_et.replace(hour=int(cfg["reset_hour_et"]),
                              minute=int(cfg["reset_minute_et"]),
                              second=0, microsecond=0)
    if now_et < boundary:
        boundary = boundary - timedelta(days=1)
    return boundary.astimezone(timezone.utc)


def _empty_state(boundary: datetime) -> dict:
    return {
        "tripped": False,
        "tripped_at": None,
        "trip_reason": None,
        "trades_today": 0,
        "consecutive_losses": 0,
        "day_start": boundary.isoformat(),
    }


def get_state() -> dict:
    boundary = _current_boundary_utc()
    raw = _rdb().get(STATE_KEY)
    if not raw:
        return _empty_state(boundary)
    try:
        saved = json.loads(raw)
        saved_start = saved.get("day_start")
        if saved_start:
            try:
                if datetime.fromisoformat(saved_start.replace("Z", "+00:00")) < boundary:
                    return _empty_state(boundary)
            except Exception:
                return _empty_state(boundary)
        saved.setdefault("day_start", boundary.isoformat())
        saved.setdefault("trades_today", 0)
        saved.setdefault("consecutive_losses", 0)
        return saved
    except Exception:
        return _empty_state(boundary)


def _save(state: dict) -> None:
    _rdb().set(STATE_KEY, json.dumps(state))


def record_entry() -> dict:
    """Called when an entry signal is accepted (BUY/SELL). Increments
    trades_today. Trips when the count crosses max_trades_per_day."""
    state = get_state()
    cfg = get_config()
    state["trades_today"] = int(state.get("trades_today", 0)) + 1
    cap = int(cfg.get("max_trades_per_day", 0))
    if cap > 0 and state["trades_today"] > cap and not state.get("tripped"):
        state["tripped"] = True
        state["tripped_at"] = datetime.now(timezone.utc).isoformat()
        state["trip_reason"] = (
            f"max_trades_per_day: {state['trades_today']} > cap {cap}"
        )
        logger.warning("runaway_guard TRIPPED on trade count: %s", state["trip_reason"])
        _telegram_trip(state["trip_reason"])
    _save(state)
    return state


def record_close(realized_pl: float) -> dict:
    """Called when a trade closes (CLOSED diary event). Updates the
    consecutive-loss streak. Trips when the streak hits the cap."""
    state = get_state()
    cfg = get_config()
    if realized_pl >= 0:
        state["consecutive_losses"] = 0
    else:
        state["consecutive_losses"] = int(state.get("consecutive_losses", 0)) + 1
    cap = int(cfg.get("max_consecutive_losses", 0))
    if cap > 0 and state["consecutive_losses"] >= cap and not state.get("tripped"):
        state["tripped"] = True
        state["tripped_at"] = datetime.now(timezone.utc).isoformat()
        state["trip_reason"] = (
            f"max_consecutive_losses: {state['consecutive_losses']} >= cap {cap}"
        )
        logger.warning("runaway_guard TRIPPED on loss streak: %s", state["trip_reason"])
        _telegram_trip(state["trip_reason"])
    _save(state)
    return state


def manual_reset() -> dict:
    state = get_state()
    state["tripped"] = False
    state["tripped_at"] = None
    state["trip_reason"] = None
    _save(state)
    logger.info("runaway_guard manually reset")
    return state


def is_blocking_entry() -> bool:
    """Webhook hot-path check. True iff a new entry should be refused
    BEFORE incrementing the counter."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return False
    state = get_state()
    return bool(state.get("tripped"))


def _telegram_trip(reason: str) -> None:
    try:
        from .ibkr_sync_cpapi import _send_telegram_alert
        _send_telegram_alert(
            "🚧 Runaway guard tripped",
            f"Bot has stopped accepting new entries.\n\n"
            f"Reason: {reason}\n\n"
            f"Resets at the next daily boundary, or reset manually in "
            f"Settings → Runaway guard.",
        )
    except Exception:
        pass
