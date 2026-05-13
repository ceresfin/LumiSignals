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
SYNC_INTERVAL = 10


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
    """If the sum of per-strategy contracts doesn't match IB's actual
    position, a stop loss almost certainly fired (IB closes the position
    silently and we get no callback). Clear all strat_pos for the ticker
    so the next signal in either strategy can enter cleanly.

    Conservative: only clears when there is a real discrepancy in absolute
    terms (tracked > actual). Never clears when tracked matches or is less.

    Every call is logged so we can audit decisions later (which call
    triggered the clear, what IB qty it saw vs tracked qty, whether the
    decision was correct in hindsight)."""
    rdb = _rdb()
    if rdb is None:
        return
    try:
        keys = list(rdb.scan_iter(f"ibkr:strat_pos:{ticker}:*"))
        if not keys:
            logger.info("RECONCILE %s: ib_qty=%+d tracked=none caller=%s decision=noop",
                        ticker, ib_qty, caller or "?")
            return
        tracked_net = 0
        strat_breakdown = []
        for k in keys:
            try:
                s = json.loads(rdb.get(k) or "{}")
                qty = int(s.get("contracts", 0))
                strat_name = s.get("strategy", "?")
                strat_dir = s.get("direction", "?")
                strat_breakdown.append(f"{strat_name}={strat_dir}{qty}")
                if strat_dir == "BUY":
                    tracked_net += qty
                elif strat_dir == "SELL":
                    tracked_net -= qty
            except Exception:
                pass
        if abs(tracked_net) > abs(ib_qty):
            # Race protection: when a BUY/SELL has just been placed, the
            # fill takes a few seconds to propagate to /portfolio/positions.
            # During that window tracked is +1 but IB still reports 0 — and
            # if we clear strat_pos here, the in-transit fill becomes an
            # orphan when it eventually lands. Hold off on CLEAR_ALL while
            # any tracked strat_pos is younger than 90s; the silent
            # stop-fill case can wait one more tick.
            now_utc = datetime.now(timezone.utc)
            youngest_age_s = None
            for k in keys:
                try:
                    s = json.loads(rdb.get(k) or "{}")
                    opened_at = s.get("opened_at")
                    if opened_at:
                        ts = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                        age_s = (now_utc - ts).total_seconds()
                        if youngest_age_s is None or age_s < youngest_age_s:
                            youngest_age_s = age_s
                except Exception:
                    pass
            if youngest_age_s is not None and youngest_age_s < 90:
                logger.info(
                    "RECONCILE %s: ib_qty=%+d tracked_net=%+d [%s] caller=%s "
                    "decision=DEFER (youngest strat_pos %.1fs old — fill likely in transit)",
                    ticker, ib_qty, tracked_net, ",".join(strat_breakdown),
                    caller or "?", youngest_age_s,
                )
                return
            logger.info(
                "RECONCILE %s: ib_qty=%+d tracked_net=%+d [%s] caller=%s decision=CLEAR_ALL (%d keys)",
                ticker, ib_qty, tracked_net, ",".join(strat_breakdown),
                caller or "?", len(keys),
            )
            for k in keys:
                rdb.delete(k)
        else:
            logger.info(
                "RECONCILE %s: ib_qty=%+d tracked_net=%+d [%s] caller=%s decision=keep",
                ticker, ib_qty, tracked_net, ",".join(strat_breakdown),
                caller or "?",
            )
    except Exception as e:
        logger.warning("strat_pos reconcile failed: %s", e)


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

    # Completed (filled) orders — recent trades from CPAPI
    filled_orders = []
    for fill in client.get_trades():
        entry = {
            "order_id": fill.get("order_ref", fill.get("execution_id", 0)),
            "symbol": fill.get("symbol", fill.get("ticker", "")),
            "sec_type": fill.get("sec_type", fill.get("secType", "STK")),
            "action": fill.get("side", ""),
            "quantity": float(fill.get("size", fill.get("shares", 0))),
            "price": float(fill.get("price", 0)),
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
                time.sleep(1)
                current_pos = 0
                for item in client.get_positions():
                    if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                        current_pos = int(item.get("quantity", 0))
                        break

                # Reconcile in case a stop loss closed one of the legs silently
                reconcile_strat_pos(ticker, current_pos, caller=f"order_proc:{direction}/{strategy_name}")

                sp = get_strat_pos(ticker, strategy_name)
                strat_long = sp.get("direction") == "BUY"
                strat_short = sp.get("direction") == "SELL"
                logger.info(
                    "Position check: %s ib_pos=%+d  [%s] strat=%s",
                    ticker, current_pos, strategy_name,
                    f"{sp.get('direction')} {sp.get('contracts',0)}" if sp else "flat",
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
                elif direction == "CLOSE_LONG" and not strat_long and not is_untracked_close:
                    logger.info("SKIP %s CLOSE_LONG [%s] — strategy not long",
                                ticker, strategy_name)
                    skip = True
                elif direction == "CLOSE_SHORT" and not strat_short and not is_untracked_close:
                    logger.info("SKIP %s CLOSE_SHORT [%s] — strategy not short",
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
                    # Fresh entry blocked by an opposing IB-side orphan.
                    # If we let this SELL through with IB already +1, the
                    # SELL closes the orphan instead of opening a short.
                    # We'd write strat_pos=SELL1 but IB ends FLAT — phantom.
                    # User must clear the orphan first (mobile Close button
                    # now works for pure orphans), then the next signal
                    # can fire cleanly.
                    logger.info(
                        "SKIP %s %s [%s] — IB has opposing orphan (qty=%+d). "
                        "Fresh entry would close the orphan rather than open a "
                        "new position; manual-flat the orphan first.",
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

                    if direction in ("CLOSE_LONG", "CLOSE_SHORT"):
                        # Per-strategy entry price — prefer strat_pos (the
                        # specific entry this strategy made), fall back to
                        # IB's aggregate avg_cost only if no strat_pos exists
                        # (orphan/untracked, e.g. manually opened).
                        sp_strat = get_strat_pos(ticker, strategy_name)
                        entry_price = 0
                        entry_qty = 0
                        if sp_strat:
                            entry_price = float(sp_strat.get("entry_price") or 0)
                            entry_qty = int(sp_strat.get("contracts") or 0)
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
                        # in strat_pos when the position was opened).
                        sp_for_close = get_strat_pos(ticker, strategy_name)
                        targeted_stop = sp_for_close.get("stop_order_id") if sp_for_close else ""
                        targeted_target = sp_for_close.get("target_order_id") if sp_for_close else ""
                        if targeted_stop:
                            try:
                                client.cancel_order(targeted_stop)
                                cancelled_stops = 1
                                logger.info("Cancelled SL %s for [%s] before close",
                                            targeted_stop, strategy_name)
                            except Exception as e:
                                logger.warning("Cancel SL %s failed (may be already filled): %s",
                                                targeted_stop, e)
                        # Also cancel the bracketed TP child (ORB has both;
                        # 2n20 has none, so this is a no-op there). Without
                        # this, a manual close on an ORB position leaves the
                        # TP limit dangling at IB until session end.
                        if targeted_target and targeted_target != "0":
                            try:
                                client.cancel_order(targeted_target)
                                logger.info("Cancelled TP %s for [%s] before close",
                                            targeted_target, strategy_name)
                            except Exception as e:
                                logger.warning("Cancel TP %s failed (may be already filled): %s",
                                                targeted_target, e)
                        else:
                            # Fall back: cancel up to `contracts` matching stops
                            # (orphan / unattributed protection from older entries).
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
                            time.sleep(1)  # give IB a beat to process cancels

                        order_payload = client.build_futures_order(fut_conid, close_action, contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)

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

                            closed_trade = {
                                "symbol": ticker,
                                "type": "futures",
                                "direction": "LONG" if direction == "CLOSE_LONG" else "SHORT",
                                "contracts": contracts,
                                "entry_price": round(entry_price, 2),
                                "exit_price": round(exit_price, 2),
                                "realized_pnl": round(pnl, 2),
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
                    elif direction == "BUY":
                        order_payload = client.build_futures_order(fut_conid, "BUY", contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)
                        # Extract our specific entry order ID from the place_order
                        # response so we can read THIS order's fill price (not
                        # any other contract's fill that happened nearby).
                        entry_order_id = ""
                        if isinstance(trade_result, list) and trade_result:
                            first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                            entry_order_id = str(first.get("order_id", "") or "")
                        elif isinstance(trade_result, dict):
                            entry_order_id = str(trade_result.get("order_id", "") or "")
                        # Place stop loss using the actual MES fill price.
                        sl_order_id = ""
                        sl_price = 0
                        tp_order_id = ""
                        tp_price = 0
                        try:
                            fill_info = client.get_order_fill(entry_order_id)
                            fill_price = float(fill_info.get("avg_price") or 0)
                            if fill_price > 0:
                                # SECOND DEFENSE: verify IB actually shows the expected
                                # direction (LONG for a BUY entry) before placing the
                                # protective SELL STP. Without this check, a strat_pos
                                # that doesn't reflect reality (cascade from an earlier
                                # phantom) gets a STOP placed that can fire and CREATE
                                # an unwanted position rather than close one.
                                time.sleep(1)  # let IB position update propagate
                                ib_qty = 0
                                for item in client.get_positions():
                                    if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                                        ib_qty = int(item.get("quantity", 0))
                                        break
                                if ib_qty <= 0:
                                    logger.error(
                                        "PROTECTIVE STOP SKIPPED for %s [%s] BUY: expected LONG but IB qty=%+d",
                                        ticker, strategy_name, ib_qty
                                    )
                                    try:
                                        from .supabase_client import send_telegram_message
                                        send_telegram_message(
                                            f"⚠️ *Stop not placed* — {ticker} [{strategy_name}] BUY entry filled "
                                            f"but IB shows qty `{ib_qty:+d}` (expected LONG). Skipping protective "
                                            f"stop to avoid creating a phantom position."
                                        )
                                    except Exception:
                                        pass
                                else:
                                    sl_price = pine_stop if pine_stop > 0 else (fill_price - sl_points)
                                    # Bracket: SL is a child of the entry order. IB
                                    # enforces OCO when paired with the TP child.
                                    sl_payload = client.build_futures_order(
                                        fut_conid, "SELL", contracts, "STP", sl_price,
                                        tif="GTC", parent_id=entry_order_id,
                                    )
                                    sl_result = client.place_order(sl_payload)
                                    if isinstance(sl_result, list) and sl_result:
                                        first = sl_result[0] if isinstance(sl_result[0], dict) else {}
                                        sl_order_id = str(first.get("order_id", "") or "")
                                    elif isinstance(sl_result, dict):
                                        sl_order_id = str(sl_result.get("order_id", "") or "")
                                    logger.info("Stop loss: SELL %s @ %.2f (entry %.2f, ib_qty=%+d, source=%s, parent=%s) sl_id=%s",
                                                ticker, sl_price, fill_price, ib_qty,
                                                "pine" if pine_stop else "config",
                                                entry_order_id, sl_order_id)
                                    # Take-profit child if Pine sent a target — also
                                    # bracketed to the entry for OCO with the SL.
                                    if pine_target > 0:
                                        tp_price = pine_target
                                        tp_payload = client.build_futures_order(
                                            fut_conid, "SELL", contracts, "LMT", tp_price,
                                            tif="GTC", parent_id=entry_order_id,
                                        )
                                        tp_result = client.place_order(tp_payload)
                                        if isinstance(tp_result, list) and tp_result:
                                            first = tp_result[0] if isinstance(tp_result[0], dict) else {}
                                            tp_order_id = str(first.get("order_id", "") or "")
                                        elif isinstance(tp_result, dict):
                                            tp_order_id = str(tp_result.get("order_id", "") or "")
                                        logger.info("Take profit: SELL %s @ %.2f (parent=%s) tp_id=%s",
                                                    ticker, tp_price, entry_order_id, tp_order_id)
                            else:
                                logger.error("Cannot place SL for %s: entry order %s not filled (status=%s)",
                                              ticker, entry_order_id, fill_info.get("status", ""))
                        except Exception as e:
                            logger.error("Failed to place stop loss/target: %s", e)
                    elif direction == "SELL":
                        order_payload = client.build_futures_order(fut_conid, "SELL", contracts, "MKT", tif="GTC")
                        trade_result = client.place_order(order_payload)
                        # Same fill-attribution pattern as BUY above.
                        entry_order_id = ""
                        if isinstance(trade_result, list) and trade_result:
                            first = trade_result[0] if isinstance(trade_result[0], dict) else {}
                            entry_order_id = str(first.get("order_id", "") or "")
                        elif isinstance(trade_result, dict):
                            entry_order_id = str(trade_result.get("order_id", "") or "")
                        sl_order_id = ""
                        sl_price = 0
                        tp_order_id = ""
                        tp_price = 0
                        try:
                            fill_info = client.get_order_fill(entry_order_id)
                            fill_price = float(fill_info.get("avg_price") or 0)
                            if fill_price > 0:
                                # SECOND DEFENSE: verify IB actually shows the expected
                                # direction (SHORT for a SELL entry) before placing the
                                # protective BUY STP. See BUY-path comment for context.
                                time.sleep(1)
                                ib_qty = 0
                                for item in client.get_positions():
                                    if item.get("symbol") == ticker and item.get("sec_type") == "FUT":
                                        ib_qty = int(item.get("quantity", 0))
                                        break
                                if ib_qty >= 0:
                                    logger.error(
                                        "PROTECTIVE STOP SKIPPED for %s [%s] SELL: expected SHORT but IB qty=%+d",
                                        ticker, strategy_name, ib_qty
                                    )
                                    try:
                                        from .supabase_client import send_telegram_message
                                        send_telegram_message(
                                            f"⚠️ *Stop not placed* — {ticker} [{strategy_name}] SELL entry filled "
                                            f"but IB shows qty `{ib_qty:+d}` (expected SHORT). Skipping protective "
                                            f"stop to avoid creating a phantom position."
                                        )
                                    except Exception:
                                        pass
                                else:
                                    sl_price = pine_stop if pine_stop > 0 else (fill_price + sl_points)
                                    # Bracket: SL is a child of the entry order. IB
                                    # enforces OCO when paired with the TP child.
                                    sl_payload = client.build_futures_order(
                                        fut_conid, "BUY", contracts, "STP", sl_price,
                                        tif="GTC", parent_id=entry_order_id,
                                    )
                                    sl_result = client.place_order(sl_payload)
                                    if isinstance(sl_result, list) and sl_result:
                                        first = sl_result[0] if isinstance(sl_result[0], dict) else {}
                                        sl_order_id = str(first.get("order_id", "") or "")
                                    elif isinstance(sl_result, dict):
                                        sl_order_id = str(sl_result.get("order_id", "") or "")
                                    logger.info("Stop loss: BUY %s @ %.2f (entry %.2f, ib_qty=%+d, source=%s, parent=%s) sl_id=%s",
                                                ticker, sl_price, fill_price, ib_qty,
                                                "pine" if pine_stop else "config",
                                                entry_order_id, sl_order_id)
                                    # Take-profit child if Pine sent a target — also
                                    # bracketed to the entry for OCO with the SL.
                                    if pine_target > 0:
                                        tp_price = pine_target
                                        tp_payload = client.build_futures_order(
                                            fut_conid, "BUY", contracts, "LMT", tp_price,
                                            tif="GTC", parent_id=entry_order_id,
                                        )
                                        tp_result = client.place_order(tp_payload)
                                        if isinstance(tp_result, list) and tp_result:
                                            first = tp_result[0] if isinstance(tp_result[0], dict) else {}
                                            tp_order_id = str(first.get("order_id", "") or "")
                                        elif isinstance(tp_result, dict):
                                            tp_order_id = str(tp_result.get("order_id", "") or "")
                                        logger.info("Take profit: BUY %s @ %.2f (parent=%s) tp_id=%s",
                                                    ticker, tp_price, entry_order_id, tp_order_id)
                            else:
                                logger.error("Cannot place SL for %s: entry order %s not filled (status=%s)",
                                              ticker, entry_order_id, fill_info.get("status", ""))
                        except Exception as e:
                            logger.error("Failed to place stop loss/target: %s", e)
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
                            continue

                        # Per-strategy position state — lets independent
                        # strategies (e.g. 2n20 + ORB) coexist on the same
                        # contract; each closes only its own leg. Stop info
                        # included so check_stop_fills() can detect when
                        # this strategy's SL hits and book the close.
                        save_strat_pos(ticker, strategy_name, direction,
                                       contracts, entry_fill_price, perm_id,
                                       stop_order_id=sl_order_id,
                                       stop_price=sl_price,
                                       target_order_id=tp_order_id,
                                       target_price=tp_price,
                                       multiplier=multiplier,
                                       metadata=pine_meta,
                                       caller=f"entry_fill:{strategy_name}")

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
            logger.info("CLOSING %s %s: %s", symbol, spread_type, close_reason)
            try:
                _close_spread(client, spread, close_reason)
            except Exception as e:
                logger.error("Failed to close %s spread: %s", symbol, e)


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


def main():
    logger.info("IB CPAPI Sync starting — connecting to %s", CPAPI_URL)

    from .ibkr_cpapi import CPAPIClient
    client = CPAPIClient(base_url=CPAPI_URL)

    try:
        client.ensure_session()
    except ConnectionError as e:
        logger.error("Failed to connect to CPAPI gateway: %s", e)
        logger.error("Make sure the CPAPI Docker container is running and authenticated")
        sys.exit(1)

    logger.info("Connected to CPAPI — syncing every %ds to %s", SYNC_INTERVAL, SERVER_URL)

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

            # Monitor open spreads for TP/SL/time stop
            if data.get("spreads"):
                monitor_spreads(client, data["spreads"])

        except Exception as e:
            logger.exception("Sync error: %s", e)  # include traceback — past silent failures wasted hours

        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
