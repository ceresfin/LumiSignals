"""2n20 Overwhelm Scalp Strategy for MES Futures — server-side detection.

Mirrors the TradingView Pine Script logic but runs entirely on the server
using Polygon 2-minute candle data. Orders are enqueued directly into Redis
(`ibkr:order:pending:{order_id}`) for the local IB sync to pick up — no HTTP
self-loop through the deprecated TradingView webhook.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, Optional, Tuple

import redis as _redis
import requests

from .overwhelm_detector import detect_overwhelm, detect_vwap_cross

logger = logging.getLogger(__name__)

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
SYNC_KEY = os.environ.get("IBKR_SYNC_KEY", "ibkr_sync_2026")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_rdb_singleton = None


def _rdb():
    global _rdb_singleton
    if _rdb_singleton is None:
        _rdb_singleton = _redis.from_url(REDIS_URL)
    return _rdb_singleton

# Config
TICKER = "MES"
GRANULARITY = 2  # 2-minute candles
CANDLE_COUNT = 15
MIN_BODY_PCT = 30.0
AVG_BODY_MULT = 0.8
LOOKBACK_BARS = 3
SCAN_INTERVAL = 120  # Check every 2 minutes (aligned with candle close)
BAR_STALE_SECONDS = 180  # Skip scan if bars haven't been pushed within this window


@dataclass
class FuturesScalpState:
    """Tracks state for the MES 2n20 strategy."""
    in_long: bool = False
    in_short: bool = False
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None


class FuturesScalp2n20:
    """2n20 Overwhelm Scalp for MES Futures — server-side."""

    def __init__(self, polygon_key: str, signal_callback=None, contract_count: int = 1):
        self.polygon_key = polygon_key
        self.signal_callback = signal_callback
        self.contract_count = max(1, int(contract_count or 1))
        self.state = FuturesScalpState()
        # Shadow state tracks the strategy's OWN hypothetical entry→exit lifecycle
        # independently of the live (TV-driven) broker position, so shadow mode can
        # log a full native signal stream for parity comparison without trading.
        self.shadow_state = FuturesScalpState()
        self._seeded = False
        self._last_scan_time: Optional[datetime] = None
        self._last_candle_time: str = ""
        self._last_drift_alert: Optional[datetime] = None

    # ── runtime source switch ──────────────────────────────────────────────
    # `ibkr:mes_2n20:source` ∈ {tradingview (default), shadow, native, off}.
    # Read every scan so the source can be flipped live with no restart, and TV
    # can't double-trade with native. Mirrors the equity:orders_enabled flag.
    def _source(self) -> str:
        try:
            v = _rdb().get("ibkr:mes_2n20:source")
            if v:
                return v.decode().strip().lower()
        except Exception:
            pass
        return "tradingview"

    def _ensure_seeded(self):
        """Seed the live (native) state from the broker once, so a bot restart
        mid-position neither re-enters nor abandons exit management. Ported from
        fx_scalp_2n20._init_states_from_broker."""
        if self._seeded:
            return
        self._seeded = True
        try:
            broker = self._get_broker_position()
            pos = int(broker.get("position", 0)) if broker else 0
            if pos != 0:
                self.state.in_long = pos > 0
                self.state.in_short = pos < 0
                try:
                    raw = _rdb().get(f"ibkr:strat_pos:{TICKER}:futures_2n20")
                    if raw:
                        sp = json.loads(raw)
                        self.state.entry_price = float(sp.get("entry_price", 0) or 0)
                except Exception:
                    pass
                logger.info("[2n20_MES] state seeded from broker: %s pos=%d @ %.2f",
                            "LONG" if pos > 0 else "SHORT", pos, self.state.entry_price)
        except Exception as e:
            logger.warning("[2n20_MES] state seed failed: %s", e)

    def _log_shadow_signal(self, kind: str, direction: str, reason: str,
                           bar_time, price, vwap):
        """Record a would-be native signal (no order) for shadow validation."""
        rec = {
            "kind": kind, "direction": direction, "reason": reason,
            "bar_time": bar_time, "price": price, "vwap": vwap,
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("[2n20_MES SHADOW] %s %s @ %.2f vwap=%s reason=%s bar=%s",
                    kind, direction, price or 0,
                    ("%.2f" % vwap) if vwap else "-", reason, bar_time)
        try:
            rdb = _rdb()
            rdb.lpush("ibkr:mes_2n20:shadow", json.dumps(rec))
            rdb.ltrim("ibkr:mes_2n20:shadow", 0, 199)  # keep last 200
        except Exception:
            pass

    def _do_entry(self, source: str, direction: str, price: float, bar_time, vwap):
        if source == "shadow":
            self.shadow_state.in_long = direction == "BUY"
            self.shadow_state.in_short = direction == "SELL"
            self.shadow_state.entry_price = price
            self.shadow_state.entry_time = datetime.now(timezone.utc)
            self._log_shadow_signal("ENTRY", direction, "overwhelm", bar_time, price, vwap)
        else:
            self._send_entry(direction, price)

    def _do_close(self, source: str, reason: str, bar_time, price, vwap):
        if source == "shadow":
            side = "CLOSE_LONG" if self.shadow_state.in_long else "CLOSE_SHORT"
            self._log_shadow_signal("EXIT", side, reason, bar_time, price, vwap)
            self.shadow_state.in_long = False
            self.shadow_state.in_short = False
            self.shadow_state.entry_price = 0.0
            self.shadow_state.entry_time = None
        else:
            self._send_close(reason)

    def _get_broker_position(self) -> Optional[dict]:
        """Fetch current MES position from the broker's last sync snapshot.

        Returns dict with keys connected/position/avg_cost on success, None on error.
        Position is signed: +N long, -N short, 0 flat.
        """
        try:
            resp = requests.get(
                f"{SERVER_URL}/api/ibkr/futures-position/{TICKER}",
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=5,
            )
            if resp.ok:
                return resp.json()
        except Exception as e:
            logger.debug("broker position fetch failed: %s", e)
        return None

    def _alert_drift(self, message: str):
        """Send a state-drift alert (rate-limited to 1/5min)."""
        now = datetime.now(timezone.utc)
        if self._last_drift_alert and (now - self._last_drift_alert).total_seconds() < 300:
            logger.warning("[2n20 DRIFT] %s (alert rate-limited)", message)
            return
        self._last_drift_alert = now
        logger.warning("[2n20 DRIFT] %s", message)
        try:
            from lumisignals.alerts import send_alert, AlertType
            alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
            if alert_pass:
                send_alert(AlertType.BOT_ERROR, "2n20 MES state drift",
                           message, smtp_pass=alert_pass)
        except Exception:
            pass

    def scan(self):
        """Check for 2n20 signals. Call every ~30 seconds."""
        # Heartbeat — confirms scan is being called even if all paths skip silently
        self._scan_call_count = getattr(self, "_scan_call_count", 0) + 1
        if self._scan_call_count % 10 == 1:
            logger.info("[2n20_MES] scan tick #%d source=%s (state in_long=%s in_short=%s)",
                        self._scan_call_count, self._source(),
                        self.state.in_long, self.state.in_short)

        # Runtime source switch: only act when native or shadow; otherwise the
        # TradingView webhook owns 2n20 and we stay idle.
        source = self._source()
        if source not in ("native", "shadow"):
            return
        self._ensure_seeded()
        st = self.shadow_state if source == "shadow" else self.state

        try:
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo("America/New_York")
        except Exception:
            et_tz = timezone(timedelta(hours=-4))  # EDT fallback
        now = datetime.now(timezone.utc)
        now_et = now.astimezone(et_tz)
        et_hour, et_minute, weekday = now_et.hour, now_et.minute, now_et.weekday()

        # CME maintenance break: 17:00-18:00 ET daily
        if et_hour == 17:
            return
        # Daily session close: flatten at 16:59 ET (every weekday Mon-Fri).
        # Matches Pine: avoids holding through the maintenance break.
        if weekday < 5 and et_hour == 16 and et_minute == 59:
            if st.in_long or st.in_short:
                self._do_close(source, "Session close", None, None, None)
            return
        # Skip weekends
        if weekday == 5:  # Saturday
            return
        if weekday == 6 and et_hour < 18:  # Sunday before Globex open
            return

        # Get 2-minute candles from server (IB-pushed, MES front month)
        candles = self._get_candles()
        if not candles or len(candles) < 13:
            return

        # IB historical bars can keep updating with late prints for ~30-60s after
        # bar close. Process bars[-2] (the second-to-last) which is guaranteed
        # finalized because bar -1 already exists after it. This is the same
        # semantic as Pine's `freq_once_per_bar_close`. Trade-off: ~2 min added
        # lag vs evaluating the still-settling bar; benefit: no false negatives
        # like bar 23:48 (body=0.50 partial, grew to 0.75 final).
        candles = candles[:-1]

        # Per-bar dedup: process each bar exactly once.
        last_time = candles[-1].get("time", "")
        if last_time == self._last_candle_time:
            return
        self._last_candle_time = last_time

        # Calculate VWAP
        vwap = self._calc_vwap(candles)
        if vwap is None:
            logger.info("[2n20_MES] scan: VWAP None (outside session) at bar %s", last_time)
            return

        curr = candles[-1]
        close = curr["close"]
        above_vwap = close > vwap
        below_vwap = close < vwap

        # Detect overwhelm using shared detector
        green_overwhelm, red_overwhelm = detect_overwhelm(candles)
        logger.info("[2n20_MES] %s bar=%s close=%.2f vwap=%.2f above=%s below=%s green_ow=%s red_ow=%s in_long=%s in_short=%s",
                    source, last_time, close, vwap, above_vwap, below_vwap,
                    green_overwhelm, red_overwhelm,
                    st.in_long, st.in_short)

        # VWAP cross using shared detector
        crossed_below_vwap, crossed_above_vwap = detect_vwap_cross(candles, vwap)

        # --- EXIT LOGIC ---
        if st.in_long:
            if red_overwhelm:
                self._do_close(source, "Red Takeout Green", last_time, close, vwap)
            elif crossed_below_vwap:
                self._do_close(source, "VWAP Cross", last_time, close, vwap)
        elif st.in_short:
            if green_overwhelm:
                self._do_close(source, "Green Takeout Red", last_time, close, vwap)
            elif crossed_above_vwap:
                self._do_close(source, "VWAP Cross", last_time, close, vwap)

        # --- ENTRY LOGIC ---
        if not st.in_long and not st.in_short:
            if above_vwap and green_overwhelm:
                self._do_entry(source, "BUY", close, last_time, vwap)
            elif below_vwap and red_overwhelm:
                self._do_entry(source, "SELL", close, last_time, vwap)

    def _get_candles(self) -> list:
        """Get 2-minute MES bars pushed by IB sync (matches TV's MES1! feed)."""
        try:
            resp = requests.get(
                f"{SERVER_URL}/api/ibkr/futures-bars/{TICKER}",
                headers={"X-Sync-Key": SYNC_KEY},
                timeout=5,
            )
            if not resp.ok:
                logger.debug("MES bars fetch HTTP %s", resp.status_code)
                return []
            data = resp.json()
            if data.get("stale"):
                logger.debug("MES bars stale: %s", data.get("reason", ""))
                return []
            updated_at = data.get("updated_at", "")
            if updated_at:
                try:
                    age = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(updated_at.replace("Z", "+00:00"))).total_seconds()
                    if age > BAR_STALE_SECONDS:
                        logger.warning("MES bars are %.0fs old — sync may be down", age)
                        return []
                except Exception:
                    pass
            # Return all bars; _calc_vwap needs the full session, _detect_overwhelm uses bars[-11:].
            return data.get("bars", [])
        except Exception as e:
            logger.debug("MES bars fetch error: %s", e)
            return []

    def _calc_vwap(self, candles: list) -> Optional[float]:
        """Cumulative session VWAP anchored at the Globex open (18:00 ET).

        Matches the Pine Script's daily VWAP for CME futures: `time("D")` resets
        at 18:00 ET (5 PM Chicago). VWAP accumulates from there through the
        17:00-18:00 ET maintenance break and resets at the next 18:00 ET.

        Returns None outside an active session (Sat, Sun pre-18:00, Fri post-17:00).
        """
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
        except Exception:
            et = timezone(timedelta(hours=-4))

        now_et = datetime.now(timezone.utc).astimezone(et)
        weekday, hour = now_et.weekday(), now_et.hour

        # Outside any active session
        if weekday == 5:                     # Saturday
            return None
        if weekday == 4 and hour >= 17:      # Friday post-close
            return None
        if weekday == 6 and hour < 18:       # Sunday before Globex open
            return None

        # Anchor = most recent 18:00 ET on Sun-Thu
        if hour >= 18:
            anchor_date = now_et.date()
        else:
            anchor_date = (now_et - timedelta(days=1)).date()
        anchor_et = datetime.combine(anchor_date, dt_time(18, 0)).replace(tzinfo=et)

        num = 0.0
        den = 0.0
        for c in candles:
            ts = c.get("time", "")
            try:
                # IB bars carry `time` as unix SECONDS; tolerate ISO too.
                if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.strip().isdigit()):
                    bar_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                else:
                    bar_dt = datetime.fromisoformat(str(ts))
                    if bar_dt.tzinfo is None:
                        bar_dt = bar_dt.replace(tzinfo=timezone.utc)
                bar_et = bar_dt.astimezone(et)
            except Exception:
                continue
            if bar_et < anchor_et:
                continue
            vol = max(c.get("volume", 1), 1)
            hlc3 = (c["high"] + c["low"] + c["close"]) / 3
            num += hlc3 * vol
            den += vol
        return num / den if den > 0 else None

    # _detect_overwhelm removed — uses shared detect_overwhelm() from overwhelm_detector.py

    def _send_entry(self, direction: str, price: float):
        """Queue a native entry — gated then broker-flat pre-flight.

        Runs the SHARED futures risk gates (kill-switch / runaway / cooldown /
        position / reconcile / sync) so native can't bypass what the TradingView
        webhook enforces, then confirms the broker is flat before queuing.
        """
        from lumisignals.futures_gates import check_futures_action
        allowed, reason, detail = check_futures_action(
            "futures_2n20", TICKER, direction, self.contract_count)
        if not allowed:
            logger.info("[2n20_MES] %s blocked by gate: %s %s", direction, reason, detail)
            return

        broker = self._get_broker_position()
        if broker is None or not broker.get("connected"):
            logger.warning("2n20 MES %s skipped — broker state unverifiable", direction)
            return
        actual_pos = int(broker.get("position", 0))
        if actual_pos != 0:
            self._alert_drift(
                f"Tried to enter {direction} but broker shows position={actual_pos}. "
                f"Strategy state in_long={self.state.in_long} in_short={self.state.in_short}. "
                f"Refusing entry; reconciling state."
            )
            self.state.in_long = actual_pos > 0
            self.state.in_short = actual_pos < 0
            return

        try:
            # No standalone dedup: per-bar dedup (_last_candle_time) prevents
            # same-bar double-fire, the state guard prevents stacking, and the
            # shared cooldown gate handles post-stop re-entry. The old blanket
            # 3-min key was a TradingView-retry artifact that suppressed legit
            # re-entries within 3 minutes.
            order_id = str(uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": TICKER,
                "type": "futures",
                "direction": direction,
                "strategy": "2n20",
                "contracts": self.contract_count,
                "status": "queued",
                "auto": True,
                "model": "0dte",
                "signal_action": direction,
            }
            _rdb().setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))

            self.state.in_long = direction == "BUY"
            self.state.in_short = direction == "SELL"
            self.state.entry_price = price
            self.state.entry_time = datetime.now(timezone.utc)
            logger.info("2n20 MES %s %dx @ %.2f (queued: %s)", direction, self.contract_count, price, order_id)

            try:
                from lumisignals.alerts import send_alert, AlertType
                alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                if alert_pass:
                    send_alert(AlertType.TRADE_OPENED,
                               f"Futures: {direction} {TICKER} — 2n20",
                               f"2n20 server-side signal @ {price:.2f}",
                               details={"Ticker": TICKER, "Direction": direction,
                                        "Strategy": "2n20", "Contracts": str(self.contract_count)},
                               smtp_pass=alert_pass)
            except Exception:
                pass

            if self.signal_callback:
                self.signal_callback({"direction": direction, "price": price, "ticker": TICKER,
                                     "model": "scalp_2n20", "strategy": "2n20_futures_server"})

        except Exception as e:
            logger.error("2n20 MES entry error: %s", e)

    def _send_close(self, reason: str):
        """Send close signal through the webhook pipeline.

        Pre-flight: query broker. Close only sends if broker actually holds a
        position matching strategy state. Drift cases:
          - state long, broker flat   → reset state, no order (already closed)
          - state long, broker short  → conflict; refuse, alert
          - state short, broker long  → conflict; refuse, alert
        Close size = abs(actual broker position), not the configured count,
        so a partially-filled SL can't leave a residual.
        """
        # Closes pass the entry-only gates (kill-switch/cooldown/etc.) but still
        # respect the reconcile gate + sync-alive — don't act on uncertain state.
        from lumisignals.futures_gates import check_futures_action
        allowed, reason_gate, _ = check_futures_action(
            "futures_2n20", TICKER, "CLOSE_LONG", self.contract_count)
        if not allowed:
            logger.info("[2n20_MES] close blocked by gate: %s", reason_gate)
            return

        broker = self._get_broker_position()
        if broker is None or not broker.get("connected"):
            logger.warning("2n20 MES close skipped — broker state unverifiable")
            return
        actual_pos = int(broker.get("position", 0))
        intended_dir = "CLOSE_LONG" if self.state.in_long else "CLOSE_SHORT"

        # Drift — broker flat
        if actual_pos == 0:
            self._alert_drift(
                f"Wanted {intended_dir} (reason={reason}) but broker is flat. "
                f"Stop probably fired silently. Resetting state."
            )
            self._reset_state()
            return
        # Drift — broker holds opposite direction
        if (self.state.in_long and actual_pos < 0) or (self.state.in_short and actual_pos > 0):
            self._alert_drift(
                f"Wanted {intended_dir} but broker shows position={actual_pos}. "
                f"Refusing close to avoid blowing through to opposite side. "
                f"Reconciling state to broker truth."
            )
            self.state.in_long = actual_pos > 0
            self.state.in_short = actual_pos < 0
            return

        # Match — close exactly the actual position size
        direction = "CLOSE_LONG" if actual_pos > 0 else "CLOSE_SHORT"
        close_qty = abs(actual_pos)

        try:
            order_id = str(uuid.uuid4())[:8]
            order = {
                "order_id": order_id,
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "user_id": 1,
                "ticker": TICKER,
                "type": "futures",
                "direction": direction,
                "strategy": "2n20",
                "reason": reason,
                "contracts": close_qty,
                "status": "queued",
            }
            _rdb().setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            logger.info("2n20 MES %s %dx — %s (queued: %s)", direction, close_qty, reason, order_id)

            if self.signal_callback:
                self.signal_callback({"direction": direction, "reason": reason, "ticker": TICKER,
                                     "model": "scalp_2n20", "strategy": "2n20_futures_server"})

        except Exception as e:
            logger.error("2n20 MES close error: %s", e)

        self._reset_state()

    def _reset_state(self):
        self.state.in_long = False
        self.state.in_short = False
        self.state.entry_price = 0.0
        self.state.entry_time = None

    def get_status(self) -> dict:
        return {
            "model": "scalp_2n20_futures",
            "ticker": TICKER,
            "in_long": self.state.in_long,
            "in_short": self.state.in_short,
            "entry_price": self.state.entry_price,
            "entry_time": self.state.entry_time.isoformat() if self.state.entry_time else "",
        }
