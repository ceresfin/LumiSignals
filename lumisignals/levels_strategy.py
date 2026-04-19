"""Institutional top-down levels strategy — zone watchlist, monitor, and LTF trigger."""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests

from .candle_classifier import (
    ACTIONABLE_PATTERNS, CandleData, classify_candle_series, classify_for_zone,
)
from .models import Signal
from .oanda_client import OandaClient, resolve_instrument
from .order_manager import MAJOR_PAIRS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model configurations — three concurrent institutional strategies
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """Configuration for a single trading model."""
    name: str              # "scalp", "intraday", "swing"
    trigger_tf: str        # Timeframe for entry trigger candle
    zone_tfs: list         # SNR level timeframes to watch
    bias_tf: str           # Trend direction timeframe
    bias_candle_tfs: list  # Candle classification timeframes for scoring
    risk_percent: float    # Risk per trade as % of account
    zone_tolerance_pct: dict  # Per-zone-TF tolerance {tf: pct}
    min_score: int = 50
    min_risk_reward: float = 1.5
    atr_stop_multiplier: float = 1.0
    watchlist_interval: int = 300
    monitor_interval: int = 30


SCALP_MODEL = ModelConfig(
    name="scalp",
    trigger_tf="15m",
    zone_tfs=["1h", "4h"],
    bias_tf="4h",
    bias_candle_tfs=["1h", "4h"],
    risk_percent=0.25,
    zone_tolerance_pct={"1h": 0.002, "4h": 0.004},
    min_score=50,
    min_risk_reward=1.5,
    watchlist_interval=300,
    monitor_interval=30,
)

INTRADAY_MODEL = ModelConfig(
    name="intraday",
    trigger_tf="1h",
    zone_tfs=["4h", "1d"],
    bias_tf="1d",
    bias_candle_tfs=["4h", "1d"],
    risk_percent=0.5,
    zone_tolerance_pct={"4h": 0.003, "1d": 0.005},
    min_score=50,
    min_risk_reward=1.5,
    watchlist_interval=300,
    monitor_interval=30,
)

SWING_MODEL = ModelConfig(
    name="swing",
    trigger_tf="1d",
    zone_tfs=["1w", "1mo"],
    bias_tf="1mo",
    bias_candle_tfs=["1w", "1mo"],
    risk_percent=1.0,
    zone_tolerance_pct={"1w": 0.006, "1mo": 0.009},
    min_score=50,
    min_risk_reward=1.5,
    watchlist_interval=300,
    monitor_interval=30,
)

ALL_MODELS = {"scalp": SCALP_MODEL, "intraday": INTRADAY_MODEL, "swing": SWING_MODEL}

# Shared watchlists for web UI access — keyed by model name
_shared_watchlists = {"scalp": [], "intraday": [], "swing": []}


TF_LABELS = {
    "1mo": "Monthly", "1w": "Weekly", "1d": "Daily",
    "4h": "4H", "1h": "1H", "30m": "30M", "15m": "15M", "5m": "5M",
}


def get_watchlist_snapshot(model_name: str = None) -> list:
    """Return current watchlist as serializable dicts for the web API.

    Args:
        model_name: "scalp", "intraday", "swing", or None for all.
    """
    if model_name:
        zones = _shared_watchlists.get(model_name, [])
    else:
        zones = []
        for wl in _shared_watchlists.values():
            zones.extend(wl)

    result = []
    for z in zones:
        result.append({
            "instrument": z.instrument,
            "direction": z.trade_direction,
            "zone_timeframe": z.zone_timeframe,
            "zone_type": z.zone_type,
            "zone_price": z.zone_price,
            "bias_score": z.bias_score,
            "trends": z.trends,
            "candle_summary": z.candle_summary,
            "atr": z.atr,
            "tf_details": z.tf_details,
            "status": z.status,
            "visit_count": z.visit_count,
            "trigger_timeframe": "",
            "trigger_pattern": "",
            "level_timeframe": TF_LABELS.get(z.zone_timeframe, z.zone_timeframe),
            "level_type": z.zone_type,
            "strategy": TF_LABELS.get(z.zone_timeframe, z.zone_timeframe) + " " + z.zone_type,
            "final_score": z.bias_score,
            "is_stock": "_" not in z.instrument,
            "model": getattr(z, "_model_name", "swing"),
        })
    return result

# Oanda granularity codes
OANDA_GRANULARITY = {
    "1mo": "M",
    "1w": "W",
    "1d": "D",
    "4h": "H4",
    "1h": "H1",
    "30m": "M30",
    "15m": "M15",
    "5m": "M5",
}

# TA-Lib function names valid at demand zones (bullish reversals)
DEMAND_PATTERNS = {
    "CDLHAMMER", "CDLENGULFING", "CDLMORNINGSTAR", "CDLPIERCING",
    "CDL3WHITESOLDIERS", "CDLDRAGONFLYDOJI", "CDLTAKURI",
    "CDLHARAMI", "CDL3INSIDE", "CDLMORNINGDOJISTAR",
    "CDLINVERTEDHAMMER", "CDLHOMINGPIGEON", "CDLMATCHINGLOW",
    "CDL3STARSINSOUTH", "CDLLADDERBOTTOM",
}

# TA-Lib function names valid at supply zones (bearish reversals)
SUPPLY_PATTERNS = {
    "CDLSHOOTINGSTAR", "CDLENGULFING", "CDLEVENINGSTAR", "CDLDARKCLOUDCOVER",
    "CDL3BLACKCROWS", "CDLGRAVESTONEDOJI", "CDLHANGINGMAN",
    "CDLHARAMI", "CDL3INSIDE", "CDLEVENINGDOJISTAR",
    "CDL2CROWS", "CDLIDENTICAL3CROWS", "CDLUPSIDEGAP2CROWS",
    "CDLADVANCEBLOCK",
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


@dataclass
class ZoneEntry:
    """A watched S/R zone from Phase 1."""
    instrument: str
    zone_timeframe: str       # "1mo", "1w", "1d"
    zone_type: str            # "demand" or "supply"
    zone_price: float
    bias_score: float         # 0-100 weighted score
    trends: dict              # {"Monthly": "bullish", ...}
    candle_summary: str
    atr: float
    tf_details: dict = field(default_factory=dict)  # Per-TF: {trend, prev_candle, curr_candle}
    status: str = "watching"  # "watching", "activated", "triggered"
    visit_count: int = 0
    activated_at: float = 0.0
    trade_direction: str = ""

    def __post_init__(self):
        if not self.trade_direction:
            self.trade_direction = "BUY" if self.zone_type == "demand" else "SELL"


@dataclass
class TriggerResult:
    """Result from Phase 3 when a trigger fires."""
    zone: ZoneEntry
    trigger_timeframe: str     # e.g. "5m"
    trigger_pattern: str       # e.g. "Bullish Engulfing"
    trigger_direction: str     # "bullish" or "bearish"
    entry: float
    stop: float
    target: float
    risk_reward: float


class LevelsStrategy:
    """Three-phase institutional top-down levels strategy.

    Phase 1 (every N minutes): Build zone watchlist from SNR levels + bias scoring.
    Phase 2 (every 30s): Monitor prices, activate/deactivate zones by proximity.
    Phase 3 (every 30s): Check LTF candle triggers for activated zones.

    Supports multiple models via ModelConfig:
      - scalp:    15m trigger at 1h/4h zones, 4h bias
      - intraday: 1h trigger at 4h/daily zones, daily bias
      - swing:    daily trigger at weekly/monthly zones, monthly bias
    """

    def __init__(self, oanda_client: OandaClient, snr_client, trade_builder_url: str,
                 api_key: str, model: ModelConfig = None,
                 # Legacy params (used if model is None)
                 min_score: int = 50, atr_stop_multiplier: float = 1.0,
                 trading_timeframe: str = "1d", zone_tolerances: dict = None,
                 min_risk_reward: float = 1.5, watchlist_interval: int = 300,
                 monitor_interval: int = 30, trigger_candle_count: int = 10,
                 zone_timeout: int = 14400, on_signal: Callable = None,
                 massive_client=None, stock_tickers: list = None,
                 stock_atr_multiplier: float = 0.5):
        self.oanda = oanda_client
        self.snr_client = snr_client
        self.trade_builder_url = trade_builder_url.rstrip("/")
        self.api_key = api_key

        # Model config — either from ModelConfig or legacy params
        if model:
            self.model = model
            self.model_name = model.name
            self.trading_timeframe = model.trigger_tf
            self.zone_tfs = model.zone_tfs
            self.bias_tf = model.bias_tf
            self.bias_candle_tfs = model.bias_candle_tfs
            self.min_score = model.min_score
            self.atr_stop_multiplier = model.atr_stop_multiplier
            self.min_risk_reward = model.min_risk_reward
            self.zone_tolerances = model.zone_tolerance_pct
            self.watchlist_interval = model.watchlist_interval
            self.monitor_interval = model.monitor_interval
            self.risk_percent = model.risk_percent
        else:
            self.model = None
            self.model_name = "swing"
            self.trading_timeframe = trading_timeframe
            self.zone_tfs = ["1w", "1mo"]
            self.bias_tf = "1mo"
            self.bias_candle_tfs = ["1w", "1mo"]
            self.min_score = min_score
            self.atr_stop_multiplier = atr_stop_multiplier
            self.min_risk_reward = min_risk_reward
            self.zone_tolerances = zone_tolerances or {"1w": 0.006, "1mo": 0.009}
            self.watchlist_interval = watchlist_interval
            self.monitor_interval = monitor_interval
            self.risk_percent = 1.0

        self.trigger_candle_count = trigger_candle_count
        self.zone_timeout = zone_timeout
        self.on_signal = on_signal
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

        # Massive client for stocks/crypto
        self.massive = massive_client
        self.stock_tickers = stock_tickers or []
        self.stock_atr_multiplier = stock_atr_multiplier

        # State
        self._watchlist: List[ZoneEntry] = []
        self._placed_setups: set = set()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def _batch_get_prices(self, instruments: list) -> dict:
        """Batch fetch mid prices for multiple instruments (max ~20 per call)."""
        prices = {}
        unique = list(set(instruments))
        for i in range(0, len(unique), 20):
            batch = unique[i:i + 20]
            try:
                data = self.oanda._request(
                    "GET",
                    f"/v3/accounts/{self.oanda.account_id}/pricing?instruments={','.join(batch)}",
                )
                for p in data.get("prices", []):
                    bid = float(p["bids"][0]["price"])
                    ask = float(p["asks"][0]["price"])
                    prices[p["instrument"]] = (bid + ask) / 2
            except Exception as e:
                logger.debug("Batch price fetch error: %s", e)
        return prices

    def _get_candles(self, instrument: str, granularity: str = None, count: int = 6) -> list:
        """Fetch completed candles, returns list of CandleData."""
        gran = granularity or "D"
        try:
            raw = self.oanda.get_candles(instrument, granularity=gran, count=count)
            completed = [c for c in raw if c.get("complete", False)]
            series = [_oanda_candle_to_data(c) for c in completed]
            return [c for c in series if c is not None]
        except Exception as e:
            logger.debug("Could not get %s candles for %s: %s", gran, instrument, e)
            return []

    def _get_current_candle(self, instrument: str, granularity: str) -> Optional[CandleData]:
        """Fetch the current in-progress candle."""
        try:
            raw = self.oanda.get_candles(instrument, granularity=granularity, count=1)
            if raw:
                # The last candle may or may not be complete
                last = raw[-1]
                if not last.get("complete", False):
                    return _oanda_candle_to_data(last)
                # If the last one is complete, there's no in-progress candle yet
            return None
        except Exception:
            return None

    def _get_trade_builder_data(self, ticker: str, market: str = "forex") -> dict:
        """Get ATR and trend direction from Trade Builder API across timeframes."""
        result = {"atr": None, "trends": {}}
        try:
            resp = self.session.get(
                f"{self.trade_builder_url}/partners/technical-analysis/trade-builder-setup",
                params={"ticker": ticker, "period": 14, "market": market,
                        "frequency": "daily,weekly,monthly"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())

            for tf_key, tf_label in [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")]:
                tf_data = data.get(tf_key, {})
                position = tf_data.get("position", "")
                if position:
                    result["trends"][tf_label] = "bullish" if position == "positive" else "bearish"
                if tf_key == "daily" and tf_data.get("atr_value"):
                    result["atr"] = float(tf_data["atr_value"])
        except Exception as e:
            logger.debug("Could not get Trade Builder data for %s: %s", ticker, e)
        return result

    def _tf_label(self, tf: str) -> str:
        return {"1mo": "Monthly", "1w": "Weekly", "1d": "Daily"}.get(tf, tf)

    # ------------------------------------------------------------------
    # Phase 1: Zone Watchlist
    # ------------------------------------------------------------------

    def _refresh_watchlist(self, pairs: list = None):
        """Phase 1: Scan all pairs (forex + stocks/crypto), build ranked zone watchlist."""
        if pairs is None:
            pairs = sorted(MAJOR_PAIRS)

        new_watchlist: List[ZoneEntry] = []

        # Scan forex pairs (via Oanda)
        for instrument in pairs:
            try:
                self._scan_pair_for_zones(instrument, new_watchlist)
            except Exception as e:
                logger.error("Error scanning %s for zones: %s", instrument, e)
            time.sleep(0.5)  # Rate limiting

        # Scan stocks/crypto (via Massive) — only for swing model (weekly/monthly zones)
        if self.massive and self.stock_tickers and self.model_name in ("swing", "swing_options"):
            for ticker in self.stock_tickers:
                try:
                    self._scan_stock_for_zones(ticker, new_watchlist)
                except Exception as e:
                    logger.error("Error scanning %s for zones: %s", ticker, e)
                time.sleep(0.8)  # Rate limiting — 112 tickers, avoid 429s

        # Sort by bias strength (highest first)
        new_watchlist.sort(key=lambda z: (-z.bias_score,))

        # Preserve activation state from previous watchlist
        old_by_key = {}
        for z in self._watchlist:
            key = f"{z.instrument}:{z.zone_timeframe}:{z.zone_type}:{z.zone_price:.5f}"
            old_by_key[key] = z

        for z in new_watchlist:
            key = f"{z.instrument}:{z.zone_timeframe}:{z.zone_type}:{z.zone_price:.5f}"
            old = old_by_key.get(key)
            if old and old.status == "activated":
                z.status = "activated"
                z.activated_at = old.activated_at
                z.visit_count = old.visit_count

        self._watchlist = new_watchlist

        # Publish to shared state for web UI
        _shared_watchlists[self.model_name] = list(self._watchlist)

        # Log summary
        pair_count = len(set(z.instrument for z in self._watchlist))
        fx_count = sum(1 for z in self._watchlist if "_" in z.instrument)
        stock_count = len(self._watchlist) - fx_count
        logger.info("[%s] Watchlist: %d zones across %d instruments (%d forex, %d stocks/crypto)",
                     self.model_name.upper(), len(self._watchlist), pair_count, fx_count, stock_count)

    def _scan_pair_for_zones(self, instrument: str, watchlist: list):
        """Scan a single pair and append qualifying ZoneEntry objects to watchlist."""
        ticker = instrument.replace("_", "")

        # 1. Get current price
        price = self._get_current_price(instrument)
        if price is None:
            return

        # 2. Get SNR levels for this model's zone timeframes
        snr_data = self.snr_client.get_snr_levels(
            ticker=ticker, intervals=self.zone_tfs, market_type="forex",
        )
        if not snr_data:
            return

        # 3. Get Trade Builder data (trend + ATR)
        tb_data = self._get_trade_builder_data(ticker)
        atr = tb_data["atr"]
        trends = tb_data["trends"]

        if atr is None or atr == 0:
            logger.debug("No ATR for %s — skipping", instrument)
            return

        # 4. Get candle series for monthly/weekly/daily
        #    Build per-TF details with labeled candles (labels from actual timestamps):
        #    Monthly: last completed month + current month (in-progress)
        #    Weekly:  2nd-to-last completed week + last completed week (NOT current week)
        #    Daily:   before 12:30 NY → day-before-yesterday + yesterday
        #             after 12:30 NY  → yesterday + today (in-progress)
        from datetime import datetime, timezone, timedelta
        from .candle_classifier import classify_candle_series as _cls, classify_candle as _cls_single, TimeframeScore

        now_utc = datetime.now(timezone.utc)
        ny_offset = timedelta(hours=-4)  # EDT
        now_ny = now_utc + ny_offset
        after_midday = now_ny.hour > 12 or (now_ny.hour == 12 and now_ny.minute >= 30)

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        def _label_from_ts(timestamp: str, fmt: str) -> str:
            """Derive a label from a candle's Oanda timestamp.

            Oanda timestamps are the START of the candle period.
            Monthly: starts last day of prev month → add 1 day to get correct month.
            Weekly: starts Monday → label as that date.
            Daily: starts at 5pm NY → label relative to today.
            """
            try:
                ts = float(timestamp)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if fmt == "month":
                    # Add 1 day: candle starting Jan 31 = February candle
                    actual = dt + timedelta(days=1)
                    return month_names[actual.month - 1]
                elif fmt == "week":
                    return dt.strftime("%b %d")
                elif fmt == "day":
                    delta = (now_ny.date() - dt.date()).days
                    if delta == 0:
                        return "Today"
                    elif delta == 1:
                        return "Yesterday"
                    else:
                        return f"{delta}d ago"
            except (ValueError, OSError):
                pass
            return ""

        def _candle_shape(candle: CandleData) -> dict:
            """Extract OHLC proportions for visual rendering."""
            rng = candle.high - candle.low
            if rng == 0:
                return {"body": 0, "upper": 0, "lower": 0, "green": True}
            body = abs(candle.close - candle.open)
            green = candle.close >= candle.open
            if green:
                upper = candle.high - candle.close
                lower = candle.open - candle.low
            else:
                upper = candle.high - candle.open
                lower = candle.close - candle.low
            return {
                "body": round(body / rng, 2),
                "upper": round(upper / rng, 2),
                "lower": round(lower / rng, 2),
                "green": green,
            }

        def _set_candle(detail, prefix, label, cls_result, candle):
            """Set candle fields on detail dict."""
            detail[prefix + "label"] = label
            detail[prefix + "pattern"] = cls_result.pattern
            detail[prefix + "direction"] = cls_result.direction
            detail[prefix + "shape"] = _candle_shape(candle)

        candle_series = {}
        tf_details = {}

        # Build candle details for this model's bias timeframes
        all_candle_tfs = list(set(self.zone_tfs + self.bias_candle_tfs))
        tf_to_gran = {"1mo": "M", "1w": "W", "1d": "D", "4h": "H4", "1h": "H1", "30m": "M30", "15m": "M15"}

        for tf in all_candle_tfs:
            gran = tf_to_gran.get(tf, "D")
            tf_label = self._tf_label(tf)
            detail = {"trend": trends.get(tf_label, "")}

            # Determine label format based on timeframe
            if tf == "1mo":
                label_fmt = "month"
                count = 500  # Max history for TA-Lib
            elif tf == "1w":
                label_fmt = "week"
                count = 500
            else:
                label_fmt = "day"  # Works for daily, 4h, 1h, etc.
                count = 100

            # Fetch completed candles
            series = self._get_candles(instrument, granularity=gran, count=count)
            if series:
                candle_series[tf] = series

            # Always show 3 candles: 2 completed + current (or 3 completed)
            if series and len(series) >= 2:
                _set_candle(detail, "candle1_", _label_from_ts(series[-2].timestamp, label_fmt) or "prev", _cls(series[:-1]), series[-2])
                _set_candle(detail, "candle2_", _label_from_ts(series[-1].timestamp, label_fmt) or "last", _cls(series), series[-1])
            elif series:
                _set_candle(detail, "candle1_", _label_from_ts(series[-1].timestamp, label_fmt) or "last", _cls(series), series[-1])

            # Try to add current in-progress candle as 3rd
            curr = self._get_current_candle(instrument, gran)
            if curr:
                cls_curr = _cls(series + [curr]) if series else _cls_single(curr)
                prefix = "candle3_" if series and len(series) >= 2 else "candle2_"
                _set_candle(detail, prefix, _label_from_ts(curr.timestamp, label_fmt) or "now", cls_curr, curr)

            tf_details[tf_label] = detail

        if not candle_series:
            return

        # Score candles — only actionable formations count for bias
        scores = []
        for tf in self.bias_candle_tfs:
            series = candle_series.get(tf)
            if not series:
                continue
            classification = _cls(series)
            if classification.pattern in ACTIONABLE_PATTERNS:
                sc = 1 if classification.direction == "bullish" else (-1 if classification.direction == "bearish" else 0)
            else:
                sc = 0  # Not actionable — neutral for bias
            scores.append(TimeframeScore(tf, classification.direction, classification.pattern, classification.strength, sc))

        candle_total = len(scores) or 1

        # Build candle summary
        parts = []
        for s in scores:
            parts.append(f"{self._tf_label(s.timeframe)}: {s.pattern} ({s.direction})")
        candle_summary = " | ".join(parts) if parts else "no data"

        # 5. Check each level within outer tolerance
        for tf in self.zone_tfs:
            levels = snr_data.get(tf, {})
            tolerance = price * self.zone_tolerances.get(tf, 0.003)

            for level_type, level_key, trade_dir in [
                ("demand", "support_price", "BUY"),
                ("supply", "resistance_price", "SELL"),
            ]:
                level_price = levels.get(level_key)
                if not level_price:
                    continue
                distance = abs(price - level_price)
                if distance > tolerance:
                    continue

                # Dedup
                setup_key = f"{instrument}:{tf}:{level_type}:{level_price:.5f}"
                if setup_key in self._placed_setups:
                    continue

                # Score: trend 60% + candle 40%
                trend_total = len(trends) or 1
                if trade_dir == "BUY":
                    trend_agrees = sum(1 for d in trends.values() if d == "bullish")
                    candle_agrees = sum(1 for s in scores if s.score > 0)
                else:
                    trend_agrees = sum(1 for d in trends.values() if d == "bearish")
                    candle_agrees = sum(1 for s in scores if s.score < 0)

                trend_pct = trend_agrees / trend_total
                candle_pct = candle_agrees / candle_total
                bias_score = round((trend_pct * 60) + (candle_pct * 40), 1)

                if bias_score < self.min_score:
                    continue

                watchlist.append(ZoneEntry(
                    instrument=instrument,
                    zone_timeframe=tf,
                    zone_type=level_type,
                    zone_price=level_price,
                    bias_score=bias_score,
                    trends=trends,
                    candle_summary=candle_summary,
                    atr=atr,
                    tf_details=tf_details,
                    trade_direction=trade_dir,
                ))

    def _scan_stock_for_zones(self, ticker: str, watchlist: list):
        """Scan a stock/crypto ticker for level-based zones using Massive data."""
        from .candle_classifier import classify_candle_series as _cls, TimeframeScore

        # 1. Get current price
        price = self.massive.get_price(ticker)
        if price is None:
            return

        # 2. Get SNR levels from LumiTrade
        market_type = "crypto" if ticker.startswith("X:") else "stock"
        snr_ticker = ticker.replace("X:", "")
        snr_data = self.snr_client.get_snr_levels(
            ticker=snr_ticker, intervals=["1mo", "1w", "1d"], market_type=market_type,
        )
        if not snr_data:
            return

        # 3. Get Trade Builder data (trend + ATR)
        tb_data = self._get_trade_builder_data(snr_ticker, market=market_type)
        atr = tb_data["atr"]
        trends = tb_data["trends"]

        if atr is None or atr == 0:
            # Estimate ATR from daily candles if Trade Builder doesn't have it
            daily = self.massive.get_candles(ticker, timespan="1d", count=14)
            if daily and len(daily) >= 2:
                ranges = [c.high - c.low for c in daily[-14:]]
                atr = sum(ranges) / len(ranges)
            else:
                logger.debug("No ATR for %s — skipping", ticker)
                return

        # 4. Get candle series from Massive
        # Keep counts small enough that API returns recent data
        candle_series = {}
        tf_counts = {"1mo": 24, "1w": 20, "1d": 30}
        for tf in ["1mo", "1w", "1d"]:
            candles = self.massive.get_candles(ticker, timespan=tf, count=tf_counts.get(tf, 30))
            if candles:
                candle_series[tf] = candles

        if not candle_series:
            return

        # Classify candles — only actionable formations count for bias
        scores = []
        for tf in ["1mo", "1w", "1d"]:
            series = candle_series.get(tf)
            if not series:
                continue
            classification = _cls(series)
            if classification.pattern in ACTIONABLE_PATTERNS:
                sc = 1 if classification.direction == "bullish" else (-1 if classification.direction == "bearish" else 0)
            else:
                sc = 0
            scores.append(TimeframeScore(tf, classification.direction, classification.pattern, classification.strength, sc))

        candle_total = len(scores) or 1

        # Build candle summary
        parts = []
        for s in scores:
            parts.append(f"{self._tf_label(s.timeframe)}: {s.pattern} ({s.direction})")
        candle_summary = " | ".join(parts) if parts else "no data"

        # Build tf_details for display (same structure as forex)
        from datetime import datetime, timezone, timedelta
        from .candle_classifier import classify_candle as _cls_single
        now_utc = datetime.now(timezone.utc)
        ny_offset = timedelta(hours=-4)
        now_ny = now_utc + ny_offset
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        def _label_from_ts_stock(timestamp, fmt):
            try:
                ts = float(timestamp)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                if fmt == "month":
                    return month_names[dt.month - 1]
                elif fmt == "week":
                    return dt.strftime("%b %d")
                elif fmt == "day":
                    # Use date labels for stocks (weekends make "Xd ago" confusing)
                    return dt.strftime("%b %d")
            except (ValueError, OSError):
                pass
            return ""

        def _candle_shape_stock(candle):
            rng = candle.high - candle.low
            if rng == 0:
                return {"body": 0, "upper": 0, "lower": 0, "green": True}
            body = abs(candle.close - candle.open)
            green = candle.close >= candle.open
            if green:
                upper = candle.high - candle.close
                lower = candle.open - candle.low
            else:
                upper = candle.high - candle.open
                lower = candle.close - candle.low
            return {"body": round(body / rng, 2), "upper": round(upper / rng, 2),
                    "lower": round(lower / rng, 2), "green": green}

        tf_details = {}
        for tf in ["1mo", "1w", "1d"]:
            tf_label = self._tf_label(tf)
            detail = {"trend": trends.get(tf_label, "")}
            series = candle_series.get(tf)
            fmt = "month" if tf == "1mo" else ("week" if tf == "1w" else "day")

            # Always show 3 candles: prev + last completed + current/recent
            if series and len(series) >= 3:
                cls1 = _cls(series[:-2])
                detail["candle1_label"] = _label_from_ts_stock(series[-3].timestamp, fmt)
                detail["candle1_pattern"] = cls1.pattern
                detail["candle1_direction"] = cls1.direction
                detail["candle1_shape"] = _candle_shape_stock(series[-3])
                cls2 = _cls(series[:-1])
                detail["candle2_label"] = _label_from_ts_stock(series[-2].timestamp, fmt)
                detail["candle2_pattern"] = cls2.pattern
                detail["candle2_direction"] = cls2.direction
                detail["candle2_shape"] = _candle_shape_stock(series[-2])
                cls3 = _cls(series)
                detail["candle3_label"] = _label_from_ts_stock(series[-1].timestamp, fmt)
                detail["candle3_pattern"] = cls3.pattern
                detail["candle3_direction"] = cls3.direction
                detail["candle3_shape"] = _candle_shape_stock(series[-1])
            elif series and len(series) >= 2:
                cls1 = _cls(series[:-1])
                detail["candle1_label"] = _label_from_ts_stock(series[-2].timestamp, fmt)
                detail["candle1_pattern"] = cls1.pattern
                detail["candle1_direction"] = cls1.direction
                detail["candle1_shape"] = _candle_shape_stock(series[-2])
                cls2 = _cls(series)
                detail["candle2_label"] = _label_from_ts_stock(series[-1].timestamp, fmt)
                detail["candle2_pattern"] = cls2.pattern
                detail["candle2_direction"] = cls2.direction
                detail["candle2_shape"] = _candle_shape_stock(series[-1])
            elif series:
                cls1 = _cls(series)
                detail["candle1_label"] = "Last"
                detail["candle1_pattern"] = cls1.pattern
                detail["candle1_direction"] = cls1.direction
                detail["candle1_shape"] = _candle_shape_stock(series[-1])
            tf_details[tf_label] = detail

        # 5. Check monthly and weekly levels only (daily is noise for stocks)
        # Tolerance = ATR × configurable multiplier (default 0.5)
        stock_tolerance = atr * self.stock_atr_multiplier
        for tf in ["1mo", "1w"]:
            levels = snr_data.get(tf, {})
            tolerance = stock_tolerance

            for level_type, level_key, trade_dir in [
                ("demand", "support_price", "BUY"),
                ("supply", "resistance_price", "SELL"),
            ]:
                level_price = levels.get(level_key)
                if not level_price:
                    continue
                distance = abs(price - level_price)
                if distance > tolerance:
                    continue

                setup_key = f"{ticker}:{tf}:{level_type}:{level_price:.5f}"
                if setup_key in self._placed_setups:
                    continue

                # Score: trend 60% + candle 40%
                trend_total = len(trends) or 1
                if trade_dir == "BUY":
                    trend_agrees = sum(1 for d in trends.values() if d == "bullish")
                    candle_agrees = sum(1 for s in scores if s.score > 0)
                else:
                    trend_agrees = sum(1 for d in trends.values() if d == "bearish")
                    candle_agrees = sum(1 for s in scores if s.score < 0)

                trend_pct = trend_agrees / trend_total
                candle_pct = candle_agrees / candle_total
                bias_score = round((trend_pct * 60) + (candle_pct * 40), 1)

                if bias_score < self.min_score:
                    continue

                watchlist.append(ZoneEntry(
                    instrument=ticker,
                    zone_timeframe=tf,
                    zone_type=level_type,
                    zone_price=level_price,
                    bias_score=bias_score,
                    trends=trends,
                    candle_summary=candle_summary,
                    atr=atr,
                    tf_details=tf_details,
                    trade_direction=trade_dir,
                ))

    # ------------------------------------------------------------------
    # Phase 2: Zone Monitor
    # ------------------------------------------------------------------

    def _monitor_zones(self):
        """Phase 2: Batch price check, activate/deactivate zones by proximity."""
        if not self._watchlist:
            return

        # Batch fetch prices — split forex (Oanda) vs stocks/crypto (Massive)
        all_instruments = list(set(z.instrument for z in self._watchlist))
        forex = [i for i in all_instruments if "_" in i]
        stocks = [i for i in all_instruments if "_" not in i]

        prices = self._batch_get_prices(forex) if forex else {}
        if stocks and self.massive:
            prices.update(self.massive.batch_get_prices(stocks))

        now = time.time()

        for zone in self._watchlist:
            price = prices.get(zone.instrument)
            if price is None:
                continue

            # Activation tolerance is tighter than outer tolerance — half the zone tolerance
            activation_tolerance = price * self.zone_tolerances.get(zone.zone_timeframe, 0.003) * 0.5
            distance = abs(price - zone.zone_price)

            if zone.status == "watching":
                if distance <= activation_tolerance:
                    zone.status = "activated"
                    zone.activated_at = now
                    is_forex = "_" in zone.instrument
                    pip_dist = (distance * 10000 if "JPY" not in zone.instrument else distance * 100) if is_forex else distance
                    dist_label = "pips" if is_forex else ""
                    logger.info(
                        "Activated: %s near %s %s @ %.5f (%.2f %s)",
                        zone.instrument, self._tf_label(zone.zone_timeframe),
                        zone.zone_type, zone.zone_price, pip_dist, dist_label,
                    )

            elif zone.status == "activated":
                # Check timeout
                if now - zone.activated_at > self.zone_timeout:
                    logger.info(
                        "Timeout: %s %s %s @ %.5f — deactivated after %d min",
                        zone.instrument, self._tf_label(zone.zone_timeframe),
                        zone.zone_type, zone.zone_price,
                        int((now - zone.activated_at) / 60),
                    )
                    zone.status = "watching"
                    zone.visit_count += 1
                    continue

                # Check if price moved away (beyond outer tolerance)
                outer_tolerance = price * self.zone_tolerances.get(zone.zone_timeframe, 0.003)
                if distance > outer_tolerance:
                    zone.status = "watching"
                    zone.visit_count += 1
                    logger.debug(
                        "Deactivated: %s moved away from %s %s @ %.5f",
                        zone.instrument, self._tf_label(zone.zone_timeframe),
                        zone.zone_type, zone.zone_price,
                    )

    # ------------------------------------------------------------------
    # Phase 3: Execution Trigger
    # ------------------------------------------------------------------

    def _check_triggers(self):
        """Phase 3: Check LTF candle patterns for activated zones."""
        activated = [z for z in self._watchlist if z.status == "activated"]
        if not activated:
            return

        gran = OANDA_GRANULARITY.get(self.trading_timeframe, "M5")

        for zone in activated:
            try:
                self._check_zone_trigger(zone, gran)
            except Exception as e:
                logger.error("Error checking trigger for %s: %s", zone.instrument, e)

    def _check_zone_trigger(self, zone: ZoneEntry, granularity: str):
        """Check a single activated zone for a LTF trigger pattern."""
        is_forex = "_" in zone.instrument
        if is_forex:
            candles = self._get_candles(
                zone.instrument, granularity=granularity,
                count=self.trigger_candle_count + 1,
            )
        else:
            # Stocks/crypto — use Massive
            candles = self.massive.get_candles(
                zone.instrument, timespan=self.trading_timeframe,
                count=self.trigger_candle_count + 1,
            ) if self.massive else []
        if len(candles) < 3:
            return

        # Run zone-filtered classification
        classification = classify_for_zone(candles, zone.zone_type)
        if classification is None:
            return  # No matching pattern

        # Pattern must align with trade direction
        expected_dir = "bullish" if zone.trade_direction == "BUY" else "bearish"
        if classification.direction != expected_dir:
            return

        # Entry = trigger candle's close price
        trigger_candle = candles[-1]
        entry = trigger_candle.close

        # Stop = below/above the zone (zone level +/- ATR x multiplier)
        stop_distance = zone.atr * self.atr_stop_multiplier
        if zone.trade_direction == "BUY":
            stop = zone.zone_price - stop_distance
        else:
            stop = zone.zone_price + stop_distance

        # Target = next S/R level in trade direction, or 2:1 R:R fallback
        target = self._find_target(zone, entry, stop_distance)

        # Reject if R:R too low
        risk = abs(entry - stop)
        if risk == 0:
            return
        reward = abs(target - entry)
        rr = round(reward / risk, 2)

        if rr < self.min_risk_reward:
            logger.debug(
                "Rejected: %s %s R:R %.1f < min %.1f",
                zone.instrument, classification.pattern, rr, self.min_risk_reward,
            )
            return

        trigger = TriggerResult(
            zone=zone,
            trigger_timeframe=self.trading_timeframe,
            trigger_pattern=classification.pattern,
            trigger_direction=classification.direction,
            entry=entry,
            stop=stop,
            target=target,
            risk_reward=rr,
        )

        self._fire_trigger(trigger)

    def _find_target(self, zone: ZoneEntry, entry: float, stop_distance: float) -> float:
        """Find the next S/R level in trade direction for the target."""
        ticker = zone.instrument.replace("_", "")
        try:
            snr_data = self.snr_client.get_snr_levels(
                ticker=ticker, intervals=["1mo", "1w", "1d"], market_type="forex",
            )
        except Exception:
            snr_data = {}

        if zone.trade_direction == "BUY":
            # Look for supply (resistance) above entry
            candidates = []
            for tf in ["1d", "1w", "1mo"]:
                r = (snr_data or {}).get(tf, {}).get("resistance_price")
                if r and r > entry + stop_distance:
                    candidates.append(r)
            if candidates:
                return min(candidates)  # Nearest resistance above
            return entry + (stop_distance * 2)  # 2:1 R:R fallback
        else:
            # Look for demand (support) below entry
            candidates = []
            for tf in ["1d", "1w", "1mo"]:
                s = (snr_data or {}).get(tf, {}).get("support_price")
                if s and s < entry - stop_distance:
                    candidates.append(s)
            if candidates:
                return max(candidates)  # Nearest support below
            return entry - (stop_distance * 2)

    def _fire_trigger(self, trigger: TriggerResult):
        """Process a trigger — log, build signal, call handler."""
        zone = trigger.zone

        # Mark as triggered
        zone.status = "triggered"

        # Dedup
        setup_key = f"{zone.instrument}:{zone.zone_timeframe}:{zone.zone_type}:{zone.zone_price:.5f}"
        if setup_key in self._placed_setups:
            return
        self._placed_setups.add(setup_key)

        logger.info(
            "Trigger: %s %s %s at %s %s -- score %d/100",
            zone.instrument, trigger.trigger_timeframe, trigger.trigger_pattern,
            self._tf_label(zone.zone_timeframe), zone.zone_type,
            int(zone.bias_score),
        )
        logger.info(
            "TRADE: %s %s @ %.5f | Stop: %.5f | Target: %.5f | R:R: %.1f",
            zone.trade_direction, zone.instrument,
            trigger.entry, trigger.stop, trigger.target, trigger.risk_reward,
        )

        # Build signal metadata
        trend_total = len(zone.trends) or 1
        if zone.trade_direction == "BUY":
            trend_agrees = sum(1 for d in zone.trends.values() if d == "bullish")
        else:
            trend_agrees = sum(1 for d in zone.trends.values() if d == "bearish")

        # Approximate candle score from bias
        candle_score_approx = round((zone.bias_score - (trend_agrees / trend_total * 60)) / 40 * 3)
        candle_score_approx = max(0, min(3, candle_score_approx))

        levels_meta = {
            "strategy": "htf_levels",
            "strategy_id": "htf_levels",
            "model": self.model_name,
            "zone_timeframe": self._tf_label(zone.zone_timeframe),
            "zone_type": zone.zone_type,
            "zone_price": zone.zone_price,
            "trigger_timeframe": trigger.trigger_timeframe,
            "trigger_pattern": trigger.trigger_pattern,
            "bias_score": zone.bias_score,
            "trend_score": f"{trend_agrees}/{trend_total}",
            "candle_score": f"{candle_score_approx}/3",
            "candle_summary": zone.candle_summary,
            "trends": zone.trends,
            "tf_details": zone.tf_details,
            "zone_visit_count": zone.visit_count,
            "atr": zone.atr,
            "is_stock": "_" not in zone.instrument,
        }

        signal = Signal(
            action=zone.trade_direction,
            symbol=zone.instrument.replace("_", ""),
            entry=trigger.entry,
            stop=trigger.stop,
            target=trigger.target,
            timeframe=zone.zone_timeframe,
            risk_reward=trigger.risk_reward,
        )

        if self.on_signal:
            self.on_signal(signal, extra_meta=levels_meta)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self, stop_event=None, **_kwargs):
        """Run the three-phase loop.

        Phase 1 runs every watchlist_interval seconds.
        Phase 2 + 3 run every monitor_interval seconds.
        """
        logger.info(
            "[%s] Strategy running -- zones: %s, trigger: %s, bias: %s, "
            "watchlist every %ds, monitor every %ds, min R:R: %.1f",
            self.model_name.upper(), self.zone_tfs, self.trading_timeframe,
            self.bias_tf, self.watchlist_interval, self.monitor_interval,
            self.min_risk_reward,
        )

        ticks_per_watchlist = max(1, self.watchlist_interval // self.monitor_interval)
        tick = 0

        while stop_event is None or not stop_event.is_set():
            # Phase 1: refresh watchlist on first tick and every N ticks
            if tick % ticks_per_watchlist == 0:
                try:
                    self._refresh_watchlist()
                except Exception as e:
                    logger.error("Watchlist refresh error: %s", e)

            # Phase 2: monitor zones
            try:
                self._monitor_zones()
            except Exception as e:
                logger.error("Zone monitor error: %s", e)

            # Phase 3: check triggers
            try:
                self._check_triggers()
            except Exception as e:
                logger.error("Trigger check error: %s", e)

            # Clean up triggered zones
            self._watchlist = [z for z in self._watchlist if z.status != "triggered"]

            tick += 1

            if stop_event is not None:
                stop_event.wait(self.monitor_interval)
            else:
                time.sleep(self.monitor_interval)
