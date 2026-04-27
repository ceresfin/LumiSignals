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
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .oanda_client import OandaClient
from .order_manager import (
    MAJOR_PAIRS, calculate_position_size, format_price,
    get_pip_precision,
)

logger = logging.getLogger(__name__)

# Config
GRANULARITY = "M2"  # 2-minute candles on Oanda
CANDLE_COUNT = 15   # Pull 15 candles for analysis (need 10 for avg body + lookback)
MIN_BODY_PCT = 30.0  # Body must be >= 30% of candle range
AVG_BODY_MULT = 0.8  # Body must be >= 80% of 10-candle average
LOOKBACK_BARS = 3    # Look back up to 3 bars for opposite candle
DEFAULT_SL_DOLLARS = 25.0  # Fixed stop loss per trade
# Forex trades 24/5: Sunday 5PM ET through Friday 5PM ET
# No session close flatten — forex has no maintenance break
VWAP_CANDLE_GRAN = "M2"  # Same granularity for VWAP


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
                 signal_callback=None):
        """
        Args:
            oanda: OandaClient instance
            pairs: List of instruments (default: MAJOR_PAIRS)
            sl_dollars: Fixed stop loss in USD per trade
            signal_callback: Optional callback(signal_dict) for logging/tracking
        """
        self.oanda = oanda
        self.pairs = pairs or sorted(MAJOR_PAIRS)
        self.sl_dollars = sl_dollars
        self.signal_callback = signal_callback
        self.states: Dict[str, FXScalpState] = {p: FXScalpState(instrument=p) for p in self.pairs}
        self._last_scan_time: Dict[str, datetime] = {}

    def scan_all(self):
        """Scan all pairs for 2n20 signals. Call this every ~30 seconds."""
        now = datetime.now(timezone.utc)
        et_hour = (now.hour - 4) % 24  # Rough EDT

        # Forex trades 24/5: Sunday 5PM ET through Friday 5PM ET
        # Friday close: flatten at 4:50 PM ET
        if now.weekday() == 4 and et_hour == 16 and now.minute >= 50:
            self._flatten_all("Friday close")
            return

        # Skip weekends (Saturday + Sunday before 5PM ET)
        if now.weekday() == 5:
            return
        if now.weekday() == 6 and et_hour < 17:
            return

        for pair in self.pairs:
            try:
                self._scan_pair(pair)
            except Exception as e:
                logger.debug("2n20 scan error %s: %s", pair, e)

    def _scan_pair(self, instrument: str):
        """Scan one pair for 2n20 signals."""
        # Rate limit: don't scan same pair more than once per 2 minutes
        now = datetime.now(timezone.utc)
        last = self._last_scan_time.get(instrument)
        if last and (now - last).total_seconds() < 110:
            return
        self._last_scan_time[instrument] = now

        # Get 2-minute candles
        candles = self.oanda.get_candles(instrument, GRANULARITY, CANDLE_COUNT)
        if not candles or len(candles) < 12:
            return

        # Parse candle data
        bars = []
        for c in candles:
            if c.get("complete", True):
                mid = c.get("mid", {})
                bars.append({
                    "open": float(mid.get("o", 0)),
                    "high": float(mid.get("h", 0)),
                    "low": float(mid.get("l", 0)),
                    "close": float(mid.get("c", 0)),
                    "volume": int(c.get("volume", 0)),
                    "time": c.get("time", ""),
                })

        if len(bars) < 12:
            return

        # Calculate daily VWAP (approximation from today's candles)
        vwap = self._calc_vwap(instrument)

        state = self.states[instrument]
        curr = bars[-1]
        close = curr["close"]

        if vwap is None:
            return

        above_vwap = close > vwap
        below_vwap = close < vwap

        # Detect overwhelm
        green_overwhelm, red_overwhelm = self._detect_overwhelm(bars)

        # VWAP cross exit
        prev_close = bars[-2]["close"]
        crossed_below_vwap = close < vwap and prev_close >= vwap
        crossed_above_vwap = close > vwap and prev_close <= vwap

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

    def _detect_overwhelm(self, bars: list) -> Tuple[bool, bool]:
        """Detect green/red overwhelm patterns. Returns (green_overwhelm, red_overwhelm)."""
        curr = bars[-1]
        curr_close = curr["close"]
        curr_open = curr["open"]
        curr_high = curr["high"]
        curr_low = curr["low"]

        is_green = curr_close > curr_open
        is_red = curr_close < curr_open
        green_body = curr_close - curr_open if is_green else 0
        red_body = curr_open - curr_close if is_red else 0

        # Body size filter
        candle_range = curr_high - curr_low
        body_size = abs(curr_close - curr_open)
        body_pct = (body_size / candle_range * 100) if candle_range > 0 else 0
        has_real_body = body_pct >= MIN_BODY_PCT

        # Significant body (>= 80% of 10-bar average)
        avg_body = sum(abs(b["close"] - b["open"]) for b in bars[-11:-1]) / 10
        is_significant = body_size >= avg_body * AVG_BODY_MULT

        if not has_real_body or not is_significant:
            return False, False

        # Find most recent opposite candle within LOOKBACK_BARS
        # For green overwhelm: find last red candle
        last_red_body = 0.0
        last_red_high = 0.0
        for i in range(2, min(2 + LOOKBACK_BARS, len(bars))):
            b = bars[-i]
            if b["close"] < b["open"]:  # red
                last_red_body = b["open"] - b["close"]
                last_red_high = b["open"]
                break

        # For red overwhelm: find last green candle
        last_green_body = 0.0
        last_green_low = 0.0
        for i in range(2, min(2 + LOOKBACK_BARS, len(bars))):
            b = bars[-i]
            if b["close"] > b["open"]:  # green
                last_green_body = b["close"] - b["open"]
                last_green_low = b["open"]
                break

        green_overwhelm = (is_green and last_red_body > 0
                          and green_body > last_red_body
                          and curr_close > last_red_high)

        red_overwhelm = (is_red and last_green_body > 0
                        and red_body > last_green_body
                        and curr_close < last_green_low)

        return green_overwhelm, red_overwhelm

    def _calc_vwap(self, instrument: str) -> Optional[float]:
        """Calculate daily VWAP from recent 2-minute candles.

        For forex, the "trading day" starts at 5 PM ET (21:00 UTC in EDT).
        We use all candles since the last 5 PM ET rollover.
        """
        try:
            # Get enough candles to cover a full forex day (~720 2-min bars = 24h)
            candles = self.oanda.get_candles(instrument, GRANULARITY, 720)
            if not candles:
                return None

            # Find the last 5 PM ET rollover (21:00 UTC in EDT, 22:00 in EST)
            now = datetime.now(timezone.utc)
            rollover_hour = 21  # 5 PM ET in UTC (EDT)
            if now.hour >= rollover_hour:
                rollover = now.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
            else:
                rollover = (now - timedelta(days=1)).replace(hour=rollover_hour, minute=0, second=0, microsecond=0)

            num = 0.0
            den = 0.0
            for c in candles:
                if not c.get("complete", True):
                    continue
                ct = c.get("time", "")
                if ct:
                    try:
                        # Oanda returns Unix epoch as string (e.g. "1777263480.000000000")
                        ts = float(ct)
                        cdt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        if cdt < rollover:
                            continue
                    except Exception:
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

            # Extract trade ID from fill
            fill = result.get("orderFillTransaction", {})
            trade_ids = fill.get("tradeOpened", {}).get("tradeID") or fill.get("tradesClosed", [{}])[0].get("tradeID", "")

            state.in_long = direction == "BUY"
            state.in_short = direction == "SELL"
            state.trade_id = str(trade_ids) if trade_ids else ""
            state.entry_price = price
            state.entry_time = datetime.now(timezone.utc)
            state.stop_price = stop_price

            logger.info("2n20 FX %s %s @ %s — SL %s, units %d",
                       direction, instrument, format_price(price, precision),
                       stop_str, abs(units))

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
            if state.trade_id:
                # Close specific trade
                self.oanda._request(
                    "PUT",
                    f"/v3/accounts/{self.oanda.account_id}/trades/{state.trade_id}/close",
                )
            else:
                # Close all for this instrument
                close_data = {"longUnits": "ALL"} if state.in_long else {"shortUnits": "ALL"}
                self.oanda._request(
                    "PUT",
                    f"/v3/accounts/{self.oanda.account_id}/positions/{instrument}/close",
                    close_data,
                )

            # Calculate P&L
            if state.entry_price > 0:
                if state.in_long:
                    pnl_pips = (price - state.entry_price) / get_pip_precision(instrument)[0]
                else:
                    pnl_pips = (state.entry_price - price) / get_pip_precision(instrument)[0]
            else:
                pnl_pips = 0

            duration = ""
            if state.entry_time:
                dur = datetime.now(timezone.utc) - state.entry_time
                mins = int(dur.total_seconds() / 60)
                duration = f"{mins}m"

            logger.info("2n20 FX CLOSE %s %s — %s | %.1f pips | %s",
                       direction, instrument, reason, pnl_pips, duration)

            if self.signal_callback:
                self.signal_callback({
                    "instrument": instrument,
                    "direction": f"CLOSE_{direction}",
                    "exit_price": price,
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
