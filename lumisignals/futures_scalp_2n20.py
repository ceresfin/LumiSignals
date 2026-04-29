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
        self._last_scan_time: Optional[datetime] = None
        self._last_candle_time: str = ""
        self._last_drift_alert: Optional[datetime] = None

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
            logger.info("[2n20_MES] scan tick #%d (state in_long=%s in_short=%s)",
                        self._scan_call_count, self.state.in_long, self.state.in_short)
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
            if self.state.in_long or self.state.in_short:
                self._send_close("Session close")
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

        # Detect overwhelm
        green_overwhelm, red_overwhelm = self._detect_overwhelm(candles)
        logger.info("[2n20_MES] scan bar=%s close=%.2f vwap=%.2f above=%s below=%s green_ow=%s red_ow=%s in_long=%s in_short=%s",
                    last_time, close, vwap, above_vwap, below_vwap,
                    green_overwhelm, red_overwhelm,
                    self.state.in_long, self.state.in_short)

        # VWAP cross detection
        prev_close = candles[-2]["close"]
        crossed_below_vwap = close < vwap and prev_close >= vwap
        crossed_above_vwap = close > vwap and prev_close <= vwap

        # --- EXIT LOGIC ---
        if self.state.in_long:
            if red_overwhelm:
                self._send_close("Red Takeout Green")
            elif crossed_below_vwap:
                self._send_close("VWAP Cross")
        elif self.state.in_short:
            if green_overwhelm:
                self._send_close("Green Takeout Red")
            elif crossed_above_vwap:
                self._send_close("VWAP Cross")

        # --- ENTRY LOGIC ---
        if not self.state.in_long and not self.state.in_short:
            if above_vwap and green_overwhelm:
                self._send_entry("BUY", close)
            elif below_vwap and red_overwhelm:
                self._send_entry("SELL", close)

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

    def _detect_overwhelm(self, bars: list) -> Tuple[bool, bool]:
        """Detect green/red overwhelm. Returns (green_overwhelm, red_overwhelm)."""
        curr = bars[-1]
        is_green = curr["close"] > curr["open"]
        is_red = curr["close"] < curr["open"]
        green_body = curr["close"] - curr["open"] if is_green else 0
        red_body = curr["open"] - curr["close"] if is_red else 0

        candle_range = curr["high"] - curr["low"]
        body_size = abs(curr["close"] - curr["open"])
        body_pct = (body_size / candle_range * 100) if candle_range > 0 else 0
        has_real_body = body_pct >= MIN_BODY_PCT

        avg_body = sum(abs(b["close"] - b["open"]) for b in bars[-11:-1]) / 10
        is_significant = body_size >= avg_body * AVG_BODY_MULT

        if not has_real_body or not is_significant:
            return False, False

        # Find most recent opposite candle
        last_red_body = 0.0
        last_red_high = 0.0
        for i in range(2, min(2 + LOOKBACK_BARS, len(bars))):
            b = bars[-i]
            if b["close"] < b["open"]:
                last_red_body = b["open"] - b["close"]
                last_red_high = b["open"]
                break

        last_green_body = 0.0
        last_green_low = 0.0
        for i in range(2, min(2 + LOOKBACK_BARS, len(bars))):
            b = bars[-i]
            if b["close"] > b["open"]:
                last_green_body = b["close"] - b["open"]
                last_green_low = b["open"]
                break

        green_overwhelm = (is_green and last_red_body > 0
                          and green_body > last_red_body
                          and curr["close"] > last_red_high)

        red_overwhelm = (is_red and last_green_body > 0
                        and red_body > last_green_body
                        and curr["close"] < last_green_low)

        return green_overwhelm, red_overwhelm

    def _send_entry(self, direction: str, price: float):
        """Send entry signal through the webhook pipeline.

        Pre-flight: confirm broker is flat. If a position already exists at IB
        (state drift, manual trade, etc.), refuse and alert rather than stack.
        """
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
            rdb = _rdb()
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            dedup_key = f"tv:futures:{TICKER}:2n20:{direction}:{today}"
            if rdb.get(dedup_key):
                logger.info("2n20 MES %s skipped — dedup (already entered today)", direction)
                return

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
            rdb.setex(f"ibkr:order:pending:{order_id}", 86400, json.dumps(order))
            rdb.setex(dedup_key, 180, "1")  # 3-min dedup (covers one 2-min candle)

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
