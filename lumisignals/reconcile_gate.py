"""Restart-safety gate.

On bot startup, the ibkr-sync service marks state as 'reconciling' and
runs the reconciler. The saas webhook handler refuses to act on entries
until state flips to 'ok'.

State auto-transitions to 'timed_out' if the first successful reconcile
hasn't completed within the timeout window. From 'timed_out', the user
must manually reset via the mobile UI to resume.

This protects against the bot accepting webhooks before it knows the
current broker state — the failure mode where you queue a new SELL while
the bot doesn't yet know it's long 3 contracts from before the restart.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

STATE_KEY = "risk:reconcile_state"
DEFAULT_TIMEOUT_SECS = 120         # 2-min hard ceiling for first reconcile
HEARTBEAT_STALE_SECS = 60          # 'ok' state needs heartbeat refresh within this


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _save(state: dict) -> None:
    try:
        _rdb().set(STATE_KEY, json.dumps(state))
    except Exception as e:
        logger.warning("reconcile_gate save failed: %s", e)


def mark_reconciling(timeout_secs: int = DEFAULT_TIMEOUT_SECS) -> dict:
    """Called by ibkr-sync at startup. Sets the lock."""
    now = _now()
    state = {
        "status": "reconciling",
        "started_at": now.isoformat(),
        "completed_at": None,
        "duration_seconds": None,
        "timeout_at": (now + timedelta(seconds=timeout_secs)).isoformat(),
        "last_heartbeat": now.isoformat(),
        "reason": None,
    }
    _save(state)
    logger.info("reconcile_gate: marked RECONCILING (timeout in %ds)", timeout_secs)
    return state


def mark_ok() -> dict:
    """Called by ibkr-sync after the first successful reconciliation pass.
    Also called periodically to refresh the heartbeat."""
    now = _now()
    state = get_state()
    if state.get("status") != "ok":
        # First successful pass — record duration
        started = state.get("started_at")
        duration = None
        if started:
            try:
                started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                duration = (now - started_dt).total_seconds()
            except Exception:
                pass
        state["status"] = "ok"
        state["completed_at"] = now.isoformat()
        state["duration_seconds"] = duration
        state["reason"] = None
        logger.info("reconcile_gate: marked OK (took %.1fs)",
                    duration if duration else 0.0)
    state["last_heartbeat"] = now.isoformat()
    _save(state)
    return state


def mark_timed_out(reason: str = "First reconciliation pass did not complete in time") -> dict:
    """Auto-called on read if status was 'reconciling' and timeout passed."""
    now = _now()
    state = get_state(skip_timeout_check=True)
    state["status"] = "timed_out"
    state["reason"] = reason
    state["last_heartbeat"] = now.isoformat()
    _save(state)
    logger.warning("reconcile_gate: TIMED_OUT — %s", reason)
    # Telegram once (rate-limited inside helper).
    try:
        from .ibkr_sync_cpapi import _send_telegram_alert
        _send_telegram_alert(
            "🚧 Bot reconciliation timed out",
            "Webhooks are being refused with 503. Open the app → Settings "
            "to reset once you're sure broker state is consistent.",
        )
    except Exception:
        pass
    return state


def manual_reset() -> dict:
    """Force-unlock from a timed_out state. The user takes responsibility for
    the broker/bot state being consistent. The next signal will be accepted."""
    now = _now()
    state = {
        "status": "ok",
        "started_at": None,
        "completed_at": now.isoformat(),
        "duration_seconds": None,
        "timeout_at": None,
        "last_heartbeat": now.isoformat(),
        "reason": "manual_reset",
    }
    _save(state)
    logger.info("reconcile_gate: manually reset to OK")
    return state


def get_state(skip_timeout_check: bool = False) -> dict:
    """Read state. By default, auto-flips 'reconciling' → 'timed_out' if the
    timeout has passed (so the next caller observes the failure)."""
    try:
        raw = _rdb().get(STATE_KEY)
    except Exception:
        # Redis unreachable — fail-closed (lock) so we don't accept signals.
        return {
            "status": "reconciling",
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "timeout_at": None,
            "last_heartbeat": None,
            "reason": "redis_unreachable",
        }
    if not raw:
        # State never written → fail-closed. Assume the ibkr-sync hasn't
        # come up yet; refuse webhooks until it does.
        return {
            "status": "reconciling",
            "started_at": None,
            "completed_at": None,
            "duration_seconds": None,
            "timeout_at": None,
            "last_heartbeat": None,
            "reason": "no_state_written",
        }
    try:
        state = json.loads(raw)
    except Exception:
        return {
            "status": "reconciling", "reason": "state_parse_error",
            "started_at": None, "completed_at": None,
            "duration_seconds": None, "timeout_at": None, "last_heartbeat": None,
        }
    if skip_timeout_check:
        return state
    # Auto-timeout: if reconciling and timeout_at has passed, flip.
    if state.get("status") == "reconciling":
        timeout_at = state.get("timeout_at")
        if timeout_at:
            try:
                t_dt = datetime.fromisoformat(timeout_at.replace("Z", "+00:00"))
                if _now() > t_dt:
                    return mark_timed_out()
            except Exception:
                pass
    return state


def is_locked() -> bool:
    """Webhook handler hot-path check. True iff entries should be refused.

    Locks on: reconciling, timed_out, or 'ok' with a stale heartbeat
    (ibkr-sync process down)."""
    state = get_state()
    status = state.get("status")
    if status != "ok":
        return True
    hb = state.get("last_heartbeat")
    if not hb:
        return True
    try:
        hb_dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        age_s = (_now() - hb_dt).total_seconds()
        if age_s > HEARTBEAT_STALE_SECS:
            return True
    except Exception:
        return True
    return False
