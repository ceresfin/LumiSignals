"""Trade diary — append-only event log for every position state change.

Goal: eliminate orphan/phantom positions by recording every intended and
observed state transition BEFORE the bot acts on it. The reconciler reads
this diary, compares it against the broker, and flags or fixes mismatches.

States (mirrors public.trade_events.state on Supabase):
    INTENT_OPEN          bot asked broker to open
    OPEN                 broker confirmed fill
    INTENT_CLOSE         bot asked broker to close
    CLOSED               broker confirmed flat
    STOP_FIRED           stop loss triggered close
    CANCELLED            order died without filling
    RECONCILE_GONE       diary says OPEN, broker says flat
    RECONCILE_PHANTOM    diary says CLOSED, broker shows position
    RECONCILE_ADOPTED    reconciler attached an unknown broker position

Design rules:
    1. Writes are best-effort. A diary failure logs but never raises — a
       broken Supabase must not stop the bot from trading. The reconciler
       (and broker-side checks) catch any missed events.
    2. The diary is broker-agnostic. Callers map their internal strategy
       names through STRATEGY_SLUG to the stable diary slug.
    3. State transitions are append-only. trade_state_current is updated
       by a Postgres trigger — readers should query it (not scan
       trade_events) for the current state of a trade.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Direct REST against PostgREST. We deliberately don't use the `supabase`
# Python SDK so this module works regardless of whether the SDK is
# installed in the runtime venv.
_SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://cgomksatarqqehekrumk.supabase.co")
_SSL_CTX = ssl.create_default_context()
_TIMEOUT = 5  # seconds — keep diary writes off the hot path

# Async write queue (task #9): trading hot path puts rows here in <1ms;
# a single daemon thread drains them to Supabase. Order preserved via FIFO.
# In-memory queue means a bot crash drops in-flight events — acceptable for
# the diary's "best-effort observability" role; the reconciler catches any
# missed events via broker state comparison.
_write_queue: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
_drain_thread: Optional[threading.Thread] = None
_drain_lock = threading.Lock()
_drain_started = False


def _drain_loop():
    """Background thread: pop diary rows from the queue and POST to Supabase.
    Failed writes are logged and dropped — the reconciler is the safety net.
    """
    while True:
        try:
            row = _write_queue.get()
        except Exception:
            time.sleep(1)
            continue
        try:
            _rest_request(
                "POST", "trade_events", body=row,
                prefer="return=minimal",
            )
        except Exception as e:
            logger.warning("diary drain: write failed (dropping): %s", e)
        finally:
            try:
                _write_queue.task_done()
            except Exception:
                pass


def _ensure_drain_started() -> None:
    """Idempotently start the drain thread. Safe to call from any thread."""
    global _drain_thread, _drain_started
    if _drain_started and _drain_thread and _drain_thread.is_alive():
        return
    with _drain_lock:
        if _drain_started and _drain_thread and _drain_thread.is_alive():
            return
        _drain_thread = threading.Thread(
            target=_drain_loop, daemon=True, name="diary-drain",
        )
        _drain_thread.start()
        _drain_started = True
        logger.info("diary drain thread started")


class State:
    INTENT_OPEN = "INTENT_OPEN"
    OPEN = "OPEN"
    INTENT_CLOSE = "INTENT_CLOSE"
    CLOSED = "CLOSED"
    STOP_FIRED = "STOP_FIRED"
    CANCELLED = "CANCELLED"
    RECONCILE_GONE = "RECONCILE_GONE"
    RECONCILE_PHANTOM = "RECONCILE_PHANTOM"
    RECONCILE_ADOPTED = "RECONCILE_ADOPTED"


# Map internal strategy_name (used in code/redis/strat_pos) to the stable
# diary slug. Extend as new strategies are wired.
STRATEGY_SLUG = {
    "2n20":                 "futures_2n20",
    "fx_2n20":              "futures_2n20",       # FX leg uses same slug if/when added
    "fx_4h_trend":          "fx_4h_trend",
    "fx_4h":                "fx_4h_trend",
    "stillwater":           "fx_4h_trend",
    "fx_h1_zone":           "fx_h1_zone",
    "fx_h1_zone_alpha":     "fx_h1_zone",
    "fx_h1_zone_beta":      "fx_h1_zone",
    "htf_levels":           "htf_levels_intraday",
    "htf_levels_intraday":  "htf_levels_intraday",
    "htf_levels_swing":     "htf_levels_swing",
    "tidewater_swing":      "htf_levels_swing",
    "options_credit":       "options_credit",
}


def strategy_slug(name: str) -> Optional[str]:
    """Return the stable diary slug for an internal strategy name, or None."""
    if not name:
        return None
    return STRATEGY_SLUG.get(name.lower())


def new_intent_id() -> str:
    """Generate a fresh client_intent_id for a new INTENT_OPEN event.

    Use one of these per logical entry attempt, then thread the same id
    through to the matching OPEN/CANCELLED event so the diary can stitch
    the pre-fill window together.
    """
    return str(uuid.uuid4())


def _supabase_user_id() -> str:
    return os.environ.get("SUPABASE_USER_ID", "")


def _service_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_KEY", "")


def _rest_request(method: str, path: str, *, body=None, params=None,
                  prefer: Optional[str] = None) -> Optional[list]:
    """Minimal PostgREST client. Returns parsed JSON list or None on failure."""
    key = _service_key()
    if not key:
        return None
    url = f"{_SUPABASE_URL}/rest/v1/{path}"
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
            raw = resp.read()
            if not raw:
                return []
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:200]
        logger.warning("diary REST %s %s -> HTTP %s: %s", method, path, e.code, body_txt)
    except Exception as e:
        logger.warning("diary REST %s %s failed: %s", method, path, e)
    return None


def record_event(
    *,
    broker: str,
    strategy_id: str,
    ticker: str,
    state: str,
    user_id: Optional[str] = None,
    reason: str = "",
    broker_trade_id: Optional[str] = None,
    client_intent_id: Optional[str] = None,
    expected_qty: Optional[int] = None,
    observed_qty: Optional[int] = None,
    entry_price: Optional[float] = None,
    exit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
    realized_pl: Optional[float] = None,
    broker_snapshot: Optional[dict] = None,
    meta: Optional[dict] = None,
) -> Optional[str]:
    """Append one row to trade_events. Returns the event uuid, or None on failure.

    Required: broker, strategy_id, ticker, state.
    user_id defaults to SUPABASE_USER_ID env var (per-bot single-user setup).
    Either broker_trade_id or client_intent_id should be set so the row can
    be stitched into trade_state_current; the trigger enforces this.
    """
    uid = user_id or _supabase_user_id()
    if not uid:
        logger.debug("diary: no SUPABASE_USER_ID — skipping record_event")
        return None
    if not _service_key():
        logger.debug("diary: no SUPABASE_SERVICE_KEY — skipping record_event")
        return None
    if not strategy_id or not ticker or not state or not broker:
        logger.warning("diary: missing required field — broker=%s strat=%s ticker=%s state=%s",
                       broker, strategy_id, ticker, state)
        return None

    row = {
        "broker": broker,
        "broker_trade_id": broker_trade_id,
        "client_intent_id": client_intent_id,
        "strategy_id": strategy_id,
        "ticker": ticker,
        "user_id": uid,
        "state": state,
        "reason": reason or None,
        "expected_qty": expected_qty,
        "observed_qty": observed_qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "realized_pl": realized_pl,
        "broker_snapshot": broker_snapshot,
        "meta": meta,
    }
    # Strip Nones so we don't overwrite trigger-set columns with nulls
    row = {k: v for k, v in row.items() if v is not None}

    # Async write via FIFO queue (#9). Returns None — the trigger
    # generates the event id server-side; we no longer need it for any
    # callers in this codebase. If the queue is full, drop with a warning;
    # the reconciler will catch the missing event on its next pass.
    _ensure_drain_started()
    try:
        _write_queue.put_nowait(row)
    except queue.Full:
        logger.warning(
            "diary write queue full (size=%d) — dropping event %s/%s/%s",
            _write_queue.qsize(), broker, strategy_id, state,
        )
    return None


def current_state(broker: str, broker_trade_id: str) -> Optional[dict]:
    """Read the latest known state of a trade from trade_state_current.

    Returns the row as a dict, or None if not found / Supabase unavailable.
    """
    if not broker_trade_id:
        return None
    if not _service_key():
        return None
    data = _rest_request(
        "GET", "trade_state_current",
        params={
            "broker": f"eq.{broker}",
            "broker_trade_id": f"eq.{broker_trade_id}",
            "limit": 1,
            "select": "*",
        },
    )
    if isinstance(data, list) and data:
        return data[0]
    return None


def find_live_open(strategy_id: str, ticker: str,
                   user_id: Optional[str] = None) -> Optional[dict]:
    """Return the live OPEN row for (strategy_id, ticker), or None.

    Used by the order handler as a fallback when Redis strat_pos has been
    wiped — if the diary still says this strategy has a live position,
    a CLOSE webhook is honored.
    """
    rows = list_live(strategy_id, ticker, user_id=user_id)
    for row in rows:
        if row.get("state") == State.OPEN:
            return row
    return None


def upsert_live_price(ticker: str, price: float,
                      bid: Optional[float] = None,
                      ask: Optional[float] = None,
                      source: str = "ib_cpapi") -> None:
    """Push the latest market price for `ticker` to the shared
    `live_prices` table on Supabase. Mobile clients subscribe via
    realtime and recompute P&L instantly without waiting for the bot's
    full positions-sync cycle.

    Best-effort: failures log but don't raise (consistent with the rest
    of this module).
    """
    if not ticker or price is None:
        return
    if not _service_key():
        return
    try:
        body = {
            "ticker": ticker,
            "price": float(price),
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }
        if bid is not None:
            body["bid"] = float(bid)
        if ask is not None:
            body["ask"] = float(ask)
        # Upsert on ticker (PK) — PostgREST supports this via Prefer header.
        _rest_request(
            "POST", "live_prices",
            body=body,
            prefer="resolution=merge-duplicates,return=minimal",
        )
    except Exception as e:
        logger.debug("upsert_live_price failed for %s: %s", ticker, e)


def list_live(strategy_id: str, ticker: str, user_id: Optional[str] = None) -> list:
    """List trades currently in a live state (INTENT_OPEN/OPEN/INTENT_CLOSE)
    for one strategy+ticker. Used by the reconciler to compare against
    actual broker positions.
    """
    uid = user_id or _supabase_user_id()
    if not _service_key():
        return []
    params = {
        "strategy_id": f"eq.{strategy_id}",
        "ticker": f"eq.{ticker}",
        "state": f"in.({State.INTENT_OPEN},{State.OPEN},{State.INTENT_CLOSE})",
        "select": "*",
    }
    if uid:
        params["user_id"] = f"eq.{uid}"
    data = _rest_request("GET", "trade_state_current", params=params)
    return data if isinstance(data, list) else []
