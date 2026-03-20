"""Levels strategy — trade at untouched S/R levels with multi-TF candle confirmation."""

import logging
import time
from typing import Callable, Optional

import requests

from .candle_classifier import CandleData, classify_candle, score_multi_timeframe
from .models import Signal
from .oanda_client import OandaClient, resolve_instrument
from .order_manager import MAJOR_PAIRS

logger = logging.getLogger(__name__)

# Oanda granularity codes
OANDA_GRANULARITY = {
    "1mo": "M",
    "1w": "W",
    "1d": "D",
    "4h": "H4",
    "1h": "H1",
}


def _oanda_candle_to_data(candle: dict) -> Optional[CandleData]:
    """Convert an Oanda candle response to CandleData."""
    mid = candle.get("mid")
    if not mid:
        return None
    return CandleData(
        open=float(mid["o"]),
        high=float(mid["h"]),
        low=float(mid["l"]),
        close=float(mid["c"]),
        timestamp=candle.get("time", ""),
    )


class LevelsStrategy:
    """Monitor untouched S/R levels and trade with multi-TF candle confirmation.

    Flow:
    1. Fetch SNR levels for all major pairs (monthly, weekly, daily)
    2. Get current price — is it near an untouched level?
    3. Pull monthly, weekly, daily candles from Oanda
    4. Score candle direction alignment across timeframes
    5. If score >= min_score at a matching level → build trade
    """

    def __init__(self, oanda_client: OandaClient, snr_client, trade_builder_url: str,
                 api_key: str, min_score: int = 2, atr_stop_multiplier: float = 1.0,
                 tolerance_pct: float = 0.003, on_signal: Callable = None):
        """
        Args:
            oanda_client: For fetching candles and current price.
            snr_client: SNRClient for fetching untouched levels.
            trade_builder_url: Base URL for Trade Builder API.
            api_key: Partner API key.
            min_score: Minimum candle direction score to enter (out of 3).
            atr_stop_multiplier: ATR multiplier for stop distance.
            tolerance_pct: How close price must be to a level (as fraction of price).
            on_signal: Callback when a trade signal is generated.
        """
        self.oanda = oanda_client
        self.snr_client = snr_client
        self.trade_builder_url = trade_builder_url.rstrip("/")
        self.api_key = api_key
        self.min_score = min_score
        self.atr_stop_multiplier = atr_stop_multiplier
        self.tolerance_pct = tolerance_pct
        self.on_signal = on_signal
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def _get_current_price(self, instrument: str) -> Optional[float]:
        """Get mid price for an instrument."""
        try:
            data = self.oanda.get_price(instrument)
            prices = data.get("prices", [])
            if prices:
                bid = float(prices[0]["bids"][0]["price"])
                ask = float(prices[0]["asks"][0]["price"])
                return (bid + ask) / 2
        except Exception as e:
            logger.debug("Could not get price for %s: %s", instrument, e)
        return None

    def _get_candles(self, instrument: str) -> tuple:
        """Fetch current and previous candles for monthly, weekly, daily.

        Returns:
            (current_candles, prev_candles) dicts keyed by timeframe.
        """
        current = {}
        previous = {}

        for tf, gran in [("1mo", "M"), ("1w", "W"), ("1d", "D")]:
            try:
                candles = self.oanda.get_candles(instrument, granularity=gran, count=2)
                if len(candles) >= 2:
                    prev = _oanda_candle_to_data(candles[0])
                    curr = _oanda_candle_to_data(candles[1])
                    if curr:
                        current[tf] = curr
                    if prev:
                        previous[tf] = prev
                elif len(candles) == 1:
                    curr = _oanda_candle_to_data(candles[0])
                    if curr:
                        current[tf] = curr
            except Exception as e:
                logger.debug("Could not get %s candles for %s: %s", tf, instrument, e)

        return current, previous

    def _get_atr(self, ticker: str) -> Optional[float]:
        """Get ATR from Trade Builder API for the daily timeframe."""
        try:
            resp = self.session.get(
                f"{self.trade_builder_url}/partners/technical-analysis/trade-builder-setup",
                params={"ticker": ticker, "period": 14, "market": "forex", "frequency": "daily"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            daily = data.get("daily", {})
            atr = daily.get("atr_value")
            if atr:
                return float(atr)
        except Exception as e:
            logger.debug("Could not get ATR for %s: %s", ticker, e)
        return None

    def scan_pair(self, instrument: str):
        """Scan a single pair for level-based trade setups."""
        # Clean ticker for API calls (EUR_USD → EURUSD)
        ticker = instrument.replace("_", "")

        # 1. Get current price
        price = self._get_current_price(instrument)
        if price is None:
            return

        # 2. Get SNR levels
        snr_data = self.snr_client.get_snr_levels(
            ticker=ticker,
            intervals=["1mo", "1w", "1d"],
            market_type="forex",
        )
        if not snr_data:
            return

        # 3. Check if price is near any untouched level
        # Scale tolerance by timeframe — higher TFs represent bigger zones
        tolerance_multiplier = {
            "1mo": 3.0,   # Monthly: 3x base tolerance (e.g. 0.9%)
            "1w": 2.0,    # Weekly: 2x base tolerance (e.g. 0.6%)
            "1d": 1.0,    # Daily: base tolerance (e.g. 0.3%)
        }
        near_levels = []

        for tf in ["1mo", "1w", "1d"]:
            levels = snr_data.get(tf, {})
            support = levels.get("support_price")
            resistance = levels.get("resistance_price")
            tf_tolerance = price * self.tolerance_pct * tolerance_multiplier.get(tf, 1.0)

            if support and abs(price - support) <= tf_tolerance:
                near_levels.append({
                    "timeframe": tf,
                    "type": "demand",
                    "level": support,
                    "distance": abs(price - support),
                    "trade_direction": "BUY",
                })
            if resistance and abs(price - resistance) <= tf_tolerance:
                near_levels.append({
                    "timeframe": tf,
                    "type": "supply",
                    "level": resistance,
                    "distance": abs(price - resistance),
                    "trade_direction": "SELL",
                })

        if not near_levels:
            return

        # Sort by distance — closest level first
        near_levels.sort(key=lambda x: x["distance"])
        best_level = near_levels[0]

        tf_label = {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily"}.get(best_level["timeframe"], best_level["timeframe"])
        logger.info(
            "LEVEL: %s price %.5f near untouched %s %s @ %.5f (%.1f pips away)",
            instrument, price, tf_label, best_level["type"], best_level["level"],
            best_level["distance"] * 10000 if "JPY" not in instrument else best_level["distance"] * 100,
        )

        # 4. Get candles and score direction
        current_candles, prev_candles = self._get_candles(instrument)
        if not current_candles:
            logger.debug("No candle data for %s", instrument)
            return

        mtf_score = score_multi_timeframe(current_candles, prev_candles)

        logger.info("CANDLES: %s — %s", instrument, mtf_score["summary"])

        # 5. Check if candle direction confirms the trade
        trade_dir = best_level["trade_direction"]
        if trade_dir == "BUY":
            score = mtf_score["long_score"]
            needed_direction = "bullish"
        else:
            score = mtf_score["short_score"]
            needed_direction = "bearish"

        if score < self.min_score:
            logger.info(
                "WAIT: %s %s at %s %s — candle score %d/%d (need %d)",
                trade_dir, instrument, tf_label, best_level["type"],
                score, mtf_score["total"], self.min_score,
            )
            return

        # 6. Get ATR for stop calculation
        atr = self._get_atr(ticker)
        if atr is None or atr == 0:
            logger.warning("No ATR for %s — cannot set stop", instrument)
            return

        # 7. Build the trade
        entry = best_level["level"]
        stop_distance = atr * self.atr_stop_multiplier

        if trade_dir == "BUY":
            stop = entry - stop_distance
            # Target: next supply level above, or 2x ATR
            target = None
            for lvl in near_levels:
                if lvl["type"] == "supply" and lvl["level"] > entry:
                    target = lvl["level"]
                    break
            if target is None:
                # Check all timeframes for a supply level above entry
                for tf in ["1d", "1w", "1mo"]:
                    r = snr_data.get(tf, {}).get("resistance_price")
                    if r and r > entry + stop_distance:
                        target = r
                        break
            if target is None:
                target = entry + (stop_distance * 2)  # Default 2:1 R:R
        else:  # SELL
            stop = entry + stop_distance
            target = None
            for lvl in near_levels:
                if lvl["type"] == "demand" and lvl["level"] < entry:
                    target = lvl["level"]
                    break
            if target is None:
                for tf in ["1d", "1w", "1mo"]:
                    s = snr_data.get(tf, {}).get("support_price")
                    if s and s < entry - stop_distance:
                        target = s
                        break
            if target is None:
                target = entry - (stop_distance * 2)

        rr = abs(target - entry) / abs(stop - entry) if abs(stop - entry) > 0 else 0

        # Log the candle patterns
        patterns = []
        for s in mtf_score["scores"]:
            tf_name = {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily"}.get(s.timeframe, s.timeframe)
            patterns.append(f"{tf_name}: {s.pattern}")
        pattern_str = " | ".join(patterns)

        logger.info(
            "TRADE: %s %s @ %.5f | Stop: %.5f | Target: %.5f | R:R: %.1f | "
            "Score: %d/%d | Candles: %s",
            trade_dir, instrument, entry, stop, target, rr,
            score, mtf_score["total"], pattern_str,
        )

        # 8. Build metadata for signal log
        candle_details = []
        for s in mtf_score["scores"]:
            tf_name = {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily"}.get(s.timeframe, s.timeframe)
            candle_details.append({
                "timeframe": tf_name,
                "pattern": s.pattern,
                "direction": s.direction,
            })

        levels_meta = {
            "strategy": "levels",
            "level_timeframe": tf_label,
            "level_type": best_level["type"],
            "level_price": best_level["level"],
            "candle_score": f"{score}/{mtf_score['total']}",
            "candle_details": candle_details,
            "candle_summary": pattern_str,
            "atr": atr,
        }

        # 9. Create signal and call handler
        signal = Signal(
            action=trade_dir,
            symbol=ticker,
            entry=entry,
            stop=stop,
            target=target,
            timeframe=best_level["timeframe"],
            risk_reward=rr,
        )

        if self.on_signal:
            self.on_signal(signal, extra_meta=levels_meta)

    def scan_all(self, pairs: list = None):
        """Scan all major pairs for level-based setups."""
        if pairs is None:
            pairs = sorted(MAJOR_PAIRS)

        logger.info("Scanning %d pairs for level setups...", len(pairs))

        for instrument in pairs:
            try:
                self.scan_pair(instrument)
            except Exception as e:
                logger.error("Error scanning %s: %s", instrument, e)
            time.sleep(0.5)  # Rate limiting

        logger.info("Scan complete")

    def run(self, interval: int = 300, stop_event=None):
        """Run the levels scanner in a loop.

        Args:
            interval: Seconds between full scans (default 5 minutes).
            stop_event: threading.Event to stop the loop.
        """
        logger.info("Levels strategy running — scanning every %ds", interval)

        while stop_event is None or not stop_event.is_set():
            self.scan_all()

            if stop_event is not None:
                stop_event.wait(interval)
            else:
                time.sleep(interval)
