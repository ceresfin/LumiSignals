"""2n20 Overwhelm Scalp Strategy for Forex — Oanda execution.

Same logic as the MES futures 2n20 Pine Script:
- 2-minute candles
- Daily VWAP as bias (above = buy only, below = sell only)
- Green overwhelms red → BUY; Red overwhelms green → SELL
- Body must be real (>= 30% of range) and significant (>= 80% of 10-bar avg)
- Exit: opposite overwhelm, VWAP cross, or session close

Differences from futures:
- Executes on Oanda (not IB)
- Fixed $25 stop loss (converted to pips per pair)
- Tracks as model "scalp_2n20" for journaling
- Runs on 28 major/cross pairs
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .oanda_client import OandaClient
from .order_manager import (
    MAJOR_PAIRS, calculate_position_size, format_price,
    get_pip_precision,
)
from .overwhelm_detector import (
    detect_overwhelm, detect_vwap_cross, parse_oanda_candles,
)

logger = logging.getLogger(__name__)

# Config
GRANULARITY = "M2"  # 2-minute candles on Oanda
CANDLE_COUNT = 15   # Pull 15 candles for analysis (need 10 for avg body + lookback)
DEFAULT_SL_DOLLARS = 25.0  # Fixed stop loss per trade
# Forex trades 24/5: Sunday 5PM ET through Friday 5PM ET
# No session close flatten — forex has no maintenance break
VWAP_CANDLE_GRAN = "M2"  # Same granularity for VWAP
VWAP_CACHE_TTL = 120  # Re-fetch VWAP candles per pair at most every 2 min (matches candle close)
VWAP_CANDLE_COUNT = 720  # ~24h of 2-min bars — covers full 18:00-ET-anchored session


@dataclass
class FXScalpState:
    """Tracks state for one currency pair."""
    instrument: str
    in_long: bool = False
    in_short: bool = False
    trade_id: Optional[str] = None
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    stop_price: float = 0.0
    strategy_tag: str = "scalp_2n20"


class FXScalp2n20:
    """2n20 Overwhelm Scalp Strategy for Forex."""

    def __init__(self, oanda: OandaClient, pairs: list = None,
                 sl_dollars: float = DEFAULT_SL_DOLLARS,
                 signal_callback=None, signal_log=None):
        """
        Args:
            oanda: OandaClient instance
            pairs: List of instruments (default: MAJOR_PAIRS)
            sl_dollars: Fixed stop loss in USD per trade
            signal_callback: Optional callback(signal_dict) for logging/tracking
            signal_log: Optional SignalLog instance — when set, every fill is recorded
                under its OANDA order_id so the Trades page can show model metadata.
        """
        self.oanda = oanda
        self.pairs = pairs or sorted(MAJOR_PAIRS)
        self.sl_dollars = sl_dollars
        self.signal_callback = signal_callback
        self.signal_log = signal_log
        self.states: Dict[str, FXScalpState] = {p: FXScalpState(instrument=p) for p in self.pairs}
        # Per-bar dedup: process each closed bar exactly once per pair (mirrors MES).
        self._last_candle_time: Dict[str, str] = {}
        # VWAP candle cache: (fetched_at_ts, candles) per pair. Refreshed every VWAP_CACHE_TTL.
        self._vwap_cache: Dict[str, Tuple[float, list]] = {}
        # On startup, reconcile in-memory state with OANDA's actual positions.
        # Without this, every bot restart wipes state.in_short/in_long, the strategy
        # thinks it's flat, and re-enters on the next signal — never firing exits
        # because exit logic is gated on `if state.in_short:` / `if state.in_long:`.
        self._init_states_from_broker()

    def _init_states_from_broker(self):
        """Read OANDA open trades and seed strategy state so exits fire correctly
        after bot restarts. Called once at construction.
        """
        try:
            resp = self.oanda._request("GET",
                f"/v3/accounts/{self.oanda.account_id}/openTrades")
            for t in resp.get("trades", []):
                inst = t.get("instrument")
                if inst not in self.states:
                    continue
                try:
                    units = int(float(t.get("currentUnits", 0)))
                except Exception:
                    continue
                if units == 0:
                    continue
                state = self.states[inst]
                # If multiple trades exist on the same pair (legacy from earlier
                # restart-driven duplicates), the most recent one wins — OANDA
                # returns trades newest-first by default.
                if state.in_long or state.in_short:
                    continue
                state.in_long = units > 0
                state.in_short = units < 0
                state.trade_id = str(t.get("id", ""))
                try:
                    state.entry_price = float(t.get("price", 0))
                except Exception:
                    pass
                try:
                    sl_order = t.get("stopLossOrder", {}) or {}
                    state.stop_price = float(sl_order.get("price", 0))
                except Exception:
                    pass
                logger.info("FX state reconciled: %s %s @ %.5f trade=%s (from OANDA)",
                            inst, "LONG" if units > 0 else "SHORT",
                            state.entry_price, state.trade_id)
        except Exception as e:
            logger.warning("FX state reconcile failed: %s", e)

    def scan_all(self):
        """Scan all pairs for 2n20 signals. Call this every ~30 seconds."""
        try:
            from zoneinfo import ZoneInfo
            et_tz = ZoneInfo("America/New_York")
        except Exception:
            et_tz = timezone(timedelta(hours=-4))  # EDT fallback
        now_et = datetime.now(timezone.utc).astimezone(et_tz)
        et_hour, et_minute, weekday = now_et.hour, now_et.minute, now_et.weekday()

        # Forex trades 24/5: Sunday 17:00 ET through Friday 17:00 ET
        # Friday close: flatten at 16:50 ET
        if weekday == 4 and et_hour == 16 and et_minute >= 50:
            self._flatten_all("Friday close")
            return

        # Skip weekends (Saturday + Sunday before 17:00 ET)
        if weekday == 5:
            return
        if weekday == 6 and et_hour < 17:
            return

        for pair in self.pairs:
            try:
                self._scan_pair(pair)
            except Exception as e:
                logger.debug("2n20 scan error %s: %s", pair, e)

    def _scan_pair(self, instrument: str):
        """Scan one pair for 2n20 signals.

        Per-bar dedup: each closed bar is processed exactly once. Cheap enough
        that scan_all can run every ~30s without hammering OANDA — the dedup
        check returns before any heavy computation when no new bar is present.
        """
        # Get 2-minute candles
        candles = self.oanda.get_candles(instrument, GRANULARITY, CANDLE_COUNT)
        if not candles or len(candles) < 12:
            return

        # Per-bar dedup — find latest complete bar's time, skip if already processed.
        latest_complete_time = ""
        for c in reversed(candles):
            if c.get("complete", True):
                latest_complete_time = str(c.get("time", ""))
                break
        if not latest_complete_time:
            return
        if self._last_candle_time.get(instrument) == latest_complete_time:
            return
        self._last_candle_time[instrument] = latest_complete_time

        # Parse candle data using shared parser
        bars = parse_oanda_candles(candles)

        if len(bars) < 12:
            return

        # Calculate daily VWAP
        vwap = self._calc_vwap(instrument)

        state = self.states[instrument]
        curr = bars[-1]
        close = curr["close"]

        if vwap is None:
            return

        above_vwap = close > vwap
        below_vwap = close < vwap

        # Detect overwhelm using shared detector
        green_overwhelm, red_overwhelm = detect_overwhelm(bars)

        # VWAP cross using shared detector
        crossed_below_vwap, crossed_above_vwap = detect_vwap_cross(bars, vwap)

        # --- EXIT LOGIC ---
        if state.in_long:
            if red_overwhelm or crossed_below_vwap:
                reason = "Red overwhelm" if red_overwhelm else "VWAP cross"
                self._close_position(state, close, reason)
        elif state.in_short:
            if green_overwhelm or crossed_above_vwap:
                reason = "Green overwhelm" if green_overwhelm else "VWAP cross"
                self._close_position(state, close, reason)

        # --- ENTRY LOGIC ---
        if not state.in_long and not state.in_short:
            # BUY: above VWAP + green overwhelms red
            if above_vwap and green_overwhelm:
                self._open_position(state, "BUY", close, instrument)
            # SELL: below VWAP + red overwhelms green
            elif below_vwap and red_overwhelm:
                self._open_position(state, "SELL", close, instrument)

    # _detect_overwhelm removed — uses shared detect_overwhelm() from overwhelm_detector.py

    def _calc_vwap(self, instrument: str) -> Optional[float]:
        """Cumulative session VWAP anchored at 18:00 ET (matches futures).

        On the user's TV setup, Pine's `time("D")` for OANDA forex resolves to
        18:00 ET — same as CME futures. Anchoring here resets at each 18:00 ET
        and accumulates through to the next 18:00 ET. Returns None outside an
        active session (Sat, Sun before 18:00, Fri post-17:00 maintenance).
        """
        try:
            from zoneinfo import ZoneInfo
            et = ZoneInfo("America/New_York")
        except Exception:
            et = timezone(timedelta(hours=-4))

        now_et = datetime.now(timezone.utc).astimezone(et)
        weekday, hour = now_et.weekday(), now_et.hour

        # Outside active session — VWAP undefined
        if weekday == 5:                     # Saturday
            return None
        if weekday == 4 and hour >= 17:      # Friday post-close
            return None
        if weekday == 6 and hour < 18:       # Sunday before Globex/VWAP anchor
            return None

        # Anchor = most recent 18:00 ET on a valid trading day (Sun-Thu)
        if hour >= 18:
            anchor_date = now_et.date()
        else:
            anchor_date = (now_et - timedelta(days=1)).date()
        anchor_et = datetime.combine(anchor_date, dt_time(18, 0)).replace(tzinfo=et)

        try:
            # Cached fetch — 720 2-min bars per pair, refreshed every VWAP_CACHE_TTL.
            # Without caching, scan_all hits OANDA 28 × 720-bar requests every cycle,
            # making the loop too slow to scan each 2-min bar across all pairs.
            cached = self._vwap_cache.get(instrument)
            now_ts = time.time()
            if cached and (now_ts - cached[0]) < VWAP_CACHE_TTL:
                candles = cached[1]
            else:
                candles = self.oanda.get_candles(instrument, GRANULARITY, VWAP_CANDLE_COUNT)
                if candles:
                    self._vwap_cache[instrument] = (now_ts, candles)
            if not candles:
                return None

            num = 0.0
            den = 0.0
            for c in candles:
                if not c.get("complete", True):
                    continue
                ct = c.get("time", "")
                if not ct:
                    continue
                try:
                    cdt = datetime.fromtimestamp(float(ct), tz=timezone.utc).astimezone(et)
                except Exception:
                    continue
                if cdt < anchor_et:
                    continue
                mid = c.get("mid", {})
                h = float(mid.get("h", 0))
                l = float(mid.get("l", 0))
                cl = float(mid.get("c", 0))
                vol = int(c.get("volume", 1))
                hlc3 = (h + l + cl) / 3
                num += hlc3 * vol
                den += vol

            return num / den if den > 0 else None
        except Exception:
            return None

    def _open_position(self, state: FXScalpState, direction: str, price: float, instrument: str):
        """Open a position with fixed $ stop loss."""
        pip_value, precision = get_pip_precision(instrument)

        # Calculate stop distance from $25 risk
        # pip_cost depends on pair type
        parts = instrument.split("_")
        if len(parts) == 2:
            base, quote = parts
            if quote == "USD":
                pip_cost = pip_value
            elif base == "USD":
                pip_cost = pip_value / price if price else pip_value
            else:
                pip_cost = pip_value / price if price else pip_value
        else:
            pip_cost = pip_value

        # For a standard 10K lot: pip_cost * 10000 = $ per pip
        # We want: units * stop_pips * pip_cost = sl_dollars
        # First, pick a reasonable stop: ~2x ATR of 2-min candles
        # Or use fixed pip stop based on pair type
        if "JPY" in instrument:
            stop_pips = 15  # ~15 pips for JPY pairs
        else:
            stop_pips = 10  # ~10 pips for non-JPY

        stop_distance = stop_pips * pip_value

        # Calculate units from fixed dollar risk
        units = calculate_position_size(
            account_balance=0, risk_percent=0,
            entry_price=price, stop_price=price - stop_distance if direction == "BUY" else price + stop_distance,
            instrument=instrument, max_units=100000,
            risk_dollar=self.sl_dollars,
        )

        if units <= 0:
            units = 1000  # minimum 1K lot

        if direction == "BUY":
            stop_price = price - stop_distance
        else:
            stop_price = price + stop_distance
            units = -units  # Negative for sell

        stop_str = format_price(stop_price, precision)

        try:
            order_data = {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "stopLossOnFill": {
                    "price": stop_str,
                },
            }
            result = self.oanda.create_order(order_data)

            # Extract trade ID, order ID, and actual fill price/time from Oanda response
            fill = result.get("orderFillTransaction", {})
            trade_ids = fill.get("tradeOpened", {}).get("tradeID") or fill.get("tradesClosed", [{}])[0].get("tradeID", "")
            order_id = (result.get("orderCreateTransaction", {}) or {}).get("id", "") or fill.get("orderID", "")

            # Use Oanda's actual fill price and time, not our candle close
            fill_price = float(fill.get("price", 0)) or price
            fill_time_str = fill.get("time", "")
            if fill_time_str:
                try:
                    fill_time = datetime.fromtimestamp(float(fill_time_str), tz=timezone.utc)
                except Exception:
                    fill_time = datetime.now(timezone.utc)
            else:
                fill_time = datetime.now(timezone.utc)

            state.in_long = direction == "BUY"
            state.in_short = direction == "SELL"
            state.trade_id = str(trade_ids) if trade_ids else ""
            state.entry_price = fill_price
            state.entry_time = fill_time
            state.stop_price = stop_price

            logger.info("2n20 FX %s %s @ %s (fill: %s) — SL %s, units %d",
                       direction, instrument, format_price(fill_price, precision),
                       format_price(price, precision), stop_str, abs(units))

            # Record to signal_log so trade_tracker / Trades page can identify
            # this trade as a 2n20 entry when enriching the OANDA trade list.
            # Record under BOTH trade_id and order_id — the tracker looks up
            # by trade_id first, then openingTransactionID, then nearby IDs.
            log_data = {
                        "model": "scalp_2n20",
                        "strategy": "2n20_fx",
                        "strategy_id": "vwap_2n20",
                        "instrument": instrument,
                        "symbol": instrument,
                        "action": direction,
                        "direction": direction,
                        "entry_price": fill_price,
                        "stop_price": stop_price,
                        "units": abs(units),
                        "trade_id": state.trade_id,
                        "sl_dollars": self.sl_dollars,
                        "level_timeframe": "2m",
                        "level_type": "vwap_overwhelm",
                        "trigger_pattern": "Green Overwhelm" if direction == "BUY" else "Red Overwhelm",
                    }
            if self.signal_log:
                try:
                    # Record under trade_id (primary lookup key for trade_tracker)
                    if state.trade_id:
                        self.signal_log.record(str(state.trade_id), log_data)
                    # Also record under order_id for redundancy
                    if order_id:
                        self.signal_log.record(str(order_id), log_data)
                except Exception as e:
                    logger.debug("signal_log record failed for %s: %s", state.trade_id, e)

            if self.signal_callback:
                self.signal_callback({
                    "instrument": instrument,
                    "direction": direction,
                    "entry_price": price,
                    "stop_price": stop_price,
                    "units": abs(units),
                    "model": "scalp_2n20",
                    "strategy": "2n20_fx",
                    "trade_id": state.trade_id,
                    "order_id": str(order_id) if order_id else "",
                    "sl_dollars": self.sl_dollars,
                })

        except Exception as e:
            logger.error("2n20 FX order error %s %s: %s", direction, instrument, e)

    def _close_position(self, state: FXScalpState, price: float, reason: str):
        """Close current position."""
        instrument = state.instrument
        _, precision = get_pip_precision(instrument)
        direction = "LONG" if state.in_long else "SHORT"

        try:
            close_result = {}
            if state.trade_id:
                # Close specific trade
                close_result = self.oanda._request(
                    "PUT",
                    f"/v3/accounts/{self.oanda.account_id}/trades/{state.trade_id}/close",
                )
            else:
                # Close all for this instrument
                close_data = {"longUnits": "ALL"} if state.in_long else {"shortUnits": "ALL"}
                close_result = self.oanda._request(
                    "PUT",
                    f"/v3/accounts/{self.oanda.account_id}/positions/{instrument}/close",
                    close_data,
                )

            # Get actual fill price and time from Oanda response
            close_fill = close_result.get("orderFillTransaction", {})
            actual_exit_price = float(close_fill.get("price", 0)) or price
            close_time_str = close_fill.get("time", "")
            actual_pnl = float(close_fill.get("pl", 0))

            # Calculate P&L in pips using actual fill prices
            pip = get_pip_precision(instrument)[0]
            if state.entry_price > 0:
                if state.in_long:
                    pnl_pips = (actual_exit_price - state.entry_price) / pip
                else:
                    pnl_pips = (state.entry_price - actual_exit_price) / pip
            else:
                pnl_pips = 0

            # Duration from actual entry time
            duration = ""
            if state.entry_time:
                dur = datetime.now(timezone.utc) - state.entry_time
                mins = int(dur.total_seconds() / 60)
                duration = f"{mins}m"

            logger.info("2n20 FX CLOSE %s %s — %s | %.1f pips | %s",
                       direction, instrument, reason, pnl_pips, duration)

            # Update signal log with close reason so trade_tracker shows it
            if self.signal_log and state.trade_id:
                try:
                    existing = self.signal_log.get(str(state.trade_id))
                    if existing and isinstance(existing, dict):
                        existing["close_reason"] = reason
                        existing["exit_price"] = actual_exit_price
                        existing["pnl_pips"] = round(pnl_pips, 1)
                        self.signal_log.record(str(state.trade_id), existing)
                except Exception:
                    pass

            if self.signal_callback:
                self.signal_callback({
                    "instrument": instrument,
                    "direction": f"CLOSE_{direction}",
                    "exit_price": actual_exit_price,
                    "entry_price": state.entry_price,
                    "pnl_pips": round(pnl_pips, 1),
                    "reason": reason,
                    "model": "scalp_2n20",
                    "strategy": "2n20_fx",
                    "trade_id": state.trade_id,
                    "duration": duration,
                })

        except Exception as e:
            logger.error("2n20 FX close error %s: %s", instrument, e)

        # Reset state
        state.in_long = False
        state.in_short = False
        state.trade_id = None
        state.entry_price = 0.0
        state.entry_time = None
        state.stop_price = 0.0

    def _flatten_all(self, reason: str):
        """Close all open 2n20 positions (session end)."""
        for pair, state in self.states.items():
            if state.in_long or state.in_short:
                try:
                    candles = self.oanda.get_candles(pair, GRANULARITY, 1)
                    if candles:
                        mid = candles[-1].get("mid", {})
                        price = float(mid.get("c", 0))
                        self._close_position(state, price, reason)
                except Exception as e:
                    logger.error("2n20 flatten error %s: %s", pair, e)

    def get_status(self) -> dict:
        """Get current status of all pairs."""
        open_positions = []
        for pair, state in self.states.items():
            if state.in_long or state.in_short:
                open_positions.append({
                    "instrument": pair,
                    "direction": "LONG" if state.in_long else "SHORT",
                    "entry_price": state.entry_price,
                    "stop_price": state.stop_price,
                    "trade_id": state.trade_id,
                    "entry_time": state.entry_time.isoformat() if state.entry_time else "",
                })
        return {
            "model": "scalp_2n20",
            "pairs": len(self.pairs),
            "open": len(open_positions),
            "positions": open_positions,
        }
