"""2n20 Overwhelm Scalp Strategy for MES Futures — server-side detection.

Same logic as the TradingView Pine Script but runs entirely on the server
using Polygon 2-minute candle data. Places orders through the existing
webhook pipeline (ibkr_sync processes them via IB Gateway).

No TradingView dependency needed.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
WEBHOOK_KEY = os.environ.get("TV_WEBHOOK_KEY", "lumisignals2026")

# Config
TICKER = "MES"
POLYGON_TICKER = "I:SPX"  # Use SPX index for candle data (MES tracks SPX)
GRANULARITY = 2  # 2-minute candles
CANDLE_COUNT = 15
MIN_BODY_PCT = 30.0
AVG_BODY_MULT = 0.8
LOOKBACK_BARS = 3
SCAN_INTERVAL = 120  # Check every 2 minutes (aligned with candle close)


@dataclass
class FuturesScalpState:
    """Tracks state for the MES 2n20 strategy."""
    in_long: bool = False
    in_short: bool = False
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None


class FuturesScalp2n20:
    """2n20 Overwhelm Scalp for MES Futures — server-side."""

    def __init__(self, polygon_key: str, signal_callback=None):
        self.polygon_key = polygon_key
        self.signal_callback = signal_callback
        self.state = FuturesScalpState()
        self._last_scan_time: Optional[datetime] = None
        self._last_candle_time: str = ""

    def scan(self):
        """Check for 2n20 signals. Call every ~30 seconds."""
        now = datetime.now(timezone.utc)
        et_hour = (now.hour - 4) % 24

        # MES trades Sun 6PM - Fri 5PM ET, skip 5-6PM maintenance
        if et_hour >= 17 and et_hour < 18:
            return
        # Friday close: flatten at 4:59 PM
        if now.weekday() == 4 and et_hour == 16 and now.minute >= 59:
            if self.state.in_long or self.state.in_short:
                self._send_close("Session close")
            return
        # Skip weekends
        if now.weekday() == 5:
            return
        if now.weekday() == 6 and et_hour < 18:
            return

        # Rate limit: only scan after a new 2-min candle should have closed
        if self._last_scan_time and (now - self._last_scan_time).total_seconds() < 110:
            return
        self._last_scan_time = now

        # Get 2-minute candles from Polygon
        candles = self._get_candles()
        if not candles or len(candles) < 12:
            return

        # Skip if we already processed this candle
        last_time = candles[-1].get("time", "")
        if last_time == self._last_candle_time:
            return
        self._last_candle_time = last_time

        # Calculate VWAP
        vwap = self._calc_vwap(candles)
        if vwap is None:
            return

        curr = candles[-1]
        close = curr["close"]
        above_vwap = close > vwap
        below_vwap = close < vwap

        # Detect overwhelm
        green_overwhelm, red_overwhelm = self._detect_overwhelm(candles)

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
        """Get 2-minute candles from Polygon."""
        try:
            now = datetime.now(timezone.utc)
            # Get last 30 minutes of 2-min candles
            start = (now - timedelta(minutes=35)).strftime("%Y-%m-%d")
            end = now.strftime("%Y-%m-%d")

            resp = requests.get(
                f"https://api.polygon.io/v2/aggs/ticker/{POLYGON_TICKER}/range/{GRANULARITY}/minute/{start}/{end}",
                params={"apiKey": self.polygon_key, "adjusted": "true", "sort": "asc", "limit": CANDLE_COUNT + 5},
                timeout=10,
            )
            if not resp.ok:
                return []

            results = resp.json().get("results", [])
            candles = []
            for bar in results:
                candles.append({
                    "open": float(bar["o"]),
                    "high": float(bar["h"]),
                    "low": float(bar["l"]),
                    "close": float(bar["c"]),
                    "volume": int(bar.get("v", 0)),
                    "time": str(bar.get("t", 0)),
                })
            return candles[-CANDLE_COUNT:]
        except Exception as e:
            logger.debug("Polygon candle error: %s", e)
            return []

    def _calc_vwap(self, candles: list) -> Optional[float]:
        """Calculate VWAP from today's candles."""
        today = datetime.now(timezone.utc).date()
        num = 0.0
        den = 0.0
        for c in candles:
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
        """Send entry signal through the webhook pipeline."""
        try:
            payload = {
                "ticker": TICKER,
                "direction": direction,
                "strategy": "2n20",
                "key": WEBHOOK_KEY,
                "type": "futures",
                "contracts": 1,
                "msg": f"2n20 server {direction} {TICKER} @ {price:.2f}",
            }
            resp = requests.post(f"{SERVER_URL}/api/webhook/tradingview",
                               json=payload, timeout=10)
            result = resp.json() if resp.ok else {}

            if result.get("status") == "queued":
                self.state.in_long = direction == "BUY"
                self.state.in_short = direction == "SELL"
                self.state.entry_price = price
                self.state.entry_time = datetime.now(timezone.utc)
                logger.info("2n20 MES %s @ %.2f (server-side)", direction, price)
            elif result.get("status") == "skipped":
                logger.info("2n20 MES %s skipped: %s", direction, result.get("reason", ""))
            else:
                logger.warning("2n20 MES %s response: %s", direction, result)

            if self.signal_callback:
                self.signal_callback({"direction": direction, "price": price, "ticker": TICKER,
                                     "model": "scalp_2n20", "strategy": "2n20_futures_server"})

        except Exception as e:
            logger.error("2n20 MES entry error: %s", e)

    def _send_close(self, reason: str):
        """Send close signal through the webhook pipeline."""
        direction = "CLOSE_LONG" if self.state.in_long else "CLOSE_SHORT"
        try:
            payload = {
                "ticker": TICKER,
                "direction": direction,
                "strategy": "2n20",
                "key": WEBHOOK_KEY,
                "type": "futures",
                "contracts": 1,
                "reason": reason,
                "msg": f"2n20 server {direction} {TICKER} — {reason}",
            }
            resp = requests.post(f"{SERVER_URL}/api/webhook/tradingview",
                               json=payload, timeout=10)

            logger.info("2n20 MES %s — %s (server-side)", direction, reason)

            if self.signal_callback:
                self.signal_callback({"direction": direction, "reason": reason, "ticker": TICKER,
                                     "model": "scalp_2n20", "strategy": "2n20_futures_server"})

        except Exception as e:
            logger.error("2n20 MES close error: %s", e)

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
