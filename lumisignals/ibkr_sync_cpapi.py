"""IB Client Portal API sync — polls positions and account data via REST.

Runs on the server alongside the CPAPI gateway (Docker).
No ib_insync or local IB Gateway needed.

    python3 -m lumisignals.ibkr_sync_cpapi

Pushes data every 10 seconds to the LumiSignals server API.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

from . import diary
from . import reconciler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ibkr_sync")

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
SYNC_KEY = os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")
CPAPI_URL = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SYNC_INTERVAL = 2  # was 10 — bookkeeping race window shrinks 5x.
                   # Brackets at IB handle risk regardless of poll interval,
                   # so we only need polling fast enough to keep the bot's
                   # view of fills/positions current.


# ─── Per-strategy futures position state ─────────────────────────────────
# Tracks each strategy's MES (or any futures) position independently in
# Redis so that, e.g., 2n20 and ORB can each hold their own long contract
# in the same instrument without one's signal getting blocked by the
# other's open position. IB aggregates positions at the account level
# (qty=2 long if both strategies are long 1); the bot dispatches its own
# close orders against its own strat_pos record so each strategy can
# exit cleanly.
#
# Key:  ibkr:strat_pos:{ticker}:{strategy}    TTL: 7 days
# Value: { ticker, strategy, direction, contracts, entry_price, perm_id, opened_at }

_redis_client = None


def _send_telegram_alert(title: str, body: str) -> bool:
    """Best-effort Telegram alert. Pulls TELEGRAM_BOT_TOKEN +
    TELEGRAM_CHAT_ID from env. Silent failure (returns False) — alerts
    should never break the caller. Rate-limit per category via Redis
    key telegram_alert:{slug}:lock with a 10-min TTL."""
    import os, hashlib
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    # Rate-limit by title (slugified): one alert per title per 10 min
    slug = hashlib.sha1(title.encode()).hexdigest()[:10]
    rdb = _rdb()
    if rdb is not None:
        try:
            if rdb.get(f"telegram_alert:{slug}:lock"):
                return False
            rdb.setex(f"telegram_alert:{slug}:lock", 600, "1")
        except Exception:
            pass
    text = f"*{title}*\n{body}"
    try:
        import urllib.request, urllib.parse, json
        data = urllib.parse.urlencode({
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        }).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        with urllib.request.urlopen(url, data=data, timeout=8) as r:
            return r.status == 200
    except Exception:
        return False


def _rdb():
    """Lazy Redis client. Returns None if unreachable (degrades gracefully
    by falling back to the old IB-level position guard)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis as _redis
        _redis_client = _redis.from_url(REDIS_URL)
        # Verify connectivity once
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.warning("Redis unavailable for strat_pos tracking: %s", e)
        _redis_client = None
        return None


def _strat_pos_key(ticker: str, strategy: str) -> str:
    return f"ibkr:strat_pos:{ticker}:{strategy}"


def get_strat_pos(ticker: str, strategy: str) -> dict:
    """Return per-strategy position state {} if none."""
    rdb = _rdb()
    if rdb is None:
        return {}
    try:
        raw = rdb.get(_strat_pos_key(ticker, strategy))
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def save_strat_pos(ticker: str, strategy: str, direction: str,
                    contracts: int, entry_price: float, perm_id: str,
                    stop_order_id: str = "", stop_price: float = 0,
                    target_order_id: str = "", target_price: float = 0,
                    multiplier: float = 1, metadata: dict = None,
                    caller: str = ""):
    """Persist per-strategy position state. stop_order_id lets the
    stop-fill watcher know which IB order belongs to this strategy's
    SL — when that order leaves IB's open-orders list, the strategy
    has been stopped out and we can clear the state and book the trade.
    target_order_id tracks the matching TP child so we can cancel it
    when SL fills (or vice versa). metadata holds Pine-supplied context
    (VIX, OR range, stop_reason, reversal) that we want on the trade row."""
    rdb = _rdb()
    if rdb is None:
        return
    from datetime import datetime as _dt, timezone as _tz
    try:
        rdb.setex(
            _strat_pos_key(ticker, strategy),
            86400 * 7,
            json.dumps({
                "ticker": ticker, "strategy": strategy,
                "direction": direction, "contracts": int(contracts),
                "entry_price": float(entry_price or 0),
                "perm_id": str(perm_id or ""),
                "stop_order_id": str(stop_order_id or ""),
                "stop_price": float(stop_price or 0),
                "target_order_id": str(target_order_id or ""),
                "target_price": float(target_price or 0),
                "multiplier": float(multiplier or 1),
                "metadata": metadata or {},
                "opened_at": _dt.now(_tz.utc).isoformat(),
            }),
        )
        logger.info(
            "STRAT_POS create %s/%s: dir=%s qty=%d entry=%s sl=%s tp=%s perm=%s caller=%s",
            ticker, strategy, direction, contracts, entry_price,
            stop_price or "-", target_price or "-", perm_id, caller or "?",
        )
    except Exception as e:
        logger.warning("strat_pos save failed for %s/%s: %s", ticker, strategy, e)


def check_stop_fills(client):
    """Detect stop-loss order fills and close the matching strat_pos.

    Each entry stores the IB order ID of its protective stop. We poll IB's
    open orders each cycle; if a tracked stop_order_id is no longer open,
    the stop has filled (or was cancelled). Filled stops mean the strategy
    is out — book the closed trade with reason "Stop Loss" and clear the
    strat_pos so the next entry signal can fire cleanly.

    Cancelled (but not filled) stops are rare (only via manual cancel in
    the IB UI). We treat them the same as filled for state purposes —
    strat_pos gets cleared. P&L attribution may be 0 in that case, which
    just means no closed-trade record gets posted."""
    rdb = _rdb()
    if rdb is None:
        return
    try:
        open_orders = client.get_open_orders() or []
    except Exception as e:
        logger.debug("check_stop_fills: get_open_orders failed: %s", e)
        return
    open_ids = set()
    for o in open_orders:
        oid = o.get("orderId") or o.get("order_id")
        if oid:
            open_ids.add(str(oid))

    try:
        keys = list(rdb.scan_iter("ibkr:strat_pos:*"))
    except Exception:
        return

    for key in keys:
        try:
            raw = rdb.get(key)
            if not raw:
                continue
            sp = json.loads(raw)
            stop_id = str(sp.get("stop_order_id") or "")
            target_id = str(sp.get("target_order_id") or "")
            stop_gone   = bool(stop_id   and stop_id   != "0" and stop_id   not in open_ids)
            target_gone = bool(target_id and target_id != "0" and target_id not in open_ids)
            if not stop_gone and not target_gone:
                continue  # both children still active (or neither tracked)

            # Decide which child fired — whichever is gone wins. If BOTH are
            # gone in the same poll, prefer the target (rare race; target
            # tends to be a LMT that fills cleanly).
            fired = "target" if target_gone else "stop"
            survivor_id = stop_id if fired == "target" else target_id

            ticker = sp.get("ticker", "")
            strategy = sp.get("strategy", "")
            direction = sp.get("direction", "")
            contracts = int(sp.get("contracts", 0))
            entry_price = float(sp.get("entry_price", 0))
            stop_price = float(sp.get("stop_price", 0))
            target_price = float(sp.get("target_price", 0))
            multiplier = float(sp.get("multiplier", 1))

            # Cancel the surviving sibling so we don't get filled twice
            if survivor_id and survivor_id != "0":
                try:
                    client.cancel_order(survivor_id)
                    logger.info("Cancelled survivor %s child %s after %s fill",
                                ticker, "TP" if fired == "stop" else "SL", survivor_id)
                except Exception as e:
                    logger.warning("Failed to cancel survivor %s: %s", survivor_id, e)

            close_reason = "Take Profit" if fired == "target" else "Stop Loss"
            exit_price = target_price if fired == "target" else stop_price
            logger.info("%s fill detected: %s [%s] — clearing strat_pos",
                        close_reason, ticker, strategy)

            pnl = 0
            if entry_price and exit_price:
                if direction == "BUY":
                    pnl = (exit_price - entry_price) * contracts * multiplier
                else:
                    pnl = (entry_price - exit_price) * contracts * multiplier

            try:
                from datetime import datetime as _dt, timezone as _tz
                requests.post(
                    f"{SERVER_URL}/api/ibkr/closed-trade",
                    json={
                        "symbol": ticker, "type": "futures",
                        "direction": "LONG" if direction == "BUY" else "SHORT",
                        "contracts": contracts,
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(exit_price, 2),
                        "realized_pnl": round(pnl, 2),
                        "stop_loss": round(stop_price, 2) if stop_price else None,
                        "take_profit": round(target_price, 2) if target_price else None,
                        "strategy": strategy,
                        "close_reason": close_reason,
                        "opened_at": sp.get("opened_at", ""),
                        "closed_at": _dt.now(_tz.utc).isoformat(),
                        "metadata": sp.get("metadata", {}),
                    },
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=10,
                )
            except Exception as e:
                logger.warning("Failed to record %s closed trade for %s/%s: %s",
                                close_reason, ticker, strategy, e)

            try:
                from .supabase_client import notify_trade_closed
                supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                if supabase_uid:
                    points = round(exit_price - entry_price, 2) if direction == "BUY" else round(entry_price - exit_price, 2)
                    notify_trade_closed(
                        user_id=supabase_uid,
                        instrument=ticker,
                        direction=direction,
                        pl=pnl,
                        pips=points,
                        reason=close_reason,
                    )
            except Exception as e:
                logger.debug("notify (child fill) failed: %s", e)

            # Diary: STOP_FIRED (or TP-hit — share the same close state so
            # the reconciler treats both as "closed by broker bracket").
            try:
                diary.record_event(
                    broker="ib",
                    broker_trade_id=str(sp.get("perm_id") or ""),
                    strategy_id=(diary.strategy_slug(strategy) or strategy),
                    ticker=ticker,
                    state=diary.State.STOP_FIRED if fired == "stop" else diary.State.CLOSED,
                    reason=close_reason,
                    expected_qty=0,
                    entry_price=entry_price or None,
                    exit_price=exit_price or None,
                    realized_pl=pnl,
                    meta={"fired": fired, "survivor_cancelled": survivor_id or None},
                )
            except Exception as _de:
                logger.warning("diary STOP_FIRED write failed: %s", _de)
            # Runaway guard: a bracket SL fire is a loss event by
            # definition for the stop path (the TP path produces a win).
            # Feed the streak counter from the actual realized P&L.
            try:
                from .runaway_guard import record_close
                record_close(float(pnl or 0))
            except Exception as _rg:
                logger.warning("runaway_guard record_close (STOP_FIRED) failed: %s", _rg)

            logger.info(
                "STRAT_POS clear  %s/%s: reason=child-fill(%s) survivor=%s",
                ticker, strategy, fired, survivor_id or "-",
            )
            rdb.delete(key)
        except Exception as e:
            logger.debug("check_stop_fills entry error: %s", e)


def clear_strat_pos(ticker: str, strategy: str, reason: str = ""):
    """Delete the strat_pos for (ticker, strategy). Reason is logged so we
    can later audit why a position state disappeared."""
    rdb = _rdb()
    if rdb is None:
        return
    try:
        # Read first so we can log what we're erasing
        raw = rdb.get(_strat_pos_key(ticker, strategy))
        prev = json.loads(raw) if raw else None
        rdb.delete(_strat_pos_key(ticker, strategy))
        if prev:
            logger.info(
                "STRAT_POS clear  %s/%s: reason=%s prev_dir=%s prev_qty=%d perm=%s",
                ticker, strategy, reason or "unspecified",
                prev.get("direction", "?"), int(prev.get("contracts", 0)),
                prev.get("perm_id", "-"),
            )
        else:
            logger.info("STRAT_POS clear  %s/%s: reason=%s (was already empty)",
                        ticker, strategy, reason or "unspecified")
    except Exception as e:
        logger.warning("clear_strat_pos failed for %s/%s: %s", ticker, strategy, e)


def reconcile_strat_pos(ticker: str, ib_qty: int, caller: str = ""):
    """DEPRECATED — no-op since 2026-05-22.

    This function used to CLEAR_ALL strat_pos for a ticker when IB's
    /portfolio/positions disagreed with our tracked net qty. The check was
    based on a snapshot endpoint with up to 4+ minutes of lag, leading to
    false positives that orphaned live positions (see 14:14 incident on
    2026-05-22). The trade diary + reconciler.py replace this — they key
    on broker_trade_id and order status, not aggregate position quantity.

    Kept as a no-op stub so any straggler call sites don't NameError.
    Remove entirely once no callers remain (search: reconcile_strat_pos).
    """
    logger.debug(
        "RECONCILE_NOOP %s ib_qty=%+d caller=%s — function deprecated",
        ticker, ib_qty, caller or "?",
    )
    return


def _lookup_signal_metadata(signal_log: dict, trade_id: str, instrument: str,
                             entry_price: float, stop_price: float) -> dict:
    """Return the signal_log entry for an Oanda trade. Mirrors trade_tracker:
    direct lookup by trade_id first, then fuzzy match by instrument + entry
    price (within 0.1%) + stop loss.

    Why: Oanda's API doesn't carry the bot's strategy/model tag. The bot
    writes those into a local signal log (the "metadata sidecar" Sonia
    described, ported from the old Airtable trade-journal pattern) keyed
    by Oanda trade_id and order_id. We join on read.
    """
    if not signal_log:
        return {}
    direct = signal_log.get(str(trade_id))
    if isinstance(direct, dict):
        return direct
    # Fallback: fuzzy match
    symbol_clean = instrument.replace("_", "").upper()
    best, best_score = None, float("inf")
    for sig in signal_log.values():
        if not isinstance(sig, dict):
            continue
        sig_symbol = (sig.get("symbol") or sig.get("instrument") or "").replace("_", "").upper()
        if sig_symbol != symbol_clean:
            continue
        sig_entry = sig.get("entry") or sig.get("entry_price") or 0
        if not (sig_entry and entry_price):
            continue
        entry_dist = abs(sig_entry - entry_price)
        if entry_dist >= entry_price * 0.001:
            continue
        score = entry_dist
        sig_stop = sig.get("stop") or sig.get("stop_price") or 0
        if stop_price and sig_stop:
            score += abs(sig_stop - stop_price)
        if score < best_score:
            best_score = score
            best = sig
    return best or {}


_last_mes_bars_push = 0
MES_BARS_PUSH_INTERVAL = 60  # seconds
_last_missed_signal_check = 0
MISSED_SIGNAL_CHECK_INTERVAL = 300  # 5 minutes


def _validate_place_order_result(result):
    """Inspect the CPAPI place_order response to detect failure.

    On a successful bracket POST, CPAPI returns a list of 2-3 dicts (entry
    + sl + optional tp), each carrying an order_id. On failure it can
    return:
      - {"error": "..."} (no account_id, request error, auth failure)
      - {"error_message": "..."} or similar on rejection
      - A list whose first element has an error key, or no order_id
      - An empty list / None

    Returns (is_failure, reason_string). When True, the caller should
    mark the diary intent as CANCELLED, alert, and skip the rest of the
    entry flow rather than building a phantom strat_pos.
    """
    if not result:
        return True, "empty response"
    if isinstance(result, dict):
        err = result.get("error") or result.get("error_message")
        if err:
            return True, str(err)[:200]
        if not result.get("order_id"):
            return True, "no order_id in dict response"
        return False, ""
    if isinstance(result, list):
        if not result:
            return True, "empty result list"
        first = result[0] if isinstance(result[0], dict) else None
        if first is None:
            return True, f"non-dict first element: {type(result[0]).__name__}"
        err = (first.get("error") or first.get("error_message")
               or first.get("text") or "")
        # CPAPI sometimes echoes confirmation prompts via "id" without a
        # real order_id; rule that out.
        if err:
            err_lower = str(err).lower()
            if any(tok in err_lower for tok in ("reject", "error", "insufficient",
                                                 "invalid", "denied", "not allowed",
                                                 "halted", "closed")):
                return True, str(err)[:200]
        if not first.get("order_id"):
            return True, f"no order_id in first element (got keys {list(first.keys())})"
        return False, ""
    return True, f"unexpected response type: {type(result).__name__}"


def push_mes_bars_to_server(client):
    """Pull 2-min MES bars from IB via CPAPI and POST them to the server's
    Redis cache. The /api/candles/MES endpoint (used by mobile_chart.html)
    reads from this cache; without the push, the mobile chart shows
    "No candle data". Throttled to one push per minute since the bars
    themselves close every 2 min and a 60s lag is fine."""
    global _last_mes_bars_push
    now = time.time()
    if now - _last_mes_bars_push < MES_BARS_PUSH_INTERVAL:
        return
    _last_mes_bars_push = now

    try:
        fut = client.search_futures("MES")
        if not fut or not fut.get("conid"):
            return
        bars = client.get_historical_bars(
            fut["conid"], period="1d", bar="2min", outside_rth=True,
        )
        if not bars:
            return
        front_month = fut.get("localSymbol") or "MES"
        try:
            requests.post(
                f"{SERVER_URL}/api/ibkr/futures-bars/MES",
                json={"bars": bars, "front_month": front_month},
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=10,
            )
            logger.debug("Pushed %d MES bars to server (%s)", len(bars), front_month)
        except Exception as e:
            logger.warning("MES bar push failed: %s", e)
    except Exception as e:
        logger.debug("MES bar fetch failed: %s", e)


def sync_oanda_positions_to_supabase():
    """Refresh unrealized_pl on Oanda position rows in Supabase, full sync
    of currently-open Oanda trades, with strategy/model joined from the
    local signal log (Oanda's API doesn't carry that metadata).
    """
    try:
        from .supabase_client import get_client
        from .oanda_client import OandaClient
        import psycopg2
    except Exception as e:
        logger.debug("oanda sync deps unavailable: %s", e)
        return
    sb = get_client()
    if not sb:
        return
    user_id = os.environ.get("SUPABASE_USER_ID", "")
    if not user_id:
        return

    # Pull Oanda creds from Postgres for the active bot user (single-user setup).
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db",
    )
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, oanda_api_key, oanda_account_id, oanda_environment "
            "FROM users WHERE bot_active = true AND oanda_api_key IS NOT NULL "
            "ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
    except Exception as e:
        logger.debug("oanda creds lookup failed: %s", e)
        return
    if not row:
        return
    pg_user_id, api_key, acct_id, env = row

    # Load that user's signal log (per-user file, written at fill time by
    # fx_scalp_2n20.SignalLog.record).
    signal_log = {}
    sig_path = f"/opt/lumisignals/signal_log_user_{pg_user_id}.json"
    try:
        import json as _json
        with open(sig_path) as f:
            signal_log = _json.load(f)
    except Exception as e:
        logger.debug("signal log load failed (%s): %s", sig_path, e)

    try:
        oc = OandaClient(account_id=acct_id, api_key=api_key, environment=env or "practice")
        resp = oc.get_trades(state="OPEN") or {}
        trades = resp.get("trades", [])
    except Exception as e:
        logger.debug("oanda fetch failed: %s", e)
        return

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    open_ids = {str(t.get("id") or "") for t in trades if t.get("id")}

    # Pull the existing oanda rows so we know which to UPDATE vs INSERT, and
    # which to DELETE because the trade closed on Oanda's side.
    try:
        existing = sb.table("positions").select("id, broker_trade_id") \
            .eq("user_id", user_id).eq("broker", "oanda").execute().data or []
    except Exception as e:
        logger.debug("oanda existing fetch failed: %s", e)
        existing = []
    existing_by_tid = {str(r.get("broker_trade_id") or ""): r["id"] for r in existing}

    # Insert / update each currently-open trade.
    for t in trades:
        tid = str(t.get("id") or "")
        if not tid:
            continue
        try:
            unreal = float(t.get("unrealizedPL") or 0)
            entry = float(t.get("price") or 0)
            units = int(float(t.get("currentUnits") or 0))
        except (TypeError, ValueError):
            continue
        sl = (t.get("stopLossOrder") or {}).get("price")
        tp = (t.get("takeProfitOrder") or {}).get("price")
        live_fields = {
            "unrealized_pl": round(unreal, 2),
            "entry_price": entry,
            "units": abs(units),
            "stop_loss": float(sl) if sl else None,
            "take_profit": float(tp) if tp else None,
            "updated_at": now_iso,
        }
        try:
            if tid in existing_by_tid:
                # Existing row — refresh live fields, preserve strategy/model.
                sb.table("positions").update(live_fields) \
                    .eq("user_id", user_id) \
                    .eq("broker", "oanda") \
                    .eq("broker_trade_id", tid).execute()
            else:
                # New row — insert minimal record. strategy/model stay empty
                # for trades the bot didn't originate; mobile shows them anyway
                # so the view matches the website (which lists all open trades).
                # Oanda returns openTime as a Unix epoch string ("1778268763.531408926"),
                # not an ISO timestamp. Convert before inserting.
                opened_at = now_iso
                ot = t.get("openTime")
                if ot:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        opened_at = _dt.fromtimestamp(float(ot), tz=_tz.utc).isoformat()
                    except (TypeError, ValueError):
                        pass
                # Join strategy/model from the signal log sidecar — accurate
                # attribution per trade (manual trades stay tagless).
                sig = _lookup_signal_metadata(
                    signal_log, tid,
                    t.get("instrument", ""),
                    entry,
                    float(sl) if sl else 0,
                )
                strategy = sig.get("strategy_id") or sig.get("strategy") or ""
                model = sig.get("model") or ""
                row = {
                    "user_id": user_id,
                    "broker": "oanda",
                    "broker_trade_id": tid,
                    "instrument": t.get("instrument", ""),
                    "asset_type": "forex",
                    "direction": "BUY" if units > 0 else "SELL",
                    "contracts": 1,
                    "strategy": strategy,
                    "model": model,
                    "opened_at": opened_at,
                    **live_fields,
                }
                sb.table("positions").insert(row).execute()
        except Exception as e:
            logger.debug("oanda position write failed for trade %s: %s", tid, e)

    # Delete any oanda rows whose trade is no longer open (closed by SL/TP/manual).
    for tid, rid in existing_by_tid.items():
        if tid and tid in open_ids:
            continue
        try:
            sb.table("positions").delete().eq("id", rid).execute()
        except Exception as e:
            logger.debug("oanda position delete failed for id %s: %s", rid, e)


def sync_positions_to_supabase(positions: list):
    """Refresh entry_price + unrealized_pl on existing Supabase position rows
    for each open IB position. Matches by (user_id, broker='ib', instrument).
    Also DELETES Supabase rows for IB futures/stock instruments that are no
    longer in the open position list — otherwise a fully-closed position
    leaves a stale "ghost" row in the mobile app.

    Options (OPT) are managed by the spread close path and not touched here.
    """
    try:
        from .supabase_client import get_client
    except Exception as e:
        logger.debug("supabase_client unavailable: %s", e)
        return
    sb = get_client()
    if not sb:
        return
    user_id = os.environ.get("SUPABASE_USER_ID", "")
    if not user_id:
        return

    seen_symbols = set()
    seen_perm_ids = set()  # broker_trade_ids we touched this cycle
    symbols_with_strat = set()  # symbols that have per-strat rows now (drop their aggregates)

    # Log every IB position-quantity change so we can correlate strat_pos
    # disappearances with the exact moment IB's qty moved.
    global _last_ib_qty
    try:
        _last_ib_qty
    except NameError:
        _last_ib_qty = {}
    for pos in positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue
        sec_type = pos.get("sec_type", "")
        # Only refresh STK / FUT here; OPT positions are part of spreads,
        # which have their own sync path.
        if sec_type not in ("STK", "FUT"):
            continue
        seen_symbols.add(symbol)
        multiplier = pos.get("multiplier") or 1
        market_price = float(pos.get("market_price") or 0)
        qty = int(pos.get("quantity") or 0)
        asset_type = "futures" if sec_type == "FUT" else "stock"

        # Push the latest market price to the shared live_prices table
        # so the mobile UI can recompute P&L locally (sub-cycle freshness)
        # instead of waiting for the per-position row to be PATCHed.
        # Best-effort: failures log but never break the sync loop.
        if market_price > 0:
            try:
                diary.upsert_live_price(symbol, market_price)
            except Exception as _lpe:
                logger.debug("live_price push failed for %s: %s", symbol, _lpe)

        # Log IB qty changes for forensics
        prev_qty = _last_ib_qty.get(symbol)
        if prev_qty is None:
            logger.info("IB_QTY %s: first-seen qty=%+d", symbol, qty)
        elif prev_qty != qty:
            logger.info("IB_QTY %s: change %+d -> %+d (delta %+d)",
                        symbol, prev_qty, qty, qty - prev_qty)
        _last_ib_qty[symbol] = qty

        # Gather all per-strategy positions for this symbol so each strategy
        # gets its own mobile card (entry, SL, TP, P&L). Without this,
        # multi-strategy positions on the same instrument (e.g. 2n20 + ORB
        # both short MES) collapse into a single aggregated row.
        strat_positions = []
        try:
            rdb = _rdb()
            if rdb:
                for k in rdb.scan_iter(f"ibkr:strat_pos:{symbol}:*"):
                    sp_raw = rdb.get(k)
                    if sp_raw:
                        try:
                            strat_positions.append(json.loads(sp_raw))
                        except Exception:
                            continue
        except Exception:
            pass

        # No strat_pos tracking for this symbol — fall back to a single
        # aggregate row (legacy behavior for manually opened positions).
        if not strat_positions:
            avg_cost = pos.get("avg_cost") or 0
            entry_price = (avg_cost / multiplier) if multiplier else avg_cost
            live_fields = {
                "entry_price": round(float(entry_price), 4),
                "unrealized_pl": round(float(pos.get("unrealized_pnl") or 0), 2),
                "contracts": int(abs(qty)),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            }
            try:
                existing = sb.table("positions").select("id") \
                    .eq("user_id", user_id).eq("broker", "ib") \
                    .eq("instrument", symbol).is_("broker_trade_id", "null") \
                    .execute().data or []
                if existing:
                    sb.table("positions").update(live_fields) \
                        .eq("user_id", user_id).eq("broker", "ib") \
                        .eq("instrument", symbol).is_("broker_trade_id", "null") \
                        .execute()
                else:
                    from datetime import datetime as _dt, timezone as _tz
                    sb.table("positions").insert({
                        "user_id": user_id, "broker": "ib",
                        "instrument": symbol, "asset_type": asset_type,
                        "direction": "BUY" if qty > 0 else "SELL",
                        "opened_at": _dt.now(_tz.utc).isoformat(),
                        **live_fields,
                    }).execute()
            except Exception as e:
                logger.debug("aggregate position refresh failed for %s: %s", symbol, e)
            continue

        # Per-strategy rows — one Supabase position per strat_pos entry
        symbols_with_strat.add(symbol)
        # If strat_pos coverage doesn't equal the IB quantity (because some
        # contracts were opened before strat tracking, or a strat_pos got
        # cleared by reconcile while the IB position stayed open), surface
        # the untracked remainder as an "orphan" row so the mobile total
        # matches IB. Otherwise the user would see fewer contracts than IB.
        tracked_qty = sum(int(sp.get("contracts") or 0) for sp in strat_positions)
        orphan_qty = abs(qty) - tracked_qty
        if orphan_qty > 0:
            avg_cost = pos.get("avg_cost") or 0
            orphan_entry = (avg_cost / multiplier) if multiplier else avg_cost
            orphan_unreal = 0.0
            orphan_dir = "BUY" if qty > 0 else "SELL"
            if market_price and orphan_entry:
                if orphan_dir == "BUY":
                    orphan_unreal = (market_price - orphan_entry) * orphan_qty * multiplier
                else:
                    orphan_unreal = (orphan_entry - market_price) * orphan_qty * multiplier
            orphan_tid = f"orphan:{symbol}"
            seen_perm_ids.add(orphan_tid)
            try:
                sb.table("positions").upsert({
                    "user_id": user_id,
                    "broker": "ib",
                    "broker_trade_id": orphan_tid,
                    "instrument": symbol,
                    "asset_type": asset_type,
                    "direction": orphan_dir,
                    "contracts": orphan_qty,
                    "entry_price": round(orphan_entry, 4),
                    "unrealized_pl": round(orphan_unreal, 2),
                    "strategy": "untracked",
                    "model": "untracked",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                }, on_conflict="user_id,broker,broker_trade_id").execute()
            except Exception as e:
                logger.debug("orphan upsert failed for %s: %s", symbol, e)

        for sp in strat_positions:
            perm_id = str(sp.get("perm_id") or "")
            if not perm_id:
                continue
            seen_perm_ids.add(perm_id)
            strat_dir = sp.get("direction", "BUY" if qty > 0 else "SELL")
            strat_qty = int(sp.get("contracts") or 0) or 1
            strat_entry = float(sp.get("entry_price") or 0)
            # Per-strategy unrealized P&L from live mark vs. each strat's entry.
            unreal = 0.0
            if market_price and strat_entry:
                if strat_dir == "BUY":
                    unreal = (market_price - strat_entry) * strat_qty * multiplier
                else:
                    unreal = (strat_entry - market_price) * strat_qty * multiplier
            row_fields = {
                "user_id": user_id,
                "broker": "ib",
                "broker_trade_id": perm_id,
                "instrument": symbol,
                "asset_type": asset_type,
                "direction": strat_dir,
                "contracts": strat_qty,
                "entry_price": round(strat_entry, 4),
                "stop_loss": float(sp.get("stop_price") or 0) or None,
                "take_profit": float(sp.get("target_price") or 0) or None,
                "unrealized_pl": round(unreal, 2),
                "strategy": sp.get("strategy", ""),
                "model": sp.get("strategy", ""),
                "opened_at": sp.get("opened_at", ""),
                "metadata": sp.get("metadata") or None,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
            }
            # Drop None values so the JSONB stays clean
            row_fields = {k: v for k, v in row_fields.items() if v is not None}
            try:
                sb.table("positions").upsert(
                    row_fields, on_conflict="user_id,broker,broker_trade_id"
                ).execute()
            except Exception as e:
                logger.debug("per-strat upsert failed for %s/%s: %s",
                              symbol, sp.get("strategy", ""), e)

    # Log symbols that DISAPPEARED from IB this cycle (position fully closed
    # by stop fill, manual close, etc.) so the audit trail captures it.
    for sym in list(_last_ib_qty.keys()):
        if sym not in seen_symbols and _last_ib_qty.get(sym):
            logger.info("IB_QTY %s: disappeared (was %+d, now 0/missing)",
                        sym, _last_ib_qty[sym])
            _last_ib_qty[sym] = 0

    # Sweep stale rows:
    # 1) Symbol no longer in IB's position list at all → drop every row
    # 2) Per-strategy row whose strat_pos has been cleared (TP/SL hit,
    #    strategy closed via webhook) but the broker_trade_id wasn't
    #    refreshed this cycle → drop just that row, the other strategies
    #    on the same symbol keep their cards
    try:
        existing = sb.table("positions").select("id, instrument, broker_trade_id") \
            .eq("user_id", user_id).eq("broker", "ib") \
            .in_("asset_type", ["futures", "stock"]) \
            .execute().data or []
        for row in existing:
            inst = row.get("instrument") or ""
            tid = str(row.get("broker_trade_id") or "")
            drop = False
            reason = ""
            if inst and inst not in seen_symbols:
                drop, reason = True, "no longer in IB"
            elif tid and tid not in seen_perm_ids:
                drop, reason = True, "strat_pos cleared"
            elif not tid and inst in symbols_with_strat:
                # Legacy aggregate row that's now replaced by per-strat rows
                drop, reason = True, "superseded by per-strategy rows"
            if drop:
                try:
                    sb.table("positions").delete().eq("id", row["id"]).execute()
                    logger.info("Cleared stale IB position row: %s (id=%s, tid=%s) — %s",
                                inst, row["id"], tid or "-", reason)
                except Exception as e:
                    logger.debug("stale row delete failed (id=%s): %s", row.get("id"), e)
    except Exception as e:
        logger.debug("stale-row sweep failed: %s", e)


def collect_ib_data(client) -> dict:
    """Collect all relevant data from IB via Client Portal API."""

    # Account summary
    account = client.get_account_summary()

    # Positions with market values and P&L (CPAPI returns same shape)
    positions = client.get_positions()

    # Group option positions into spreads
    spreads = _detect_spreads(positions)

    # Enrich spreads with signal metadata from stored order details
    # Build a map from recent trades/fills
    perm_id_map = {}
    for fill in client.get_trades():
        perm_id = fill.get("order_ref", fill.get("execution_id", ""))
        if perm_id:
            perm_id_map[perm_id] = {
                "symbol": fill.get("symbol", ""),
                "perm_id": perm_id,
            }

    for spread in spreads:
        try:
            # Search by ticker + strikes
            resp = requests.get(
                f"{SERVER_URL}/api/ibkr/order/search",
                params={
                    "ticker": spread["symbol"],
                    "sell_strike": spread.get("short_strike", 0),
                    "buy_strike": spread.get("long_strike", 0),
                },
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=5,
            )
            if resp.status_code == 200:
                details = resp.json()
                if details.get("model") or details.get("perm_id"):
                    spread["perm_id"] = details.get("perm_id", "")
                    spread["order_id"] = details.get("order_id", "")
                    spread["model"] = details.get("model", "")
                    spread["strategy"] = details.get("strategy", "")
                    spread["trigger_pattern"] = details.get("trigger_pattern", "")
                    spread["bias_score"] = details.get("bias_score", 0)
                    spread["zone_type"] = details.get("zone_type", "")
                    spread["zone_timeframe"] = details.get("zone_timeframe", "")
                    spread["verdict"] = details.get("verdict", "")
                    spread["opened_at"] = details.get("queued_at", "")
                    # Override max_profit/risk with planned values from order
                    planned_profit = details.get("max_profit", 0)
                    planned_risk = details.get("max_risk", 0)
                    if planned_profit:
                        spread["max_profit"] = planned_profit
                    if planned_risk:
                        spread["max_risk"] = planned_risk
                    spread["risk_reward"] = details.get("risk_reward", 0)
        except Exception:
            pass
        # Signal log fallback if model still missing
        if not spread.get("model") and spread.get("symbol"):
            try:
                resp = requests.get(
                    f"{SERVER_URL}/api/ibkr/signal-lookup/{spread['symbol']}",
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=5,
                )
                if resp.status_code == 200:
                    sig = resp.json()
                    if sig.get("model"):
                        spread["model"] = sig["model"]
                        spread["trigger_pattern"] = sig.get("trigger_pattern", "")
                        spread["bias_score"] = sig.get("bias_score", 0)
                        spread["zone_type"] = sig.get("zone_type", "")
                        spread["zone_timeframe"] = sig.get("zone_timeframe", "")
                        spread["risk_reward"] = sig.get("risk_reward", 0)
            except Exception:
                pass

    # Open orders from CPAPI
    open_orders = []
    for order in client.get_open_orders():
        order_entry = {
            "order_id": order.get("orderId", 0),
            "symbol": order.get("ticker", ""),
            "sec_type": order.get("secType", "STK"),
            "action": order.get("side", ""),
            "quantity": float(order.get("totalSize", order.get("remainingQuantity", 0))),
            "order_type": order.get("orderType", ""),
            # CPAPI returns "" (empty string) for the price of a market order, so
            # the default kwarg doesn't help — `or 0` covers both None and "".
            "limit_price": float(order.get("price") or 0),
            "status": order.get("status", ""),
            "time": order.get("lastExecutionTime_r", ""),
        }
        if order.get("isCombo") or order.get("conidex", "").count(";;;") > 0:
            # Combo order (spread) — resolve leg details from conIds
            legs = []
            sell_strike = 0
            buy_strike = 0
            expiration = ""
            right = ""
            for leg in order.get("legs", []):
                leg_conid = leg.get("conid", 0)
                leg_info = {"con_id": leg_conid, "action": leg.get("side", ""), "ratio": leg.get("ratio", 1)}
                try:
                    info = client.get_contract_info(leg_conid)
                    if info and not info.get("error"):
                        leg_info["strike"] = float(info.get("strike", 0))
                        leg_info["expiration"] = str(info.get("maturityDate", "")).replace("-", "")
                        leg_info["right"] = info.get("right", "")
                        if leg.get("side") == "SELL":
                            sell_strike = leg_info["strike"]
                        else:
                            buy_strike = leg_info["strike"]
                        if not expiration:
                            expiration = leg_info["expiration"]
                        if not right:
                            right = leg_info["right"]
                except Exception:
                    pass
                legs.append(leg_info)
            # If leg resolution failed, look up stored order details from server
            if not right:
                for lookup_id in [order.get("orderId"), order.get("permId")]:
                    if not lookup_id:
                        continue
                    try:
                        resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/order/details/{lookup_id}",
                            headers={"X-Sync-Key": SYNC_KEY},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            details = resp.json()
                            if details.get("right"):
                                right = details["right"]
                                sell_strike = float(details.get("sell_strike", sell_strike))
                                buy_strike = float(details.get("buy_strike", buy_strike))
                                expiration = details.get("expiration", expiration)
                                order_entry["spread_type"] = details.get("spread_type", "")
                                order_entry["is_credit"] = details.get("is_credit", False)
                                order_entry["model"] = details.get("model", "")
                                order_entry["trigger_pattern"] = details.get("trigger_pattern", "")
                                order_entry["bias_score"] = details.get("bias_score", 0)
                                order_entry["zone_type"] = details.get("zone_type", "")
                                order_entry["zone_timeframe"] = details.get("zone_timeframe", "")
                                order_entry["verdict"] = details.get("verdict", "")
                                order_entry["limit_price"] = float(details.get("limit_price", 0))
                                order_entry["max_profit"] = float(details.get("max_profit", 0))
                                order_entry["max_risk"] = float(details.get("max_risk", 0))
                                order_entry["risk_reward"] = float(details.get("risk_reward", 0))
                                order_entry["signal_action"] = details.get("signal_action", "")
                                order_entry["queued_at"] = details.get("queued_at", "")
                                break
                    except Exception:
                        pass
                # Try searching by symbol + strikes
                if not order_entry.get("model") and order.get("ticker"):
                    try:
                        resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/order/search",
                            params={"ticker": order.get("ticker"), "sell_strike": sell_strike or 0, "buy_strike": buy_strike or 0},
                            headers={"X-Sync-Key": SYNC_KEY},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            details = resp.json()
                            if details.get("model"):
                                order_entry.update({
                                    "model": details.get("model", ""),
                                    "trigger_pattern": details.get("trigger_pattern", ""),
                                    "bias_score": details.get("bias_score", 0),
                                    "zone_type": details.get("zone_type", ""),
                                    "zone_timeframe": details.get("zone_timeframe", ""),
                                    "is_credit": details.get("is_credit", False),
                                    "limit_price": float(details.get("limit_price", 0)),
                                    "max_profit": float(details.get("max_profit", 0)),
                                    "max_risk": float(details.get("max_risk", 0)),
                                    "risk_reward": float(details.get("risk_reward", 0)),
                                    "signal_action": details.get("signal_action", ""),
                                    "queued_at": details.get("queued_at", ""),
                                    "right": details.get("right", ""),
                                    "sell_strike": float(details.get("sell_strike", 0)),
                                    "buy_strike": float(details.get("buy_strike", 0)),
                                    "expiration": details.get("expiration", ""),
                                    "spread_type": details.get("spread_type", ""),
                                })
                                right = details.get("right", "")
                                sell_strike = float(details.get("sell_strike", 0))
                                buy_strike = float(details.get("buy_strike", 0))
                                expiration = details.get("expiration", "")
                    except Exception:
                        pass
            order_entry["legs"] = legs
            # Try to enrich with stored order data by searching ticker + strikes
            if order.get("ticker") and sell_strike and buy_strike:
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/order/search",
                        params={"ticker": order.get("ticker"), "sell_strike": sell_strike, "buy_strike": buy_strike},
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        details = resp.json()
                        if details.get("limit_price"):
                            if not order_entry.get("limit_price") or order_entry["limit_price"] == 0:
                                order_entry["limit_price"] = float(details["limit_price"])
                                order_entry["net_premium"] = float(details["limit_price"])
                            if not order_entry.get("max_profit"):
                                order_entry["max_profit"] = float(details.get("max_profit", 0))
                            if not order_entry.get("max_risk") or order_entry["max_risk"] == 100:
                                order_entry["max_risk"] = float(details.get("max_risk", 0))
                            if not order_entry.get("risk_reward"):
                                order_entry["risk_reward"] = float(details.get("risk_reward", 0))
                            if not order_entry.get("is_credit") and details.get("is_credit") is not None:
                                order_entry["is_credit"] = details["is_credit"]
                            if not order_entry.get("model"):
                                order_entry["model"] = details.get("model", "")
                                order_entry["trigger_pattern"] = details.get("trigger_pattern", "")
                                order_entry["bias_score"] = details.get("bias_score", 0)
                                order_entry["zone_type"] = details.get("zone_type", "")
                                order_entry["zone_timeframe"] = details.get("zone_timeframe", "")
                                order_entry["signal_action"] = details.get("signal_action", "")
                                order_entry["queued_at"] = details.get("queued_at", "")
                except Exception:
                    pass
            # Fallback to signal log if model still missing
            if not order_entry.get("model") and order.get("ticker"):
                try:
                    resp = requests.get(
                        f"{SERVER_URL}/api/ibkr/signal-lookup/{order.get("ticker")}",
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        sig = resp.json()
                        if sig.get("model"):
                            order_entry["model"] = sig["model"]
                            order_entry["trigger_pattern"] = sig.get("trigger_pattern", "")
                            order_entry["bias_score"] = sig.get("bias_score", 0)
                            order_entry["zone_type"] = sig.get("zone_type", "")
                            order_entry["zone_timeframe"] = sig.get("zone_timeframe", "")
                            order_entry["signal_action"] = sig.get("signal_action", "")
                            order_entry["risk_reward"] = sig.get("risk_reward", 0)
                except Exception:
                    pass
            order_entry["sec_type"] = "SPREAD"
            order_entry["sell_strike"] = sell_strike
            order_entry["buy_strike"] = buy_strike
            order_entry["expiration"] = expiration
            order_entry["right"] = right
            # Determine spread type from leg structure
            # Credit spread: sell the more expensive (closer to money) option
            # For calls: sell lower strike = bear call credit
            # For puts: sell higher strike = bull put credit
            width = abs(sell_strike - buy_strike) if sell_strike and buy_strike else 0
            premium = abs(order_entry.get("limit_price") or 0)
            if right == "C":
                if sell_strike < buy_strike:
                    order_entry["spread_type"] = "Bear Call Credit"
                    order_entry["direction"] = "SELL"
                else:
                    order_entry["spread_type"] = "Bull Call Debit"
                    order_entry["direction"] = "BUY"
            elif right == "P":
                if sell_strike > buy_strike:
                    order_entry["spread_type"] = "Bull Put Credit"
                    order_entry["direction"] = "BUY"
                else:
                    order_entry["spread_type"] = "Bear Put Debit"
                    order_entry["direction"] = "SELL"
            else:
                order_entry["spread_type"] = "Spread"
                order_entry["direction"] = ""
            is_credit = "Credit" in order_entry["spread_type"]
            order_entry["width"] = width
            order_entry["net_premium"] = premium
            order_entry["is_credit"] = is_credit
            if is_credit:
                order_entry["max_profit"] = round(premium * 100, 2)
                order_entry["max_risk"] = round((width - premium) * 100, 2) if width else 0
            else:
                order_entry["max_risk"] = round(premium * 100, 2)
                order_entry["max_profit"] = round((width - premium) * 100, 2) if width else 0
            order_entry["risk_reward"] = round(order_entry["max_profit"] / order_entry["max_risk"], 2) if order_entry["max_risk"] > 0 else 0
        elif order.get("secType") == "OPT":
            # Single-leg option order — strike/right/expiration would need a
            # /iserver/contract/{conid}/info call. Skip enrichment for now;
            # the combo branch above handles the multi-leg spreads we care about.
            pass
        open_orders.append(order_entry)

    # Completed (filled) orders — recent trades from CPAPI.
    # IB occasionally returns price (and size) as a string with a currency
    # suffix like "2425.00 USD"; raw float() blows up on that. _num strips
    # any non-numeric trailing tokens before parsing.
    def _num(v, default=0.0):
        try:
            if v is None:
                return default
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            # Take the leading numeric token (handles "2425.00 USD",
            # "1,234.56", "+1.5", etc.)
            cleaned = []
            for ch in s.replace(",", ""):
                if ch.isdigit() or ch in ".-+":
                    cleaned.append(ch)
                else:
                    if cleaned:
                        break
            return float("".join(cleaned)) if cleaned else default
        except Exception:
            return default

    filled_orders = []
    for fill in client.get_trades():
        entry = {
            "order_id": fill.get("order_ref", fill.get("execution_id", 0)),
            "symbol": fill.get("symbol", fill.get("ticker", "")),
            "sec_type": fill.get("sec_type", fill.get("secType", "STK")),
            "action": fill.get("side", ""),
            "quantity": _num(fill.get("size", fill.get("shares", 0))),
            "price": _num(fill.get("price", 0)),
            "time": fill.get("trade_time_r", fill.get("trade_time", "")),
        }
        filled_orders.append(entry)

    return {
        "account": account,
        "positions": positions,
        "spreads": spreads,
        "open_orders": open_orders,
        "filled_orders": filled_orders,
    }


def _detect_spreads(positions: list) -> list:
    """Group option positions into vertical spreads.

    Handles multiple spreads on the same symbol by pairing each short leg
    with the nearest long leg at a different strike, matching quantities.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for pos in positions:
        if pos["sec_type"] == "OPT":
            key = (pos["symbol"], pos["expiration"], pos["right"])
            groups[key].append(pos)

    spreads = []
    for (symbol, expiration, right), legs in groups.items():
        # Separate into long and short legs
        longs = [l for l in legs if l["quantity"] > 0]
        shorts = [l for l in legs if l["quantity"] < 0]

        # Sort by strike
        longs.sort(key=lambda x: x["strike"])
        shorts.sort(key=lambda x: x["strike"])

        # Pair each short leg with the nearest long leg
        used_longs = set()
        for short_leg in shorts:
            # Find closest long leg by strike that hasn't been fully used
            best_long = None
            best_dist = float("inf")
            for i, long_leg in enumerate(longs):
                if i in used_longs:
                    continue
                dist = abs(long_leg["strike"] - short_leg["strike"])
                if dist > 0 and dist < best_dist:
                    best_long = long_leg
                    best_long_idx = i
                    best_dist = dist

            if best_long:
                used_longs.add(best_long_idx)
                # Determine quantity (use the smaller of the two)
                qty = min(abs(short_leg["quantity"]), abs(best_long["quantity"]))
                width = abs(best_long["strike"] - short_leg["strike"])

                # Determine spread type
                if right == "P":
                    if short_leg["strike"] > best_long["strike"]:
                        spread_type = "Put Credit Spread"
                    else:
                        spread_type = "Put Debit Spread"
                else:
                    if short_leg["strike"] < best_long["strike"]:
                        spread_type = "Call Credit Spread"
                    else:
                        spread_type = "Call Debit Spread"

                net_cost = (best_long["avg_cost"] - short_leg["avg_cost"]) * qty / qty if qty else 0

                # P&L
                long_pnl = (best_long.get("unrealized_pnl", 0) or 0)
                short_pnl = (short_leg.get("unrealized_pnl", 0) or 0)
                # Scale P&L if quantities don't match exactly
                if abs(best_long["quantity"]) != qty:
                    long_pnl = long_pnl * qty / abs(best_long["quantity"])
                if abs(short_leg["quantity"]) != qty:
                    short_pnl = short_pnl * qty / abs(short_leg["quantity"])
                spread_pnl = round(long_pnl + short_pnl, 2)

                long_mkt = (best_long.get("market_value", 0) or 0)
                short_mkt = (short_leg.get("market_value", 0) or 0)
                if abs(best_long["quantity"]) != qty:
                    long_mkt = long_mkt * qty / abs(best_long["quantity"])
                if abs(short_leg["quantity"]) != qty:
                    short_mkt = short_mkt * qty / abs(short_leg["quantity"])
                current_value = round(long_mkt + short_mkt, 2)

                spreads.append({
                    "symbol": symbol,
                    "expiration": expiration,
                    "right": right,
                    "spread_type": spread_type,
                    "long_strike": best_long["strike"],
                    "short_strike": short_leg["strike"],
                    "quantity": qty,
                    "width": width,
                    "net_cost": round(net_cost, 2),
                    "max_risk": round((width * 100) - abs(net_cost), 2) if "Credit" in spread_type else round(abs(net_cost), 2),
                    "max_profit": round(abs(net_cost), 2) if "Credit" in spread_type else round((width * 100) - abs(net_cost), 2),
                    "unrealized_pnl": spread_pnl,
                    "current_value": current_value,
                })
            else:
                # Unpaired short leg
                spreads.append(_single_leg_entry(symbol, expiration, right, short_leg))

        # Any unpaired long legs
        for i, long_leg in enumerate(longs):
            if i not in used_longs:
                spreads.append(_single_leg_entry(symbol, expiration, right, long_leg))

    return spreads


def _single_leg_entry(symbol, expiration, right, leg):
    """Create a spread entry for an unpaired single option leg."""
    direction = "Long" if leg["quantity"] > 0 else "Short"
    opt_type = "Call" if right == "C" else "Put"
    return {
        "symbol": symbol,
        "expiration": expiration,
        "right": right,
        "spread_type": f"{direction} {opt_type}",
        "long_strike": leg["strike"] if leg["quantity"] > 0 else 0,
        "short_strike": leg["strike"] if leg["quantity"] < 0 else 0,
        "quantity": abs(leg["quantity"]),
        "width": 0,
        "net_cost": round(leg["avg_cost"], 2),
        "max_risk": round(leg["avg_cost"], 2),
        "max_profit": 0,
        "unrealized_pnl": round(leg.get("unrealized_pnl", 0) or 0, 2),
        "current_value": round(leg.get("market_value", 0) or 0, 2),
    }


def check_analyze_requests(client):
    """Check Redis (via server) for pending options analyze requests."""
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/analyze/pending",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return

        requests_list = resp.json().get("requests", [])
        for req in requests_list:
            ticker = req["ticker"]
            zone_type = req.get("zone_type", "supply")
            zone_price = float(req.get("zone_price", 0))
            current_price = float(req.get("current_price", 0))
            request_id = req["request_id"]

            logger.info("Analyzing options for %s (%s zone @ %.2f)", ticker, zone_type, zone_price)

            from .ibkr_analyzer import analyze_spreads_ib
            result = analyze_spreads_ib(ib, ticker, zone_type, zone_price, current_price)
            result["request_id"] = request_id
            result["ticker"] = ticker

            # Push result back
            requests.post(
                f"{SERVER_URL}/api/ibkr/analyze/result",
                json=result,
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=10,
            )
            logger.info("Analysis complete for %s: credit=%s, debit=%s",
                         ticker,
                         result["credit_spread"]["verdict"] if result.get("credit_spread") else "none",
                         result["debit_spread"]["verdict"] if result.get("debit_spread") else "none")

    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.debug("Analyze check: %s", e)


def check_order_requests(client):
    """Check for pending spread orders to place on IB."""
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/orders/pending",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return

        orders = resp.json().get("orders", [])

        # ─── FUTURES DEDUP: only keep the most recent order per ticker ───
        # For scalping, we only care about the latest signal. Older ones are stale.
        futures_orders = [o for o in orders if o.get("type") == "futures"]
        other_orders = [o for o in orders if o.get("type") != "futures"]
        if len(futures_orders) > 1:
            # Group by ticker, keep only the most recent
            by_ticker = {}
            for o in futures_orders:
                tk = o.get("ticker", "")
                existing = by_ticker.get(tk)
                if not existing or o.get("queued_at", "") > existing.get("queued_at", ""):
                    # Mark the older one as superseded
                    if existing:
                        try:
                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                json={"order_id": existing["order_id"], "status": "superseded"},
                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                        except Exception:
                            pass
                        logger.info("SKIP superseded %s %s — newer order exists", existing.get("direction"), tk)
                    by_ticker[tk] = o
                else:
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                            json={"order_id": o["order_id"], "status": "superseded"},
                            headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                    except Exception:
                        pass
                    logger.info("SKIP superseded %s %s — newer order exists", o.get("direction"), tk)
            futures_orders = list(by_ticker.values())

        orders = other_orders + futures_orders

        for order in orders:
            order_id = order["order_id"]
            ticker = order["ticker"]

            # ─── FUTURES ORDERS ───
            if order.get("type") == "futures":
                direction = order.get("direction", "")
                contracts = int(order.get("contracts", 1))
                strategy_name = order.get("strategy", "")

                # Weekend lockout: between Friday 17:00 ET flatten and
                # Sunday 18:00 ET open, futures should not re-enter on
                # late TV signals (this is how an MES short got stuck
                # over the 2026-05-15 weekend).
                rdb_lock = _rdb()
                if rdb_lock is not None:
                    try:
                        if rdb_lock.get("ibkr:weekend_lockout"):
                            logger.info(
                                "SKIP weekend lockout %s %s %s — futures market closed",
                                direction, ticker, strategy_name,
                            )
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                    json={"order_id": order_id,
                                          "status": "rejected",
                                          "reason": "weekend lockout (futures market closed)"},
                                    headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass

                # Skip stale orders (queued more than 5 minutes ago)
                queued_at = order.get("queued_at", "")
                if queued_at:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        queued_time = _dt.fromisoformat(queued_at.replace("Z", "+00:00"))
                        age_seconds = (_dt.now(_tz.utc) - queued_time).total_seconds()
                        if age_seconds > 300:
                            logger.info("SKIP stale %s %s — queued %.0fs ago", direction, ticker, age_seconds)
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                    json={"order_id": order_id, "status": "expired"},
                                    headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                            except Exception:
                                pass
                            continue
                    except Exception:
                        pass

                logger.info("Futures order: %s %s %dx — %s", direction, ticker, contracts, strategy_name)

                # Per-strategy position guard. Each strategy tracks its own
                # position in Redis (ibkr:strat_pos:{ticker}:{strategy}) so
                # independent strategies (e.g. 2n20 and ORB) can both hold a
                # position in the same contract at the same time. IB aggregates
                # at the account level; we book per-strategy here.
                #
                # Position truth: fills-based (~1-2s lag) instead of
                # /portfolio/positions (up to 4+ min lag — caused the 2026-05-22
                # CLEAR_ALL false positive). The time.sleep(1) below used
                # to be needed to let positions endpoint settle; with fills,
                # we don't have to wait.
                current_pos = 0
                try:
                    _fills_qty = reconciler.qty_map_from_fills(client)
                    current_pos = int(_fills_qty.get(ticker, 0))
                except Exception as _e:
                    logger.debug("fills-based current_pos lookup failed, falling back: %s", _e)
                    for item in client.get_positions():
                        if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                            current_pos = int(item.get("quantity", 0))
                            break

                # NOTE: reconcile_strat_pos() used to be called here as a
                # "best-effort cleanup" against stale strat_pos when IB's
                # position didn't match tracked qty. Disabled 2026-05-22
                # after it CLEAR_ALL'd a live 2n20 trade based on a 4.5-minute
                # /portfolio/positions lag — exactly the false-positive
                # category the trade diary system was built to eliminate.
                # The diary (lumisignals/diary.py) + reconciler.py now own
                # all reconciliation, keyed on broker_trade_id rather than
                # aggregate position quantities. See task #56.

                sp = get_strat_pos(ticker, strategy_name)
                strat_long = sp.get("direction") == "BUY"
                strat_short = sp.get("direction") == "SELL"

                # Diary fallback: if strat_pos (Redis) is empty for this
                # (ticker, strategy) but the trade diary still has a live
                # OPEN row, honor close webhooks via diary. Task #7 —
                # without this, today's bot SKIPPED two TV CLOSE signals
                # because the old reconciler had wiped strat_pos. The
                # diary keys on broker_trade_id so it survives strat_pos
                # bugs.
                diary_live = None
                diary_long = False
                diary_short = False
                # Diary lookup applies to BOTH close signals (fallback when
                # strat_pos got wiped) AND entry signals (so close-and-reverse
                # can detect opposing positions the strategy still owns per
                # the diary even if Redis lost the strat_pos row). Only
                # consulted when strat_pos is empty for THIS strategy.
                if direction in ("CLOSE_LONG", "CLOSE_SHORT", "BUY", "SELL") and \
                   not (strat_long or strat_short):
                    try:
                        diary_live = diary.find_live_open(
                            diary.strategy_slug(strategy_name) or strategy_name,
                            ticker,
                        )
                        if diary_live:
                            qty = int(diary_live.get("expected_qty") or 0)
                            diary_long = qty > 0
                            diary_short = qty < 0
                            if diary_long or diary_short:
                                logger.info(
                                    "Diary fallback: strat_pos empty but diary OPEN "
                                    "%s [%s] qty=%+d broker_trade_id=%s",
                                    ticker, strategy_name, qty,
                                    diary_live.get("broker_trade_id") or "-",
                                )
                    except Exception as _e:
                        logger.debug("diary fallback lookup failed: %s", _e)

                logger.info(
                    "Position check: %s ib_pos=%+d  [%s] strat=%s diary=%s",
                    ticker, current_pos, strategy_name,
                    f"{sp.get('direction')} {sp.get('contracts',0)}" if sp else "flat",
                    ("OPEN+" if diary_long else "OPEN-" if diary_short else "flat"),
                )

                # Manual close of an "untracked" orphan row (mobile Close
                # button on a position whose strat_pos was already cleared).
                # We don't have a matching strat_pos to gate on, so honor
                # the close request as long as IB's net direction agrees.
                #
                # Treat as untracked when EITHER:
                #   - strategy is the explicit "untracked" tag, or
                #   - no strat_pos exists for this ticker at all (every
                #     strategy has been cleared — the position is a pure
                #     orphan and we can't tell which strategy "owns" it).
                # The second case is what catches the audit-card Close path
                # since the mobile sends p.strategy (often null → defaults
                # to "manual_close") rather than the literal "untracked".
                # If some OTHER strategy still tracks this ticker, we don't
                # treat as untracked — that would let one strategy close
                # another's position by accident.
                rdb_check = _rdb()
                no_strat_pos_at_all = False
                if rdb_check is not None:
                    try:
                        no_strat_pos_at_all = not any(
                            True for _ in rdb_check.scan_iter(f"ibkr:strat_pos:{ticker}:*")
                        )
                    except Exception:
                        pass
                is_untracked_close = (
                    direction in ("CLOSE_LONG", "CLOSE_SHORT")
                    and (strategy_name == "untracked" or no_strat_pos_at_all)
                )

                skip = False
                if direction == "BUY" and strat_long:
                    logger.info("SKIP %s BUY [%s] — strategy already long (opened %s)",
                                ticker, strategy_name, sp.get("opened_at", ""))
                    skip = True
                elif direction == "SELL" and strat_short:
                    logger.info("SKIP %s SELL [%s] — strategy already short (opened %s)",
                                ticker, strategy_name, sp.get("opened_at", ""))
                    skip = True
                # Diary-based same-direction duplicate guard. Fires when
                # strat_pos was wiped but the diary still shows this
                # strategy holds a position in the same direction as the
                # new signal — without this, today's 2026-05-27 10:08
                # incident recurred (SELL signal stacked onto a leftover
                # short, ending with two unprotected shorts). If diary is
                # stale (broker actually flat), the reconciler will write
                # RECONCILE_GONE and clear it, unblocking the next signal.
                elif direction == "BUY" and diary_long and not (strat_long or strat_short):
                    logger.info(
                        "SKIP %s BUY [%s] — diary has live OPEN long "
                        "(broker_trade_id=%s); refusing to stack a duplicate.",
                        ticker, strategy_name,
                        (diary_live or {}).get("broker_trade_id") or "-",
                    )
                    skip = True
                elif direction == "SELL" and diary_short and not (strat_long or strat_short):
                    logger.info(
                        "SKIP %s SELL [%s] — diary has live OPEN short "
                        "(broker_trade_id=%s); refusing to stack a duplicate.",
                        ticker, strategy_name,
                        (diary_live or {}).get("broker_trade_id") or "-",
                    )
                    skip = True
                elif direction == "CLOSE_LONG" and not strat_long and not is_untracked_close and not diary_long:
                    logger.info("SKIP %s CLOSE_LONG [%s] — strategy not long (diary also flat)",
                                ticker, strategy_name)
                    skip = True
                elif direction == "CLOSE_SHORT" and not strat_short and not is_untracked_close and not diary_short:
                    logger.info("SKIP %s CLOSE_SHORT [%s] — strategy not short (diary also flat)",
                                ticker, strategy_name)
                    skip = True
                elif is_untracked_close:
                    # Validate against IB's net direction so we don't
                    # accidentally flip a position rather than close it.
                    ib_long  = current_pos > 0
                    ib_short = current_pos < 0
                    if direction == "CLOSE_LONG" and not ib_long:
                        logger.info("SKIP %s CLOSE_LONG [untracked] — IB net is not long (qty=%+d)",
                                    ticker, current_pos)
                        skip = True
                    elif direction == "CLOSE_SHORT" and not ib_short:
                        logger.info("SKIP %s CLOSE_SHORT [untracked] — IB net is not short (qty=%+d)",
                                    ticker, current_pos)
                        skip = True
                    else:
                        logger.info("ALLOW %s %s [untracked] — IB qty=%+d, manual mobile close",
                                    ticker, direction, current_pos)
                elif (
                    direction in ("BUY", "SELL")
                    and not strat_long and not strat_short
                    and ((direction == "BUY" and current_pos < 0)
                         or (direction == "SELL" and current_pos > 0))
                ):
                    # Opposing position at IB. Three sub-cases:
                    #   (a) Diary has live OPEN for THIS strategy in the
                    #       opposing direction → close-and-reverse path
                    #       below picks it up (don't skip).
                    #   (b) No diary lineage → still skip (we don't know
                    #       whose orphan it is, can't safely reverse).
                    # The previous behavior was always (b); (a) is new in
                    # 2026-05-27 so legitimate reversal signals on diary-
                    # tracked positions stop getting blocked.
                    can_reverse_via_diary = (
                        (direction == "BUY" and diary_short)
                        or (direction == "SELL" and diary_long)
                    )
                    if can_reverse_via_diary:
                        logger.info(
                            "ALLOW %s %s [%s] — opposing IB qty=%+d will be reversed "
                            "via diary lineage (broker_trade_id=%s)",
                            ticker, direction, strategy_name, current_pos,
                            (diary_live or {}).get("broker_trade_id") or "-",
                        )
                    else:
                        logger.info(
                            "SKIP %s %s [%s] — IB has opposing orphan (qty=%+d). "
                            "No diary lineage to reverse from; manual-flat the orphan first.",
                            ticker, direction, strategy_name, current_pos,
                        )
                        skip = True

                if skip:
                    try:
                        requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                      json={"order_id": order_id, "status": "skipped", "ticker": ticker, "direction": direction},
                                      headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                    except Exception:
                        pass
                    continue

                try:
                    # Resolve front-month futures contract via CPAPI
                    fut_info = client.search_futures(ticker)
                    if not fut_info or not fut_info.get("conid"):
                        raise ValueError(f"No futures contract found for {ticker}")
                    fut_conid = fut_info["conid"]
                    multiplier = float(fut_info.get("multiplier", 5))
                    logger.info("Resolved %s to conid %s exp %s", ticker, fut_conid, fut_info.get("expiration", ""))

                    # Get futures stop loss setting from server
                    sl_dollars = 25.0
                    try:
                        sl_resp = requests.get(
                            f"{SERVER_URL}/api/ibkr/exit-rules",
                            headers={"X-Sync-Key": SYNC_KEY},
                            timeout=5,
                        )
                        if sl_resp.status_code == 200:
                            sl_dollars = float(sl_resp.json().get("futures_stop_loss", 25))
                    except Exception:
                        pass

                    sl_points = sl_dollars / multiplier

                    # Pine's calculated plan (ORB sends; 2n20 doesn't). If
                    # present, use Pine's stop/target verbatim instead of
                    # deriving from sl_dollars. ORB's VIX-aware stop sizing
                    # only matters if we actually honor it.
                    pine_stop = float(order.get("stop_price") or 0)
                    pine_target = float(order.get("target_price") or 0)
                    pine_meta = {k: order[k] for k in (
                        "vix", "or_high", "or_low", "or_range",
                        "stop_size", "stop_reason", "reversal",
                    ) if order.get(k) is not None}
                    # Latency telemetry from the saas webhook handler
                    # (Tier 2 #9). Stored on the queued order; threaded
                    # into the INTENT_OPEN diary row below.
                    webhook_received_at = order.get("webhook_received_at")
                    tv_latency_seconds = order.get("tv_latency_seconds")

                    if direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                        # Per-strategy entry price — prefer strat_pos (the
                        # specific entry this strategy made), fall back to
                        # the diary's OPEN row (#7 — survives strat_pos
                        # wipes), then IB's aggregate avg_cost as a last
                        # resort.
                        sp_strat = get_strat_pos(ticker, strategy_name)
                        entry_price = 0
                        entry_qty = 0
                        if sp_strat:
                            entry_price = float(sp_strat.get("entry_price") or 0)
                            entry_qty = int(sp_strat.get("contracts") or 0)
                        if not entry_price and diary_live:
                            entry_price = float(diary_live.get("entry_price") or 0)
                            entry_qty = abs(int(diary_live.get("expected_qty") or 0))

                        # Diary: INTENT_CLOSE so a mid-close failure still
                        # leaves a clear "we tried to close it" marker.
                        diary_strategy_id = diary.strategy_slug(strategy_name) or strategy_name
                        diary_perm_id = (
                            str((sp_strat or {}).get("perm_id") or "")
                            or (diary_live or {}).get("broker_trade_id")
                            or None
                        )
                        try:
                            diary.record_event(
                                broker="ib",
                                broker_trade_id=diary_perm_id,
                                strategy_id=diary_strategy_id,
                                ticker=ticker,
                                state=diary.State.INTENT_CLOSE,
                                reason=f"TV {direction} [{strategy_name}]",
                                expected_qty=0,
                            )
                        except Exception as _de:
                            logger.warning("diary INTENT_CLOSE write failed: %s", _de)
                        if not entry_price:
                            for item in client.get_positions():
                                if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                                    entry_price = item.get("avg_cost", 0) / multiplier
                                    entry_qty = abs(int(item.get("quantity", 0)))
                                    break

                        # Cancel matching protective stop(s) before placing the
                        # close. Without this, IB sees pending SELL STPs + new
                        # SELL MKT and rejects the close as overselling — which
                        # is what caused the runaway accumulation seen May 11.
                        close_action = "SELL" if direction == "CLOSE_LONG" else "BUY"
                        cancelled_stops = 0
                        # Prefer cancelling THIS strategy's specific stop (tracked
                        # in strat_pos when the position was opened). Fall back
                        # to the diary's meta.stop_order_id when strat_pos is
                        # empty — task #7.
                        sp_for_close = get_strat_pos(ticker, strategy_name)
                        targeted_stop = (sp_for_close or {}).get("stop_order_id", "")
                        targeted_target = (sp_for_close or {}).get("target_order_id", "")
                        if not targeted_stop and diary_live:
                            dm = diary_live.get("meta") or {}
                            targeted_stop = dm.get("stop_order_id") or ""
                            targeted_target = dm.get("target_order_id") or ""

                        # Atomic stop-and-close via order-modify (Phase 3).
                        # When we have the stop's order_id, modify it from
                        # STP into MKT in a single REST call. The stop fires
                        # immediately as a market order — same orderId, no
                        # second order, no cancel-then-place race window.
                        # The stop's identity is preserved across its
                        # transformation into the close. Empirically validated
                        # against IBeam/CPAPI on 2026-05-22.
                        #
                        # Fallback to legacy cancel-then-close when stop_order_id
                        # is missing (orphan, untracked, or pre-Phase-3 legacy
                        # position). The TP child, when present, is cancelled
                        # explicitly either way.
                        # Hard #3: atomic close failure handling.
                        # - modify_order can fail silently (returns error dict
                        #   instead of raising). Validate using the same helper
                        #   as place_order and retry once.
                        # - If atomic fails AND fallback cancel also fails, the
                        #   safest action is to NOT place a fresh close MKT
                        #   (would risk a double-stop). Alert and skip instead.
                        atomic_close_used = False
                        trade_result = None
                        if targeted_stop:
                            for _mod_attempt in range(2):  # original + 1 retry
                                try:
                                    logger.info(
                                        "Atomic close: modify STP %s → MKT for [%s] (attempt %d)",
                                        targeted_stop, strategy_name, _mod_attempt + 1,
                                    )
                                    trade_result = client.modify_order(
                                        targeted_stop,
                                        conid=fut_conid,
                                        side=close_action,
                                        quantity=contracts,
                                        order_type="MKT",
                                        tif="GTC",
                                    )
                                    _is_fail, _fail_reason = _validate_place_order_result(trade_result)
                                    if not _is_fail:
                                        atomic_close_used = True
                                        break
                                    logger.warning(
                                        "Atomic STP→MKT modify rejected (attempt %d): %s",
                                        _mod_attempt + 1, _fail_reason,
                                    )
                                except Exception as e:
                                    logger.warning(
                                        "Atomic STP→MKT modify raised (attempt %d): %s",
                                        _mod_attempt + 1, e,
                                    )
                                if _mod_attempt == 0:
                                    time.sleep(0.5)
                            if not atomic_close_used:
                                logger.error(
                                    "Atomic close FAILED after 2 attempts for [%s] — "
                                    "falling back to cancel+close",
                                    strategy_name,
                                )

                        if not atomic_close_used:
                            # Legacy path: explicit cancel before placing close.
                            # If cancel of the TRACKED stop fails, refuse to
                            # place the fresh close — both could fill and we'd
                            # double-stop. Telegram + skip instead.
                            cancel_failed_hard = False
                            if targeted_stop:
                                try:
                                    cancel_result = client.cancel_order(targeted_stop)
                                    cancel_err = (
                                        cancel_result.get("error")
                                        if isinstance(cancel_result, dict)
                                        else None
                                    )
                                    if cancel_err:
                                        logger.error(
                                            "Cancel SL %s REJECTED by IB: %s — refusing fresh close to avoid double-stop",
                                            targeted_stop, cancel_err,
                                        )
                                        cancel_failed_hard = True
                                    else:
                                        cancelled_stops = 1
                                        logger.info("Cancelled SL %s for [%s] before close",
                                                    targeted_stop, strategy_name)
                                except Exception as e:
                                    logger.error(
                                        "Cancel SL %s raised: %s — refusing fresh close to avoid double-stop",
                                        targeted_stop, e,
                                    )
                                    cancel_failed_hard = True
                                if cancel_failed_hard:
                                    try:
                                        _send_telegram_alert(
                                            f"🚨 Close FAILED: {ticker} [{strategy_name}]",
                                            f"{direction} {ticker}: atomic STP→MKT modify "
                                            f"failed AND explicit cancel of stop "
                                            f"{targeted_stop} also failed.\n\n"
                                            f"Refusing to place fresh close MKT — would risk "
                                            f"a double-stop fill. Manually flatten via IB.",
                                        )
                                    except Exception:
                                        pass
                                    continue  # skip this order
                            else:
                                # Cancel matching orphan stops as protection.
                                try:
                                    open_orders_now = client.get_open_orders() or []
                                    matching = [o for o in open_orders_now
                                                if o.get("ticker") == ticker
                                                and o.get("side") == close_action
                                                and o.get("orderType") in ("Stop", "STP")
                                                and o.get("status") not in ("Filled", "Cancelled")][:contracts]
                                    for o in matching:
                                        try:
                                            client.cancel_order(str(o.get("orderId")))
                                            cancelled_stops += 1
                                        except Exception:
                                            pass
                                    if cancelled_stops:
                                        logger.info("Cancelled %d orphan %s stop(s) on %s before close",
                                                    cancelled_stops, close_action, ticker)
                                except Exception as e:
                                    logger.debug("orphan stop cancel scan failed: %s", e)
                            if cancelled_stops:
                                time.sleep(1)
                            order_payload = client.build_futures_order(
                                fut_conid, close_action, contracts, "MKT", tif="GTC",
                            )
                            trade_result = client.place_order(order_payload)

                        # TP child cancel (atomic-close path doesn't auto-handle TP).
                        # In the atomic path, the SL becomes the close, but a
                        # separate TP child needs its own cancel. In legacy path,
                        # this is already handled above.
                        if atomic_close_used and targeted_target and targeted_target != "0":
                            try:
                                client.cancel_order(targeted_target)
                                logger.info("Cancelled TP %s for [%s] after atomic close",
                                            targeted_target, strategy_name)
                            except Exception as e:
                                logger.warning("Cancel TP %s failed: %s", targeted_target, e)

                        # Extract close-order ID and read its specific fill
                        # price (avoids the get_trades()[-1] cross-contract
                        # contamination bug that mis-priced stops on entries).
                        close_order_id = ""
                        if isinstance(trade_result, list) and trade_result:
                            first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                            close_order_id = str(first.get("order_id", "") or "")
                        elif isinstance(trade_result, dict):
                            close_order_id = str(trade_result.get("order_id", "") or "")
                        exit_price = 0
                        try:
                            fill_info = client.get_order_fill(close_order_id)
                            exit_price = float(fill_info.get("avg_price") or 0)
                        except Exception:
                            pass
                        if entry_price and exit_price:
                            if direction == "CLOSE_LONG":
                                pnl = (exit_price - entry_price) * contracts * multiplier
                            else:
                                pnl = (entry_price - exit_price) * contracts * multiplier
                            from datetime import datetime as _dt, timezone as _tz
                            # Use reason from webhook, or default
                            close_reason = order.get("reason", "")
                            if not close_reason:
                                close_reason = "Exit Long" if direction == "CLOSE_LONG" else "Exit Short"

                            # Entry strategy = THIS close's strategy. Each
                            # strategy owns its own strat_pos; closing 2n20
                            # should attribute to 2n20 even if ORB also has
                            # a position on the same instrument.
                            entry_strategy = strategy_name.replace("_exit", "")

                            # opened_at — prefer the per-strategy strat_pos
                            # (most accurate, captures THIS strategy's entry
                            # timestamp). Fall back to the legacy
                            # /api/ibkr/futures-entry endpoint only when
                            # there's no strat_pos.
                            opened_at = ""
                            if sp_strat:
                                opened_at = sp_strat.get("opened_at", "")
                            if not opened_at:
                                entry_dir = "BUY" if direction == "CLOSE_LONG" else "SELL"
                                try:
                                    entry_resp = requests.get(
                                        f"{SERVER_URL}/api/ibkr/futures-entry/{ticker}/{entry_dir}",
                                        headers={"X-Sync-Key": SYNC_KEY},
                                        timeout=5,
                                    )
                                    if entry_resp.status_code == 200:
                                        entry_data = entry_resp.json()
                                        opened_at = entry_data.get("opened_at", "")
                                        # Mark this entry as closed so it's not reused,
                                        # but do NOT overwrite entry_strategy — that
                                        # endpoint returns "most recent entry for any
                                        # strategy" which is exactly the bug we're
                                        # fixing.
                                        if entry_data.get("order_id"):
                                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                                json={"order_id": entry_data["order_id"], "status": "closed"},
                                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                                except Exception:
                                    pass
                            if not opened_at:
                                opened_at = order.get("queued_at", "")

                            # SL/TP come from the strat_pos record so the
                            # closed-trade row carries the original bracket
                            # levels. Used downstream to compute planned_rr
                            # and achieved_rr.
                            sp_stop = float((sp_strat or {}).get("stop_price") or 0) or None
                            sp_target = float((sp_strat or {}).get("target_price") or 0) or None
                            closed_trade = {
                                "symbol": ticker,
                                "type": "futures",
                                "direction": "LONG" if direction == "CLOSE_LONG" else "SHORT",
                                "contracts": contracts,
                                "entry_price": round(entry_price, 2),
                                "exit_price": round(exit_price, 2),
                                "realized_pnl": round(pnl, 2),
                                "stop_loss": round(sp_stop, 2) if sp_stop else None,
                                "take_profit": round(sp_target, 2) if sp_target else None,
                                "strategy": entry_strategy,
                                "close_reason": close_reason,
                                "opened_at": opened_at,
                                "closed_at": _dt.now(_tz.utc).isoformat(),
                            }
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/closed-trade",
                                              json=closed_trade, headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                            except Exception:
                                pass
                            logger.info("Closed %s %s: entry=%.2f exit=%.2f P&L=$%.2f", ticker, direction, entry_price, exit_price, pnl)
                            # Diary: CLOSED with realized P&L. broker_trade_id
                            # is the original entry's perm_id from strat_pos.
                            try:
                                diary.record_event(
                                    broker="ib",
                                    broker_trade_id=diary_perm_id,
                                    strategy_id=diary_strategy_id,
                                    ticker=ticker,
                                    state=diary.State.CLOSED,
                                    reason=close_reason or f"TV {direction}",
                                    expected_qty=0,
                                    entry_price=entry_price,
                                    exit_price=exit_price,
                                    realized_pl=pnl,
                                )
                            except Exception as _de:
                                logger.warning("diary CLOSED write failed: %s", _de)
                            # Runaway guard: feed the consecutive-loss streak
                            # counter. Resets to 0 on any winner; trips when
                            # streak crosses the configured cap.
                            try:
                                from .runaway_guard import record_close
                                record_close(float(pnl or 0))
                            except Exception as _rg:
                                logger.warning("runaway_guard record_close (CLOSED) failed: %s", _rg)
                            # Push notification: trade closed.
                            try:
                                from .supabase_client import notify_trade_closed
                                supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                                if supabase_uid:
                                    points = round(exit_price - entry_price, 2) if direction == "CLOSE_LONG" else round(entry_price - exit_price, 2)
                                    notify_trade_closed(
                                        user_id=supabase_uid,
                                        instrument=ticker,
                                        direction=("BUY" if direction == "CLOSE_LONG" else "SELL"),
                                        pl=pnl,
                                        pips=points,  # MES points (not pips), repurposing the field
                                        reason=close_reason or strategy_name.upper(),
                                    )
                            except Exception as e:
                                logger.debug("notify_trade_closed failed: %s", e)
                    elif direction in ("BUY", "SELL"):
                        # Atomic 3-order bracket: parent entry + SL child +
                        # optional TP child, all wired by cOID/parentId in
                        # ONE POST. IB holds children as PreSubmitted until
                        # the parent fills, then activates them as OCA.
                        # Position is never unprotected — eliminates the
                        # ~2-3s window between entry fill and SL placement
                        # that the previous sequential approach left open.
                        #
                        # Pre-trade SL pricing: Pine-supplied stop wins;
                        # otherwise we pull a fresh quote and anchor on the
                        # last price ± sl_points. Slippage of a tick or two
                        # between this estimate and the actual fill costs
                        # us at most a few dollars on the $25 stop budget —
                        # immaterial against the risk of an unprotected
                        # window during fast markets.
                        last_price = 0.0  # signal_price for the diary; may be set below
                        if pine_stop > 0:
                            sl_price = pine_stop
                            quote_source = "pine"
                        else:
                            # Warm the IBeam subscription, then poll the
                            # snapshot until quotes arrive. Field 31=last,
                            # 84=bid, 86=ask.
                            #
                            # Why polling: a cold CPAPI session needs to
                            # SUBSCRIBE to the conid before quotes flow.
                            # First snapshot triggers the subscribe; quotes
                            # arrive on subsequent reads. Bumped from a fixed
                            # 400ms sleep to a 2.5s warmup + 5s poll after
                            # 22h of MES entries silently refused on
                            # 2026-05-14 because the cold-session warmup
                            # never finished within the old window.
                            try:
                                client._request("GET", "/iserver/marketdata/snapshot",
                                                params={"conids": str(fut_conid),
                                                        "fields": "31,84,86"})
                            except Exception:
                                pass
                            time.sleep(2.5)
                            last_price = 0.0
                            deadline = time.time() + 5.0
                            while time.time() < deadline and not last_price:
                                try:
                                    snap = client._request(
                                        "GET", "/iserver/marketdata/snapshot",
                                        params={"conids": str(fut_conid),
                                                "fields": "31,84,86"})
                                except Exception:
                                    snap = None
                                if isinstance(snap, list) and snap:
                                    row = snap[0]
                                    for key in ("31", "84", "86"):
                                        try:
                                            v = float(row.get(key) or 0)
                                            if v > 0:
                                                last_price = v
                                                break
                                        except (TypeError, ValueError):
                                            continue
                                if not last_price:
                                    time.sleep(0.5)
                            if not last_price:
                                logger.error(
                                    "Cannot price SL for %s %s [%s] — no quote from IBeam, "
                                    "refusing to place unprotected entry",
                                    direction, ticker, strategy_name,
                                )
                                # Alert: webhook signal arrived but the entry
                                # got refused — this is exactly the silent-
                                # failure pattern the user hit today (TV alerts
                                # firing, IBeam quote unavailable, zero fills
                                # for 22h). Rate-limited per title so a
                                # crash-looping refusal doesn't spam Telegram.
                                try:
                                    _send_telegram_alert(
                                        f"⚠️ Entry refused: {ticker} [{strategy_name}]",
                                        f"{direction} {ticker} signal received but "
                                        f"IBeam has no quote — entry not placed.\n"
                                        f"Check IB market data subscription / restart sync.",
                                    )
                                except Exception:
                                    pass
                                continue
                            sl_price = ((last_price - sl_points) if direction == "BUY"
                                        else (last_price + sl_points))
                            quote_source = f"config (anchor={last_price:.2f})"
                        tp_price = pine_target if pine_target > 0 else 0

                        # Diary intent + strategy ID resolved BEFORE the
                        # bracket build so we can encode them into the
                        # parent's cOID. Every IB order then self-identifies
                        # via order_ref — the reconciler can decode strategy
                        # attribution from any fill without external lookup,
                        # and "phantom" detection becomes "adopt by tag".
                        diary_intent_id = diary.new_intent_id()
                        diary_strategy_id = diary.strategy_slug(strategy_name) or strategy_name
                        # IB cOID limit is 36 chars. Format: lumi_<slug>_<8 hex>
                        # — 8 hex from uuid is 4 billion-space, ample for
                        # our trade volume.
                        entry_coid = f"lumi_{diary_strategy_id}_{diary_intent_id.replace('-', '')[:8]}"[:36]

                        # Close-and-reverse detection. When THIS strategy
                        # currently holds the OPPOSITE direction (intra-
                        # strategy reversal), submit a single MKT sized
                        # (existing_qty + entry_qty). IB processes the fills
                        # as: close existing + open new in one trade. Net
                        # position lands at exactly the intended direction.
                        # The SL/TP children are sized to entry_qty only
                        # (protecting the NEW position, not the inflated
                        # close-and-open total).
                        #
                        # Safety gate: refuse to auto-reverse if any OTHER
                        # strategy holds a strat_pos for this ticker. A
                        # reversal MKT would inadvertently close the other
                        # strategy's leg too — IB position is fungible.
                        # In that case fall back to legacy single-qty entry
                        # and log loudly so the operator sees the divergence.
                        reverse_qty = 0
                        prior_sl_id = ""
                        prior_tp_id = ""
                        reverse_via = None  # "strat_pos" | "diary"

                        # Helper: refuse reversal if any OTHER strategy holds
                        # a strat_pos for this ticker (would close their leg).
                        def _other_strat_pos_present():
                            try:
                                rev_chk = _rdb()
                                if rev_chk is None:
                                    return False
                                for k in rev_chk.scan_iter(f"ibkr:strat_pos:{ticker}:*"):
                                    if not k.endswith(f":{strategy_name}"):
                                        return True
                            except Exception:
                                pass
                            return False

                        # Case 1: strat_pos says this strategy holds opposing.
                        if (direction == "BUY" and strat_short) or \
                           (direction == "SELL" and strat_long):
                            if not _other_strat_pos_present():
                                reverse_qty = int(sp.get("contracts") or 0)
                                prior_sl_id = str(sp.get("stop_order_id") or "")
                                prior_tp_id = str(sp.get("target_order_id") or "")
                                reverse_via = "strat_pos"
                            else:
                                logger.warning(
                                    "REVERSE SKIP %s %s [%s] — other strat_pos rows "
                                    "share this ticker; refusing to auto-flip.",
                                    ticker, direction, strategy_name,
                                )

                        # Case 2: strat_pos empty but diary has live OPEN for
                        # this strategy in the opposing direction. The diary
                        # remembers the entry id; we use it to cancel obsolete
                        # bracket children after the reverse fills.
                        if reverse_qty == 0 and diary_live and \
                           ((direction == "BUY" and diary_short) or
                            (direction == "SELL" and diary_long)):
                            if not _other_strat_pos_present():
                                reverse_qty = abs(int(diary_live.get("expected_qty") or 0))
                                dm = diary_live.get("meta") or {}
                                prior_sl_id = str(dm.get("stop_order_id") or "")
                                prior_tp_id = str(dm.get("target_order_id") or "")
                                reverse_via = "diary"
                            else:
                                logger.warning(
                                    "REVERSE SKIP %s %s [%s] — diary lineage exists "
                                    "but other strat_pos rows share this ticker.",
                                    ticker, direction, strategy_name,
                                )

                        if reverse_qty > 0:
                            logger.info(
                                "REVERSE %s %s via=%s — existing %d %s, opening %d %s, "
                                "single MKT %d contracts (SL child sized %d)",
                                ticker, direction, reverse_via,
                                reverse_qty, "long" if direction == "SELL" else "short",
                                contracts, "short" if direction == "SELL" else "long",
                                reverse_qty + contracts, contracts,
                            )

                        parent_qty = contracts + reverse_qty
                        bracket_payload = client.build_futures_bracket(
                            fut_conid, direction, parent_qty,
                            stop_price=sl_price,
                            entry_type="MKT",
                            target_price=tp_price if tp_price > 0 else None,
                            tif="GTC",
                            entry_coid=entry_coid,
                            child_quantity=(contracts if reverse_qty > 0 else None),
                        )

                        # Diary: INTENT_OPEN before we hit the broker. This
                        # row carries an intent_id we'll thread to OPEN/
                        # CANCELLED below so the reconciler can see we
                        # tried, even if the place_order fails silently.
                        #
                        # signal_price = last_price (the IBeam quote at the
                        # moment we processed the signal). Not exactly the
                        # bar close Pine saw — Pine fires on bar close, then
                        # webhook delivery adds 5-30s. But this is the price
                        # we'd have to beat for the trade to be at "no
                        # slippage". Used by /api/strategies/slippage to
                        # measure decision-to-fill drift over many trades.
                        try:
                            diary.record_event(
                                broker="ib",
                                strategy_id=diary_strategy_id,
                                ticker=ticker,
                                state=diary.State.INTENT_OPEN,
                                reason=f"TV {direction} [{strategy_name}]",
                                client_intent_id=diary_intent_id,
                                expected_qty=(contracts if direction == "BUY" else -contracts),
                                stop_price=sl_price,
                                target_price=(tp_price if tp_price > 0 else None),
                                signal_price=last_price if last_price else None,
                                webhook_received_at=webhook_received_at,
                                tv_latency_seconds=tv_latency_seconds,
                                meta={"quote_source": quote_source} if quote_source else None,
                            )
                        except Exception as _de:
                            logger.warning("diary INTENT_OPEN write failed: %s", _de)

                        # Hard #4: re-tickle CPAPI session right before placing
                        # the order. ensure_session() raises ConnectionError if
                        # the session can't be recovered without a browser
                        # login. Mark the intent CANCELLED + alert in that case
                        # so reconciler doesn't see a phantom INTENT_OPEN forever.
                        try:
                            client.ensure_session()
                        except ConnectionError as _se:
                            logger.error(
                                "CPAPI session dead — refusing entry %s %s [%s]: %s",
                                direction, ticker, strategy_name, _se,
                            )
                            try:
                                diary.record_event(
                                    broker="ib",
                                    strategy_id=diary_strategy_id,
                                    ticker=ticker,
                                    state=diary.State.CANCELLED,
                                    reason="CPAPI session expired before place_order",
                                    client_intent_id=diary_intent_id,
                                    expected_qty=0,
                                )
                            except Exception as _de:
                                logger.warning("diary CANCELLED (session) write failed: %s", _de)
                            try:
                                _send_telegram_alert(
                                    f"🚧 Entry refused: CPAPI session dead",
                                    f"{direction} {ticker} [{strategy_name}] signal arrived but "
                                    f"CPAPI session has expired and could not auto-reauth.\n\n"
                                    f"Open bot.lumitrade.ai/ib-auth and re-authenticate.",
                                )
                            except Exception:
                                pass
                            continue

                        trade_result = client.place_order(bracket_payload)

                        # Hard #1: validate the response. CPAPI can return
                        # error dicts that we'd otherwise parse as empty
                        # order_ids and silently proceed. Detect failure here
                        # — mark diary CANCELLED, alert, skip the rest.
                        _is_fail, _fail_reason = _validate_place_order_result(trade_result)
                        if _is_fail:
                            logger.error(
                                "place_order REJECTED %s %s [%s]: %s | response=%r",
                                direction, ticker, strategy_name, _fail_reason, trade_result,
                            )
                            try:
                                diary.record_event(
                                    broker="ib",
                                    strategy_id=diary_strategy_id,
                                    ticker=ticker,
                                    state=diary.State.CANCELLED,
                                    reason=f"place_order failed: {_fail_reason}",
                                    client_intent_id=diary_intent_id,
                                    expected_qty=0,
                                )
                            except Exception as _de:
                                logger.warning("diary CANCELLED (place_order) write failed: %s", _de)
                            try:
                                _send_telegram_alert(
                                    f"❌ Entry rejected by IB: {ticker} [{strategy_name}]",
                                    f"{direction} {ticker} bracket REJECTED.\n"
                                    f"Reason: {_fail_reason}\n\n"
                                    f"No position opened. Check IB account state.",
                                )
                            except Exception:
                                pass
                            continue

                        # Response is an array of result objects in the same
                        # order as the orders we posted: [entry, sl, tp?].
                        entry_order_id = ""
                        sl_order_id = ""
                        tp_order_id = ""
                        if isinstance(trade_result, list):
                            if len(trade_result) >= 1 and isinstance(trade_result[0], dict):
                                entry_order_id = str(trade_result[0].get("order_id", "") or "")
                            if len(trade_result) >= 2 and isinstance(trade_result[1], dict):
                                sl_order_id = str(trade_result[1].get("order_id", "") or "")
                            if len(trade_result) >= 3 and isinstance(trade_result[2], dict):
                                tp_order_id = str(trade_result[2].get("order_id", "") or "")
                        elif isinstance(trade_result, dict):
                            entry_order_id = str(trade_result.get("order_id", "") or "")

                        # If CPAPI's bracket response didn't surface the
                        # child order IDs (we've observed empty sl_order_id
                        # for every bracket today), discover them by
                        # searching open orders for the parent's children.
                        # This populates the diary's stop_order_id field so
                        # check_stop_fills() can detect stop fires within
                        # ~2s — critical for 30-second scalps. Task #3.
                        #
                        # Hard #2: CPAPI sometimes hasn't published the
                        # children yet when the bracket POST returns.
                        # Poll up to 5 times (0.5 s apart, ~2.5 s total) —
                        # uses the existing ~2 s settle window before
                        # strat_pos is created. If SL still missing after
                        # polling AND we have a parent order_id, the
                        # position is at IB but we have no SL to monitor;
                        # fire a high-priority Telegram so the user knows
                        # the bracket is broken.
                        if entry_order_id and (not sl_order_id or not tp_order_id):
                            for _attempt in range(5):
                                try:
                                    open_orders = client.get_open_orders() or []
                                    children = [
                                        o for o in open_orders
                                        if str(o.get("parentId") or "") == entry_order_id
                                    ]
                                    for c in children:
                                        ot = (c.get("orderType") or "").upper()
                                        cid = str(c.get("orderId") or "")
                                        if not cid:
                                            continue
                                        if not sl_order_id and ot in ("STP", "STOP", "STOP_LIMIT"):
                                            sl_order_id = cid
                                        elif not tp_order_id and ot in ("LMT", "LIMIT", "LIMIT_ON_CLOSE"):
                                            tp_order_id = cid
                                except Exception as _e:
                                    logger.debug("bracket child discovery failed: %s", _e)
                                # Stop polling once SL is found (TP is
                                # optional — never wait for it alone).
                                if sl_order_id:
                                    break
                                if _attempt < 4:
                                    time.sleep(0.5)
                            if sl_order_id:
                                logger.info(
                                    "Bracket children discovered for entry %s: sl=%s tp=%s",
                                    entry_order_id, sl_order_id or "-", tp_order_id or "-",
                                )
                            else:
                                # Position is (likely) live at IB but the SL
                                # never surfaced. Either CPAPI didn't accept
                                # the child or it's still propagating. Either
                                # way, check_stop_fills can't monitor it and
                                # the user needs to know NOW.
                                logger.error(
                                    "BRACKET SL MISSING after %d polls for entry %s "
                                    "(%s %s [%s]) — position may be NAKED. Reconciler "
                                    "will retry on next pass.",
                                    5, entry_order_id, direction, ticker, strategy_name,
                                )
                                try:
                                    _send_telegram_alert(
                                        f"⚠️ Naked entry risk: {ticker} [{strategy_name}]",
                                        f"{direction} {ticker} bracket parent placed "
                                        f"(order {entry_order_id}) but SL child did not "
                                        f"surface after 2.5 s of polling.\n\n"
                                        f"Position may be unprotected. Check IB and "
                                        f"consider manual SL placement.",
                                    )
                                except Exception:
                                    pass

                        logger.info(
                            "Bracket %s %s %dx — entry=%s, sl=%s @ %.2f (%s), tp=%s",
                            direction, ticker, contracts, entry_order_id,
                            sl_order_id, sl_price, quote_source,
                            f"{tp_order_id} @ {tp_price:.2f}" if tp_price > 0 else "none",
                        )
                    else:
                        logger.error("Unknown futures direction: %s", direction)
                        continue

                    time.sleep(2)
                    from datetime import datetime as _dt2, timezone as _tz2
                    # Extract order ID from CPAPI response
                    perm_id = ""
                    ib_order_id = 0
                    order_status = "Submitted"
                    if isinstance(trade_result, list) and trade_result:
                        first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                        ib_order_id = first.get("order_id", 0)
                        order_status = first.get("order_status", "Submitted")
                        perm_id = str(ib_order_id)
                    elif isinstance(trade_result, dict):
                        ib_order_id = trade_result.get("order_id", 0)
                        order_status = trade_result.get("order_status", "Submitted")
                        perm_id = str(ib_order_id)
                    now_iso = _dt2.now(_tz2.utc).isoformat()

                    result = {
                        "order_id": order_id,
                        "ib_order_id": ib_order_id,
                        "perm_id": perm_id,
                        "status": order_status,
                        "ticker": ticker,
                        "direction": direction,
                        "type": "futures",
                    }
                    logger.info("Futures order placed: %s %s — %s (id=%s)", direction, ticker, order_status, perm_id)

                    # Store entry details for BUY/SELL (not CLOSE) using order ID as unique key
                    if direction in ("BUY", "SELL"):
                        # Guard: if IB returned id=0 or empty perm_id, the
                        # order didn't actually reach the broker. Don't
                        # create a phantom strat_pos that will confuse
                        # reconcile and trigger spurious CLEAR_ALLs.
                        if not perm_id or str(perm_id) in ("0", "", "None"):
                            logger.error(
                                "Order placement returned invalid id (%r) for %s %s [%s] "
                                "— refusing to create strat_pos. Raw trade_result was: %r",
                                perm_id, direction, ticker, strategy_name, trade_result
                            )
                            try:
                                from .supabase_client import send_telegram_message
                                send_telegram_message(
                                    f"⚠️ *Order placement failed* — {direction} {ticker} "
                                    f"[{strategy_name}]: IB returned invalid id `{perm_id}`. "
                                    f"No position opened. Will retry on next signal."
                                )
                            except Exception:
                                pass
                            try:
                                requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                    json={"order_id": order_id, "status": "failed",
                                          "ticker": ticker, "direction": direction,
                                          "error": f"invalid perm_id {perm_id!r}"},
                                    headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                            except Exception:
                                pass
                            try:
                                diary.record_event(
                                    broker="ib",
                                    strategy_id=diary_strategy_id,
                                    ticker=ticker,
                                    state=diary.State.CANCELLED,
                                    reason=f"invalid perm_id {perm_id!r}",
                                    client_intent_id=diary_intent_id,
                                    expected_qty=0,
                                )
                            except Exception as _de:
                                logger.warning("diary CANCELLED write failed: %s", _de)
                            continue

                        # Read THIS order's fill price by order ID — not the
                        # last entry from client.get_trades(), which can be
                        # an options spread fill from a different contract.
                        # Same bug class fixed for SL placement in fa0e9e3.
                        entry_fill_price = 0
                        try:
                            fill_info = client.get_order_fill(perm_id)
                            entry_fill_price = float(fill_info.get("avg_price") or 0)
                        except Exception:
                            pass

                        # Guard #2: if we still couldn't get a fill price after
                        # the entry order was supposedly placed, the order may
                        # have been rejected silently. Don't create strat_pos
                        # in that case either.
                        if not entry_fill_price:
                            logger.error(
                                "Order %s [%s/%s/%s] has no fill price after place — "
                                "refusing to create strat_pos",
                                perm_id, direction, ticker, strategy_name
                            )
                            try:
                                from .supabase_client import send_telegram_message
                                send_telegram_message(
                                    f"⚠️ *Order placed but never filled* — {direction} {ticker} "
                                    f"[{strategy_name}] order {perm_id}. No position opened."
                                )
                            except Exception:
                                pass
                            try:
                                diary.record_event(
                                    broker="ib",
                                    broker_trade_id=str(perm_id),
                                    client_intent_id=diary_intent_id,
                                    strategy_id=diary_strategy_id,
                                    ticker=ticker,
                                    state=diary.State.CANCELLED,
                                    reason="placed but never filled",
                                    expected_qty=0,
                                )
                            except Exception as _de:
                                logger.warning("diary CANCELLED (no fill) write failed: %s", _de)
                            continue

                        # Per-strategy position state — lets independent
                        # strategies (e.g. 2n20 + ORB) coexist on the same
                        # contract; each closes only its own leg. Stop info
                        # included so check_stop_fills() can detect when
                        # this strategy's SL hits and book the close.
                        # Persist the entry_coid in strat_pos metadata so the
                        # close handler (Phase 2) can submit the close in the
                        # same OCA group and IB cancels the SL atomically.
                        strat_meta = dict(pine_meta or {})
                        strat_meta["entry_coid"] = entry_coid
                        if reverse_qty > 0:
                            strat_meta["reversed_from_qty"] = reverse_qty
                        save_strat_pos(ticker, strategy_name, direction,
                                       contracts, entry_fill_price, perm_id,
                                       stop_order_id=sl_order_id,
                                       stop_price=sl_price,
                                       target_order_id=tp_order_id,
                                       target_price=tp_price,
                                       multiplier=multiplier,
                                       metadata=strat_meta,
                                       caller=f"entry_fill:{strategy_name}")

                        # If this was a close-and-reverse, the PRIOR strat_pos's
                        # bracket SL/TP children are now obsolete (they were
                        # sized to protect the OLD direction). Cancel them so
                        # they don't linger and accidentally fire later. The
                        # new bracket's children (sl_order_id / tp_order_id)
                        # are correctly sized for the new position.
                        if reverse_qty > 0:
                            for oid, label in ((prior_sl_id, "SL"), (prior_tp_id, "TP")):
                                if oid and oid != "0" and oid != sl_order_id and oid != tp_order_id:
                                    try:
                                        client.cancel_order(oid)
                                        logger.info(
                                            "Cancelled obsolete %s %s from reversed position",
                                            label, oid,
                                        )
                                    except Exception as _ce:
                                        logger.debug("obsolete %s cancel failed: %s", label, _ce)

                            # Also write CLOSED for the prior diary lineage
                            # so it doesn't stay live forever. Without this,
                            # the diary accumulates stale OPEN rows after
                            # each reverse, and the same-direction-duplicate
                            # guard would block future same-direction signals
                            # indefinitely.
                            if reverse_via == "diary" and diary_live:
                                prior_btid = diary_live.get("broker_trade_id")
                                if prior_btid:
                                    try:
                                        diary.record_event(
                                            broker="ib",
                                            broker_trade_id=str(prior_btid),
                                            strategy_id=diary_strategy_id,
                                            ticker=ticker,
                                            state=diary.State.CLOSED,
                                            reason=f"closed by close-and-reverse "
                                                   f"(replaced by {perm_id})",
                                            expected_qty=0,
                                            exit_price=entry_fill_price,
                                            meta={
                                                "replaced_by_broker_trade_id": str(perm_id),
                                                "reversed_to": direction,
                                            },
                                        )
                                        logger.info(
                                            "Diary: CLOSED prior trade %s "
                                            "(replaced by %s in close-and-reverse)",
                                            prior_btid, perm_id,
                                        )
                                    except Exception as _de:
                                        logger.warning("diary close-prior write failed: %s", _de)

                        # Diary: OPEN — bind broker_trade_id to the intent so
                        # the trigger retires the orphan INTENT_OPEN row.
                        try:
                            diary.record_event(
                                broker="ib",
                                broker_trade_id=str(perm_id),
                                client_intent_id=diary_intent_id,
                                strategy_id=diary_strategy_id,
                                ticker=ticker,
                                state=diary.State.OPEN,
                                reason=f"IB fill {direction}",
                                expected_qty=(contracts if direction == "BUY"
                                              else -contracts),
                                entry_price=entry_fill_price,
                                stop_price=sl_price,
                                target_price=(tp_price if tp_price > 0 else None),
                                meta={
                                    "stop_order_id": sl_order_id or None,
                                    "target_order_id": tp_order_id or None,
                                    "multiplier": multiplier,
                                    "entry_coid": entry_coid,
                                },
                            )
                        except Exception as _de:
                            logger.warning("diary OPEN write failed: %s", _de)

                        # Push + Telegram notification with the full plan
                        # (entry/target/stop/risk/reward) when Pine supplied it.
                        try:
                            from .supabase_client import notify_trade_opened
                            supabase_uid = os.environ.get("SUPABASE_USER_ID", "")
                            if supabase_uid and entry_fill_price:
                                # Compute risk/reward in dollars when stop+target known
                                risk_d = None
                                reward_d = None
                                rr = None
                                if sl_price and entry_fill_price:
                                    risk_d = abs(entry_fill_price - sl_price) * multiplier * contracts
                                if tp_price and entry_fill_price:
                                    reward_d = abs(tp_price - entry_fill_price) * multiplier * contracts
                                if risk_d and reward_d:
                                    rr = round(reward_d / risk_d, 2)
                                # Strategy string for the alert — Telegram's Markdown
                                # parser breaks on bare underscores (e.g. ORB_BREAKOUT
                                # gets read as italic-start with no close → 400), so
                                # we soften them to spaces here.
                                strat_label = f"{strategy_name.upper().replace('_', ' ')} {direction}"
                                notify_trade_opened(
                                    user_id=supabase_uid,
                                    instrument=ticker,
                                    direction=direction,
                                    entry_price=entry_fill_price,
                                    strategy=strat_label,
                                    stop=sl_price or None,
                                    target=tp_price or None,
                                    risk_dollars=risk_d,
                                    reward_dollars=reward_d,
                                    rr_ratio=rr,
                                )
                        except Exception as e:
                            logger.debug("notify_trade_opened failed: %s", e)
                        try:
                            requests.post(f"{SERVER_URL}/api/ibkr/order/update",
                                json={
                                    "order_id": f"futures_entry_{perm_id}",
                                    "ticker": ticker,
                                    "direction": direction,
                                    "perm_id": perm_id,
                                    "opened_at": now_iso,
                                    "strategy": strategy_name,
                                    "status": "entry",
                                    "type": "futures",
                                    "entry_price": entry_fill_price,
                                },
                                headers={"X-Sync-Key": SYNC_KEY}, timeout=5)
                        except Exception:
                            pass
                    elif direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                        # This strategy's leg is done — release the strat_pos
                        # so the next entry signal can fire.
                        clear_strat_pos(ticker, strategy_name, reason=f"webhook {direction}")

                except Exception as e:
                    result = {
                        "order_id": order_id,
                        "status": "failed",
                        "ticker": ticker,
                        "error": str(e),
                    }
                    logger.error("Futures order failed: %s — %s", ticker, e)

                try:
                    requests.post(f"{SERVER_URL}/api/ibkr/order/update", json=result,
                                  headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                except Exception:
                    pass
                continue

            # ─── MANUAL OPTIONS CLOSE (from mobile) ───
            if order.get("type") == "options_close":
                ticker = order.get("ticker", "")
                logger.info("Manual options close: %s %s %s / %s exp %s x%d",
                            ticker, order.get("right", ""),
                            order.get("sell_strike", 0), order.get("buy_strike", 0),
                            order.get("expiration", ""), int(order.get("contracts", 1)))
                spread = {
                    "symbol": ticker,
                    "expiration": order.get("expiration", ""),
                    "right": order.get("right", ""),
                    "long_strike": float(order.get("buy_strike", 0)),
                    "short_strike": float(order.get("sell_strike", 0)),
                    "quantity": int(order.get("contracts", 1)),
                    "spread_type": order.get("spread_type", ""),
                    "strategy": order.get("strategy", "manual_close"),
                }
                try:
                    _close_spread(client, spread, "Manual close (mobile)")
                    status_result = {"order_id": order["order_id"], "status": "closed",
                                      "ticker": ticker, "type": "options_close"}
                except Exception as e:
                    logger.error("Manual options close failed for %s: %s", ticker, e)
                    status_result = {"order_id": order["order_id"], "status": "failed",
                                      "ticker": ticker, "error": str(e),
                                      "type": "options_close"}
                try:
                    requests.post(f"{SERVER_URL}/api/ibkr/order/update", json=status_result,
                                  headers={"X-Sync-Key": SYNC_KEY}, timeout=10)
                except Exception:
                    pass
                continue

            # ─── OPTIONS ORDERS ───
            spread_type = order.get("spread_type", "")
            buy_strike = float(order.get("buy_strike", 0))
            sell_strike = float(order.get("sell_strike", 0))
            right = order.get("right", "")
            expiration = order.get("expiration", "")
            quantity = int(order.get("quantity", 1))
            limit_price = float(order["limit_price"])

            is_credit = "Credit" in spread_type
            logger.info("Placing %s order: %s SELL %s / BUY %s %s exp %s x%d @ $%.2f (%s)",
                        spread_type, ticker, sell_strike, buy_strike, right, expiration, quantity, limit_price,
                        "credit" if is_credit else "debit")

            try:
                # Resolve option contract conIds via CPAPI
                buy_conid = client.search_option_contract(ticker, expiration, buy_strike, right)
                sell_conid = client.search_option_contract(ticker, expiration, sell_strike, right)

                if not buy_conid or not sell_conid:
                    raise ValueError(f"Could not find option contracts: buy={buy_strike} sell={sell_strike}")

                # Build and place combo order
                spread_payload = client.build_spread_order(
                    sell_conid, buy_conid, quantity, limit_price, is_credit, tif="GTC"
                )
                trade_result = client.place_order(spread_payload)
                time.sleep(3)

                # Extract order ID from CPAPI response
                perm_id = ""
                if isinstance(trade_result, list) and trade_result:
                    first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                    perm_id = str(first.get("order_id", ""))
                elif isinstance(trade_result, dict):
                    perm_id = str(trade_result.get("order_id", ""))

                result = {
                    "order_id": order_id,
                    "ib_order_id": trade.order.orderId,
                    "perm_id": perm_id,
                    "status": trade.orderStatus.status,
                    "ticker": ticker,
                    "spread_type": spread_type,
                    "sell_strike": sell_strike,
                    "buy_strike": buy_strike,
                    "right": right,
                    "expiration": expiration,
                    "quantity": quantity,
                    "limit_price": limit_price,
                    "is_credit": is_credit,
                    "message": f"Order placed: {trade.orderStatus.status}",
                    # Pass through signal metadata
                    "model": order.get("model", ""),
                    "strategy": order.get("strategy", ""),
                    "zone_type": order.get("zone_type", ""),
                    "zone_price": order.get("zone_price", 0),
                    "trigger_pattern": order.get("trigger_pattern", ""),
                    "bias_score": order.get("bias_score", 0),
                    "zone_timeframe": order.get("zone_timeframe", ""),
                    "verdict": order.get("verdict", ""),
                    "width": order.get("width", 0),
                    "max_risk": order.get("max_risk", 0),
                    "max_profit": order.get("max_profit", 0),
                    "risk_reward": order.get("risk_reward", 0),
                }
                # Update order status on server
                try:
                    requests.post(
                        f"{SERVER_URL}/api/ibkr/order/update",
                        json=result,
                        headers={"X-Sync-Key": SYNC_KEY},
                        timeout=10,
                    )
                except Exception:
                    pass
                logger.info("Order placed: %s — %s", ticker, trade.orderStatus.status)

            except Exception as e:
                result = {
                    "order_id": order_id,
                    "status": "failed",
                    "ticker": ticker,
                    "error": str(e),
                    "message": f"Order failed: {e}",
                }
                logger.error("Order failed for %s: %s", ticker, e)

            # Update order status on server
            try:
                requests.post(
                    f"{SERVER_URL}/api/ibkr/order/update",
                    json=result,
                    headers={"X-Sync-Key": SYNC_KEY},
                    timeout=10,
                )
            except Exception:
                pass

    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        logger.error("Order check error: %s", e)
        import traceback
        traceback.print_exc()


def push_to_server(data: dict):
    """Push IB data to the LumiSignals server."""
    try:
        resp = requests.post(
            f"{SERVER_URL}/api/ibkr/sync",
            json=data,
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.debug("Synced to server")
        else:
            logger.warning("Server returned %s: %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("Failed to push to server: %s", e)


def monitor_spreads(client, spreads: list):
    """Monitor open spreads and auto-close when TP/SL/time stop is hit."""
    if not spreads:
        return

    # Fetch exit rules from server
    try:
        resp = requests.get(
            f"{SERVER_URL}/api/ibkr/exit-rules",
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=5,
        )
        if resp.status_code != 200:
            return
        rules = resp.json()
    except Exception:
        return

    default_credit_tp = rules.get("credit_tp_pct", 50)
    default_credit_sl = rules.get("credit_sl_pct", 100)
    default_debit_tp = rules.get("debit_tp_pct", 75)
    default_debit_sl = rules.get("debit_sl_pct", 50)
    time_stop_dte = rules.get("time_stop_dte", 7)

    from datetime import datetime, timezone

    for spread in spreads:
        symbol = spread["symbol"]
        spread_type = spread.get("spread_type", "")
        is_credit = "Credit" in spread_type
        net_cost = abs(spread.get("net_cost", 0))
        pnl = spread.get("unrealized_pnl", 0)
        expiration = spread.get("expiration", "")
        quantity = spread.get("quantity", 0)

        # Per-spread TP/SL overrides (from 0DTE webhook orders)
        spread_tp = spread.get("tp_pct")
        spread_sl = spread.get("sl_pct")
        spread_time_stop_min = spread.get("time_stop_min", 0)

        if not net_cost or not expiration or not quantity:
            continue

        # Calculate DTE
        try:
            exp_date = datetime.strptime(expiration, "%Y%m%d").date()
            dte = (exp_date - datetime.now().date()).days
        except Exception:
            dte = 999

        close_reason = None
        close_price = None  # limit price for closing order

        if is_credit:
            credit_received = net_cost
            tp_pct = spread_tp if spread_tp else default_credit_tp
            sl_pct = spread_sl if spread_sl else default_credit_sl

            if pnl > 0 and pnl >= credit_received * (tp_pct / 100):
                close_reason = f"TAKE PROFIT — captured {tp_pct}% of credit (P&L: ${pnl:+.2f})"
            elif pnl < 0 and abs(pnl) >= credit_received * (sl_pct / 100):
                close_reason = f"STOP LOSS — loss exceeded {sl_pct}% of credit (P&L: ${pnl:+.2f})"
        else:
            debit_paid = net_cost
            tp_pct = spread_tp if spread_tp else default_debit_tp
            sl_pct = spread_sl if spread_sl else default_debit_sl

            if pnl > 0 and pnl >= debit_paid * (tp_pct / 100):
                close_reason = f"TAKE PROFIT — {tp_pct}% gain (P&L: ${pnl:+.2f})"
            elif pnl < 0 and abs(pnl) >= debit_paid * (sl_pct / 100):
                close_reason = f"STOP LOSS — {sl_pct}% loss (P&L: ${pnl:+.2f})"

        # Minute-based time stop (for 0DTE scalps)
        if not close_reason and spread_time_stop_min > 0:
            opened_at = spread.get("opened_at", "")
            if opened_at:
                try:
                    opened_str = opened_at.replace("Z", "+00:00")
                    if "T" not in opened_str and " " in opened_str:
                        opened_str = opened_str.replace(" ", "T", 1)
                    opened_dt = datetime.fromisoformat(opened_str)
                    minutes_held = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 60
                    if minutes_held >= spread_time_stop_min:
                        close_reason = f"TIME STOP — held {int(minutes_held)} min (limit: {spread_time_stop_min} min)"
                except Exception:
                    pass

        # DTE-based time stop (for swing trades)
        if not close_reason and dte <= time_stop_dte:
            close_reason = f"TIME STOP — {dte} DTE remaining (limit: {time_stop_dte})"

        if close_reason:
            # Dedup: after we fire a close order, the spread may still show
            # open in IB for several seconds (broker propagation + fill
            # latency). Without this guard, every sync tick during that
            # window re-runs _close_spread, sending a new close order AND a
            # new Telegram/push notification. At SYNC_INTERVAL=2s a single
            # close was generating 5+ duplicate notifications.
            dedup_rdb = _rdb()
            close_key = (
                f"ibkr:spread_closing:{symbol}:{expiration}:"
                f"{spread.get('long_strike',0)}:{spread.get('short_strike',0)}:"
                f"{spread.get('right','')}"
            )
            if dedup_rdb is not None:
                try:
                    if dedup_rdb.get(close_key):
                        # Close already in flight — skip this tick.
                        continue
                    # 90s lock: long enough for fill + position propagation,
                    # short enough to recover if the close failed silently.
                    dedup_rdb.setex(close_key, 90, "1")
                except Exception:
                    pass
            logger.info("CLOSING %s %s: %s", symbol, spread_type, close_reason)
            try:
                _close_spread(client, spread, close_reason)
            except Exception as e:
                logger.error("Failed to close %s spread: %s", symbol, e)
                # Clear the lock so the next tick can retry
                if dedup_rdb is not None:
                    try:
                        dedup_rdb.delete(close_key)
                    except Exception:
                        pass


def _close_spread(client, spread: dict, reason: str):
    """Close an open spread by placing an opposite market order."""
    symbol = spread["symbol"]
    expiration = spread.get("expiration", "")
    right = spread.get("right", "")
    long_strike = spread.get("long_strike", 0)
    short_strike = spread.get("short_strike", 0)
    quantity = int(spread.get("quantity", 0))

    if not all([symbol, expiration, right, long_strike, short_strike, quantity]):
        logger.error("Missing data to close spread: %s", spread)
        return

    # Resolve conIds for the legs
    long_conid = client.search_option_contract(symbol, expiration, long_strike, right)
    short_conid = client.search_option_contract(symbol, expiration, short_strike, right)

    if not long_conid or not short_conid:
        logger.error("Could not resolve conIds for spread close: %s %s/%s", symbol, long_strike, short_strike)
        return

    # Build and place closing order (reverse legs)
    close_payload = client.build_close_spread_order(long_conid, short_conid, quantity)
    trade_result = client.place_order(close_payload)
    time.sleep(3)

    status = "Submitted"
    if isinstance(trade_result, list) and trade_result:
        status = trade_result[0].get("order_status", "Submitted") if isinstance(trade_result[0], dict) else "Submitted"
    logger.info("Close order for %s: status=%s reason=%s", symbol, status, reason)

    # Send alert
    try:
        from lumisignals.alerts import send_alert, AlertType
        alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
        if alert_pass:
            send_alert(
                AlertType.TRADE_CLOSED,
                f"{symbol} spread closed — {reason}",
                f"Auto-closed {spread.get('spread_type', '')} on {symbol}",
                details={
                    "Symbol": symbol,
                    "Spread": spread.get("spread_type", ""),
                    "P&L": f"${spread.get('unrealized_pnl', 0):+.2f}",
                    "Reason": reason,
                },
                smtp_pass=alert_pass,
            )
    except Exception:
        pass

    # Record closed trade on server
    try:
        from datetime import datetime, timezone
        closed_trade = {
            "perm_id": spread.get("perm_id", ""),
            "order_id": spread.get("order_id", ""),
            "symbol": symbol,
            "spread_type": spread.get("spread_type", ""),
            "long_strike": spread.get("long_strike", 0),
            "short_strike": spread.get("short_strike", 0),
            "right": spread.get("right", ""),
            "expiration": expiration,
            "quantity": quantity,
            "width": spread.get("width", 0),
            "entry_cost": spread.get("net_cost", 0),
            "realized_pnl": spread.get("unrealized_pnl", 0),
            "max_profit": spread.get("max_profit", 0),
            "max_risk": spread.get("max_risk", 0),
            "close_reason": reason,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "model": spread.get("model", ""),
            "strategy": spread.get("strategy", ""),
            "trigger_pattern": spread.get("trigger_pattern", ""),
            "bias_score": spread.get("bias_score", 0),
            "zone_type": spread.get("zone_type", ""),
            "zone_timeframe": spread.get("zone_timeframe", ""),
            "opened_at": spread.get("opened_at", ""),
        }
        requests.post(
            f"{SERVER_URL}/api/ibkr/closed-trade",
            json=closed_trade,
            headers={"X-Sync-Key": SYNC_KEY},
            timeout=10,
        )
    except Exception:
        pass


# ─── Weekend safety net ──────────────────────────────────────────────────
# Futures (MES, NQ, ES, …) should not carry across a CME weekend close.
# The 2n20 strategy has its own end-of-week flatten, but the TV-webhook
# path doesn't — and on 2026-05-15 we ended up with a stuck MES short
# overnight Saturday because Pine sent a fresh SELL minutes after the
# strategy's own flatten ran. This is the independent safety net:
#   - At 16:55–17:00 ET Friday, flatten every open futures position with a
#     market order opposite to current side.
#   - Set a Redis lockout flag (ibkr:weekend_lockout) so check_order_requests
#     refuses any new futures entries between Friday close and Sunday open.
# Idempotent: once the flatten has been recorded for a given Friday, the
# function is a no-op until the next Friday window opens.

_ET_TZ = None

def _et_now():
    """Current datetime in US/Eastern. Cache zoneinfo lookup."""
    from datetime import datetime as _dt
    global _ET_TZ
    if _ET_TZ is None:
        try:
            from zoneinfo import ZoneInfo
            _ET_TZ = ZoneInfo("America/New_York")
        except Exception:
            # Fallback: rough UTC-4 (won't be correct around DST switches
            # but the only behavior gated on this is a 5-min window, so
            # an offset miss just means we run a few minutes early/late).
            from datetime import timezone as _tz, timedelta as _td
            _ET_TZ = _tz(_td(hours=-4))
    return _dt.now(_ET_TZ)


def weekend_flatten_futures(client):
    """Friday 16:55 ET safety net: flatten all open futures positions.

    Runs every sync tick; the time/lockout checks keep it a no-op outside
    the window. Sets ibkr:weekend_lockout (TTL through Sunday 17:55 ET)
    so check_order_requests can refuse any TV-fired futures entries until
    the next regular session.
    """
    try:
        now_et = _et_now()
        # Friday = weekday 4. Window: 16:55-17:00 ET (CME futures close 17:00).
        is_friday = now_et.weekday() == 4
        in_window = (
            now_et.hour == 16 and now_et.minute >= 55
        ) or (
            now_et.hour == 17 and now_et.minute == 0
        )
        if not (is_friday and in_window):
            return

        rdb = _rdb()
        if rdb is None:
            return

        # Set lockout flag for the whole weekend. CME reopens Sunday 18:00
        # ET; we lift the flag at Sunday 17:55 so the bot is ready when
        # quotes return. TTL in seconds from Friday 16:55 ET → Sunday 17:55 ET.
        # Set every tick in case earlier set was missed; SET overrides TTL.
        rdb.setex("ibkr:weekend_lockout", 49 * 3600, "1")  # 49h: covers Fri 17:00 → Sun 18:00

        # Idempotent: skip if we already flattened this Friday.
        date_key = now_et.strftime("%Y-%m-%d")
        done_key = f"ibkr:weekend_flatten:done:{date_key}"
        if rdb.get(done_key):
            return

        positions = client.get_positions() or []
        fut_positions = [p for p in positions
                         if p.get("sec_type") == "FUT" and int(p.get("quantity", 0)) != 0]

        if not fut_positions:
            # Nothing to do, but still mark done so we don't re-check.
            rdb.setex(done_key, 24 * 3600, "1")
            return

        from .ibkr_cpapi import CPAPIClient
        flattened = []
        errors = []

        # First pass: for each tracked strat_pos with a known stop_order_id,
        # modify the stop into a MKT — atomic close per leg. The SL's
        # identity is preserved; it transforms into the exit. This
        # eliminates the pre-2026-05-23 bug where MKT closes left dormant
        # protective stops alive over the weekend, which could fire as
        # unintended entries on Sunday open if price gapped through them.
        try:
            sp_keys = list(rdb.scan_iter("ibkr:strat_pos:*"))
        except Exception:
            sp_keys = []
        per_ticker_closed_qty: dict = {}
        for k in sp_keys:
            try:
                sp_raw = rdb.get(k)
                if not sp_raw:
                    continue
                sp = json.loads(sp_raw)
                sym = sp.get("ticker") or ""
                qty = int(sp.get("contracts") or 0)
                direction = sp.get("direction") or ""
                stop_id = str(sp.get("stop_order_id") or "")
                target_id = str(sp.get("target_order_id") or "")
                # Look up the conid from positions (strat_pos doesn't store it).
                conid = 0
                for p in fut_positions:
                    if p.get("symbol") == sym:
                        try:
                            conid = int(p.get("con_id", 0) or 0)
                        except (TypeError, ValueError):
                            conid = 0
                        break
                if qty == 0 or not sym or conid == 0 or not direction:
                    continue
                close_side = "SELL" if direction == "BUY" else "BUY"
                if not stop_id:
                    # No tracked stop — fall through to second pass.
                    continue
                try:
                    resp = client.modify_order(
                        stop_id, conid=conid, side=close_side,
                        quantity=qty, order_type="MKT", tif="DAY",
                    )
                    logger.info(
                        "WEEKEND FLATTEN (atomic): STP %s -> MKT close %s %s ×%d resp=%s",
                        stop_id, close_side, sym, qty, resp,
                    )
                    flattened.append(f"atomic {close_side} {sym} ×{qty}")
                    # Track the NET CHANGE to IB position caused by the
                    # close, not the leg size. Closing a long (direction=
                    # "BUY") via SELL reduces position by qty → -qty.
                    # Closing a short via BUY increases by qty → +qty.
                    # Original code had the sign inverted, causing the
                    # residual pass to over-sell (observed 2026-05-26
                    # when starting +3 → oversold to -2). Fix is critical
                    # before next Friday's auto-flatten.
                    per_ticker_closed_qty[sym] = (
                        per_ticker_closed_qty.get(sym, 0)
                        + (-qty if direction == "BUY" else qty)
                    )
                    # Cancel any TP child explicitly — modify only handles the SL.
                    if target_id and target_id != "0":
                        try:
                            client.cancel_order(target_id)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(
                        "WEEKEND FLATTEN atomic-modify failed for %s/%s SL=%s: %s — "
                        "falling back to cancel+MKT close",
                        sym, sp.get("strategy", "?"), stop_id, e,
                    )
                    # Fall back: cancel the stop, then we'll MKT-close in the
                    # untracked-residual pass below.
                    try:
                        client.cancel_order(stop_id)
                    except Exception:
                        pass
                # Drop the strat_pos record either way — Sunday starts clean.
                rdb.delete(k)
            except Exception as e:
                logger.warning("WEEKEND FLATTEN strat_pos %s error: %s", k, e)

        # Second pass: any untracked residual (IB qty that wasn't covered
        # by the atomic-modify pass) — close with MKT and cancel any
        # leftover stops on the contract.
        for pos in fut_positions:
            try:
                qty = int(pos.get("quantity", 0))
                conid = int(pos.get("con_id", 0))
                sym = pos.get("symbol", "?")
                if qty == 0 or conid == 0:
                    continue
                # Subtract what the atomic pass already closed from the IB qty.
                # net residual = IB qty + atomic-pass delta (atomic delta is
                # signed in the opposite direction of the original position).
                residual = qty + per_ticker_closed_qty.get(sym, 0)
                if residual == 0:
                    continue
                side = "SELL" if residual > 0 else "BUY"

                # Cancel any leftover open stops on this contract first.
                try:
                    open_orders_now = client.get_open_orders() or []
                    for o in open_orders_now:
                        if (o.get("ticker") == sym
                                and o.get("orderType") in ("Stop", "STP", "STOP_LIMIT")
                                and o.get("status") not in ("Filled", "Cancelled")):
                            try:
                                client.cancel_order(str(o.get("orderId")))
                                logger.info("WEEKEND FLATTEN: cancelled leftover STP %s on %s",
                                            o.get("orderId"), sym)
                            except Exception:
                                pass
                except Exception:
                    pass

                payload = CPAPIClient.build_futures_order(
                    conid=conid, action=side, quantity=abs(residual),
                    order_type="MKT", tif="DAY",
                )
                resp = client.place_order(payload)
                logger.info("WEEKEND FLATTEN (residual): %s %s %d → %s",
                            side, sym, abs(residual), resp)
                flattened.append(f"residual {side} {sym} ×{abs(residual)}")
                # Final safety: drop any remaining strat_pos for this ticker.
                try:
                    for k in rdb.scan_iter(match=f"ibkr:strat_pos:{sym}:*"):
                        rdb.delete(k)
                except Exception:
                    pass
            except Exception as e:
                logger.error("WEEKEND FLATTEN residual failed for %s: %s",
                             pos.get("symbol", "?"), e)
                errors.append(f"{pos.get('symbol','?')}: {e}")

        rdb.setex(done_key, 24 * 3600, "1")
        try:
            _send_telegram_alert(
                "🌅 Weekend flatten",
                "Flattened: " + (", ".join(flattened) or "(none)") +
                (f"\nErrors: {'; '.join(errors)}" if errors else ""),
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("weekend_flatten_futures error: %s", e)


def main():
    logger.info("IB CPAPI Sync starting — connecting to %s", CPAPI_URL)

    # Restart-safety gate: mark RECONCILING immediately so the saas webhook
    # handler refuses new entries until we've completed at least one full
    # sync+reconcile pass. Flips to OK at the end of the first error-free
    # loop iteration; held to refresh the heartbeat on every iteration after.
    try:
        from .reconcile_gate import mark_reconciling
        mark_reconciling()
    except Exception as _e:
        logger.warning("reconcile_gate mark_reconciling failed: %s", _e)

    from .ibkr_cpapi import CPAPIClient
    client = CPAPIClient(base_url=CPAPI_URL)

    try:
        client.ensure_session()
    except ConnectionError as e:
        logger.error("Failed to connect to CPAPI gateway: %s", e)
        logger.error("Make sure the CPAPI Docker container is running and authenticated")
        sys.exit(1)

    logger.info("Connected to CPAPI — syncing every %ds to %s", SYNC_INTERVAL, SERVER_URL)

    # Detect paper vs live from the IB account id and persist to Redis so
    # the saas service / diary writes can tag every new row. Paper account
    # ids start with "DU"; everything else is live.
    try:
        from .account_type import detect_from_account_id, set_account_type
        acct_type = detect_from_account_id(client.account_id or "")
        set_account_type(acct_type)
        logger.info("IB account_type=%s (account_id=%s)", acct_type, client.account_id)
    except Exception as _e:
        logger.warning("account_type detection failed: %s", _e)

    # Crash-loop alerting: fire one Telegram after N consecutive exceptions
    # so the next "could not convert string to float" doesn't go silent for
    # 22 hours. Rate-limit to one alert per error-streak (cleared on first
    # successful tick).
    consecutive_errors = 0
    alerted_for_streak = False
    first_pass_complete = False
    global _last_missed_signal_check

    while True:
        try:
            # Keep session alive
            try:
                client.ensure_session()
            except ConnectionError:
                logger.error("CPAPI session expired — waiting for re-auth...")
                # Send alert
                try:
                    from lumisignals.alerts import send_alert, AlertType
                    alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                    if alert_pass:
                        send_alert(AlertType.SYSTEM_ERROR, "CPAPI Session Expired",
                                   "Manual browser login required. SSH tunnel and open https://localhost:5000",
                                   smtp_pass=alert_pass)
                except Exception:
                    pass
                # Telegram alert too — email lag has hidden expiries for hours.
                # _send_telegram_alert rate-limits per title (10 min), so we
                # won't spam even though this branch hits every loop until reauth.
                try:
                    _send_telegram_alert(
                        "🔐 IBeam session expired",
                        "Bot cannot place orders. Open bot.lumitrade.ai/ib-auth "
                        "and click Re-authenticate.",
                    )
                except Exception:
                    pass
                time.sleep(60)
                continue

            data = collect_ib_data(client)

            acct = data["account"]
            n_pos = len(data["positions"])
            n_spreads = len(data["spreads"])
            n_orders = len(data["open_orders"])
            logger.info(
                "NAV: $%s | Positions: %d | Spreads: %d | Open orders: %d",
                f"{acct.get('NetLiquidation', 0):,.2f}", n_pos, n_spreads, n_orders,
            )

            push_to_server(data)

            # Refresh open IB positions in Supabase so the mobile app sees
            # live mark price and unrealized P&L (web app reads Redis; mobile
            # reads Supabase directly, so the rows would otherwise stay frozen
            # at order-placement-time values).
            sync_positions_to_supabase(data.get("positions", []))
            sync_oanda_positions_to_supabase()

            # Diary reconciler: compare what the trade-event diary thinks
            # is live against what IB actually shows. Detection only in v1
            # — flags RECONCILE_GONE / RECONCILE_PHANTOM events and Telegram
            # alerts; never closes positions or alters state.
            #
            # Position truth comes from /iserver/account/trades (fills),
            # which lags real fills by ~1-2s — fast enough to catch scalp
            # stops that hold positions for only 30s. /portfolio/positions
            # (which lagged 4.5min on 2026-05-22) is no longer used here.
            #
            # Safe to call every tick — self-throttles to MIN_INTERVAL.
            try:
                # Fast tier (every ~5s): fills-based net positions + order
                # status. Catches scalp closes within seconds, INTENT_OPEN
                # confirmations, and per-trade lifecycle transitions.
                fill_details = reconciler.net_positions_from_fills(client)
                ib_qty = {s: d["qty"] for s, d in fill_details.items() if d["qty"] != 0}
                # Multipliers used to compute realized_pl on RECONCILE_GONE.
                # Hardcoded for now; future step is to read from
                # symbol_metadata table (cached in Redis).
                mults = {"MES": 5, "MNQ": 2, "MGC": 10, "MCL": 100}
                ord_snap = reconciler.orders_by_id(client)
                reconciler.run_pass("ib", ib_qty,
                                    fill_details=fill_details,
                                    multiplier_by_ticker=mults,
                                    order_status_by_id=ord_snap)
                # Slow tier (every ~60s): /portfolio/positions sanity
                # backstop. Catches positions the fills stream wouldn't
                # see (manual IB GUI entries, holdings >7d). Self-throttles.
                reconciler.slow_tier_pass("ib", data.get("positions", []))
            except Exception as e:
                logger.debug("reconciler pass failed: %s", e)

            # Friday 16:55 ET safety net: flatten all open futures so no
            # position carries through the weekend. Sets the weekend lockout
            # flag that check_order_requests reads to refuse new entries.
            weekend_flatten_futures(client)

            # Watch for stop-loss fills. When a strategy's SL fires, its
            # tracked stop_order_id disappears from open orders — clear the
            # strat_pos and record the closed trade so we don't wait for
            # the next signal to reconcile drift.
            check_stop_fills(client)

            # Drive any active SPX 0DTE leg-in butterflies one tick forward.
            # Each butterfly's state lives in ibkr:butterfly:* in Redis;
            # the handler advances phases (QUEUED -> DEBIT_OPEN -> WATCHING
            # -> CREDIT_OPEN -> COMPLETE / SALVAGE / ABANDONED).
            try:
                from .orb_butterfly_handler import process_butterflies
                def _spx_price():
                    try:
                        import urllib.request as _ur, urllib.parse as _up, json as _j
                        key = os.environ.get("MASSIVE_API_KEY", "")
                        if not key:
                            return None
                        url = f"https://api.polygon.io/v3/snapshot/indices?ticker=I:SPX&apiKey={_up.quote(key)}"
                        with _ur.urlopen(url, timeout=5) as r:
                            d = _j.load(r)
                        for row in d.get("results", []):
                            v = row.get("value") or row.get("session", {}).get("close")
                            if v:
                                return float(v)
                    except Exception:
                        return None
                    return None
                process_butterflies(client, _rdb(), spx_price_fn=_spx_price)
            except Exception as e:
                logger.debug("butterfly processor error: %s", e)

            # Push 2-min MES bars to the server's Redis cache so the mobile
            # /chart page (and the 2n20 strategy bar reader) has data. Bars
            # close every 2 min; we publish at most once per minute.
            push_mes_bars_to_server(client)

            # Check for options analyze requests
            check_analyze_requests(client)

            # Check for pending orders to place
            check_order_requests(client)

            # Monitor open spreads for TP/SL/time stop — DISABLED.
            # The close path (build_close_spread_order) uses CPAPI combo
            # orders which fail silently: IB returns "Submitted" but never
            # executes. With monitor_spreads running, every sync tick re-
            # fired the close attempt, generating a notification each
            # time and accumulating zombie orders at IB (saw 54 stale
            # MES Markets + 4 SPX legs in one inventory). Re-enable only
            # after rewriting _close_spread to use two-leg singles like
            # orb_butterfly_handler does.
            # if data.get("spreads"):
            #     monitor_spreads(client, data["spreads"])

            # Tick completed without exception — reset the crash-loop counter
            consecutive_errors = 0
            alerted_for_streak = False

            # Restart-safety gate: first error-free loop flips state to OK,
            # which unlocks the saas webhook handler. Subsequent loops just
            # refresh the heartbeat so the gate knows we're still alive.
            try:
                from .reconcile_gate import mark_ok
                mark_ok()
                if not first_pass_complete:
                    first_pass_complete = True
                    logger.info("First sync+reconcile pass complete — webhooks unlocked")
            except Exception as _e:
                logger.debug("reconcile_gate mark_ok failed: %s", _e)

            # Missed-signal alerting (Tier 1 #3): every 5 min, run the 2n20
            # replay over the last 30 min and Telegram if Pine fired signals
            # we never received. Cheap when there's nothing to alert.
            now_secs = time.time()
            if now_secs - _last_missed_signal_check >= MISSED_SIGNAL_CHECK_INTERVAL:
                _last_missed_signal_check = now_secs
                try:
                    from .missed_signal_alert import check_and_alert
                    res = check_and_alert()
                    if res.get("new_alerts"):
                        logger.warning("missed-signal check: %s", res)
                except Exception as _e:
                    logger.debug("missed_signal_alert.check_and_alert failed: %s", _e)

        except Exception as e:
            logger.exception("Sync error: %s", e)  # include traceback — past silent failures wasted hours
            consecutive_errors += 1
            # Fire one Telegram after the 3rd consecutive error in the main
            # loop. Without this, breakage (today's "could not convert string
            # to float") can run for many hours before being noticed.
            if consecutive_errors >= 3 and not alerted_for_streak:
                try:
                    _send_telegram_alert(
                        "🚨 IBKR sync crash loop",
                        f"{consecutive_errors} consecutive sync errors.\n"
                        f"Latest: {type(e).__name__}: {e}",
                    )
                    alerted_for_streak = True
                except Exception:
                    pass

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
