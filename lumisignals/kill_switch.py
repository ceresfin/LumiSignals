"""Daily-loss kill switch.

When realized day P&L falls below -threshold_usd, the bot refuses new
entry signals (BUY / SELL webhooks). Existing positions keep their
bracket SL — the kill switch is a *new-trade* gate, not a panic-flatten.
The bracket SL at IB is the per-trade safety net; this is the per-day
ceiling that stops you from chasing a bad streak into the ground.

State + config live in Redis (single-user for now; per-user once mobile
auth gets wired into the bot path). Auto-resets at the configured
reset_hour:reset_minute ET each day — default 9:30 AM ET (matches the
"trading day" boundary the rest of the app uses).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

CFG_KEY = "risk:kill_switch:config"
STATE_KEY = "risk:kill_switch:state"

DEFAULT_CONFIG = {
    "enabled": True,
    "threshold_usd": 250.0,
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
        # Fallback for environments without zoneinfo — EDT-ish, not DST-safe.
        return timezone(timedelta(hours=-4))


def get_config() -> dict:
    """Read the current kill-switch config, merging with defaults for any
    missing keys so the contract is forwards-compatible."""
    raw = _rdb().get(CFG_KEY)
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(raw)
        return {**DEFAULT_CONFIG, **saved}
    except Exception:
        return dict(DEFAULT_CONFIG)


def set_config(updates: dict) -> dict:
    """Patch the config. Caller passes only the fields they want to change.
    Returns the new merged config."""
    merged = {**get_config(), **(updates or {})}
    # Sanitize
    try:
        merged["threshold_usd"] = max(0.0, float(merged.get("threshold_usd", 250.0)))
    except (TypeError, ValueError):
        merged["threshold_usd"] = 250.0
    try:
        merged["reset_hour_et"] = int(merged.get("reset_hour_et", 9)) % 24
    except (TypeError, ValueError):
        merged["reset_hour_et"] = 9
    try:
        merged["reset_minute_et"] = int(merged.get("reset_minute_et", 30)) % 60
    except (TypeError, ValueError):
        merged["reset_minute_et"] = 30
    merged["enabled"] = bool(merged.get("enabled", True))
    _rdb().set(CFG_KEY, json.dumps(merged))
    return merged


def _current_reset_boundary_utc() -> datetime:
    """The most-recent reset_hour:reset_minute ET as a UTC instant."""
    cfg = get_config()
    et = _et_tz()
    now_et = datetime.now(timezone.utc).astimezone(et)
    boundary_et = now_et.replace(hour=int(cfg["reset_hour_et"]),
                                 minute=int(cfg["reset_minute_et"]),
                                 second=0, microsecond=0)
    if now_et < boundary_et:
        boundary_et = boundary_et - timedelta(days=1)
    return boundary_et.astimezone(timezone.utc)


def _empty_state(boundary: datetime) -> dict:
    return {
        "tripped": False,
        "tripped_at": None,
        "day_pnl": 0.0,
        "day_start": boundary.isoformat(),
        "reason": None,
    }


def get_state() -> dict:
    """Read state. Auto-resets when we've crossed the daily boundary
    since the saved day_start."""
    boundary = _current_reset_boundary_utc()
    raw = _rdb().get(STATE_KEY)
    if not raw:
        return _empty_state(boundary)
    try:
        saved = json.loads(raw)
        saved_start_str = saved.get("day_start")
        if saved_start_str:
            try:
                saved_dt = datetime.fromisoformat(saved_start_str.replace("Z", "+00:00"))
                if saved_dt < boundary:
                    # New day — reset
                    return _empty_state(boundary)
            except Exception:
                return _empty_state(boundary)
        saved.setdefault("day_start", boundary.isoformat())
        return saved
    except Exception:
        return _empty_state(boundary)


def _save_state(state: dict) -> None:
    _rdb().set(STATE_KEY, json.dumps(state))


def compute_day_pnl() -> float:
    """Sum realized P&L of CLOSED trade_events since the current daily boundary.
    Best-effort: returns 0.0 if the diary query fails."""
    try:
        from .diary import query_events
        boundary = _current_reset_boundary_utc()
        events = query_events(since=boundary.isoformat(), limit=5000)
        return sum(float(e.get("realized_pl") or 0.0)
                   for e in events if e.get("state") == "CLOSED")
    except Exception as e:
        logger.warning("kill_switch: compute_day_pnl failed: %s", e)
        return 0.0


def check_and_trip() -> dict:
    """Recompute day P&L; flip tripped if we just crossed the threshold.
    Once tripped, stays tripped until the daily reset or manual_reset()."""
    cfg = get_config()
    state = get_state()
    if not cfg.get("enabled"):
        # Disabled — never trips, but still reports day P&L for the UI.
        state["tripped"] = False
        state["reason"] = None
        state["day_pnl"] = compute_day_pnl()
        _save_state(state)
        return state
    pnl = compute_day_pnl()
    state["day_pnl"] = pnl
    threshold = abs(float(cfg.get("threshold_usd", 250.0)))
    if pnl <= -threshold and not state.get("tripped"):
        state["tripped"] = True
        state["tripped_at"] = datetime.now(timezone.utc).isoformat()
        state["reason"] = f"Day P&L ${pnl:.2f} crossed -${threshold:.2f}"
        logger.warning("KILL SWITCH TRIPPED: %s", state["reason"])
    _save_state(state)
    return state


def manual_reset() -> dict:
    """Force-untrip. Day P&L stays at current value; the user is taking
    responsibility for resuming. Next loss can re-trip."""
    state = get_state()
    state["tripped"] = False
    state["tripped_at"] = None
    state["reason"] = None
    _save_state(state)
    logger.info("kill switch manually reset")
    return state


def is_blocking_entry() -> bool:
    """Cheap check for the webhook hot path. True iff a new entry order
    should be refused right now."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return False
    state = check_and_trip()
    return bool(state.get("tripped"))
