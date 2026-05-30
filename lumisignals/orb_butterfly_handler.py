"""ORB SPX 0DTE Leg-In Butterfly executor — two-leg implementation.

IB CPAPI's combo-order endpoint (conidex semicolon syntax) is broken in
practice — every variant returns "Combo key is not complete" or "Failed
to create margin order". Validated workaround: place each leg of the
spread as an individual single-leg LMT order, simultaneously, then track
fills. If one fills and the other doesn't within a short window, cancel
the survivor and close the filled leg at market.

Phases:

  QUEUED         Webhook stored the trigger. Next sync tick fetches live
                 quotes and places the two debit legs.

  DEBIT_LEGGED   Both K1-BUY and K2-SELL orders are live. Poll for fills.
                 Within 10s, expect both filled → WATCHING. Otherwise
                 handle partial or no-fill: cancel survivor + close
                 orphan, or retry (capped at 2).

  WATCHING       Debit complete. Watching SPX. When SPX crosses
                 K1 + 20% × (K3-K1), proceed to credit leg.

  CREDIT_LEGGED  Both K2-SELL and K3-BUY orders live. Poll for fills.
                 Walking limit per leg every 60s ($0.05 step) toward
                 (bid+ask)/2 if not filled, down to credit_floor.

  SALVAGE        Credit unfilled by 15:30 ET. Close the held debit
                 spread at market to recover any remaining value.

  COMPLETE       All four legs filled. Butterfly assembled. P&L will
                 settle at 0DTE close.

  ABANDONED      Debit too expensive, partial fill not recoverable, or
                 retries exhausted. Tracker terminal, no further action.
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── CONFIG ───
SPX_TICKER          = "SPX"
DEBIT_MAX           = 1.40          # absolute cap; will never pay more
DEBIT_CHEAP_LIMIT   = 1.20          # below this, take marketable
CREDIT_TARGET       = 2.30
CREDIT_FLOOR        = 1.50
CREDIT_STEP         = 0.05
CREDIT_STEP_SEC     = 60
LEG_FILL_TIMEOUT_S  = 30            # partial-fill timeout (per pair, any mode)
DEBIT_RETRY_MAX     = 2
DEBIT_CUTOFF_ET     = "11:00"
CREDIT_WINDOW_END_ET= "15:30"
THRESHOLD_PCT       = 0.20
MULTIPLIER          = 100
PHASE_KEY_PREFIX    = "ibkr:butterfly:"


def _key(bid: str) -> str:
    return PHASE_KEY_PREFIX + bid


def _now_et_hhmm() -> str:
    now = datetime.now(timezone.utc)
    et = now + timedelta(hours=-4 if now.month in (3,4,5,6,7,8,9,10) else -5)
    return et.strftime("%H:%M")


def _save(rdb, bid: str, state: dict):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    rdb.setex(_key(bid), 86400, json.dumps(state))


def _telegram(text: str):
    """Send to Telegram + log. Used for the user-facing milestones we
    actually want a phone ping for: entry filled and final close."""
    try:
        from .supabase_client import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.debug("butterfly telegram error: %s", e)
    logger.info("[butterfly] %s", text.replace("\n", " | "))


def _quiet(text: str):
    """Log-only notification — captures every state-machine transition for
    debugging without pinging the user's phone. Used for intermediate
    steps (queued, retries, partial fills, salvage stages, pre-entry
    abandons) that aren't worth a Telegram message on their own."""
    logger.info("[butterfly] %s", text.replace("\n", " | "))


def _0dte_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=-4)).strftime("%Y%m%d")


def _lookup_option_conid(client, symbol: str, expiry: str, strike: float, right: str):
    """SPX is an INDEX. search_contract returns it under either IND or STK."""
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
        "conid": underlying_conid, "sectype": "OPT",
        "month": expiry[:6], "strike": strike, "right": right, "exchange": "SMART",
    })
    if isinstance(sec_def, list) and sec_def:
        for opt in sec_def:
            if (str(opt.get("maturityDate","")).replace("-","") == expiry
                    and float(opt.get("strike",0)) == strike):
                return opt.get("conid")
        return sec_def[0].get("conid")
    return None


def _extract_error_text(result):
    """Pull a human-readable error string out of whatever CPAPI returned.
    Handles the common shapes: dict {'error': '...'}, list of dicts each
    with 'error' or 'message', empty/None. Returns None when the response
    doesn't look like an error (caller should treat as transient)."""
    if result is None:
        return None
    candidates = result if isinstance(result, list) else [result]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for key in ("error", "errorMessage", "message"):
            v = item.get(key)
            if v:
                return str(v)
    return None


def _place_leg(client, conid: int, side: str, qty: int, price: float):
    """Single-leg LMT order. Walks confirmation prompts. Returns
    (order_id, err_msg) tuple.

    Return shapes:
      ("12345", None)               — placement succeeded
      (None, "Combo key is not...") — permanent CPAPI rejection; caller
                                       should fast-abandon, not retry
      (None, None)                  — transient (exception/network);
                                       caller may retry

    Every failure logs payload + raw response at WARN so a future log
    diff between successful and failed placements has the diagnostic
    context needed to identify what trips the intermittent failures."""
    payload = {"orders": [{
        "conid": conid, "orderType": "LMT", "side": side,
        "quantity": qty, "price": round(price, 2), "tif": "DAY",
    }]}
    try:
        result = client.place_order(payload)
    except Exception as e:
        logger.warning(
            "place_leg %s conid=%s qty=%s price=%s EXCEPTION: %s | payload=%s",
            side, conid, qty, price, e, payload,
        )
        return (None, None)
    # Walk any remaining confirmation prompts that place_order's
    # internal loop didn't auto-handle.
    while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
        try:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        except Exception as e:
            logger.warning(
                "place_leg %s conid=%s reply-walk EXCEPTION: %s | payload=%s",
                side, conid, e, payload,
            )
            return (None, None)
    if isinstance(result, list) and result and result[0].get("order_id"):
        return (str(result[0]["order_id"]), None)
    if isinstance(result, dict) and result.get("order_id"):
        return (str(result["order_id"]), None)
    err = _extract_error_text(result)
    logger.warning(
        "place_leg %s conid=%s qty=%s price=%s no order_id | "
        "err=%r | payload=%s | response=%s",
        side, conid, qty, price, err, payload, result,
    )
    return (None, err)


def _close_leg_at_market(client, conid: int, side: str, qty: int):
    """Market order to close an orphan filled leg. side = opposite of original entry."""
    payload = {"orders": [{
        "conid": conid, "orderType": "MKT", "side": side,
        "quantity": qty, "tif": "DAY",
    }]}
    try:
        result = client.place_order(payload)
        while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        # Surface failures so an orphan-close-that-didn't-close is
        # visible. Caller has no return value to check.
        success = (
            (isinstance(result, list) and result and result[0].get("order_id"))
            or (isinstance(result, dict) and result.get("order_id"))
        )
        if not success:
            err = _extract_error_text(result)
            logger.warning(
                "close_leg_at_market %s conid=%s qty=%s no order_id | "
                "err=%r | response=%s",
                side, conid, qty, err, result,
            )
    except Exception as e:
        logger.warning(
            "close_leg_at_market %s conid=%s qty=%s EXCEPTION: %s",
            side, conid, qty, e,
        )


def queue_butterfly(rdb, payload: dict) -> str:
    """Webhook entry. Stores fresh butterfly tracker in Redis."""
    import uuid
    bid = "bf_" + uuid.uuid4().hex[:10]
    direction = (payload.get("direction") or "").upper()
    spread_type = payload.get("spread_type", "call" if direction == "BUY" else "put")
    state = {
        "butterfly_id": bid,
        "phase": "QUEUED",
        "ticker": payload.get("ticker", SPX_TICKER),
        "direction": direction,
        "spread_type": spread_type,
        "long_strike": float(payload.get("long_strike") or 0),
        "body_strike": float(payload.get("body_strike") or 0),
        "wing_strike": float(payload.get("wing_strike") or 0),
        "expiry": payload.get("expiry", "0DTE"),
        "contracts": int(payload.get("contracts") or 1),
        "debit_target": float(payload.get("debit_target") or DEBIT_MAX),
        "credit_target": float(payload.get("credit_target") or CREDIT_TARGET),
        "vix": float(payload.get("vix") or 0),
        "spx_or_high": float(payload.get("spx_or_high") or 0),
        "spx_or_low": float(payload.get("spx_or_low") or 0),
        "reversal": bool(payload.get("reversal", False)),
        "force_test": bool(payload.get("force_test", False)),
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "threshold_px": None,
        "debit_conids": {"long": None, "short": None},
        "debit_long_oid": "", "debit_short_oid": "",
        "debit_long_price": None, "debit_short_price": None,
        "debit_long_filled": None, "debit_short_filled": None,
        "debit_legged_at": None,
        "debit_fill_price": None,
        "debit_retries": 0,
        "credit_conids": {"short": None, "long": None},
        "credit_short_oid": "", "credit_long_oid": "",
        "credit_short_price": None, "credit_long_price": None,
        "credit_short_filled": None, "credit_long_filled": None,
        "credit_legged_at": None,
        "credit_fill_price": None,
        "credit_current_step": 0,
    }
    _save(rdb, bid, state)
    _quiet(
        f"🦋 *Butterfly queued* {state['ticker']} {direction}\n"
        f"K1/K2/K3: `{state['long_strike']:.0f}/{state['body_strike']:.0f}/{state['wing_strike']:.0f}`\n"
        f"Debit cap: `${state['debit_target']:.2f}` Credit tgt: `${state['credit_target']:.2f}`"
    )
    logger.info("Butterfly %s queued: %s %s K1/K2/K3=%s/%s/%s",
                bid, state["ticker"], direction,
                state["long_strike"], state["body_strike"], state["wing_strike"])
    return bid


# ─── PHASE HANDLERS ───

def _phase_queued(client, rdb, state):
    """Place K1 BUY + K2 SELL as two simultaneous marketable LMT orders."""
    bid = state["butterfly_id"]
    if _now_et_hhmm() >= DEBIT_CUTOFF_ET and not state.get("force_test"):
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = f"debit window closed ({DEBIT_CUTOFF_ET} ET)"
        _save(rdb, bid, state)
        _quiet(f"🦋 *Abandoned* — debit window closed before placement")
        return

    expiry = _0dte_expiry() if state["expiry"] == "0DTE" else state["expiry"]
    right = "C" if state["spread_type"] == "call" else "P"
    long_conid = _lookup_option_conid(client, state["ticker"], expiry, state["long_strike"], right)
    short_conid = _lookup_option_conid(client, state["ticker"], expiry, state["body_strike"], right)
    if not (long_conid and short_conid):
        state["debit_retries"] += 1
        if state["debit_retries"] >= DEBIT_RETRY_MAX:
            state["phase"] = "ABANDONED"
            state["abandon_reason"] = "could not resolve option conids"
            _quiet(f"🦋 *Abandoned* — option conid lookup failed")
        _save(rdb, bid, state)
        return
    state["debit_conids"] = {"long": long_conid, "short": short_conid}

    # Quote pricing goes through the pluggable source (Schwab during the
    # bridge window, IB CPAPI after real-time data sharing propagates,
    # Tastytrade if/when that account opens). Order placement still uses
    # the IB conid above — we look up both because the quote source
    # builds its own native identifier (OCC for Schwab, conid for IB).
    from .orb_quote_source import get_quote_source
    qs = get_quote_source(client=client, rdb=rdb)
    long_bid, long_ask = qs.get_option_quote(
        state["ticker"], expiry, state["long_strike"], right
    )
    short_bid, short_ask = qs.get_option_quote(
        state["ticker"], expiry, state["body_strike"], right
    )
    if not all([long_bid, long_ask, short_bid, short_ask]):
        state["debit_retries"] += 1
        logger.info("Butterfly %s: quote fetch incomplete (try %d/%d)",
                    bid, state["debit_retries"], DEBIT_RETRY_MAX)
        if state["debit_retries"] >= DEBIT_RETRY_MAX:
            state["phase"] = "ABANDONED"
            state["abandon_reason"] = "no live quotes for option legs"
            _quiet(f"🦋 *Abandoned* — couldn't fetch live quotes")
        _save(rdb, bid, state)
        return

    # Three-tier entry pricing:
    #   mid < $1.20      → take marketable (long@ask, short@bid). Fills fast.
    #   $1.20 - $1.40    → limit at NET $1.20 (passive, wait for pullback).
    #   > $1.40          → limit at NET $1.40 (passive, wait for pullback to cap).
    # In all cases, sit until 11:00 ET if the patient limit never fills,
    # then abandon. Per-leg prices derived by splitting the adjustment
    # equally across both legs from their mids.
    long_mid = (long_bid + long_ask) / 2.0
    short_mid = (short_bid + short_ask) / 2.0
    net_mid = long_mid - short_mid

    if net_mid < DEBIT_CHEAP_LIMIT:
        mode = "marketable"
        long_price = long_ask
        short_price = short_bid
        target_net = round(long_ask - short_bid, 2)
    elif net_mid <= state["debit_target"]:
        # Bidding BELOW current mid (long) and ASKING ABOVE mid (short)
        # so net comes out at $1.20. The orders sit as passive limits;
        # IB doesn't fill them unless market moves to us. No bid/ask
        # clipping — going below long_bid or above short_ask is the
        # whole point of "patient".
        mode = "patient_120"
        target_net = DEBIT_CHEAP_LIMIT
        delta = (net_mid - DEBIT_CHEAP_LIMIT) / 2.0
        long_price = max(0.01, long_mid - delta)
        short_price = max(0.01, short_mid + delta)
    else:
        mode = "patient_cap"
        target_net = state["debit_target"]
        delta = (net_mid - state["debit_target"]) / 2.0
        long_price = max(0.01, long_mid - delta)
        short_price = max(0.01, short_mid + delta)

    state["debit_mode"] = mode
    state["debit_target_net"] = round(target_net, 2)
    state["debit_quote_at_signal"] = {
        "long_bid": round(long_bid, 2), "long_ask": round(long_ask, 2),
        "short_bid": round(short_bid, 2), "short_ask": round(short_ask, 2),
        "net_mid": round(net_mid, 2),
    }

    qty = state["contracts"]
    # 250ms gap between consecutive CPAPI place_order calls — hypothesis
    # for the intermittent "Combo key is not complete" CPAPI rejection
    # is rapid-fire state carry-over between requests. Cheap mitigation
    # that doesn't materially affect leg-in slippage.
    import time as _time
    long_oid, long_err = _place_leg(client, long_conid, "BUY", qty, long_price)
    _time.sleep(0.25)
    short_oid, short_err = _place_leg(client, short_conid, "SELL", qty, short_price)
    if not (long_oid and short_oid):
        # Cancel partial placement
        if long_oid:
            try: client.cancel_order(long_oid)
            except Exception: pass
        if short_oid:
            try: client.cancel_order(short_oid)
            except Exception: pass
        permanent_err = long_err or short_err
        if permanent_err:
            # CPAPI returned a structured error (not a network/timeout
            # blip). Retrying will fail the same way. Fast-abandon +
            # Telegram with the diagnostic context — saves the 30s of
            # wasted retries and surfaces actionable info.
            state["phase"] = "ABANDONED"
            state["abandon_reason"] = f"permanent CPAPI error: {permanent_err}"
            _quiet(
                f"🦋 *Abandoned* — leg placement permanent error "
                f"(`{permanent_err[:80]}`)"
            )
            try:
                from .ibkr_sync_cpapi import _send_telegram_alert
                _send_telegram_alert(
                    "❌ ORB butterfly placement rejected",
                    f"{bid} debit leg permanent CPAPI error: "
                    f"`{permanent_err}`. Strikes "
                    f"K1={state.get('long_strike')} "
                    f"K2={state.get('body_strike')} "
                    f"K3={state.get('wing_strike')}. "
                    f"See bot log for full payload.",
                )
            except Exception:
                pass
        else:
            state["debit_retries"] += 1
            if state["debit_retries"] >= DEBIT_RETRY_MAX:
                state["phase"] = "ABANDONED"
                state["abandon_reason"] = "place_order transient failure (twice)"
                _quiet(f"🦋 *Abandoned* — leg placement transient failure × 2")
        _save(rdb, bid, state)
        return

    state["debit_long_oid"] = long_oid
    state["debit_short_oid"] = short_oid
    state["debit_long_price"] = round(long_price, 2)
    state["debit_short_price"] = round(short_price, 2)
    state["debit_legged_at"] = datetime.now(timezone.utc).isoformat()
    state["phase"] = "DEBIT_LEGGED"
    _save(rdb, bid, state)
    mode_label = {"marketable": "MARKETABLE (cheap)",
                  "patient_120": "PATIENT @ $1.20 net",
                  "patient_cap": f"PATIENT @ ${state['debit_target']:.2f} cap"}.get(mode, mode)
    _quiet(
        f"🦋 *Debit legged in* — {mode_label}\n"
        f"Net mid was `${net_mid:.2f}`, targeting `${target_net:.2f}`\n"
        f"BUY `{state['long_strike']:.0f}` @ `${long_price:.2f}` (order {long_oid})\n"
        f"SELL `{state['body_strike']:.0f}` @ `${short_price:.2f}` (order {short_oid})"
    )


def _phase_debit_legged(client, rdb, state):
    """Poll both legs.
       - Both filled → WATCHING
       - Partial fill (after 30s) → cancel survivor + close orphan + ABANDON
       - No fill, marketable mode → retry/abandon after 30s
       - No fill, patient mode → keep waiting until DEBIT_CUTOFF_ET, then ABANDON
    """
    bid = state["butterfly_id"]
    lf = client.get_order_fill(state["debit_long_oid"], max_wait=1)
    sf = client.get_order_fill(state["debit_short_oid"], max_wait=1)
    long_filled = lf.get("filled", False)
    short_filled = sf.get("filled", False)

    if long_filled and short_filled:
        lp = float(lf.get("avg_price") or state["debit_long_price"])
        sp = float(sf.get("avg_price") or state["debit_short_price"])
        state["debit_long_filled"] = lp
        state["debit_short_filled"] = sp
        state["debit_fill_price"] = round(lp - sp, 2)
        state["phase"] = "WATCHING"
        _save(rdb, bid, state)
        _telegram(
            f"✅ *Debit filled* — long `${lp:.2f}` short `${sp:.2f}` = net `${state['debit_fill_price']:.2f}`\n"
            f"Watching SPX for {THRESHOLD_PCT*100:.0f}% leg-in trigger…"
        )
        return

    legged_at = datetime.fromisoformat(state["debit_legged_at"])
    elapsed = (datetime.now(timezone.utc) - legged_at).total_seconds()
    long_conid = state["debit_conids"]["long"]
    short_conid = state["debit_conids"]["short"]
    qty = state["contracts"]
    mode = state.get("debit_mode", "marketable")

    # Partial fill (one side picked off, the other won't): always handle after 30s
    if (long_filled or short_filled) and elapsed > LEG_FILL_TIMEOUT_S:
        if long_filled and not short_filled:
            try: client.cancel_order(state["debit_short_oid"])
            except Exception: pass
            _close_leg_at_market(client, long_conid, "SELL", qty)
            state["abandon_reason"] = "partial fill: only long filled, closed at market"
            _quiet(f"🦋 *Partial fill* — only long filled, sold at market")
        else:
            try: client.cancel_order(state["debit_long_oid"])
            except Exception: pass
            _close_leg_at_market(client, short_conid, "BUY", qty)
            state["abandon_reason"] = "partial fill: only short filled, closed at market"
            _quiet(f"🦋 *Partial fill* — only short filled, bought back at market")
        state["phase"] = "ABANDONED"
        _save(rdb, bid, state)
        return

    # No fills yet
    if mode == "marketable":
        # Marketable should fill in <30s; if not, retry once then abandon
        if elapsed > LEG_FILL_TIMEOUT_S:
            try: client.cancel_order(state["debit_long_oid"])
            except Exception: pass
            try: client.cancel_order(state["debit_short_oid"])
            except Exception: pass
            state["debit_retries"] += 1
            if state["debit_retries"] >= DEBIT_RETRY_MAX:
                state["phase"] = "ABANDONED"
                state["abandon_reason"] = "marketable order didn't fill (twice)"
                _save(rdb, bid, state)
                _quiet(f"🦋 *Abandoned* — marketable order didn't fill in {LEG_FILL_TIMEOUT_S}s, twice")
            else:
                state["phase"] = "QUEUED"
                _save(rdb, bid, state)
                _quiet(f"🦋 No fill in {LEG_FILL_TIMEOUT_S}s — retrying ({state['debit_retries']}/{DEBIT_RETRY_MAX})")
        return

    # Patient mode (patient_120 / patient_cap) — sit on the limit until cutoff
    if _now_et_hhmm() >= DEBIT_CUTOFF_ET and not state.get("force_test"):
        try: client.cancel_order(state["debit_long_oid"])
        except Exception: pass
        try: client.cancel_order(state["debit_short_oid"])
        except Exception: pass
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = (
            f"patient limit @ net ${state.get('debit_target_net', 0):.2f} never filled by {DEBIT_CUTOFF_ET} ET"
        )
        _save(rdb, bid, state)
        _quiet(
            f"🦋 *Abandoned* — patient `${state.get('debit_target_net',0):.2f}` "
            f"never filled by {DEBIT_CUTOFF_ET} ET"
        )


def _phase_watching(client, rdb, state, spx_price):
    """Wait for SPX to cross 20%-into-the-fly threshold."""
    bid = state["butterfly_id"]
    if state.get("threshold_px") is None:
        K1, K3 = state["long_strike"], state["wing_strike"]
        if state["spread_type"] == "call":
            threshold = K1 + THRESHOLD_PCT * (K3 - K1)
        else:
            threshold = K1 - THRESHOLD_PCT * (K1 - K3)
        state["threshold_px"] = round(threshold, 2)
        _save(rdb, bid, state)

    # Stuck-WATCHING watchdog: alert once if the butterfly has been
    # waiting > 30 min without the threshold being hit (or quote feed
    # being available). Catches the silent-feed-failure case the way
    # bf_6e42bd320e went unnoticed for 2 hours on 2026-05-29.
    debit_legged_at = state.get("debit_legged_at")
    if debit_legged_at and not state.get("watching_alert_sent"):
        try:
            elapsed = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(debit_legged_at)).total_seconds()
            if elapsed > 30 * 60:
                from .ibkr_sync_cpapi import _send_telegram_alert
                _send_telegram_alert(
                    "⚠️ ORB butterfly stuck in WATCHING",
                    f"{bid} has been waiting for SPX to cross "
                    f"{state.get('threshold_px')} for {elapsed/60:.0f} min. "
                    f"Strikes K1={state.get('long_strike')} "
                    f"K2={state.get('body_strike')} "
                    f"K3={state.get('wing_strike')}, "
                    f"direction={state.get('direction')}. "
                    f"Last SPX price seen: {spx_price}.",
                )
                state["watching_alert_sent"] = True
                _save(rdb, bid, state)
        except Exception:
            pass

    if not spx_price:
        return

    triggered = (
        (state["spread_type"] == "call" and spx_price >= state["threshold_px"]) or
        (state["spread_type"] == "put"  and spx_price <= state["threshold_px"])
    )
    if not triggered:
        return

    # Place credit legs: SELL K2 + BUY K3
    expiry = _0dte_expiry() if state["expiry"] == "0DTE" else state["expiry"]
    right = "C" if state["spread_type"] == "call" else "P"
    short_conid = _lookup_option_conid(client, state["ticker"], expiry, state["body_strike"], right)
    long_conid = _lookup_option_conid(client, state["ticker"], expiry, state["wing_strike"], right)
    if not (short_conid and long_conid):
        logger.warning("Butterfly %s: credit conid lookup failed", bid)
        return
    state["credit_conids"] = {"short": short_conid, "long": long_conid}

    from .orb_quote_source import get_quote_source
    qs = get_quote_source(client=client, rdb=rdb)
    sb, sa = qs.get_option_quote(state["ticker"], expiry,
                                 state["body_strike"], right)
    lb, la = qs.get_option_quote(state["ticker"], expiry,
                                 state["wing_strike"], right)
    if not all([sb, sa, lb, la]):
        logger.info("Butterfly %s: credit quote fetch incomplete", bid)
        return
    # Marketable prices for credit: sell @ bid, buy @ ask. Net credit = short_bid - long_ask.
    net_credit = sb - la
    if net_credit < CREDIT_FLOOR:
        logger.info("Butterfly %s: credit too thin: $%.2f < floor $%.2f", bid, net_credit, CREDIT_FLOOR)
        return  # next tick will check again as quotes move

    qty = state["contracts"]
    # 250ms gap — same rationale as debit-side. Credit-side has no
    # retry counter (just falls through to next tick) so a permanent
    # error here would silently re-fire every tick until SALVAGE
    # window at 15:30 ET; the WARN-level logging in _place_leg makes
    # those visible in the bot log for diagnosis.
    import time as _time
    short_oid, _short_err = _place_leg(client, short_conid, "SELL", qty, sb)
    _time.sleep(0.25)
    long_oid, _long_err = _place_leg(client, long_conid, "BUY", qty, la)
    if not (short_oid and long_oid):
        if short_oid:
            try: client.cancel_order(short_oid)
            except Exception: pass
        if long_oid:
            try: client.cancel_order(long_oid)
            except Exception: pass
        return  # next tick retries

    state["credit_short_oid"] = short_oid
    state["credit_long_oid"] = long_oid
    state["credit_short_price"] = round(sb, 2)
    state["credit_long_price"] = round(la, 2)
    state["credit_legged_at"] = datetime.now(timezone.utc).isoformat()
    state["phase"] = "CREDIT_LEGGED"
    _save(rdb, bid, state)
    _quiet(
        f"🦋 *Credit legged in* (SPX={spx_price:.2f} ≥ {state['threshold_px']:.2f})\n"
        f"SELL `{state['body_strike']:.0f}` @ `${sb:.2f}` (order {short_oid})\n"
        f"BUY `{state['wing_strike']:.0f}` @ `${la:.2f}` (order {long_oid})\n"
        f"Net credit: `${net_credit:.2f}`"
    )


def _phase_credit_legged(client, rdb, state):
    """Poll credit legs. Both filled -> COMPLETE. Partial -> close survivor."""
    bid = state["butterfly_id"]
    sf = client.get_order_fill(state["credit_short_oid"], max_wait=1)
    lf = client.get_order_fill(state["credit_long_oid"], max_wait=1)
    short_filled = sf.get("filled", False)
    long_filled = lf.get("filled", False)

    if short_filled and long_filled:
        sp = float(sf.get("avg_price") or state["credit_short_price"])
        lp = float(lf.get("avg_price") or state["credit_long_price"])
        state["credit_short_filled"] = sp
        state["credit_long_filled"] = lp
        state["credit_fill_price"] = round(sp - lp, 2)
        state["phase"] = "COMPLETE"
        _save(rdb, bid, state)
        net_credit = state["credit_fill_price"] - (state.get("debit_fill_price") or 0)
        _telegram(
            f"✅ *Butterfly complete* {state['ticker']}\n"
            f"Debit net `${state['debit_fill_price']:.2f}` Credit net `${state['credit_fill_price']:.2f}`\n"
            f"Locked-in net credit `${net_credit:.2f}` × {state['contracts']} × ${MULTIPLIER} "
            f"= guaranteed profit ≥ `${net_credit * state['contracts'] * MULTIPLIER:.0f}`"
        )
        return

    legged_at = datetime.fromisoformat(state["credit_legged_at"])
    elapsed = (datetime.now(timezone.utc) - legged_at).total_seconds()
    if elapsed < LEG_FILL_TIMEOUT_S:
        return

    short_conid = state["credit_conids"]["short"]
    long_conid = state["credit_conids"]["long"]
    qty = state["contracts"]

    if short_filled and not long_filled:
        try: client.cancel_order(state["credit_long_oid"])
        except Exception: pass
        _close_leg_at_market(client, short_conid, "BUY", qty)
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _quiet(f"🦋 *Partial credit fill* — bought back orphan short at market, moving to salvage")
        return
    if long_filled and not short_filled:
        try: client.cancel_order(state["credit_short_oid"])
        except Exception: pass
        _close_leg_at_market(client, long_conid, "SELL", qty)
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _quiet(f"🦋 *Partial credit fill* — sold orphan long at market, moving to salvage")
        return

    # Neither filled
    try: client.cancel_order(state["credit_short_oid"])
    except Exception: pass
    try: client.cancel_order(state["credit_long_oid"])
    except Exception: pass

    if _now_et_hhmm() >= CREDIT_WINDOW_END_ET:
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _quiet(f"🦋 *Credit unfilled by {CREDIT_WINDOW_END_ET}* — moving to salvage")
    else:
        # Walk down the credit limit by $0.05 and retry
        state["credit_current_step"] += 1
        if state["credit_current_step"] * CREDIT_STEP >= (state["credit_target"] - CREDIT_FLOOR):
            state["phase"] = "SALVAGE"
            _save(rdb, bid, state)
            _quiet(f"🦋 *Credit floor hit* (after {state['credit_current_step']} steps) — salvage")
        else:
            state["phase"] = "WATCHING"
            _save(rdb, bid, state)
            _quiet(f"🦋 Credit no-fill, re-evaluating ({state['credit_current_step']}/$.05 steps)")


def _phase_salvage(client, rdb, state):
    """Close the held debit spread at market — recover value before cash settlement."""
    bid = state["butterfly_id"]
    long_conid = state["debit_conids"]["long"]
    short_conid = state["debit_conids"]["short"]
    qty = state["contracts"]
    if long_conid:
        _close_leg_at_market(client, long_conid, "SELL", qty)
    if short_conid:
        _close_leg_at_market(client, short_conid, "BUY", qty)
    state["phase"] = "ABANDONED"
    state["abandon_reason"] = "credit never filled — closed debit at market"
    _save(rdb, bid, state)
    _telegram(f"🦋 *Salvage* sold debit spread at market")


_startup_cleanup_done = False


def cleanup_expired_butterflies(rdb):
    """One-shot at process startup: mark any non-terminal butterfly whose
    0DTE expiry day is in the past as EXPIRED_UNRESOLVED. Prevents the
    worker from continuing to tick on stale WATCHING/QUEUED state after
    a restart spans an expiry boundary."""
    global _startup_cleanup_done
    if _startup_cleanup_done:
        return
    _startup_cleanup_done = True
    try:
        today_et = (datetime.now(timezone.utc)
                    + timedelta(hours=-4)).strftime("%Y%m%d")
        keys = list(rdb.scan_iter(PHASE_KEY_PREFIX + "*"))
    except Exception as e:
        logger.warning("butterfly cleanup scan failed: %s", e)
        return
    for key in keys:
        try:
            raw = rdb.get(key)
            if not raw:
                continue
            state = json.loads(raw)
            phase = state.get("phase", "")
            if phase in ("COMPLETE", "ABANDONED", "EXPIRED_UNRESOLVED"):
                continue
            queued_at = state.get("queued_at", "")
            if not queued_at:
                continue
            queued_et = (datetime.fromisoformat(queued_at.replace("Z", "+00:00"))
                         + timedelta(hours=-4))
            queued_day = queued_et.strftime("%Y%m%d")
            if queued_day >= today_et:
                continue
            state["phase"] = "EXPIRED_UNRESOLVED"
            state["abandon_reason"] = (
                f"startup cleanup: queued {queued_day} but today is "
                f"{today_et}; 0DTE has already settled"
            )
            _save(rdb, state["butterfly_id"], state)
            try:
                from .ibkr_sync_cpapi import _send_telegram_alert
                _send_telegram_alert(
                    "🧹 ORB butterfly auto-cleaned",
                    f"Worker restart found stale butterfly "
                    f"{state['butterfly_id']} in phase {phase}, queued "
                    f"{queued_day}. Marked EXPIRED_UNRESOLVED. Check IB "
                    f"for residual positions from this butterfly.",
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning("butterfly cleanup error on %s: %s", key, e)


def process_butterflies(client, rdb, spx_price_fn=None):
    """Drive every active butterfly one tick forward."""
    cleanup_expired_butterflies(rdb)
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
                _phase_queued(client, rdb, state)
            elif phase == "DEBIT_LEGGED":
                _phase_debit_legged(client, rdb, state)
            elif phase == "WATCHING":
                _phase_watching(client, rdb, state, spx_price)
            elif phase == "CREDIT_LEGGED":
                _phase_credit_legged(client, rdb, state)
            elif phase == "SALVAGE":
                _phase_salvage(client, rdb, state)
            # COMPLETE / ABANDONED — terminal
        except Exception as e:
            logger.warning("butterfly process error on %s: %s", key, e)
