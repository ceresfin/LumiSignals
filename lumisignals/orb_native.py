"""Native Opening-Range-Breakout (ORB) signal generator — server-side, from IB.

ONE trigger — the MES/ES breakout of the first 15-minute opening range
(9:30–9:45 ET) — fires TWO trades:
  • a MES futures bracket   (strategy "orb_breakout") via the normal order queue
  • an SPX 0DTE leg-in butterfly (strategy "orb_butterfly") via queue_butterfly,
    whose state machine (orb_butterfly_handler) already executes it.

This module only GENERATES the trigger (OR tracking, breakout, VIX-aware stop,
strike math) — execution is the existing, unchanged paths. Behaviour is governed
at runtime by the Redis flag `ibkr:orb:source` (tradingview | shadow | native |
off); when `native`, the TradingView ORB alerts are ignored by the webhook.

Data: MES bars from `ibkr:bars:MES:2m` (IB real-time); SPX opening-range bars
from IB `get_historical_bars` on the SPX index conid; VIX from Polygon `I:VIX`
latest 15-min bar (IB doesn't expose VIX).
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import redis as _redis
import requests

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CPAPI_BASE_URL = os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api")
_rdb_singleton = None


def _rdb():
    global _rdb_singleton
    if _rdb_singleton is None:
        _rdb_singleton = _redis.from_url(REDIS_URL)
    return _rdb_singleton


# ── ORB parameters (from the Pine) ──────────────────────────────────────────
MES_TICKER = "MES"
OR_START = 930          # 9:30 ET
OR_END = 945            # 9:45 ET (exclusive)
ENTRY_END = 1100        # last entry 11:00 ET
REVERSAL_END = 1115     # reversal allowed until 11:15 ET
OFFSET = 0.50           # breakout offset, points
TARGET_PTS = 20.0       # +20 from entry
VIX_THRESHOLD = 25.0
LOW_VOL_STOP = 4.0      # fixed stop when VIX < 25
MAX_RANGE_STOP = 20.0   # if OR range > this, use range/2
# butterfly strike offsets from the SPX OR edge (rounded to $5)
BF_K1, BF_K2, BF_K3 = 10, 15, 20
BF_DEBIT_TARGET = 1.50
BF_CREDIT_TARGET = 2.30


def _et_now():
    now = datetime.now(timezone.utc)
    # DST-approx (Mar–Oct EDT). Matches the convention used elsewhere in the bot.
    return now + timedelta(hours=-4 if now.month in (3, 4, 5, 6, 7, 8, 9, 10) else -5)


def _round5(x):
    return round(x / 5.0) * 5.0


class ORBNative:
    """Detects the OR breakout once per session and fans it out to both legs."""

    def __init__(self, massive_key, signal_callback=None, contract_count=1):
        self.massive_key = massive_key
        self.signal_callback = signal_callback
        self.contract_count = max(1, int(contract_count or 1))
        self._spx_conid = None
        self._scan_count = 0

    # ── runtime source switch ──
    def _source(self):
        try:
            v = _rdb().get("ibkr:orb:source")
            if v:
                return v.decode().strip().lower()
        except Exception:
            pass
        return "tradingview"

    # ── per-day state ──
    def _state_key(self):
        return "ibkr:orb:state:" + _et_now().strftime("%Y-%m-%d")

    def _load_state(self):
        try:
            raw = _rdb().get(self._state_key())
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return {
            "or_built": False,
            "mes_or_high": None, "mes_or_low": None,
            "spx_or_high": None, "spx_or_low": None,
            "trades_taken": 0, "first_dir": None, "stopped_out": False,
            "first_entry": None,
        }

    def _save_state(self, state):
        try:
            _rdb().setex(self._state_key(), 86400, json.dumps(state))
        except Exception as e:
            logger.debug("[ORB] state save failed: %s", e)

    # ── data ──
    def _mes_bars(self):
        """Closed 2m MES bars from the IB-pushed cache (drop the forming last)."""
        try:
            resp = requests.get(
                f"{os.environ.get('LUMISIGNALS_URL', 'https://bot.lumitrade.ai')}/api/ibkr/futures-bars/{MES_TICKER}",
                headers={"X-Sync-Key": os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")},
                timeout=5)
            if resp.ok:
                bars = resp.json().get("bars", [])
                return bars[:-1] if len(bars) > 1 else bars
        except Exception as e:
            logger.debug("[ORB] MES bars fetch failed: %s", e)
        return []

    def _resolve_spx(self, client):
        if self._spx_conid:
            return self._spx_conid
        for st in ("IND", "STK"):
            try:
                r = client.search_contract("SPX", st) or []
                if r and r[0].get("conid"):
                    self._spx_conid = int(r[0]["conid"])
                    return self._spx_conid
            except Exception:
                continue
        return None

    def _spx_bars(self):
        """Real-time SPX index 1-min bars from IB (for the SPX OR / strikes)."""
        try:
            from lumisignals.ibkr_cpapi import CPAPIClient
            client = CPAPIClient(base_url=CPAPI_BASE_URL)
            try:
                client.ensure_session()
            except Exception:
                pass
            conid = self._resolve_spx(client)
            if not conid:
                return []
            return client.get_historical_bars(conid, period="1d", bar="1min",
                                               outside_rth=False) or []
        except Exception as e:
            logger.debug("[ORB] SPX bars fetch failed: %s", e)
            return []

    def _vix(self):
        """Latest 15-min Polygon VIX close (intraday)."""
        try:
            from lumisignals.massive_client import get_shared_client
            v = get_shared_client(self.massive_key).get_candles("I:VIX", "15m", 5) or []
            if v:
                return float(v[-1].close)
        except Exception as e:
            logger.debug("[ORB] VIX fetch failed: %s", e)
        return None

    @staticmethod
    def _or_from_bars(bars):
        """High/low over the 9:30–9:45 ET window of the most recent session date."""
        et = _et_now().date()
        hi = lo = None
        for b in bars:
            try:
                t = b["time"] if isinstance(b, dict) else b.get("time")
                dt = datetime.fromtimestamp(float(t), tz=timezone.utc) + timedelta(
                    hours=-4 if datetime.now(timezone.utc).month in range(3, 11) else -5)
            except Exception:
                continue
            if dt.date() != et:
                continue
            hhmm = dt.hour * 100 + dt.minute
            if OR_START <= hhmm < OR_END:
                h = float(b["high"]); lo_ = float(b["low"])
                hi = h if hi is None else max(hi, h)
                lo = lo_ if lo is None else min(lo, lo_)
        return hi, lo

    def _build_or(self, state):
        mes_hi, mes_lo = self._or_from_bars(self._mes_bars())
        spx_hi, spx_lo = self._or_from_bars(self._spx_bars())
        if mes_hi is None or mes_lo is None:
            logger.info("[ORB] OR not ready — no MES bars in 9:30-9:45 window yet")
            return
        state["mes_or_high"], state["mes_or_low"] = mes_hi, mes_lo
        state["spx_or_high"], state["spx_or_low"] = spx_hi, spx_lo
        state["or_built"] = True
        logger.info("[ORB] OR built — MES %.2f/%.2f (range %.2f), SPX %s/%s",
                    mes_hi, mes_lo, mes_hi - mes_lo, spx_hi, spx_lo)

    # ── main loop ──
    def scan(self):
        self._scan_count += 1
        source = self._source()
        if source not in ("native", "shadow"):
            return
        et = _et_now()
        if et.weekday() >= 5:
            return
        hhmm = et.hour * 100 + et.minute
        if hhmm < OR_START or hhmm > REVERSAL_END:
            return  # only active in the morning OR/entry/reversal windows

        state = self._load_state()
        if hhmm >= OR_END and not state.get("or_built"):
            self._build_or(state)
        if state.get("or_built"):
            if state["trades_taken"] >= 1 and not state.get("stopped_out"):
                self._update_first_outcome(state)
            if state["trades_taken"] < 2:
                self._check_breakout(state, hhmm, source)
        self._save_state(state)

    def _update_first_outcome(self, state):
        """Decide whether the first MES trade stopped out (→ reversal armed) or
        hit target. Guards against placement lag via `first_pos_seen`: only
        treats a missing strat_pos as 'closed' once we've actually seen it open.
        Stop vs target inferred from the last MES close vs the entry."""
        try:
            open_now = bool(_rdb().get(f"ibkr:strat_pos:{MES_TICKER}:orb_breakout"))
        except Exception:
            return
        if open_now:
            state["first_pos_seen"] = True
            return
        if not state.get("first_pos_seen"):
            return  # not yet established (placement lag) — wait
        bars = self._mes_bars()
        fe, fd = state.get("first_entry"), state.get("first_dir")
        if not bars or fe is None:
            return
        close = float(bars[-1]["close"])
        stopped = (close < fe) if fd == "BUY" else (close > fe)
        state["stopped_out"] = bool(stopped)
        if stopped:
            logger.info("[ORB] first trade (%s @ %.2f) closed at a loss — reversal armed", fd, fe)

    def _check_breakout(self, state, hhmm, source):
        bars = self._mes_bars()
        if not bars:
            return
        close = float(bars[-1]["close"])
        hi, lo = state["mes_or_high"], state["mes_or_low"]
        first = state["trades_taken"] == 0

        # First trade (entry window) — break either side.
        if first and hhmm <= ENTRY_END:
            if close > hi + OFFSET:
                self._fire("BUY", hi + OFFSET, state, source, reversal=False)
            elif close < lo - OFFSET:
                self._fire("SELL", lo - OFFSET, state, source, reversal=False)
            return

        # Reversal (one, opposite of a stopped-out first trade) until 11:15.
        if (not first and state.get("stopped_out")
                and state["trades_taken"] < 2 and hhmm <= REVERSAL_END):
            if state["first_dir"] == "SELL" and close > hi + OFFSET:
                self._fire("BUY", hi + OFFSET, state, source, reversal=True)
            elif state["first_dir"] == "BUY" and close < lo - OFFSET:
                self._fire("SELL", lo - OFFSET, state, source, reversal=True)

    def _vix_stop(self, or_range, vix):
        if vix is not None and vix < VIX_THRESHOLD:
            return LOW_VOL_STOP, f"VIX<25 fixed {LOW_VOL_STOP:.1f}pts"
        if or_range > MAX_RANGE_STOP:
            return or_range / 2, f"VIX>=25 range/2 {or_range / 2:.1f}pts"
        return or_range, f"VIX>=25 full range {or_range:.1f}pts"

    def _fire(self, direction, entry, state, source, reversal):
        vix = self._vix()
        or_range = state["mes_or_high"] - state["mes_or_low"]
        stop_size, stop_reason = self._vix_stop(or_range, vix)
        if direction == "BUY":
            stop_price = entry - stop_size
            target_price = entry + TARGET_PTS
        else:
            stop_price = entry + stop_size
            target_price = entry - TARGET_PTS

        self._record_parity(direction, entry, stop_price, target_price, reversal,
                            traded=(source == "native"))

        if source != "native":
            logger.info("[ORB SHADOW] %s entry=%.2f stop=%.2f tgt=%.2f reversal=%s (no orders)",
                        direction, entry, stop_price, target_price, reversal)
            state["trades_taken"] += 1
            if state["first_dir"] is None:
                state["first_dir"] = direction
                state["first_entry"] = entry
            return

        # Gate then queue the MES bracket (same path as 2n20/webhook).
        try:
            from lumisignals.futures_gates import check_futures_action
            allowed, reason, detail = check_futures_action(
                "orb_breakout", MES_TICKER, direction, self.contract_count)
            if not allowed:
                logger.info("[ORB] MES %s blocked by gate: %s %s", direction, reason, detail)
                return
        except Exception as e:
            logger.warning("[ORB] gate check failed (skipping): %s", e)
            return

        rdb = _rdb()
        oid = str(uuid.uuid4())[:8]
        order = {
            "order_id": oid, "queued_at": datetime.now(timezone.utc).isoformat(),
            "user_id": 1, "ticker": MES_TICKER, "type": "futures",
            "direction": direction, "strategy": "orb_breakout",
            "contracts": self.contract_count, "status": "queued",
            "auto": True, "signal_action": direction,
            "entry_price": round(entry, 2), "stop_price": round(stop_price, 2),
            "target_price": round(target_price, 2),
            "vix": vix, "or_high": state["mes_or_high"], "or_low": state["mes_or_low"],
            "or_range": round(or_range, 2), "stop_size": round(stop_size, 2),
            "stop_reason": stop_reason, "reversal": reversal,
        }
        rdb.setex(f"ibkr:order:pending:{oid}", 86400, json.dumps(order))
        logger.info("[ORB] MES %s queued entry=%.2f stop=%.2f tgt=%.2f (%s) rev=%s",
                    direction, entry, stop_price, target_price, stop_reason, reversal)

        # Fan out the SPX 0DTE butterfly off the SAME trigger.
        self._fire_butterfly(direction, state, vix, reversal)

        state["trades_taken"] += 1
        if state["first_dir"] is None:
            state["first_dir"] = direction
            state["first_entry"] = entry
        if self.signal_callback:
            try:
                self.signal_callback({"direction": direction, "ticker": MES_TICKER,
                                     "strategy": "orb_breakout", "reason": stop_reason})
            except Exception:
                pass

    def _fire_butterfly(self, direction, state, vix, reversal):
        spx_hi, spx_lo = state.get("spx_or_high"), state.get("spx_or_low")
        if not spx_hi or not spx_lo:
            logger.warning("[ORB] no SPX OR — skipping butterfly leg")
            return
        if direction == "BUY":
            spread_type, edge, sign = "call", spx_hi, 1
        else:
            spread_type, edge, sign = "put", spx_lo, -1
        k1 = _round5(edge + sign * BF_K1)
        k2 = _round5(edge + sign * BF_K2)
        k3 = _round5(edge + sign * BF_K3)
        try:
            from lumisignals.orb_butterfly_handler import queue_butterfly
            bid = queue_butterfly(_rdb(), {
                "ticker": "SPX", "strategy": "orb_butterfly", "type": "options",
                "direction": direction, "spread_type": spread_type,
                "long_strike": k1, "body_strike": k2, "wing_strike": k3,
                "expiry": "0DTE", "contracts": self.contract_count,
                "debit_target": BF_DEBIT_TARGET, "credit_target": BF_CREDIT_TARGET,
                "vix": vix, "spx_or_high": spx_hi, "spx_or_low": spx_lo,
                "reversal": reversal,
            })
            logger.info("[ORB] butterfly queued %s K1/K2/K3=%s/%s/%s id=%s",
                        spread_type, k1, k2, k3, bid)
        except Exception as e:
            logger.error("[ORB] butterfly queue failed: %s", e)

    def _record_parity(self, direction, entry, stop, target, reversal, traded):
        rec = {
            "direction": direction, "entry": round(entry, 2),
            "stop": round(stop, 2), "target": round(target, 2),
            "reversal": reversal, "traded": bool(traded),
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            rdb = _rdb()
            rdb.lpush("ibkr:orb:native", json.dumps(rec))
            rdb.ltrim("ibkr:orb:native", 0, 99)
        except Exception:
            pass
