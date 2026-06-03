"""Trade-diary reconciler — compare what the diary says against what the
broker actually shows, every sync tick.

v1 is **detection-only**: emits RECONCILE_* diary events and Telegram
alerts on first detection. No corrective broker actions (no auto-close,
no auto-adopt) until we've watched it run for a while and confirmed it
catches what it should without false positives.

Detection cases (per broker per ticker per user):

  diary live qty     broker qty    diagnosis              event written
  ──────────────────────────────────────────────────────────────────────
  +N                 +N            in sync                — none —
  +N                 0             broker silently closed RECONCILE_GONE
  0  (no live row)   +N (or -N)    unknown broker pos     RECONCILE_PHANTOM
  +N                 +M (N != M)   partial mismatch       RECONCILE_PHANTOM
  INTENT_OPEN aged   never opened  order died             CANCELLED
  > stale_intent_s   at broker                            (treated as terminal)

Cooldown: once a (broker, ticker, kind) mismatch has been flagged, don't
re-flag it for ALERT_COOLDOWN_SECONDS. The bot/operator should have
intervened by then; spamming the diary helps no one.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from . import diary

logger = logging.getLogger(__name__)

# Minimum seconds between fast-tier reconcile passes. Called every sync
# tick; the pass itself short-circuits if it ran recently. Fast enough to
# detect scalp stops (positions sometimes held only 30s).
MIN_INTERVAL_SECONDS = 5

# Slow-tier: /portfolio/positions sanity backstop interval. Catches drift
# that the fills stream wouldn't see (e.g. positions opened in IB GUI by
# the user before the bot has any fills for them, or fills > 7d old).
# This is the only place we still touch the lagging position summary.
SLOW_TIER_INTERVAL_SECONDS = 60

# How old can an INTENT_OPEN be without a corresponding OPEN before we
# assume the order died and mark it CANCELLED? IB usually fills MKT
# orders in <2s. 5 minutes is very forgiving.
STALE_INTENT_SECONDS = 300

# Grace period after an OPEN event before we'll flag it as RECONCILE_GONE.
# With fills-based truth (net_positions_from_fills), the trades endpoint
# lags fills by only 1-2s, so a short grace handles ordinary jitter. The
# big lag we saw earlier (4.5min) was from /portfolio/positions, which is
# no longer in the hot path. 10s is comfortable.
RECONCILE_GONE_GRACE_SECONDS = 10

# Suppress duplicate alerts for the same (broker, ticker, kind) for
# this many seconds. Prevents the same orphan from spamming the diary
# every reconcile pass.
ALERT_COOLDOWN_SECONDS = 600

# Module-level state. Single bot process, so plain dicts are fine.
_last_pass_at: float = 0.0
_last_slow_pass_at: float = 0.0
_recent_emits: Dict[tuple, float] = {}


def _is_disabled() -> bool:
    """Redis kill switch — when `ibkr:reconciler:disabled` = "1" the
    reconciler skips every pass. Set/unset with redis-cli without a
    redeploy. Added 2026-06-02 after the adopt path on reconciler.py:481
    silently synthesized a 15-contract MES strat_pos from accumulated
    orphan fills, exposing the bot to $1k of risk on a position no
    strategy actually opened.
    """
    try:
        import os
        import redis as _redis
        _r = _redis.from_url(os.environ.get("REDIS_URL",
                                            "redis://localhost:6379/0"))
        return _r.get("ibkr:reconciler:disabled") == b"1"
    except Exception:
        return False


def _should_emit(key: tuple) -> bool:
    """Return True iff this mismatch wasn't already flagged recently."""
    now = time.time()
    last = _recent_emits.get(key, 0.0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return False
    _recent_emits[key] = now
    return True


def _parse_event_time(s: Optional[str]) -> Optional[float]:
    """Parse a Supabase timestamptz string into a unix epoch seconds float."""
    if not s:
        return None
    try:
        # Supabase returns ISO-8601 with timezone; handle both 'Z' and offset.
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _telegram(title: str, body: str) -> None:
    """Best-effort Telegram alert. Never raises."""
    try:
        from .supabase_client import send_telegram_message
        send_telegram_message(f"*{title}*\n{body}")
    except Exception as e:
        logger.debug("reconciler telegram failed: %s", e)


def _live_rows_for_user(broker: str) -> list:
    """Pull every live trade_state_current row for this broker."""
    if not diary._service_key():
        return []
    uid = diary._supabase_user_id()
    params = {
        "broker": f"eq.{broker}",
        "state": (
            f"in.({diary.State.INTENT_OPEN},"
            f"{diary.State.OPEN},"
            f"{diary.State.INTENT_CLOSE})"
        ),
        "select": "*",
    }
    if uid:
        params["user_id"] = f"eq.{uid}"
    data = diary._rest_request("GET", "trade_state_current", params=params)
    return data if isinstance(data, list) else []


def run_pass(
    broker: str,
    broker_qty_by_ticker: Dict[str, int],
    fill_details: Optional[Dict[str, Dict]] = None,
    multiplier_by_ticker: Optional[Dict[str, float]] = None,
    order_status_by_id: Optional[Dict[str, dict]] = None,
) -> None:
    """One reconcile pass for the given broker.

    broker_qty_by_ticker: signed net contracts/units per ticker — positive
    = long, negative = short, 0 or absent = flat.

    fill_details (optional): the full output of net_positions_from_fills(),
    used to recover exit_price / realized_pl on RECONCILE_GONE events.

    multiplier_by_ticker (optional): $/pt for each ticker (MES=5, MNQ=2, …)
    used to compute realized_pl. If absent, exit_price is recorded without
    pnl.

    Idempotent within the cooldown window; safe to call every loop tick.
    """
    if _is_disabled():
        return
    global _last_pass_at
    now = time.time()
    if now - _last_pass_at < MIN_INTERVAL_SECONDS:
        return
    _last_pass_at = now

    try:
        live = _live_rows_for_user(broker)
    except Exception as e:
        logger.warning("reconciler: live fetch failed: %s", e)
        return

    # Group diary rows by ticker. Sum expected_qty across OPEN rows —
    # multiple strategies (e.g. 2n20 + ORB) can each hold a leg of the
    # same ticker, and the broker only shows the aggregate.
    diary_qty_by_ticker: Dict[str, int] = {}
    rows_by_ticker: Dict[str, list] = {}
    for row in live:
        t = row.get("ticker")
        if not t:
            continue
        rows_by_ticker.setdefault(t, []).append(row)
        if row.get("state") == diary.State.OPEN:
            qty = int(row.get("expected_qty") or 0)
            diary_qty_by_ticker[t] = diary_qty_by_ticker.get(t, 0) + qty

    # 1a. Order-status confirmation (task #1): for any live row with a
    #     broker_trade_id, look it up in the order snapshot. If we see
    #     a terminal status the diary doesn't yet reflect, promote/cancel
    #     immediately — much faster than waiting on STALE_INTENT_SECONDS.
    if order_status_by_id:
        for rows in rows_by_ticker.values():
            for row in rows:
                btid = row.get("broker_trade_id")
                state = row.get("state")
                if not btid or state not in (
                    diary.State.INTENT_OPEN, diary.State.OPEN, diary.State.INTENT_CLOSE
                ):
                    continue
                ord_row = order_status_by_id.get(str(btid))
                if not ord_row:
                    continue
                ord_status = str(ord_row.get("status") or "")

                if state == diary.State.INTENT_OPEN and ord_status == "Filled":
                    # Promote to OPEN with the actual fill price.
                    try:
                        avg_price = float(ord_row.get("avgPrice") or 0) or None
                    except (TypeError, ValueError):
                        avg_price = None
                    key = ("confirm_open", btid)
                    if _should_emit(key):
                        logger.info(
                            "RECONCILE confirm: %s INTENT_OPEN→OPEN (order %s Filled @ %s)",
                            row.get("ticker"), btid, avg_price,
                        )
                        diary.record_event(
                            broker=broker,
                            broker_trade_id=btid,
                            client_intent_id=row.get("client_intent_id"),
                            strategy_id=row.get("strategy_id"),
                            ticker=row.get("ticker"),
                            state=diary.State.OPEN,
                            reason=f"order-status confirm: Filled",
                            expected_qty=int(row.get("expected_qty") or 0),
                            entry_price=avg_price,
                        )
                elif ord_status in ("Cancelled", "Rejected", "Inactive"):
                    key = ("cancel_via_status", btid)
                    if _should_emit(key):
                        logger.info(
                            "RECONCILE confirm: %s %s→CANCELLED (order %s %s)",
                            row.get("ticker"), state, btid, ord_status,
                        )
                        diary.record_event(
                            broker=broker,
                            broker_trade_id=btid,
                            client_intent_id=row.get("client_intent_id"),
                            strategy_id=row.get("strategy_id"),
                            ticker=row.get("ticker"),
                            state=diary.State.CANCELLED,
                            reason=f"order-status confirm: {ord_status}",
                            expected_qty=0,
                        )

    # 1b. Stale-intent timeout: any INTENT_OPEN older than STALE_INTENT_SECONDS
    #     with no broker_trade_id is treated as a failed order placement.
    for rows in rows_by_ticker.values():
        for row in rows:
            if row.get("state") != diary.State.INTENT_OPEN:
                continue
            if row.get("broker_trade_id"):
                continue
            ts = _parse_event_time(row.get("last_event_time"))
            if not ts or (now - ts) < STALE_INTENT_SECONDS:
                continue
            intent_id = row.get("client_intent_id")
            ticker = row.get("ticker")
            key = ("stale_intent", intent_id)
            if not _should_emit(key):
                continue
            logger.warning(
                "RECONCILE: stale INTENT_OPEN %s/%s intent=%s age=%.0fs",
                row.get("strategy_id"), ticker, intent_id, now - ts,
            )
            diary.record_event(
                broker=broker,
                client_intent_id=intent_id,
                strategy_id=row.get("strategy_id"),
                ticker=ticker,
                state=diary.State.CANCELLED,
                reason=f"stale INTENT_OPEN — no fill within {STALE_INTENT_SECONDS}s",
                expected_qty=0,
            )

    # 2. Per-ticker quantity comparison.
    all_tickers = set(diary_qty_by_ticker) | {t for t, q in broker_qty_by_ticker.items() if q}
    for ticker in all_tickers:
        diary_qty = diary_qty_by_ticker.get(ticker, 0)
        broker_qty = broker_qty_by_ticker.get(ticker, 0)
        if diary_qty == broker_qty:
            continue

        rows = rows_by_ticker.get(ticker, [])

        # Case A: diary expects position, broker is flat → broker closed
        # silently (stop fired untracked, manual close, IB silent fill).
        if diary_qty != 0 and broker_qty == 0:
            for row in rows:
                if row.get("state") != diary.State.OPEN:
                    continue
                # Grace period: a fresh OPEN may lead the IB position summary
                # by 20-40s. Skip GONE flagging until the position has had
                # time to settle in /portfolio/positions.
                opened_at = _parse_event_time(row.get("last_event_time"))
                if opened_at and (now - opened_at) < RECONCILE_GONE_GRACE_SECONDS:
                    logger.debug(
                        "reconciler: skip GONE for %s/%s — OPEN age %.0fs < grace %ds",
                        row.get("strategy_id"), ticker,
                        now - opened_at, RECONCILE_GONE_GRACE_SECONDS,
                    )
                    continue
                btid = row.get("broker_trade_id") or "intent:" + (row.get("client_intent_id") or "")
                key = ("gone", broker, ticker, btid)
                if not _should_emit(key):
                    continue
                logger.warning(
                    "RECONCILE: %s %s diary says OPEN qty=%+d but broker is flat (trade=%s)",
                    broker, ticker, row.get("expected_qty") or 0, btid,
                )

                # Try to recover the closing fill from fill_details — when
                # net is now 0 but expected_qty was +N (long), the most
                # recent fill for this ticker must have been a SELL (close).
                # That's our exit. Same logic mirrored for shorts.
                exit_price = None
                realized_pl = None
                close_reason = "broker is flat but diary says OPEN"
                if fill_details and ticker in fill_details:
                    fd = fill_details[ticker]
                    expected = int(row.get("expected_qty") or 0)
                    last_side = fd.get("last_side")
                    last_price = float(fd.get("last_price") or 0)
                    if last_price > 0 and (
                        (expected > 0 and last_side == "S") or
                        (expected < 0 and last_side == "B")
                    ):
                        exit_price = last_price
                        close_reason = f"close inferred from last {last_side} fill @ {last_price}"
                        entry_price = float(row.get("entry_price") or 0)
                        mult = (multiplier_by_ticker or {}).get(ticker)
                        if entry_price and mult:
                            qty = abs(expected)
                            if expected > 0:
                                realized_pl = round((exit_price - entry_price) * qty * mult, 2)
                            else:
                                realized_pl = round((entry_price - exit_price) * qty * mult, 2)

                diary.record_event(
                    broker=broker,
                    broker_trade_id=row.get("broker_trade_id"),
                    client_intent_id=row.get("client_intent_id"),
                    strategy_id=row.get("strategy_id"),
                    ticker=ticker,
                    state=diary.State.RECONCILE_GONE,
                    reason=close_reason,
                    expected_qty=int(row.get("expected_qty") or 0),
                    observed_qty=0,
                    exit_price=exit_price,
                    realized_pl=realized_pl,
                )
                pl_text = f", est. P&L `${realized_pl}`" if realized_pl is not None else ""
                exit_text = f" exit~`{exit_price}`" if exit_price else ""
                _telegram(
                    "🔎 Diary mismatch: broker flat",
                    f"`{ticker}` [{row.get('strategy_id')}] diary expected "
                    f"qty=`{row.get('expected_qty')}`, broker shows `0`{exit_text}{pl_text}. "
                    f"Trade `{btid}`.",
                )
            continue

        # Case B: broker has position, diary has no live row.
        # Classify by the fill's order_ref:
        #   lumi_<slug>_<hash>  → bot-placed but we lost lineage → ADOPT
        #                          with decoded strategy_id
        #   any other order_ref → external (IB GUI / mobile) → ADOPT
        #                          under strategy='manual'
        #   no matching fill    → genuine PHANTOM → hard alert (rare)
        if diary_qty == 0 and broker_qty != 0:
            last_order_id = (fill_details or {}).get(ticker, {}).get("last_order_id") or ""
            last_price = float((fill_details or {}).get(ticker, {}).get("last_price") or 0)
            order_ref = ""
            if last_order_id and order_status_by_id:
                ord_row = order_status_by_id.get(str(last_order_id)) or {}
                order_ref = str(ord_row.get("order_ref") or "")

            # Decode strategy from lumi_<slug>_<hash>
            decoded_strategy = None
            if order_ref.startswith("lumi_"):
                # Trim 'lumi_' and trailing '_<hash>'. Hash is 8 hex.
                inner = order_ref[5:]
                if "_" in inner:
                    decoded_strategy = inner.rsplit("_", 1)[0] or None

            # Fallback: even when /orders returns order_ref correctly,
            # /trades' order_id sometimes uses a different ID scheme than
            # /orders' orderId, so the lookup above misses (observed
            # 2026-06-01: 55 fills all adopted as "manual" because of
            # this mismatch). Look up our own Redis mapping keyed by the
            # perm_id we get back from place_order — bulletproof against
            # IB endpoint quirks. See record_strategy_for_perm in
            # ibkr_sync_cpapi.py.
            if not decoded_strategy and last_order_id:
                try:
                    import os
                    import redis as _redis
                    _rdb_fb = _redis.from_url(
                        os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
                    raw = _rdb_fb.get(f"ibkr:strategy_by_perm:{last_order_id}")
                    if raw:
                        decoded_strategy = (
                            raw.decode() if isinstance(raw, bytes) else str(raw)
                        )
                        # Synthesize a faux order_ref so downstream logging
                        # still shows the source clearly.
                        order_ref = f"lumi_{decoded_strategy}_redislookup"
                except Exception as e:
                    logger.debug("reconciler perm→strategy redis fallback failed: %s", e)

            if last_order_id:
                # Adopt — synthetic broker_trade_id from the actual fill id
                # so subsequent passes update this row instead of recreating.
                btid = f"adopted:{last_order_id}"
                if decoded_strategy:
                    strat = decoded_strategy
                    reason = f"adopted from lumi-tagged fill (order_ref={order_ref})"
                    title = "🪝 Bot lineage recovered"
                else:
                    strat = "manual"
                    reason = (f"adopted from external fill "
                              f"(order_id={last_order_id}, ref={order_ref or 'none'})")
                    title = "🪝 External fill auto-adopted"
                key = ("adopt", broker, ticker, last_order_id)
                if not _should_emit(key):
                    continue
                logger.info(
                    "RECONCILE adopt: %s %s qty=%+d order_id=%s ref=%s strategy=%s",
                    broker, ticker, broker_qty, last_order_id,
                    order_ref or "(none)", strat,
                )
                diary.record_event(
                    broker=broker,
                    broker_trade_id=btid,
                    strategy_id=strat,
                    ticker=ticker,
                    state=diary.State.RECONCILE_ADOPTED,
                    reason=reason,
                    expected_qty=broker_qty,
                    observed_qty=broker_qty,
                    entry_price=last_price or None,
                    meta={"source_order_id": str(last_order_id),
                          "source_order_ref": order_ref or None,
                          "decoded_strategy": decoded_strategy},
                )
                # Find a matching bracket SL in the open-orders snapshot —
                # opposite side, STP orderType, same ticker. Linking it via
                # stop_order_id lets check_stop_fills monitor the adopted
                # position properly so an SL fire clears strat_pos cleanly
                # instead of triggering another orphan cycle on next loop.
                # Best-effort: empty stop_order_id is also fine, the bot
                # falls back to "IB_QTY disappeared" detection.
                exit_side = "SELL" if broker_qty > 0 else "BUY"
                discovered_sl_id = ""
                discovered_sl_price = 0.0
                discovered_tp_id = ""
                discovered_tp_price = 0.0
                for _ord in (order_status_by_id or {}).values():
                    if not isinstance(_ord, dict):
                        continue
                    o_ticker = (_ord.get("ticker") or "").upper()
                    if o_ticker and o_ticker != ticker.upper():
                        continue
                    o_side = (_ord.get("side") or "").upper()
                    if o_side != exit_side:
                        continue
                    o_status = (_ord.get("status") or "").lower()
                    if o_status in ("filled", "cancelled"):
                        continue
                    o_type = (_ord.get("orderType") or "").upper()
                    if o_type in ("STP", "STOP", "STOP_LIMIT") and not discovered_sl_id:
                        discovered_sl_id = str(_ord.get("orderId") or "")
                        try:
                            discovered_sl_price = float(
                                _ord.get("stop_price") or _ord.get("price") or 0
                            )
                        except (TypeError, ValueError):
                            discovered_sl_price = 0.0
                    elif o_type in ("LMT", "LIMIT") and not discovered_tp_id:
                        discovered_tp_id = str(_ord.get("orderId") or "")
                        try:
                            discovered_tp_price = float(_ord.get("price") or 0)
                        except (TypeError, ValueError):
                            discovered_tp_price = 0.0
                if discovered_sl_id or discovered_tp_id:
                    logger.info(
                        "RECONCILE adopt: bracket children linked for %s — "
                        "sl=%s @ %.2f tp=%s @ %.2f",
                        ticker, discovered_sl_id or "-", discovered_sl_price,
                        discovered_tp_id or "-", discovered_tp_price,
                    )

                # Also create a Redis strat_pos so downstream code (mobile
                # UI mismatch warning, close path, check_stop_fills, etc.)
                # sees the position as "tracked" under the adopted strategy.
                # Without this the mobile shows "ALL ORPHAN" forever and
                # closes go through the [untracked] fallback path.
                # Lazy import to avoid a circular reconciler ↔ ibkr_sync
                # cycle at module load time.
                try:
                    from .ibkr_sync_cpapi import save_strat_pos
                    # If the order originated from the mobile MTF dashboard
                    # (or a future panel that calls model_by_perm), pick up
                    # the model so the audit row shows "MTF·" / "Scalp·" /
                    # "Intraday·" instead of just the strategy name alone.
                    adopt_model = ""
                    try:
                        if last_order_id:
                            import redis as _redis_m
                            rdb_m = _redis_m.from_url(os.environ.get("REDIS_URL",
                                "redis://localhost:6379/0"))
                            raw_m = rdb_m.get(f"ibkr:model_by_perm:{last_order_id}")
                            if raw_m:
                                adopt_model = (raw_m.decode() if isinstance(raw_m, bytes) else str(raw_m))
                    except Exception as _me:
                        logger.debug("model_by_perm lookup failed: %s", _me)
                    save_strat_pos(
                        ticker=ticker,
                        strategy=strat,
                        direction="BUY" if broker_qty > 0 else "SELL",
                        contracts=abs(int(broker_qty)),
                        entry_price=float(last_price or 0),
                        perm_id=str(last_order_id or ""),
                        stop_order_id=discovered_sl_id,
                        stop_price=discovered_sl_price,
                        target_order_id=discovered_tp_id,
                        target_price=discovered_tp_price,
                        metadata={"model": adopt_model} if adopt_model else None,
                        caller="reconciler_adopt",
                    )
                except Exception as _e:
                    logger.warning(
                        "RECONCILE adopt: strat_pos save failed for %s/%s: %s",
                        ticker, strat, _e,
                    )
                _telegram(
                    title,
                    f"`{ticker}` qty=`{broker_qty:+d}` adopted under `{strat}` "
                    f"(from order `{last_order_id}`).",
                )
                continue

            # True phantom: position exists, no matching fill in 7-day window.
            # That's a "shouldn't happen" — alert hard, do not auto-adopt.
            key = ("phantom", broker, ticker, broker_qty)
            if not _should_emit(key):
                continue
            logger.warning(
                "RECONCILE: %s %s broker shows qty=%+d but NO fill in 7d — investigate",
                broker, ticker, broker_qty,
            )
            diary.record_event(
                broker=broker,
                broker_trade_id=f"phantom:{ticker}:{broker_qty}",
                strategy_id="unknown",
                ticker=ticker,
                state=diary.State.RECONCILE_PHANTOM,
                reason="position with no fill in 7-day trades window",
                expected_qty=0,
                observed_qty=broker_qty,
            )
            _telegram(
                "🚨 True phantom position",
                f"`{ticker}` broker shows `{broker_qty:+d}` but no fill in 7d. "
                f"Pre-existing position from before the bot was deployed?",
            )
            continue

        # Case C: both have positions but quantities disagree → partial
        # mismatch. Could be a half-fill, an untracked extra contract, or
        # one strategy's exit happened without a diary CLOSED write.
        key = ("partial", broker, ticker, diary_qty, broker_qty)
        if not _should_emit(key):
            continue
        logger.warning(
            "RECONCILE: %s %s diary qty=%+d, broker qty=%+d (delta=%+d)",
            broker, ticker, diary_qty, broker_qty, broker_qty - diary_qty,
        )
        # Attach to the first live OPEN row so the diary view shows the
        # mismatch under a known trade. Strategy-attribution may be off if
        # multiple strategies hold the ticker; the operator decides.
        anchor = next(
            (r for r in rows if r.get("state") == diary.State.OPEN),
            rows[0] if rows else None,
        )
        diary.record_event(
            broker=broker,
            broker_trade_id=(anchor or {}).get("broker_trade_id"),
            client_intent_id=(anchor or {}).get("client_intent_id"),
            strategy_id=(anchor or {}).get("strategy_id") or "unknown",
            ticker=ticker,
            state=diary.State.RECONCILE_PHANTOM,
            reason=f"qty mismatch diary={diary_qty} broker={broker_qty}",
            expected_qty=diary_qty,
            observed_qty=broker_qty,
        )
        _telegram(
            "🔎 Diary mismatch: qty drift",
            f"`{ticker}` diary=`{diary_qty:+d}`, broker=`{broker_qty:+d}`. "
            f"Strategy `{(anchor or {}).get('strategy_id') or 'unknown'}`.",
        )


def positions_to_qty_by_ticker(positions: Iterable[dict]) -> Dict[str, int]:
    """Convert a list of IB position dicts (from CPAPI client.get_positions)
    into a signed qty-per-symbol map suitable for run_pass().

    DEPRECATED for hot-path use — /portfolio/positions lags real fills by
    minutes. Prefer net_positions_from_fills(). Kept for slow-tier sanity
    backstop in #6.
    """
    out: Dict[str, int] = {}
    for p in positions:
        sym = p.get("symbol") or p.get("ticker")
        if not sym:
            continue
        try:
            qty = int(p.get("quantity") or p.get("position") or 0)
        except (TypeError, ValueError):
            continue
        if not qty:
            continue
        out[sym] = out.get(sym, 0) + qty
    return out


def net_positions_from_fills(client) -> Dict[str, Dict]:
    """Compute authoritative net qty per ticker by summing IB trade fills.

    Calls /iserver/account/trades (≤7 days of fills, ~1-2s latency) and
    sums signed sizes per symbol. Returns a richer dict per ticker so
    callers can also see the most recent fill's price + order_id (used by
    the diary to recover exit prices on RECONCILE_GONE — #8).

        {ticker: {
            qty: int,                    # signed net contracts (long positive)
            last_trade_at_ms: int,       # epoch ms of most recent fill
            last_price: float,           # price of most recent fill
            last_side: str,              # 'B' or 'S' of most recent fill
            last_order_id: str,          # IB order id of most recent fill
        }}

    Tickers with zero net qty are omitted.

    Caveat: the 7-day window means positions opened > 7 days ago and not
    touched since won't be reflected. The bot doesn't hold swing futures
    positions, so this is a non-issue in practice. Slow-tier backstop
    (#6) catches any drift.
    """
    try:
        trades = client.get_trades() or []
    except Exception as e:
        logger.warning("net_positions_from_fills: get_trades failed: %s", e)
        return {}

    # For each ticker, track the most recent fill. IB's `position` field on
    # a trade record is the authoritative post-trade net. We do NOT sum
    # signed sizes — that double-counts opening fills outside the 7-day
    # window and produced false phantoms (observed 2026-05-22: replay sum
    # said +2 while IB pos_after said 0).
    #
    # `side` here uses 'B' for buy, 'S' for sell. The sign on `position`
    # already reflects long(+)/short(-).
    by_ticker: Dict[str, Dict] = {}
    for t in trades:
        sym = t.get("symbol")
        if not sym:
            continue
        tt = int(t.get("trade_time_r") or 0)
        slot = by_ticker.get(sym)
        if slot is not None and tt <= slot["last_trade_at_ms"]:
            continue
        try:
            pos_after = float(t.get("position") or 0)
        except (TypeError, ValueError):
            pos_after = 0
        try:
            last_price = float(t.get("price") or 0)
        except (TypeError, ValueError):
            last_price = 0.0
        by_ticker[sym] = {
            "qty": int(round(pos_after)),
            "last_trade_at_ms": tt,
            "last_side": t.get("side", ""),
            "last_price": last_price,
            "last_order_id": str(t.get("order_id") or ""),
        }
    return by_ticker


def qty_map_from_fills(client) -> Dict[str, int]:
    """Thin wrapper returning just {ticker: signed_qty} — drop-in
    replacement for positions_to_qty_by_ticker() that pulls fill data
    instead of position summaries. Use for run_pass()."""
    full = net_positions_from_fills(client)
    return {sym: slot["qty"] for sym, slot in full.items() if slot["qty"] != 0}


def slow_tier_pass(broker: str, position_summary: Iterable[dict]) -> None:
    """Slow-tier backstop pass. Compares /portfolio/positions (lagging, but
    catches positions our fills stream wouldn't see — e.g. manual GUI
    entries, holdings > 7 days old) against the diary.

    Only flags genuine phantoms — positions the broker shows that the
    diary has no record of at all. Doesn't flag GONE; the fast tier owns
    that detection because the fast tier sees real-time fills.

    Self-throttles to SLOW_TIER_INTERVAL_SECONDS. Called by run_pass().
    """
    if _is_disabled():
        return
    global _last_slow_pass_at
    now = time.time()
    if now - _last_slow_pass_at < SLOW_TIER_INTERVAL_SECONDS:
        return
    _last_slow_pass_at = now

    # Pull live diary rows for context — we only care whether SOMETHING
    # is open per ticker (any state).
    if not diary._service_key():
        return
    uid = diary._supabase_user_id()
    params = {
        "broker": f"eq.{broker}",
        "select": "ticker,state,broker_trade_id",
    }
    if uid:
        params["user_id"] = f"eq.{uid}"
    rows = diary._rest_request("GET", "trade_state_current", params=params) or []
    diary_tickers_live = {
        r.get("ticker") for r in rows
        if r.get("state") in (diary.State.INTENT_OPEN, diary.State.OPEN, diary.State.INTENT_CLOSE)
    }

    for p in position_summary or []:
        sym = p.get("symbol") or p.get("ticker")
        if not sym:
            continue
        try:
            qty = int(p.get("quantity") or p.get("position") or 0)
        except (TypeError, ValueError):
            continue
        if qty == 0 or sym in diary_tickers_live:
            continue
        key = ("slow_phantom", broker, sym, qty)
        if not _should_emit(key):
            continue
        logger.warning(
            "RECONCILE (slow tier): %s %s broker shows qty=%+d but diary has no live row",
            broker, sym, qty,
        )
        diary.record_event(
            broker=broker,
            broker_trade_id=f"slow_phantom:{sym}:{qty}",
            strategy_id="unknown",
            ticker=sym,
            state=diary.State.RECONCILE_PHANTOM,
            reason="slow-tier: position summary shows holding with no diary record",
            expected_qty=0,
            observed_qty=qty,
        )
        _telegram(
            "🐢 Slow-tier diary mismatch",
            f"`{sym}` position summary shows `{qty:+d}` but no diary row. "
            f"Likely a manual / pre-existing position.",
        )


def orders_by_id(client) -> Dict[str, dict]:
    """Snapshot all known orders keyed by orderId (as string).

    Used for order-status confirmation (task #1) — given a broker_trade_id
    we can answer "is it Filled, Cancelled, Submitted?" in O(1) without
    polling per-order. CPAPI's /iserver/account/orders typically includes
    recent terminal-state orders (~24h window) alongside live ones.
    """
    try:
        raw = client.get_open_orders() or []
    except Exception as e:
        logger.debug("orders_by_id: get_open_orders failed: %s", e)
        return {}
    out: Dict[str, dict] = {}
    for o in raw:
        oid = str(o.get("orderId") or "")
        if oid:
            out[oid] = o
    return out
