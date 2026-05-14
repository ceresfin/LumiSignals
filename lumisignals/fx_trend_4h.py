"""FX Intraday 4H Trend Strategy — live execution.

Same rules as saas/backtest_fx_4h.py v4 (the one with edge):

  Entry (all true on a 4H bar close):
    - close > 20 EMA on 4H
    - close > weekly VWAP (Sun 17:00 ET anchor)
    - close > monthly VWAP (1st 17:00 ET anchor)
    - green overwhelm pattern (or all mirrored for shorts)
  Plus gates:
    - regime is ELIGIBLE this week (regime:fx_4h:{pair} in Redis)
    - correlation guard: don't open EUR_USD if GBP_USD already open (and vice versa)
    - concurrency cap: max 2 open positions across the universe
    - no new entries Fri >= 12:00 ET

  Risk: $1000 per trade
  Stop: entry ± 1.5 × ATR(14) on 4H
  Target: 2:1 R:R (Oanda native takeProfitOnFill)
  Invalidation exit (bot-checked): 4H close back across EMA20

Detection: poll Oanda every minute, react to each newly closed 4H bar
exactly once per pair via per-pair candle-time dedup (mirrors fx_scalp_2n20).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .oanda_client import OandaClient
from .overwhelm_detector import detect_overwhelm, parse_oanda_candles
from .regime import week_anchor, to_et, pip_factor, RegimeFingerprint

logger = logging.getLogger(__name__)

# ─── Strategy constants ───────────────────────────────────────────────────
DEFAULT_PAIRS = ["EUR_USD", "USD_JPY", "GBP_USD", "USD_CHF",
                  "AUD_USD", "USD_CAD", "NZD_USD"]
GRANULARITY = "H4"
CANDLE_FETCH_COUNT = 240         # ~40 days of H4 — enough for EMA(20),
                                  # ATR(14), and a clean monthly VWAP.
EMA_PERIOD = 20
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
RR_TARGET = 2.0
RISK_PER_TRADE = 1000.0          # dollars
MAX_CONCURRENT = 2
FRIDAY_CUTOFF_HOUR_ET = 12

# Pairs in the same group can't both be open at once (highly correlated;
# would compound losses on EUR/GBP risk).  Extend as needed.
CORRELATION_GROUPS: List[set[str]] = [
    {"EUR_USD", "GBP_USD"},
]

# Anchor for monthly VWAP (first 17:00 ET of the month).
MONTH_ANCHOR_HOUR_ET = 17


# ─── State ────────────────────────────────────────────────────────────────
@dataclass
class FX4HState:
    instrument: str
    # Trade currently open (Oanda trade id) and key parameters so we can
    # apply bot-side exits (EMA invalidation, Friday flat).
    trade_id: Optional[str] = None
    direction: Optional[str] = None      # "BUY" or "SELL"
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    units: int = 0
    opened_at: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.trade_id is not None


# ─── Helpers ──────────────────────────────────────────────────────────────
def _ema(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    sma = sum(closes[:period]) / period
    alpha = 2.0 / (period + 1)
    ema = sma
    for v in closes[period:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _atr(bars: list[dict], period: int) -> Optional[float]:
    """Wilder ATR(N) on a list of {high, low, close} bars."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["high"] - b["low"])
            continue
        prev_c = bars[i - 1]["close"]
        trs.append(max(b["high"] - b["low"],
                       abs(b["high"] - prev_c),
                       abs(b["low"] - prev_c)))
    atr = sum(trs[:period]) / period
    for v in trs[period:]:
        atr = (atr * (period - 1) + v) / period
    return atr


def _month_anchor(ts: datetime) -> datetime:
    et = to_et(ts)
    candidate = et.replace(day=1, hour=MONTH_ANCHOR_HOUR_ET,
                            minute=0, second=0, microsecond=0)
    if candidate > et:
        prev_last = et.replace(day=1) - timedelta(days=1)
        candidate = prev_last.replace(day=1, hour=MONTH_ANCHOR_HOUR_ET,
                                       minute=0, second=0, microsecond=0)
    return candidate


def _vwap_from_anchor(bars: list[dict], anchor_fn) -> Optional[float]:
    """Running VWAP since the most recent anchor of each bar's timestamp.
    Bars need 'time', 'high', 'low', 'close', 'volume'.  Returns VWAP
    valid for the most recent bar."""
    if not bars:
        return None
    last_ts = bars[-1]["ts"]
    anchor = anchor_fn(last_ts)
    num = 0.0
    den = 0.0
    for b in bars:
        if b["ts"] < anchor:
            continue
        vol = max(int(b.get("volume", 1)), 1)
        hlc3 = (b["high"] + b["low"] + b["close"]) / 3
        num += hlc3 * vol
        den += vol
    return num / den if den > 0 else None


# ─── Strategy ─────────────────────────────────────────────────────────────
class FXTrend4H:
    """FX 4H trend strategy.  Polled every minute by the parent loop;
    reacts to each newly closed 4H bar exactly once per pair."""

    def __init__(self, oanda: OandaClient,
                 pairs: Optional[List[str]] = None,
                 risk_per_trade: float = RISK_PER_TRADE,
                 signal_callback=None,
                 redis_url: Optional[str] = None):
        self.oanda = oanda
        self.pairs = pairs or list(DEFAULT_PAIRS)
        self.risk_per_trade = risk_per_trade
        self.signal_callback = signal_callback
        self.states: Dict[str, FX4HState] = {
            p: FX4HState(instrument=p) for p in self.pairs
        }
        self._last_candle_time: Dict[str, str] = {}
        # Redis client for regime lookup + persistent state recovery
        import redis as _redis
        self._rdb = _redis.from_url(
            redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        self._init_states_from_broker()

    # ─── Startup state recovery ───────────────────────────────────────────
    def _init_states_from_broker(self):
        """Read Oanda's open trades + our Redis state cache so a restart
        doesn't lose track of in-flight positions."""
        try:
            resp = self.oanda.get_trades(state="OPEN", count=50)
            trades = resp.get("trades", [])
        except Exception as e:
            logger.warning("fx_4h startup: could not fetch open trades: %s", e)
            trades = []
        # Match by client extension tag we set on entry, otherwise by Redis
        for tr in trades:
            tag = (tr.get("clientExtensions") or {}).get("tag", "")
            if not tag.startswith("fx_4h:"):
                continue
            instr = tr.get("instrument", "")
            if instr not in self.states:
                continue
            st = self.states[instr]
            st.trade_id = tr.get("id")
            st.direction = "BUY" if int(tr.get("currentUnits", 0)) > 0 else "SELL"
            st.entry_price = float(tr.get("price", 0))
            st.units = abs(int(tr.get("currentUnits", 0)))
            # Pull stop/target from the persisted Redis record so we have
            # the prices the bot wants for invalidation checks.
            cached = self._read_state(instr)
            if cached:
                st.stop_price = float(cached.get("stop_price") or 0)
                st.target_price = float(cached.get("target_price") or 0)
                ts = cached.get("opened_at")
                if ts:
                    try:
                        st.opened_at = datetime.fromisoformat(ts)
                    except Exception:
                        pass
            logger.info("fx_4h restored open trade: %s %s %d units @ %.5f",
                        instr, st.direction, st.units, st.entry_price)

    # ─── Redis persistence ────────────────────────────────────────────────
    def _state_key(self, pair: str) -> str:
        return f"fx_4h:state:{pair}"

    def _write_state(self, pair: str, st: FX4HState):
        if not st.is_open:
            self._rdb.delete(self._state_key(pair))
            return
        self._rdb.set(self._state_key(pair), json.dumps({
            "trade_id": st.trade_id,
            "direction": st.direction,
            "entry_price": st.entry_price,
            "stop_price": st.stop_price,
            "target_price": st.target_price,
            "units": st.units,
            "opened_at": st.opened_at.isoformat() if st.opened_at else "",
        }))

    def _read_state(self, pair: str) -> dict:
        raw = self._rdb.get(self._state_key(pair))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _regime_ok(self, pair: str) -> bool:
        raw = self._rdb.get(f"regime:fx_4h:{pair}")
        if not raw:
            # No regime data yet — conservative: refuse the trade.
            return False
        try:
            state = json.loads(raw)
            return bool(state.get("eligible"))
        except Exception:
            return False

    # ─── Public scan loop ─────────────────────────────────────────────────
    def scan_all(self):
        for pair in self.pairs:
            try:
                self._scan_pair(pair)
            except Exception as e:
                logger.exception("fx_4h scan %s failed: %s", pair, e)

    def _scan_pair(self, pair: str):
        # Fetch enough H4 history for indicators + VWAP windows.
        candles = self.oanda.get_candles(pair, GRANULARITY, CANDLE_FETCH_COUNT)
        if not candles:
            return
        # Parse + filter to completed bars.
        bars: list[dict] = []
        for c in candles:
            if not c.get("complete", True):
                continue
            mid = c.get("mid", {})
            try:
                ts_raw = c.get("time", "").replace("Z", "")
                if "." in ts_raw:
                    base, frac = ts_raw.split(".", 1)
                    ts_raw = f"{base}.{frac[:6]}"
                ts = datetime.fromisoformat(ts_raw).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            bars.append({
                "ts": ts,
                "open": float(mid.get("o", 0)),
                "high": float(mid.get("h", 0)),
                "low": float(mid.get("l", 0)),
                "close": float(mid.get("c", 0)),
                "volume": int(c.get("volume", 0)),
            })
        if len(bars) < EMA_PERIOD + 5:
            return

        latest = bars[-1]
        latest_ts_iso = latest["ts"].isoformat()
        state = self.states[pair]

        # ─── Exit checks (always — even if we don't act on a new bar) ───
        if state.is_open:
            self._check_exits(pair, state, bars, latest)
            # If still open after the check, fall through (we never enter
            # a new position on the same pair while one is live).
            if state.is_open:
                return

        # ─── Once-per-bar dedup ──────────────────────────────────────────
        if self._last_candle_time.get(pair) == latest_ts_iso:
            return
        # Only entry-check on a newly closed bar.
        self._last_candle_time[pair] = latest_ts_iso

        self._check_entries(pair, bars, latest)

    # ─── Exit logic ───────────────────────────────────────────────────────
    def _check_exits(self, pair: str, state: FX4HState,
                     bars: list[dict], latest: dict):
        """EMA invalidation + Friday-flat exits.  Oanda's bracket
        (takeProfitOnFill / stopLossOnFill) handles the price-based
        stops/targets so we don't need to mirror those here."""
        closes = [b["close"] for b in bars]
        ema = _ema(closes, EMA_PERIOD)
        if ema is None:
            return
        prev_close = bars[-2]["close"] if len(bars) >= 2 else latest["close"]
        prev_ema = _ema(closes[:-1], EMA_PERIOD)

        # Only act on newly-closed bars for invalidation
        latest_ts_iso = latest["ts"].isoformat()
        same_bar_as_last_check = (
            self._rdb.get(f"fx_4h:last_exit_check:{pair}") == latest_ts_iso
        )
        # Friday cutoff (always fires)
        et = to_et(latest["ts"])
        friday_flat = (et.weekday() == 4 and et.hour >= 16)
        if friday_flat:
            self._close_trade(pair, state, latest["close"], "WEEKEND_FLAT")
            return

        if same_bar_as_last_check:
            return
        self._rdb.set(f"fx_4h:last_exit_check:{pair}", latest_ts_iso, ex=86400)

        # Cross of EMA against the trade direction
        if state.direction == "BUY":
            if prev_ema is not None and prev_close > prev_ema and latest["close"] < ema:
                self._close_trade(pair, state, latest["close"], "EMA_INVALIDATION")
        elif state.direction == "SELL":
            if prev_ema is not None and prev_close < prev_ema and latest["close"] > ema:
                self._close_trade(pair, state, latest["close"], "EMA_INVALIDATION")

    # ─── Entry logic ──────────────────────────────────────────────────────
    def _check_entries(self, pair: str, bars: list[dict], latest: dict):
        # Friday cutoff
        et = to_et(latest["ts"])
        if et.weekday() == 4 and et.hour >= FRIDAY_CUTOFF_HOUR_ET:
            return

        # Regime gate
        if not self._regime_ok(pair):
            return

        # Concurrency cap
        open_count = sum(1 for s in self.states.values() if s.is_open)
        if open_count >= MAX_CONCURRENT:
            return

        # Correlation guard
        for group in CORRELATION_GROUPS:
            if pair in group:
                for other in group:
                    if other != pair and self.states.get(other, FX4HState(other)).is_open:
                        logger.info("fx_4h SKIP %s: correlated %s already open",
                                    pair, other)
                        return

        # Indicators
        closes = [b["close"] for b in bars]
        ema = _ema(closes, EMA_PERIOD)
        atr = _atr(bars, ATR_PERIOD)
        if ema is None or atr is None:
            return
        vwap_w = _vwap_from_anchor(bars, week_anchor)
        vwap_m = _vwap_from_anchor(bars, _month_anchor)
        if vwap_w is None or vwap_m is None:
            return

        # Overwhelm trigger
        ohlc = [{"open": b["open"], "high": b["high"], "low": b["low"],
                 "close": b["close"]} for b in bars[-12:]]
        green, red = detect_overwhelm(ohlc)
        if not green and not red:
            return

        close = latest["close"]
        if green:
            if not (close > ema and close > vwap_w and close > vwap_m):
                return
            direction = "BUY"
        else:
            if not (close < ema and close < vwap_w and close < vwap_m):
                return
            direction = "SELL"

        # Size the position
        pf = pip_factor(pair)
        stop_distance_price = ATR_STOP_MULT * atr
        stop_pips = stop_distance_price / pf
        # USD-per-pip per unit (assumes USD quote pairs; USD-base pairs
        # get converted by the rate so it's a reasonable approximation).
        quote = pair.split("_")[1]
        if quote == "USD":
            usd_per_pip_per_unit = pf
        else:
            usd_per_pip_per_unit = pf / close if close else pf
        units = int(self.risk_per_trade / (stop_pips * usd_per_pip_per_unit))
        if units <= 0:
            logger.warning("fx_4h size came out 0 for %s; skipping", pair)
            return

        # Price levels
        if direction == "BUY":
            stop = close - stop_distance_price
            target = close + RR_TARGET * stop_distance_price
        else:
            stop = close + stop_distance_price
            target = close - RR_TARGET * stop_distance_price
            units = -units   # negative units = SELL on Oanda

        self._open_trade(pair, direction, close, stop, target, units, atr)

    # ─── Order placement ──────────────────────────────────────────────────
    def _open_trade(self, pair: str, direction: str,
                    entry: float, stop: float, target: float,
                    units: int, atr: float):
        from .fx_scalp_2n20 import get_pip_precision, format_price
        _, precision = get_pip_precision(pair)
        order_data = {
            "type": "MARKET",
            "instrument": pair,
            "units": str(units),
            "stopLossOnFill": {"price": format_price(stop, precision)},
            "takeProfitOnFill": {"price": format_price(target, precision)},
            "clientExtensions": {
                "tag": f"fx_4h:{pair}",
                "comment": f"fx_4h_trend ATR={atr:.5f}",
            },
        }
        try:
            result = self.oanda.create_order(order_data)
        except Exception as e:
            logger.error("fx_4h open failed for %s: %s", pair, e)
            return
        # Parse the fill from the response.
        fill = result.get("orderFillTransaction") or {}
        trade_id = fill.get("tradeOpened", {}).get("tradeID") \
                   or fill.get("id")
        actual_fill = float(fill.get("price", entry))

        state = self.states[pair]
        state.trade_id = str(trade_id) if trade_id else None
        state.direction = direction
        state.entry_price = actual_fill
        state.stop_price = stop
        state.target_price = target
        state.units = abs(units)
        state.opened_at = datetime.now(timezone.utc)
        self._write_state(pair, state)

        logger.info("fx_4h OPEN %s %s %d units @ %.5f  SL=%.5f TP=%.5f",
                    pair, direction, abs(units), actual_fill, stop, target)
        # Notification
        try:
            from .supabase_client import notify_trade_opened
            uid = os.environ.get("SUPABASE_USER_ID", "")
            risk = abs(actual_fill - stop) * abs(units) / (actual_fill if "USD" != pair.split("_")[1] else 1)
            reward = abs(target - actual_fill) * abs(units) / (actual_fill if "USD" != pair.split("_")[1] else 1)
            if uid:
                notify_trade_opened(
                    user_id=uid, instrument=pair, direction=direction,
                    entry_price=actual_fill, strategy=f"FX 4H {direction}",
                    stop=stop, target=target,
                    risk_dollars=risk, reward_dollars=reward, rr_ratio=2.0,
                )
        except Exception as e:
            logger.debug("fx_4h notify open failed: %s", e)
        if self.signal_callback:
            try:
                self.signal_callback({
                    "instrument": pair, "direction": direction,
                    "entry": actual_fill, "stop": stop, "target": target,
                    "units": units, "strategy": "fx_4h_trend",
                })
            except Exception:
                pass

    def _close_trade(self, pair: str, state: FX4HState,
                     last_price: float, reason: str):
        if not state.trade_id:
            return
        try:
            resp = self.oanda._request(
                "PUT",
                f"/v3/accounts/{self.oanda.account_id}/trades/{state.trade_id}/close",
                json_data={"units": "ALL"},
            )
        except Exception as e:
            logger.error("fx_4h close failed for %s (trade %s): %s",
                         pair, state.trade_id, e)
            return
        fill = resp.get("orderFillTransaction") or {}
        exit_price = float(fill.get("price", last_price))
        pnl = float(fill.get("pl", 0))
        logger.info("fx_4h CLOSE %s %s @ %.5f reason=%s pnl=$%.2f",
                    pair, state.direction, exit_price, reason, pnl)

        # Telegram + record
        try:
            from .supabase_client import notify_trade_closed, record_closed_trade
            uid = os.environ.get("SUPABASE_USER_ID", "")
            pf = pip_factor(pair)
            pip_move = (exit_price - state.entry_price) / pf * \
                       (1 if state.direction == "BUY" else -1)
            if uid:
                notify_trade_closed(uid, pair, state.direction, pnl,
                                     pip_move, reason)
                record_closed_trade(uid, {
                    "id": state.trade_id,
                    "broker": "oanda",
                    "instrument": pair,
                    "asset_type": "forex",
                    "direction": "LONG" if state.direction == "BUY" else "SHORT",
                    "units": state.units,
                    "entry": state.entry_price,
                    "close_price": exit_price,
                    "stop_loss": state.stop_price,
                    "take_profit": state.target_price,
                    "realized_pl": pnl,
                    "pips": pip_move,
                    "strategy": "fx_4h_trend",
                    "model": "intraday_4h",
                    "close_reason": reason,
                    "won": pnl > 0,
                    "time_opened": state.opened_at.isoformat() if state.opened_at else "",
                    "time_closed": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as e:
            logger.debug("fx_4h notify close failed: %s", e)

        # Clear state
        state.trade_id = None
        state.direction = None
        state.entry_price = 0.0
        state.stop_price = 0.0
        state.target_price = 0.0
        state.units = 0
        state.opened_at = None
        self._write_state(pair, state)
