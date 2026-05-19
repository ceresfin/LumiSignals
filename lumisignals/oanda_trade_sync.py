"""Periodic Oanda → Supabase trades-table sync.

History: previously walked Oanda's `/trades?state=CLOSED` endpoint and
upserted each result. That endpoint silently stops returning recently-
closed trades on some Oanda paper accounts (we hit this on
2026-05-19 — trades 38560+ never appeared via the trades API even
though their open/close fills are clearly in the transactions log).
Rewrote to walk the transactions endpoint instead, which is the
broker's immutable record of every fill that ever happened.

Algorithm
---------
1. Track `oanda:last_txn_id:{user_id}` in Redis — the highest
   transaction ID we've processed.
2. Each cycle, fetch ORDER_FILL transactions from (last_seen + 1) to
   the current `lastTransactionID`, paginating 1000-at-a-time
   (Oanda's idrange max).
3. Pair `tradeOpened` and `tradesClosed` entries by tradeID:
     - tradeOpened sets the entry side (price, units, time, instrument)
     - tradesClosed sets the exit side (price, realizedPL, time)
   When the opening fill is outside the current window, fetch the
   opening transaction directly by ID.
4. Look up strategy/model in the per-user signal_log keyed by tradeID.
5. Call record_closed_trade — upsert by (user_id, broker, broker_trade_id)
   so reruns converge.

Compared to the old trades-API approach this also gets us:
  - Reliable detection of every closure, including weird Oanda states
  - Free attribution of `close_reason` from the fill's `reason` field
    (STOP_LOSS_ORDER, TAKE_PROFIT_ORDER, LIMIT_ORDER, MARKET_ORDER)
  - Correct entry/exit times — straight from the broker
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

from .oanda_client import OandaClient
from .supabase_client import record_closed_trade, remove_position

logger = logging.getLogger(__name__)


def _redis():
    try:
        import redis
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception as e:
        logger.debug("redis unavailable: %s", e)
        return None


def _load_signal_log(pg_user_id: Optional[int] = None) -> dict:
    """Load the per-user signal log sidecar. Keyed by Oanda trade ID.

    Path uses the POSTGRES user id (integer), not the Supabase UUID —
    bot_runner writes `signal_log_user_{users.id}.json`. When pg_user_id
    isn't supplied, walk the candidate paths in order.
    """
    paths = []
    if pg_user_id is not None:
        paths.append(f"/opt/lumisignals/signal_log_user_{pg_user_id}.json")
    paths.extend([
        # Common single-user setup — most installs have id=1
        "/opt/lumisignals/signal_log_user_1.json",
        "/opt/lumisignals/app/signal_log.json",
        "signal_log.json",
    ])
    for p in paths:
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _parse_time(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Oanda returns either RFC3339 ("2026-05-18T07:32:29.123Z") or
        # unix-epoch-as-string ("1778268763.531408926"). Handle both.
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00").split(".")[0] + "+00:00")
        from datetime import timezone
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    except Exception:
        return None


def _to_iso(s: str) -> Optional[str]:
    """Normalize an Oanda time field to ISO 8601 UTC. Supabase rejects
    the unix-epoch-string variant Oanda sometimes returns, so we always
    convert before write."""
    dt = _parse_time(s)
    return dt.isoformat() if dt else None


def _close_reason(reason_code: str) -> str:
    """Map Oanda's ORDER_FILL.reason to a human label."""
    m = {
        "STOP_LOSS_ORDER":    "Stop Loss",
        "TAKE_PROFIT_ORDER":  "Take Profit",
        "TRAILING_STOP_LOSS_ORDER": "Trailing Stop",
        "LIMIT_ORDER":        "Limit Fill",
        "MARKET_ORDER":       "Manual close",
        "MARKET_IF_TOUCHED_ORDER": "MIT",
        "STOP_ORDER":         "Stop Order",
    }
    return m.get(reason_code or "", reason_code or "Manual")


def sync_closed_trades(client: OandaClient,
                       user_id: Optional[str] = None,
                       seed_lookback: int = 2000) -> int:
    """Walk new ORDER_FILL transactions, upsert any closed trades into
    Supabase. Returns count of trades written this cycle.

    seed_lookback: on the first run (no Redis cursor), how far back to
    seed. 2000 transactions covers a few days of normal activity.
    """
    user_id = user_id or os.environ.get("SUPABASE_USER_ID", "")
    if not user_id:
        return 0

    # 1. Current lastTransactionID from the account summary.
    try:
        acct = client._request("GET", f"/v3/accounts/{client.account_id}/summary")
        current_last = int((acct.get("account") or {}).get("lastTransactionID") or 0)
    except Exception as e:
        logger.warning("oanda_trade_sync: account summary failed: %s", e)
        return 0
    if current_last <= 0:
        return 0

    # 2. Resolve cursor.
    rdb = _redis()
    cursor_key = f"oanda:last_txn_id:{user_id}"
    last_seen = 0
    if rdb is not None:
        try:
            v = rdb.get(cursor_key)
            if v:
                last_seen = int(v)
        except Exception:
            pass
    if last_seen == 0:
        last_seen = max(1, current_last - seed_lookback)
    if current_last <= last_seen:
        return 0

    # 3. Page-fetch ORDER_FILL transactions in [last_seen+1, current_last].
    # Oanda's idrange caps at 1000 IDs per request.
    fill_txns = []
    cursor = last_seen + 1
    page_size = 1000
    pages = 0
    while cursor <= current_last and pages < 50:  # 50K txn safety ceiling
        page_to = min(cursor + page_size - 1, current_last)
        try:
            url = (f"/v3/accounts/{client.account_id}/transactions/idrange"
                   f"?from={cursor}&to={page_to}&type=ORDER_FILL")
            resp = client._request("GET", url)
            page_txns = resp.get("transactions", []) or []
            fill_txns.extend(page_txns)
        except Exception as e:
            logger.warning("oanda_trade_sync: txn page %d-%d failed: %s",
                           cursor, page_to, e)
            break
        cursor = page_to + 1
        pages += 1

    # 4. Index by what the transaction means for each trade:
    #    opens[tradeID] = the fill that opened it
    #    closes        = list of (tradeID, tradesClosed-entry, txn)
    opens: dict = {}
    closes: list = []
    for t in fill_txns:
        to = t.get("tradeOpened") or {}
        if to.get("tradeID"):
            opens[str(to["tradeID"])] = t
        for tc in (t.get("tradesClosed") or []):
            tid = str(tc.get("tradeID") or "")
            if tid:
                closes.append((tid, tc, t))

    if not closes:
        # Nothing closed in this batch. Advance the cursor so we don't
        # rescan the same range forever.
        if rdb is not None:
            try:
                rdb.set(cursor_key, current_last)
            except Exception:
                pass
        return 0

    # 5. Load signal_log for attribution. Resolve the Postgres user id
    # so we pick the correct per-user sidecar (bot_runner writes one
    # file per Postgres-users.id, not per Supabase UUID).
    pg_user_id = None
    try:
        import psycopg2
        with psycopg2.connect(os.environ.get(
            "DATABASE_URL",
            "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
        )) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM users WHERE bot_active=true "
                "AND oanda_api_key IS NOT NULL ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                pg_user_id = row[0]
    except Exception as e:
        logger.debug("oanda_trade_sync: pg user lookup failed: %s", e)
    signal_log = _load_signal_log(pg_user_id)

    # 6. Process each closure.
    written = 0
    for tid, close_info, close_txn in closes:
        open_txn = opens.get(tid)
        if open_txn is None:
            # Opening fill is outside the current window — fetch by ID.
            try:
                resp = client._request(
                    "GET", f"/v3/accounts/{client.account_id}/transactions/{tid}")
                cand = resp.get("transaction") or {}
                if ((cand.get("tradeOpened") or {}).get("tradeID")) == tid:
                    open_txn = cand
            except Exception as e:
                logger.debug("oanda_trade_sync: fetch open %s failed: %s", tid, e)
        if open_txn is None:
            continue

        try:
            entry_price = float(open_txn.get("price") or 0)
            exit_price = float(close_txn.get("price") or 0)
            units = int(float(open_txn.get("units") or 0))
            if units == 0:
                continue
            direction = "LONG" if units > 0 else "SHORT"
            instrument = (open_txn.get("instrument")
                          or close_txn.get("instrument") or "")
            realized_pl = float(close_info.get("realizedPL") or 0)

            pip = 0.01 if "JPY" in instrument else 0.0001
            pips = (exit_price - entry_price) / pip
            if direction == "SHORT":
                pips = -pips

            # Signal_log attribution. H1Zone records the signal_log
            # entry at LIMIT placement, keyed by the LimitOrder's
            # transaction ID — NOT the trade_id, which only exists
            # after the fill. So look up by:
            #   1. trade_id (covers MARKET fills where they match)
            #   2. open-fill transaction's id (the order_fill txn itself)
            #   3. orderID on the open fill (the LimitOrder txn that
            #      this fill filled — H1Zone's signal_log key)
            sig = (signal_log.get(tid)
                   or signal_log.get(str(open_txn.get("id") or ""))
                   or signal_log.get(str(open_txn.get("orderID") or ""))
                   or {})
            strat_raw = sig.get("strategy_id") or sig.get("strategy") or ""
            strat = strat_raw.lower() if strat_raw else "unknown"
            model = (sig.get("model") or "").lower()

            stop_loss = sig.get("stop") or sig.get("stop_price")
            take_profit = sig.get("target") or sig.get("target_price")

            t_open = _parse_time(open_txn.get("time"))
            t_close = _parse_time(close_txn.get("time"))
            duration_mins = (
                int((t_close - t_open).total_seconds() // 60)
                if t_open and t_close else None
            )

            # Planned RR & achieved RR — when both legs are known.
            planned_rr = achieved_rr = None
            if stop_loss and entry_price:
                risk = abs(entry_price - float(stop_loss))
                if risk > 0:
                    if take_profit:
                        planned_rr = round(abs(float(take_profit) - entry_price) / risk, 2)
                    achieved_rr = round((exit_price - entry_price) / risk
                                        * (1 if direction == "LONG" else -1), 2)

            record_closed_trade(user_id, {
                "id": tid,
                "broker": "oanda",
                "asset_type": "forex",
                "instrument": instrument,
                "direction": direction,
                "units": abs(units),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "realized_pl": round(realized_pl, 2),
                "pips": round(pips, 1),
                "planned_rr": planned_rr,
                "achieved_rr": achieved_rr,
                "strategy": strat,
                "model": model,
                "close_reason": _close_reason(close_txn.get("reason")),
                "won": realized_pl > 0,
                "time_opened": _to_iso(open_txn.get("time")),
                "time_closed": _to_iso(close_txn.get("time")),
                "duration_mins": duration_mins,
            })

            # Drop the corresponding open-positions row. Strategies that
            # exit via Oanda's native bracket (HTF Levels, H1 Zone Scalp,
            # FX 4H) don't observe the close themselves, so without this
            # the positions table accumulates ghosts.
            try:
                remove_position(user_id, "oanda", tid)
            except Exception as e:
                logger.debug("remove_position %s failed: %s", tid, e)

            written += 1
        except Exception as e:
            logger.debug("oanda_trade_sync: write failed for trade %s: %s", tid, e)

    # 7. Advance cursor regardless of success — we don't want to retry
    # the same range forever on bad data.
    if rdb is not None:
        try:
            rdb.set(cursor_key, current_last)
        except Exception:
            pass

    if written:
        logger.info("oanda_trade_sync: upserted %d closed trades (txns %d-%d, %d pages)",
                    written, last_seen + 1, current_last, pages)
    return written
