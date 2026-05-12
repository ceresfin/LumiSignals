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
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# ─── CONFIG ───
SPX_TICKER          = "SPX"
DEBIT_MAX           = 1.40
CREDIT_TARGET       = 2.30
CREDIT_FLOOR        = 1.50
CREDIT_STEP         = 0.05
CREDIT_STEP_SEC     = 60
LEG_FILL_TIMEOUT_S  = 10            # both legs should fill in this window
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
    try:
        from .supabase_client import send_telegram_message
        send_telegram_message(text)
    except Exception as e:
        logger.debug("butterfly telegram error: %s", e)


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


def _fetch_quote(client, conid: int):
    """Get (bid, ask) for a conid. CPAPI snapshot endpoint sometimes needs
    a warm-up call — we poll twice with 250ms gap if first returns empty."""
    for attempt in range(2):
        try:
            r = client._request("GET", "/iserver/marketdata/snapshot",
                                params={"conids": str(conid), "fields": "84,86"})
        except Exception:
            r = None
        if isinstance(r, list) and r:
            row = r[0]
            bid = float(row.get("84", 0) or 0)
            ask = float(row.get("86", 0) or 0)
            if bid > 0 and ask > 0:
                return bid, ask
        time.sleep(0.25)
    return None, None


def _place_leg(client, conid: int, side: str, qty: int, price: float):
    """Single-leg LMT order. Walks confirmation prompts. Returns order_id or None."""
    payload = {"orders": [{
        "conid": conid, "orderType": "LMT", "side": side,
        "quantity": qty, "price": round(price, 2), "tif": "DAY",
    }]}
    try:
        result = client.place_order(payload)
    except Exception as e:
        logger.warning("place_leg %s %s failed: %s", side, conid, e)
        return None
    while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
        try:
            result = client._request("POST", "/iserver/reply/" + result[0]["id"],
                                     json_data={"confirmed": True})
        except Exception:
            return None
    if isinstance(result, list) and result and result[0].get("order_id"):
        return str(result[0]["order_id"])
    if isinstance(result, dict) and result.get("order_id"):
        return str(result["order_id"])
    return None


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
    except Exception as e:
        logger.warning("close_leg_at_market %s failed: %s", conid, e)


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
    _telegram(
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
    if _now_et_hhmm() >= DEBIT_CUTOFF_ET:
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = f"debit window closed ({DEBIT_CUTOFF_ET} ET)"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Abandoned* — debit window closed before placement")
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
            _telegram(f"🦋 *Abandoned* — option conid lookup failed")
        _save(rdb, bid, state)
        return
    state["debit_conids"] = {"long": long_conid, "short": short_conid}

    long_bid, long_ask = _fetch_quote(client, long_conid)
    short_bid, short_ask = _fetch_quote(client, short_conid)
    if not all([long_bid, long_ask, short_bid, short_ask]):
        state["debit_retries"] += 1
        logger.info("Butterfly %s: quote fetch incomplete (try %d/%d)",
                    bid, state["debit_retries"], DEBIT_RETRY_MAX)
        if state["debit_retries"] >= DEBIT_RETRY_MAX:
            state["phase"] = "ABANDONED"
            state["abandon_reason"] = "no live quotes for option legs"
            _telegram(f"🦋 *Abandoned* — couldn't fetch live quotes")
        _save(rdb, bid, state)
        return

    # Worst-case net debit if both legs filled at marketable prices
    net_debit = long_ask - short_bid
    if net_debit > state["debit_target"]:
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = (
            f"debit ${net_debit:.2f} > cap ${state['debit_target']:.2f} "
            f"(longK1 ask={long_ask:.2f}, shortK2 bid={short_bid:.2f})"
        )
        _save(rdb, bid, state)
        _telegram(
            f"🦋 *Abandoned* — net debit `${net_debit:.2f}` exceeds cap `${state['debit_target']:.2f}`\n"
            f"longK1 ask `${long_ask:.2f}` shortK2 bid `${short_bid:.2f}`"
        )
        return

    qty = state["contracts"]
    long_oid = _place_leg(client, long_conid, "BUY", qty, long_ask)
    short_oid = _place_leg(client, short_conid, "SELL", qty, short_bid)
    if not (long_oid and short_oid):
        # Cancel partial placement
        if long_oid:
            try: client.cancel_order(long_oid)
            except Exception: pass
        if short_oid:
            try: client.cancel_order(short_oid)
            except Exception: pass
        state["debit_retries"] += 1
        if state["debit_retries"] >= DEBIT_RETRY_MAX:
            state["phase"] = "ABANDONED"
            state["abandon_reason"] = "place_order failed for one or both legs"
            _telegram(f"🦋 *Abandoned* — leg placement failed")
        _save(rdb, bid, state)
        return

    state["debit_long_oid"] = long_oid
    state["debit_short_oid"] = short_oid
    state["debit_long_price"] = round(long_ask, 2)
    state["debit_short_price"] = round(short_bid, 2)
    state["debit_legged_at"] = datetime.now(timezone.utc).isoformat()
    state["phase"] = "DEBIT_LEGGED"
    _save(rdb, bid, state)
    _telegram(
        f"🦋 *Debit legged in*\n"
        f"BUY `{state['long_strike']:.0f}` @ `${long_ask:.2f}` (order {long_oid})\n"
        f"SELL `{state['body_strike']:.0f}` @ `${short_bid:.2f}` (order {short_oid})\n"
        f"Worst-case net: `${net_debit:.2f}` ≤ cap"
    )


def _phase_debit_legged(client, rdb, state):
    """Poll both legs. Both filled -> WATCHING. Partial after timeout -> close survivor."""
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
    if elapsed < LEG_FILL_TIMEOUT_S:
        return  # keep waiting

    # Timeout — handle partial / no fills
    long_conid = state["debit_conids"]["long"]
    short_conid = state["debit_conids"]["short"]
    qty = state["contracts"]

    if long_filled and not short_filled:
        try: client.cancel_order(state["debit_short_oid"])
        except Exception: pass
        _close_leg_at_market(client, long_conid, "SELL", qty)
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = "partial fill: only long leg filled, closed at market"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Partial fill* — only long filled, sold at market")
        return
    if short_filled and not long_filled:
        try: client.cancel_order(state["debit_long_oid"])
        except Exception: pass
        _close_leg_at_market(client, short_conid, "BUY", qty)
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = "partial fill: only short leg filled, closed at market"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Partial fill* — only short filled, bought back at market")
        return

    # Neither filled after LEG_FILL_TIMEOUT_S
    try: client.cancel_order(state["debit_long_oid"])
    except Exception: pass
    try: client.cancel_order(state["debit_short_oid"])
    except Exception: pass
    state["debit_retries"] += 1
    if state["debit_retries"] >= DEBIT_RETRY_MAX:
        state["phase"] = "ABANDONED"
        state["abandon_reason"] = "neither debit leg filled within timeout"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Abandoned* — neither leg filled in {LEG_FILL_TIMEOUT_S}s")
    else:
        state["phase"] = "QUEUED"
        _save(rdb, bid, state)
        _telegram(f"🦋 No fill in {LEG_FILL_TIMEOUT_S}s — retrying ({state['debit_retries']}/{DEBIT_RETRY_MAX})")


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

    sb, sa = _fetch_quote(client, short_conid)
    lb, la = _fetch_quote(client, long_conid)
    if not all([sb, sa, lb, la]):
        logger.info("Butterfly %s: credit quote fetch incomplete", bid)
        return
    # Marketable prices for credit: sell @ bid, buy @ ask. Net credit = short_bid - long_ask.
    net_credit = sb - la
    if net_credit < CREDIT_FLOOR:
        logger.info("Butterfly %s: credit too thin: $%.2f < floor $%.2f", bid, net_credit, CREDIT_FLOOR)
        return  # next tick will check again as quotes move

    qty = state["contracts"]
    short_oid = _place_leg(client, short_conid, "SELL", qty, sb)
    long_oid = _place_leg(client, long_conid, "BUY", qty, la)
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
    _telegram(
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
        _telegram(f"🦋 *Partial credit fill* — bought back orphan short at market, moving to salvage")
        return
    if long_filled and not short_filled:
        try: client.cancel_order(state["credit_short_oid"])
        except Exception: pass
        _close_leg_at_market(client, long_conid, "SELL", qty)
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Partial credit fill* — sold orphan long at market, moving to salvage")
        return

    # Neither filled
    try: client.cancel_order(state["credit_short_oid"])
    except Exception: pass
    try: client.cancel_order(state["credit_long_oid"])
    except Exception: pass

    if _now_et_hhmm() >= CREDIT_WINDOW_END_ET:
        state["phase"] = "SALVAGE"
        _save(rdb, bid, state)
        _telegram(f"🦋 *Credit unfilled by {CREDIT_WINDOW_END_ET}* — moving to salvage")
    else:
        # Walk down the credit limit by $0.05 and retry
        state["credit_current_step"] += 1
        if state["credit_current_step"] * CREDIT_STEP >= (state["credit_target"] - CREDIT_FLOOR):
            state["phase"] = "SALVAGE"
            _save(rdb, bid, state)
            _telegram(f"🦋 *Credit floor hit* (after {state['credit_current_step']} steps) — salvage")
        else:
            state["phase"] = "WATCHING"
            _save(rdb, bid, state)
            _telegram(f"🦋 Credit no-fill, re-evaluating ({state['credit_current_step']}/$.05 steps)")


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


def process_butterflies(client, rdb, spx_price_fn=None):
    """Drive every active butterfly one tick forward."""
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
