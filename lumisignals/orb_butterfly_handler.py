"""ORB SPX 0DTE Leg-In Butterfly executor.

State machine driven by the orb_butterfly Pine alert payload. Phases:

    QUEUED          Webhook received the trigger. Butterfly state cached in
                    Redis. Next sync cycle places the debit order.

    DEBIT_OPEN      Limit-buy on K1/K2 debit spread is live at $1.40 max.
                    Watching IB for fill. If not filled by debit_cutoff
                    (11:00 ET), cancel and ABANDON.

    WATCHING        Debit filled. Watching SPX. When SPX crosses the
                    20%-into-the-fly threshold, place credit-leg limit
                    order at credit_target ($2.30) and advance.

    CREDIT_OPEN     Credit-leg limit-sell on K2/K3 is live. Walking the
                    limit down by $0.05 every 60s if not filled, down to
                    credit_floor. On fill -> COMPLETE.

    SALVAGE         Credit floor reached or end of credit window without
                    fill. Debit alone is held; at 3:30 PM ET market-sell
                    the debit to recover any value before cash settlement.

    COMPLETE        Both legs filled. Butterfly assembled. P&L pending
                    expiration cash settlement.

    ABANDONED       Debit never filled and cutoff passed. Order cancelled,
                    no exposure. Tracker can be cleaned up.

Redis schema (per butterfly): ibkr:butterfly:{butterfly_id} -> JSON blob.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─── CONFIG ───
SPX_TICKER          = "SPX"
DEBIT_MAX           = 1.40          # never pay more
CREDIT_TARGET       = 2.30          # initial limit
CREDIT_FLOOR        = 1.50          # walk no lower than this
CREDIT_STEP         = 0.05          # walk decrement
CREDIT_STEP_SEC     = 60            # seconds between walk steps
DEBIT_CUTOFF_ET     = "11:00"       # cancel debit if not filled by then
CREDIT_WINDOW_END_ET= "15:30"       # last call for credit; salvage debit after
THRESHOLD_PCT       = 0.20          # SPX must reach K1 + 20% × (K3-K1) for credit
MULTIPLIER          = 100           # SPX option multiplier
PHASE_KEY_PREFIX    = "ibkr:butterfly:"


def _key(butterfly_id: str) -> str:
    return PHASE_KEY_PREFIX + butterfly_id


def _now_et_hhmm() -> str:
    """Current ET time as HH:MM, naive (DST-aware via offset)."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    # EDT = UTC-4 (March-Nov), EST = UTC-5. Approximation via DST detection
    jan = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    jul = datetime(now.year, 7, 1, tzinfo=timezone.utc)
    # Crude DST check: if now is in March-Oct (rough), use EDT
    et = now + timedelta(hours=-4 if now.month in (3,4,5,6,7,8,9,10) else -5)
    return et.strftime("%H:%M")


def _save(rdb, butterfly_id: str, state: dict):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    rdb.setex(_key(butterfly_id), 86400, json.dumps(state))


def _load(rdb, butterfly_id: str) -> dict:
    raw = rdb.get(_key(butterfly_id))
    return json.loads(raw) if raw else None


def _telegram(text: str):
    """Best-effort Telegram notify; never raises."""
    try:
        from .supabase_client import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.debug("butterfly telegram error: %s", e)


def queue_butterfly(rdb, payload: dict) -> str:
    """Called from the webhook. Stores a fresh butterfly tracker in Redis.

    Returns the butterfly_id (also stored in the record).
    """
    import uuid
    butterfly_id = "bf_" + uuid.uuid4().hex[:10]

    direction = (payload.get("direction") or "").upper()
    spread_type = payload.get("spread_type", "call" if direction == "BUY" else "put")
    state = {
        "butterfly_id": butterfly_id,
        "phase": "QUEUED",
        "ticker": payload.get("ticker", SPX_TICKER),
        "direction": direction,
        "spread_type": spread_type,            # "call" or "put"
        "long_strike": float(payload.get("long_strike") or 0),
        "body_strike": float(payload.get("body_strike") or 0),
        "wing_strike": float(payload.get("wing_strike") or 0),
        "expiry": payload.get("expiry", "0DTE"),
        "contracts": int(payload.get("contracts") or 1),
        "debit_target": float(payload.get("debit_target") or DEBIT_MAX),
        "credit_target": float(payload.get("credit_target") or CREDIT_TARGET),
        "spx_or_high": float(payload.get("spx_or_high") or 0),
        "spx_or_low": float(payload.get("spx_or_low") or 0),
        "es_or_high": float(payload.get("es_or_high") or 0),
        "es_or_low": float(payload.get("es_or_low") or 0),
        "vix": float(payload.get("vix") or 0),
        "reversal": bool(payload.get("reversal", False)),
        "queued_at": datetime.now(timezone.utc).isoformat(),
        # Computed: 20% into the fly threshold
        "threshold_px": None,                  # set on first phase tick
        # Phase artifacts
        "debit_order_id": "",
        "debit_fill_price": None,
        "debit_conids": {"long": None, "short": None},
        "credit_order_id": "",
        "credit_fill_price": None,
        "credit_conids": {"long": None, "short": None},
        "credit_current_limit": None,
        "credit_last_step_at": None,
    }
    _save(rdb, butterfly_id, state)
    _telegram(
        f"🦋 *Butterfly queued* {state['ticker']} {direction}\n"
        f"K1/K2/K3: `{state['long_strike']:.0f}/{state['body_strike']:.0f}/{state['wing_strike']:.0f}`\n"
        f"Debit cap: `${state['debit_target']:.2f}` Credit tgt: `${state['credit_target']:.2f}`"
    )
    logger.info("Butterfly %s queued: %s %s K1/K2/K3=%s/%s/%s",
                butterfly_id, state["ticker"], direction,
                state["long_strike"], state["body_strike"], state["wing_strike"])
    return butterfly_id


# ─── PHASE HANDLERS ───────────────────────────────────────────────────────

def _lookup_option_conids(client, symbol: str, expiry_yyyymmdd: str,
                          strike: float, right: str) -> int:
    """SPX is an INDEX. Try IND lookup first, fall back to STK."""
    try:
        results = client.search_contract(symbol, "IND") or []
    except Exception:
        results = []
    if not results:
        results = client.search_contract(symbol, "STK") or []
    if not results:
        return None
    underlying_conid = results[0].get("conid")
    if not underlying_conid:
        return None
    sec_def = client._request("GET", "/iserver/secdef/info", params={
        "conid": underlying_conid,
        "sectype": "OPT",
        "month": expiry_yyyymmdd[:6],
        "strike": strike,
        "right": right,
        "exchange": "SMART",
    })
    if isinstance(sec_def, list) and sec_def:
        for opt in sec_def:
            if (str(opt.get("maturityDate","")).replace("-","") == expiry_yyyymmdd
                    and float(opt.get("strike",0)) == strike):
                return opt.get("conid")
        return sec_def[0].get("conid")
    return None


def _0dte_expiry() -> str:
    """Today's date in YYYYMMDD ET (SPX 0DTE settles on day's close)."""
    from datetime import timedelta
    now_et = datetime.now(timezone.utc) + timedelta(hours=-4)
    return now_et.strftime("%Y%m%d")


def _phase_queued_to_debit(client, rdb, state: dict):
    """Place the debit-leg limit order. Phase transitions to DEBIT_OPEN."""
    bid = state["butterfly_id"]
    expiry = _0dte_expiry() if state["expiry"] == "0DTE" else state["expiry"]
    right = "C" if state["spread_type"] == "call" else "P"

    long_conid  = _lookup_option_conids(client, state["ticker"], expiry, state["long_strike"], right)
    short_conid = _lookup_option_conids(client, state["ticker"], expiry, state["body_strike"], right)
    if not (long_conid and short_conid):
        logger.warning("Butterfly %s: option conid lookup failed (long=%s short=%s)",
                       bid, long_conid, short_conid)
        return

    state["debit_conids"] = {"long": long_conid, "short": short_conid}

    payload = client.build_spread_order(
        sell_conid=short_conid, buy_conid=long_conid,
        quantity=state["contracts"],
        limit_price=state["debit_target"], is_credit=False, tif="DAY",
    )
    try:
        result = client.place_order(payload)
        # Walk through confirmation prompts
        while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        order_id = ""
        if isinstance(result, list) and result:
            order_id = str(result[0].get("order_id", ""))
        elif isinstance(result, dict):
            order_id = str(result.get("order_id", ""))
        if not order_id:
            # Abandon after 3 failed attempts so we don't hammer IB forever
            state["debit_retries"] = int(state.get("debit_retries", 0)) + 1
            logger.warning("Butterfly %s: debit place_order failed (try %d/3): %s",
                            bid, state["debit_retries"], result)
            if state["debit_retries"] >= 3:
                state["phase"] = "ABANDONED"
                state["abandon_reason"] = f"debit place_order failed 3x: {result}"
                _telegram(f"🦋 *Abandoned* — debit order rejected by IB ({result})")
            _save(rdb, bid, state)
            return
        state["debit_order_id"] = order_id
        state["phase"] = "DEBIT_OPEN"
        _save(rdb, bid, state)
        _telegram(
            f"🦋 *Debit placed* `{state['long_strike']:.0f}/{state['body_strike']:.0f}` "
            f"@ ≤${state['debit_target']:.2f} (order {order_id})"
        )
        logger.info("Butterfly %s: debit order placed %s", bid, order_id)
    except Exception as e:
        logger.error("Butterfly %s debit placement failed: %s", bid, e)


def _phase_debit_open(client, rdb, state: dict):
    """Watch debit order for fill or cutoff."""
    bid = state["butterfly_id"]
    oid = state["debit_order_id"]
    if not oid:
        state["phase"] = "QUEUED"
        _save(rdb, bid, state)
        return

    # Cutoff check
    if _now_et_hhmm() >= DEBIT_CUTOFF_ET:
        try:
            client.cancel_order(oid)
        except Exception:
            pass
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = f"debit not filled by {DEBIT_CUTOFF_ET} ET"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Abandoned* — debit unfilled by {DEBIT_CUTOFF_ET} ET")
        logger.info("Butterfly %s ABANDONED: debit cutoff", bid)
        return

    fill = client.get_order_fill(oid, max_wait=1)
    if fill.get("filled"):
        state["debit_fill_price"] = float(fill.get("avg_price") or state["debit_target"])
        state["phase"] = "WATCHING"
        _save(rdb, bid, state)
        _telegram(
            f"🦋 *Debit filled* @ `${state['debit_fill_price']:.2f}`\n"
            f"Watching SPX for {THRESHOLD_PCT*100:.0f}% leg-in trigger…"
        )
        logger.info("Butterfly %s: debit filled @ %.2f", bid, state["debit_fill_price"])


def _phase_watching(client, rdb, state: dict, spx_price: float):
    """Wait until SPX crosses the 20%-into-the-fly threshold."""
    bid = state["butterfly_id"]
    if state.get("threshold_px") is None:
        K1 = state["long_strike"]
        K3 = state["wing_strike"]
        if state["spread_type"] == "call":
            threshold = K1 + THRESHOLD_PCT * (K3 - K1)
        else:
            threshold = K1 - THRESHOLD_PCT * (K1 - K3)  # K1 > K3 for puts
        state["threshold_px"] = round(threshold, 2)
        _save(rdb, bid, state)

    if spx_price is None or spx_price <= 0:
        return

    triggered = (
        (state["spread_type"] == "call" and spx_price >= state["threshold_px"]) or
        (state["spread_type"] == "put"  and spx_price <= state["threshold_px"])
    )
    if not triggered:
        return

    # Place credit limit at credit_target
    expiry = _0dte_expiry() if state["expiry"] == "0DTE" else state["expiry"]
    right = "C" if state["spread_type"] == "call" else "P"

    short_conid = _lookup_option_conids(client, state["ticker"], expiry, state["body_strike"], right)
    long_conid  = _lookup_option_conids(client, state["ticker"], expiry, state["wing_strike"], right)
    if not (short_conid and long_conid):
        logger.warning("Butterfly %s: credit leg conid lookup failed", bid)
        return

    state["credit_conids"] = {"short": short_conid, "long": long_conid}
    state["credit_current_limit"] = state["credit_target"]

    payload = client.build_spread_order(
        sell_conid=short_conid, buy_conid=long_conid,
        quantity=state["contracts"],
        limit_price=state["credit_current_limit"], is_credit=True, tif="DAY",
    )
    try:
        result = client.place_order(payload)
        while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        order_id = ""
        if isinstance(result, list) and result:
            order_id = str(result[0].get("order_id", ""))
        elif isinstance(result, dict):
            order_id = str(result.get("order_id", ""))
        state["credit_order_id"] = order_id
        state["credit_last_step_at"] = datetime.now(timezone.utc).isoformat()
        state["phase"] = "CREDIT_OPEN"
        _save(rdb, bid, state)
        _telegram(
            f"🦋 *Credit placed* `{state['body_strike']:.0f}/{state['wing_strike']:.0f}` "
            f"@ ${state['credit_current_limit']:.2f} "
            f"(SPX={spx_price:.2f}, threshold={state['threshold_px']:.2f})"
        )
        logger.info("Butterfly %s: credit placed @ %.2f", bid, state["credit_current_limit"])
    except Exception as e:
        logger.error("Butterfly %s credit placement failed: %s", bid, e)


def _phase_credit_open(client, rdb, state: dict):
    """Walk the credit limit down by $0.05 every 60s. Stop at credit_floor."""
    bid = state["butterfly_id"]
    oid = state["credit_order_id"]

    fill = client.get_order_fill(oid, max_wait=1) if oid else {"filled": False}
    if fill.get("filled"):
        state["credit_fill_price"] = float(fill.get("avg_price") or state["credit_current_limit"])
        state["phase"] = "COMPLETE"
        _save(rdb, bid, state)
        net = state["credit_fill_price"] - (state["debit_fill_price"] or 0)
        _telegram(
            f"✅ *Butterfly complete* {state['ticker']}\n"
            f"Debit `${state['debit_fill_price']:.2f}` Credit `${state['credit_fill_price']:.2f}`\n"
            f"Net credit `${net:.2f}` × {state['contracts']} × ${MULTIPLIER} "
            f"= locked profit ≥ `${net * state['contracts'] * MULTIPLIER:.0f}`"
        )
        logger.info("Butterfly %s COMPLETE: debit=%.2f credit=%.2f", bid,
                    state["debit_fill_price"], state["credit_fill_price"])
        return

    # Salvage cutoff
    if _now_et_hhmm() >= CREDIT_WINDOW_END_ET:
        try:
            if oid:
                client.cancel_order(oid)
        except Exception:
            pass
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Credit unfilled by {CREDIT_WINDOW_END_ET}* — moving to salvage")
        return

    # Walking limit step
    last_step_iso = state.get("credit_last_step_at")
    last_step = datetime.fromisoformat(last_step_iso) if last_step_iso else None
    elapsed = (datetime.now(timezone.utc) - last_step).total_seconds() if last_step else 1e9
    if elapsed < CREDIT_STEP_SEC:
        return

    new_limit = round(state["credit_current_limit"] - CREDIT_STEP, 2)
    if new_limit < CREDIT_FLOOR:
        try:
            if oid:
                client.cancel_order(oid)
        except Exception:
            pass
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Credit hit floor* (${CREDIT_FLOOR:.2f}) — moving to salvage")
        return

    # Cancel & re-place at lower limit
    try:
        if oid:
            client.cancel_order(oid)
    except Exception:
        pass

    short_conid = state["credit_conids"]["short"]
    long_conid  = state["credit_conids"]["long"]
    payload = client.build_spread_order(
        sell_conid=short_conid, buy_conid=long_conid,
        quantity=state["contracts"],
        limit_price=new_limit, is_credit=True, tif="DAY",
    )
    try:
        result = client.place_order(payload)
        while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        order_id = ""
        if isinstance(result, list) and result:
            order_id = str(result[0].get("order_id", ""))
        elif isinstance(result, dict):
            order_id = str(result.get("order_id", ""))
        state["credit_order_id"] = order_id
        state["credit_current_limit"] = new_limit
        state["credit_last_step_at"] = datetime.now(timezone.utc).isoformat()
        _save(rdb, bid, state)
        logger.info("Butterfly %s: credit walked to %.2f", bid, new_limit)
    except Exception as e:
        logger.error("Butterfly %s credit re-place failed: %s", bid, e)


def _phase_salvage(client, rdb, state: dict):
    """Sell the debit spread at market to recover any value before cash settle."""
    bid = state["butterfly_id"]
    long_conid  = state["debit_conids"]["long"]
    short_conid = state["debit_conids"]["short"]
    if not (long_conid and short_conid):
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = "salvage failed: missing conids"
        _save(rdb, bid, state)
        return

    payload = client.build_close_spread_order(long_conid, short_conid, state["contracts"])
    try:
        result = client.place_order(payload)
        while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        order_id = ""
        if isinstance(result, list) and result:
            order_id = str(result[0].get("order_id", ""))
        elif isinstance(result, dict):
            order_id = str(result.get("order_id", ""))
        state["salvage_order_id"] = order_id
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = "credit never filled — sold debit at market"
        _save(rdb, bid, state)
        _telegram(
            f"🦋 *Salvage* sold debit spread at market "
            f"(credit never filled by {CREDIT_WINDOW_END_ET})"
        )
    except Exception as e:
        logger.error("Butterfly %s salvage failed: %s", bid, e)


# ─── PUBLIC ENTRY POINT (called from sync loop) ──────────────────────────

def process_butterflies(client, rdb, spx_price_fn=None):
    """Drive every active butterfly one tick forward.

    spx_price_fn: callable returning current SPX index price as float, or None.
                  Caller can pass a Polygon/IB-backed fetcher.
    """
    try:
        keys = list(rdb.scan_iter(PHASE_KEY_PREFIX + "*"))
    except Exception as e:
        logger.debug("butterfly scan_iter failed: %s", e)
        return

    spx_price = None
    if spx_price_fn:
        try:
            spx_price = spx_price_fn()
        except Exception as e:
            logger.debug("spx_price_fn failed: %s", e)

    for key in keys:
        try:
            raw = rdb.get(key)
            if not raw:
                continue
            state = json.loads(raw)
            phase = state.get("phase", "QUEUED")

            if phase == "QUEUED":
                _phase_queued_to_debit(client, rdb, state)
            elif phase == "DEBIT_OPEN":
                _phase_debit_open(client, rdb, state)
            elif phase == "WATCHING":
                _phase_watching(client, rdb, state, spx_price)
            elif phase == "CREDIT_OPEN":
                _phase_credit_open(client, rdb, state)
            elif phase == "SALVAGE":
                _phase_salvage(client, rdb, state)
            # COMPLETE / ABANDONED — terminal, no action
        except Exception as e:
            logger.warning("butterfly process error on %s: %s", key, e)
