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

Per-strategy state (2026-06-01)
-------------------------------
All public functions now accept an optional `strategy` argument so
the guard's state and config are keyed per strategy. Without this,
a streak of HTF FX losses (e.g., scalp_h1zone) would trip the
shared counter and block MES 2n20 entries — which is what happened
this morning. Callers that don't pass a strategy use the legacy
global keys for backward compatibility during the rollout.

Default caps differ per strategy via STRATEGY_DEFAULTS below. Users
can override at runtime with set_config({...}, strategy=...).
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis

logger = logging.getLogger(__name__)

# Legacy global keys (used when strategy=None for backward compat)
LEGACY_CFG_KEY = "risk:runaway_guard:config"
LEGACY_STATE_KEY = "risk:runaway_guard:state"

DEFAULT_CONFIG = {
    "enabled": True,
    # 40 covers normal MES 2n20 days — empirically 30-36 trades over a
    # session on choppy markets, with headroom for outlier days. The
    # consecutive-loss circuit breaker (max_consecutive_losses) is the
    # tighter defense against runaway streaks; this cap is a backstop
    # for the case where Pine fires 50+ alerts in an hour from a bug.
    "max_trades_per_day": 40,         # 0 = no cap
    "max_consecutive_losses": 3,      # 0 = no cap
    "reset_hour_et": 9,
    "reset_minute_et": 30,
}

# Per-strategy defaults. Falls back to DEFAULT_CONFIG for unlisted strategies.
# Tunable via set_config(..., strategy=<slug>).
STRATEGY_DEFAULTS = {
    # MES 2n20 via TradingView webhook. 10-loss cap chosen 2026-06-01
    # after the global 3-cap was tripping from unrelated HTF FX losses
    # (see commit message). 65 trades/day matches the prior global cap.
    "futures_2n20":        {"max_consecutive_losses": 10, "max_trades_per_day": 65},
    # Pine sometimes sends the strategy as just "tradingview". Treat
    # the same as futures_2n20 since that's the only TV-driven webhook.
    "tradingview":         {"max_consecutive_losses": 10, "max_trades_per_day": 65},
    # HTF FX scalpers — known degraded. Tight cap so the strategy
    # auto-pauses if it keeps bleeding.
    "scalp_h1zone_alpha":  {"max_consecutive_losses": 3, "max_trades_per_day": 20},
    "scalp_h1zone_beta":   {"max_consecutive_losses": 3, "max_trades_per_day": 20},
    "fx_h1_zone_scalp":    {"max_consecutive_losses": 3, "max_trades_per_day": 20},
    # Options spreads from the swing panel — manual + few per day.
    "swing_setup":         {"max_consecutive_losses": 3, "max_trades_per_day": 10},
}


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _et_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        return timezone(timedelta(hours=-4))


def _cfg_key(strategy: Optional[str]) -> str:
    return f"risk:runaway_guard:config:{strategy}" if strategy else LEGACY_CFG_KEY


def _state_key(strategy: Optional[str]) -> str:
    return f"risk:runaway_guard:state:{strategy}" if strategy else LEGACY_STATE_KEY


def get_config(strategy: Optional[str] = None) -> dict:
    """Merged config: DEFAULT_CONFIG ← STRATEGY_DEFAULTS[strategy] ← Redis override."""
    base = dict(DEFAULT_CONFIG)
    if strategy and strategy in STRATEGY_DEFAULTS:
        base.update(STRATEGY_DEFAULTS[strategy])
    raw = _rdb().get(_cfg_key(strategy))
    if raw:
        try:
            base.update(json.loads(raw))
        except Exception:
            pass
    return base


def set_config(updates: dict, strategy: Optional[str] = None) -> dict:
    merged = {**get_config(strategy), **(updates or {})}
    for k, lo in (("max_trades_per_day", 0), ("max_consecutive_losses", 0),
                  ("reset_hour_et", 0), ("reset_minute_et", 0)):
        try:
            merged[k] = max(lo, int(merged.get(k, DEFAULT_CONFIG[k])))
        except (TypeError, ValueError):
            merged[k] = DEFAULT_CONFIG[k]
    merged["reset_hour_et"] = merged["reset_hour_et"] % 24
    merged["reset_minute_et"] = merged["reset_minute_et"] % 60
    merged["enabled"] = bool(merged.get("enabled", True))
    _rdb().set(_cfg_key(strategy), json.dumps(merged))
    return merged


def _current_boundary_utc(strategy: Optional[str] = None) -> datetime:
    cfg = get_config(strategy)
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


def get_state(strategy: Optional[str] = None) -> dict:
    boundary = _current_boundary_utc(strategy)
    raw = _rdb().get(_state_key(strategy))
    if not raw:
        state = _empty_state(boundary)
    else:
        try:
            saved = json.loads(raw)
            saved_start = saved.get("day_start")
            if saved_start:
                try:
                    if datetime.fromisoformat(saved_start.replace("Z", "+00:00")) < boundary:
                        state = _empty_state(boundary)
                    else:
                        saved.setdefault("day_start", boundary.isoformat())
                        saved.setdefault("trades_today", 0)
                        saved.setdefault("consecutive_losses", 0)
                        state = saved
                except Exception:
                    state = _empty_state(boundary)
            else:
                state = _empty_state(boundary)
        except Exception:
            state = _empty_state(boundary)
    _ensure_seeded_from_diary(state, boundary, strategy)
    return state


def _ensure_seeded_from_diary(state: dict, boundary: datetime,
                              strategy: Optional[str] = None) -> None:
    """Backfill trades_today + consecutive_losses from the diary the first
    time we run in a given day_start window.

    Idempotent via a `seeded:<day_start>` sentinel in the saved state.
    Without this, deploying the guard mid-day would show trades_today=0
    even though the diary has dozens of INTENT_OPEN rows in the window —
    confusing UX and worse, the trip logic wouldn't see the trade-count
    history accurately.

    When strategy is provided, the seed query filters by that strategy
    so an HTF FX losing streak does NOT seed the 2n20 counter.
    """
    if state.get("seeded_for") == state.get("day_start"):
        return
    try:
        from .diary import query_events
        events = query_events(strategy_id=strategy, ticker=None,
                              since=boundary.isoformat(),
                              until=None, limit=5000) or []
    except Exception as e:
        logger.debug("runaway_guard seed: diary query failed: %s", e)
        return
    intent_opens = [e for e in events if e.get("state") == "INTENT_OPEN"]
    state["trades_today"] = len(intent_opens)
    # Consecutive losses: walk CLOSED events newest-first, count negatives
    # until we hit the first winner.
    closed_desc = sorted(
        [e for e in events if e.get("state") == "CLOSED"
         and e.get("realized_pl") is not None],
        key=lambda e: e.get("event_time", ""), reverse=True,
    )
    streak = 0
    for c in closed_desc:
        try:
            pl = float(c.get("realized_pl"))
        except (TypeError, ValueError):
            continue
        if pl < 0:
            streak += 1
        else:
            break
    state["consecutive_losses"] = streak
    state["seeded_for"] = state["day_start"]
    _save(state, strategy)
    logger.info(
        "runaway_guard[%s]: seeded from diary — trades_today=%d, "
        "consecutive_losses=%d (day_start=%s)",
        strategy or "global", state["trades_today"],
        state["consecutive_losses"], state["day_start"],
    )


def _save(state: dict, strategy: Optional[str] = None) -> None:
    _rdb().set(_state_key(strategy), json.dumps(state))


def record_entry(strategy: Optional[str] = None) -> dict:
    """Called when an entry signal is accepted (BUY/SELL). Increments
    trades_today. Trips when the count crosses max_trades_per_day."""
    state = get_state(strategy)
    cfg = get_config(strategy)
    state["trades_today"] = int(state.get("trades_today", 0)) + 1
    cap = int(cfg.get("max_trades_per_day", 0))
    if cap > 0 and state["trades_today"] > cap and not state.get("tripped"):
        state["tripped"] = True
        state["tripped_at"] = datetime.now(timezone.utc).isoformat()
        state["trip_reason"] = (
            f"max_trades_per_day: {state['trades_today']} > cap {cap}"
        )
        logger.warning("runaway_guard[%s] TRIPPED on trade count: %s",
                       strategy or "global", state["trip_reason"])
        _telegram_trip(state["trip_reason"], strategy)
    _save(state, strategy)
    return state


def record_close(realized_pl: float, strategy: Optional[str] = None) -> dict:
    """Called when a trade closes (CLOSED diary event). Updates the
    consecutive-loss streak. Trips when the streak hits the cap."""
    state = get_state(strategy)
    cfg = get_config(strategy)
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
        logger.warning("runaway_guard[%s] TRIPPED on loss streak: %s",
                       strategy or "global", state["trip_reason"])
        _telegram_trip(state["trip_reason"], strategy)
    _save(state, strategy)
    return state


def manual_reset(strategy: Optional[str] = None) -> dict:
    state = get_state(strategy)
    state["tripped"] = False
    state["tripped_at"] = None
    state["trip_reason"] = None
    _save(state, strategy)
    logger.info("runaway_guard[%s] manually reset", strategy or "global")
    return state


def is_blocking_entry(strategy: Optional[str] = None) -> bool:
    """Webhook hot-path check. True iff a new entry should be refused
    BEFORE incrementing the counter."""
    cfg = get_config(strategy)
    if not cfg.get("enabled"):
        return False
    state = get_state(strategy)
    return bool(state.get("tripped"))


def _telegram_trip(reason: str, strategy: Optional[str] = None) -> None:
    try:
        from .ibkr_sync_cpapi import _send_telegram_alert
        scope = strategy or "global"
        _send_telegram_alert(
            f"🚧 Runaway guard tripped ({scope})",
            f"Strategy {scope} has stopped accepting new entries.\n\n"
            f"Reason: {reason}\n\n"
            f"Resets at the next daily boundary, or reset manually in "
            f"Settings → Runaway guard.",
        )
    except Exception:
        pass
