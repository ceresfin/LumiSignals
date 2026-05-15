"""H1 Zone Scalp — paper-launch strategy.

Spec (locked 2026-05-14):

  Universe: 7 USD majors
  Zones:    find_untouched_levels(H1) — single price points, treated as zone edges
  Entry:    Limit 2 pips BEYOND the level in the loss direction
              BUY at demand D  -> limit at D + 2 pips
              SELL at supply S -> limit at S - 2 pips
            Catches wicks that don't quite reach the exact level price.
  Stop:     3 × ATR(5m), beyond the level
              BUY:  stop = D - 3×ATR(5m)
              SELL: stop = S + 3×ATR(5m)
  Trend:    calculate_adx_direction(...) direction-only, no strength threshold
              alpha: 15m candles must agree with zone direction
              beta : 1h  candles must agree with zone direction
            Both fire independently — when 15m AND 1h agree, BOTH variants
            place trades on the same signal (= 8 trades on one zone).
  Targets:  4 separate trades per signal, each $10 risk:
              T1 = entry + 25% of (entry → opposing zone) distance
              T2 = entry + 50%
              T3 = entry + 75%
              T4 = ride to nearest opposing H1 zone (100%)
                   When T3 fills, T4's stop is moved to entry+1R and trails
                   by 1×ATR(5m) on each new 5m close.
  Stop-tightening rule: if T1 distance < default stop (3×ATR(5m)), tighten
                stop to T1_distance / 1.2 so T1 R:R ≥ 1.2.
                Floor: never tighten below 1×ATR(5m) — if even that wouldn't
                hit the 1.2:1 minimum, skip the setup (zone too close).
  Daily circuit breaker: NONE (paper-only by design).

Each trade is tagged in Oanda clientExtensions with
  "scalp_h1zone:{variant}:{pair}:{target_label}"
so we can reconcile on restart and the Trades tab can split by variant.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .oanda_client import OandaClient
from .order_manager import get_pip_precision, format_price
from .untouched_levels import find_untouched_levels, calculate_trend_direction

logger = logging.getLogger(__name__)

# ─── Strategy constants ───────────────────────────────────────────────────
DEFAULT_PAIRS = ["EUR_USD", "USD_JPY", "GBP_USD", "USD_CHF",
                 "AUD_USD", "USD_CAD", "NZD_USD"]
VARIANTS = ("alpha", "beta")

ENTRY_OFFSET_PIPS = 2.0          # 2 pips beyond the level (loss direction)
ATR_STOP_MULT = 3.0              # 3 × ATR(5m) beyond level for default stop
RISK_PER_TRADE = 10.0            # USD per trade leg
TARGET_FRACTIONS = (0.25, 0.50, 0.75, 1.00)  # T1..T4 share of (entry → opposing) distance
MIN_T1_RR = 1.2                  # tighten stop until T1 reaches at least 1.2:1
ATR_FLOOR_MULT = 1.0             # never tighten stop below 1×ATR(5m) — noise floor
TRAIL_AFTER_T3_LOCK_R = 1.0      # T4 stop → entry + 1R after T3 fills
TRAIL_ATR_MULT = 1.0             # then trail by 1×ATR(5m)

H1_CANDLE_COUNT = 30             # for find_untouched_levels (10-bar lookback + buffer)
TRIGGER_CANDLE_COUNT = 100       # 5m candles for ATR + price reads
ADX_15M_COUNT = 250              # N=15 structure — need enough pivot history
ADX_1H_COUNT = 250                # for an honest macro read (not just recent micro)

ZONE_REFRESH_SECONDS = 600       # re-derive H1 zones every 10 min
                                  # (H1 closes once per hour, so 10 min is plenty)

# Variants always run independently; this just controls trend-TF lookup
VARIANT_TF = {
    "alpha": "M15",
    "beta":  "H1",
}
VARIANT_CANDLE_COUNT = {
    "alpha": ADX_15M_COUNT,
    "beta":  ADX_1H_COUNT,
}


# ─── State ────────────────────────────────────────────────────────────────
@dataclass
class TradeLeg:
    """One of the 4 trade legs (T1/T2/T3/T4) on a single signal."""
    target_label: str         # "T1" | "T2" | "T3" | "T4"
    order_id: Optional[str] = None
    trade_id: Optional[str] = None
    units: int = 0
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0   # 0.0 for T4 (no fixed target — opposing zone or trailing)
    state: str = "PENDING"      # PENDING | FILLED | CLOSED


@dataclass
class SignalBundle:
    """The 4-trade bundle from one signal — one variant on one pair."""
    pair: str
    variant: str                # "alpha" | "beta"
    direction: str              # "BUY" | "SELL"
    zone_price: float
    opposing_zone: float
    stop_distance: float        # in PRICE units (not pips)
    atr_5m_at_entry: float
    legs: List[TradeLeg] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    t3_filled: bool = False     # toggles the T4-trailing path


@dataclass
class PairState:
    """Per-pair, per-variant rolling state."""
    pair: str
    variant: str
    last_zone_refresh_ts: float = 0.0
    s1: Optional[float] = None
    s2: Optional[float] = None
    d1: Optional[float] = None
    d2: Optional[float] = None
    # Active signal bundles (typically 0 or 1 per pair-variant at any moment;
    # we allow >1 if multiple zones touched in quick succession)
    bundles: List[SignalBundle] = field(default_factory=list)
    # Dedup: don't re-fire on the same zone price within this many seconds
    last_fire_zone: Optional[float] = None
    last_fire_ts: float = 0.0


# ─── Helpers ──────────────────────────────────────────────────────────────
def _pip_factor(pair: str) -> float:
    pip, _ = get_pip_precision(pair)
    return pip


def _usd_per_pip_per_unit(pair: str, current_price: float) -> float:
    """USD-per-pip per 1 unit, used to convert $-risk → units.
    Approximation for non-USD-quoted pairs uses current price.
    """
    pf = _pip_factor(pair)
    parts = pair.split("_")
    if len(parts) != 2:
        return pf
    base, quote = parts
    if quote == "USD":
        return pf
    if base == "USD":
        return pf / current_price if current_price else pf
    # cross pair (none in this universe today, but be safe)
    return pf / current_price if current_price else pf


def _atr(bars: List[dict], period: int = 14) -> Optional[float]:
    """Wilder ATR on a list of bars sorted oldest-first.
    Each bar must have float keys: high, low, close.
    """
    if len(bars) < period + 1:
        return None
    trs: List[float] = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    atr_val = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def _parse_oanda_candles(resp: dict) -> List[dict]:
    """Return list of {time, open, high, low, close} dicts, oldest-first.
    Skips bars whose 'complete' flag is False (i.e. the current forming bar).
    """
    out = []
    for c in resp.get("candles", []):
        if not c.get("complete"):
            continue
        mid = c.get("mid") or {}
        try:
            out.append({
                "time": c.get("time"),
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low":  float(mid["l"]),
                "close": float(mid["c"]),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


# ─── Strategy class ───────────────────────────────────────────────────────
class H1ZoneScalp:
    """H1 Zone Scalp strategy — runs α + β in parallel, paper-only by intent."""

    def __init__(self, oanda: OandaClient, pairs: Optional[List[str]] = None,
                 signal_callback=None):
        self.oanda = oanda
        self.pairs = pairs or list(DEFAULT_PAIRS)
        self.signal_callback = signal_callback
        # state[pair][variant] = PairState
        self.state: Dict[str, Dict[str, PairState]] = {
            p: {v: PairState(pair=p, variant=v) for v in VARIANTS}
            for p in self.pairs
        }
        # On startup, reconcile in-memory bundles with Oanda's open trades by
        # parsing the clientExtensions tag we put on each leg.
        self._init_from_broker()

    # ─── Boot reconciliation ──────────────────────────────────────────────
    def _init_from_broker(self):
        """Read Oanda open trades and rebuild SignalBundles for any leg whose
        clientExtensions tag matches scalp_h1zone:{variant}:{pair}:{target}.
        Without this, restarting the bot would lose track of T4 trailing.
        """
        try:
            resp = self.oanda._request("GET",
                f"/v3/accounts/{self.oanda.account_id}/openTrades")
            trades = resp.get("trades", [])
        except Exception as e:
            logger.warning("[H1ZONE] init_from_broker failed: %s", e)
            return

        # Group legs by (pair, variant, signal cohort).
        # Cohort = trades opened within ~3 seconds of each other on the same
        # pair+variant — those came from one signal.
        leg_rows: List[Tuple[str, str, str, dict]] = []
        for t in trades:
            tag = ((t.get("clientExtensions") or {}).get("tag") or "")
            if not tag.startswith("scalp_h1zone:"):
                continue
            parts = tag.split(":")
            if len(parts) != 4:
                continue
            _, variant, pair, target_label = parts
            if pair not in self.state or variant not in self.state[pair]:
                continue
            leg_rows.append((pair, variant, target_label, t))

        # Bucket by pair+variant, then by 3-second open window
        from collections import defaultdict
        by_pv: Dict[Tuple[str, str], list] = defaultdict(list)
        for pair, variant, tl, t in leg_rows:
            by_pv[(pair, variant)].append((tl, t))

        for (pair, variant), rows in by_pv.items():
            rows.sort(key=lambda r: r[1].get("openTime", ""))
            cohorts: List[List[Tuple[str, dict]]] = []
            for row in rows:
                placed = False
                for c in cohorts:
                    if abs(_iso_to_epoch(row[1].get("openTime", ""))
                           - _iso_to_epoch(c[0][1].get("openTime", ""))) < 5:
                        c.append(row); placed = True; break
                if not placed:
                    cohorts.append([row])
            for c in cohorts:
                bundle = self._rebuild_bundle_from_cohort(pair, variant, c)
                if bundle is not None:
                    self.state[pair][variant].bundles.append(bundle)
        n = sum(len(self.state[p][v].bundles) for p in self.pairs for v in VARIANTS)
        logger.info("[H1ZONE] init_from_broker: recovered %d active bundles", n)

    def _rebuild_bundle_from_cohort(self, pair, variant, cohort):
        """Reconstruct one SignalBundle from a cohort of recovered legs."""
        if not cohort:
            return None
        first = cohort[0][1]
        try:
            units = int(float(first.get("currentUnits", 0)))
        except Exception:
            units = 0
        direction = "BUY" if units > 0 else "SELL"
        entry_price = float(first.get("price", 0))
        # Find a leg with a stopLossOrder for stop_distance
        stop_price = 0.0
        for _, t in cohort:
            sl = t.get("stopLossOrder") or {}
            sp = sl.get("price")
            if sp:
                stop_price = float(sp); break
        if not stop_price:
            return None
        bundle = SignalBundle(
            pair=pair, variant=variant, direction=direction,
            zone_price=entry_price,  # approximate — we don't store the original level
            opposing_zone=0.0,       # unknown post-restart; T4 still has its TP order on Oanda
            stop_distance=abs(entry_price - stop_price),
            atr_5m_at_entry=0.0,     # unknown — we'll re-derive on the trail step
        )
        # T3 may have already filled before restart — detect by checking if
        # the trade marked as T4 has a stop that's already moved past entry+1R.
        # Otherwise mark all FILLED (each leg's exit is server-side).
        for tl, t in cohort:
            leg = TradeLeg(
                target_label=tl,
                order_id=None,
                trade_id=str(t.get("id", "")),
                units=abs(int(float(t.get("currentUnits", 0)))),
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=float((t.get("takeProfitOrder") or {}).get("price", 0)) or 0.0,
                state="FILLED",
            )
            bundle.legs.append(leg)
        # Heuristic for t3_filled: if T1/T2/T3 are not present in cohort, T3 must have hit.
        cohort_labels = {tl for tl, _ in cohort}
        if "T3" not in cohort_labels and "T4" in cohort_labels:
            bundle.t3_filled = True
        logger.info("[H1ZONE] recovered bundle %s %s %s entry=%.5f legs=%s t3=%s",
                    pair, variant, direction, entry_price,
                    sorted(cohort_labels), bundle.t3_filled)
        return bundle

    # ─── Main scan tick ───────────────────────────────────────────────────
    def scan_all(self):
        """Called every ~30s by bot_runner."""
        # Build a fresh "what's already in flight" cache once per tick so
        # _maybe_fire can dedup against Oanda's authoritative state (not just
        # our in-memory `last_fire_*` which can decay across restarts and
        # 1-hour boundaries).
        active = self._snapshot_active_keys()
        for pair in self.pairs:
            for variant in VARIANTS:
                try:
                    self._scan_pair_variant(pair, variant, active=active)
                except Exception as e:
                    logger.debug("[H1ZONE] scan %s/%s error: %s",
                                 pair, variant, e)

    def _snapshot_active_keys(self) -> set:
        """Return a set of (pair, variant, direction) tuples that already
        have at least one leg in flight on Oanda (pending limit OR open
        trade) tagged scalp_h1zone:{variant}:{pair}:T*.
        """
        active: set = set()
        acct = self.oanda.account_id
        # Pending limit orders
        try:
            resp = self.oanda._request("GET", f"/v3/accounts/{acct}/pendingOrders")
            for o in resp.get("orders", []):
                tag = ((o.get("clientExtensions") or {}).get("tag") or "")
                if not tag.startswith("scalp_h1zone:"):
                    continue
                parts = tag.split(":")
                if len(parts) != 4:
                    continue
                _, variant, pair, _label = parts
                try:
                    units = int(float(o.get("units", 0)))
                except Exception:
                    continue
                direction = "BUY" if units > 0 else "SELL"
                active.add((pair, variant, direction))
        except Exception as e:
            logger.debug("[H1ZONE] snapshot pendingOrders failed: %s", e)
        # Open trades
        try:
            resp = self.oanda._request("GET", f"/v3/accounts/{acct}/openTrades")
            for t in resp.get("trades", []):
                tag = ((t.get("clientExtensions") or {}).get("tag") or "")
                if not tag.startswith("scalp_h1zone:"):
                    continue
                parts = tag.split(":")
                if len(parts) != 4:
                    continue
                _, variant, pair, _label = parts
                try:
                    units = int(float(t.get("currentUnits", 0)))
                except Exception:
                    continue
                direction = "BUY" if units > 0 else "SELL"
                active.add((pair, variant, direction))
        except Exception as e:
            logger.debug("[H1ZONE] snapshot openTrades failed: %s", e)
        return active

    def _scan_pair_variant(self, pair: str, variant: str, *, active: set = None):
        ps = self.state[pair][variant]

        # 1) Manage already-open bundles (T3-fill detection + T4 trailing)
        if ps.bundles:
            self._manage_bundles(ps)

        # 2) Refresh H1 zones if stale
        now = time.time()
        if now - ps.last_zone_refresh_ts > ZONE_REFRESH_SECONDS:
            self._refresh_zones(pair, ps)

        # 3) Look for new signal
        if ps.s1 is None and ps.d1 is None:
            return  # no zones available yet

        # 4) Fetch trend + 5m bars
        trend = self._fetch_adx_direction(pair, variant)
        if trend not in ("UP", "DOWN"):
            return  # SIDE → no fire
        m5 = self._fetch_5m_bars(pair)
        if len(m5) < 16:
            return
        atr5 = _atr(m5, 14)
        if atr5 is None or atr5 <= 0:
            return
        current_price = m5[-1]["close"]
        pf = _pip_factor(pair)
        offset_price = ENTRY_OFFSET_PIPS * pf

        # 5) Evaluate buy + sell paths
        if trend == "UP" and ps.d1 is not None:
            # BUY at demand. opposing zone = nearest supply above current price.
            self._maybe_fire(
                ps, direction="BUY", level=ps.d1,
                opposing=ps.s1 if (ps.s1 and ps.s1 > current_price) else
                         (ps.s2 if (ps.s2 and ps.s2 > current_price) else None),
                current_price=current_price, atr5=atr5,
                offset_price=offset_price, active=active)
        if trend == "DOWN" and ps.s1 is not None:
            # SELL at supply. opposing zone = nearest demand below current.
            self._maybe_fire(
                ps, direction="SELL", level=ps.s1,
                opposing=ps.d1 if (ps.d1 and ps.d1 < current_price) else
                         (ps.d2 if (ps.d2 and ps.d2 < current_price) else None),
                current_price=current_price, atr5=atr5,
                offset_price=offset_price, active=active)

    # ─── Zone refresh ─────────────────────────────────────────────────────
    def _refresh_zones(self, pair: str, ps: PairState):
        bars = self._fetch_h1_bars(pair)
        if len(bars) < 12:
            return
        # find_untouched_levels expects most-recent-first
        highs = [b["high"] for b in reversed(bars)]
        lows = [b["low"] for b in reversed(bars)]
        cur_price = bars[-1]["close"]
        s1, s2, d1, d2 = find_untouched_levels(highs, lows, cur_price, lookback=10)
        ps.s1, ps.s2, ps.d1, ps.d2 = s1, s2, d1, d2
        ps.last_zone_refresh_ts = time.time()
        logger.debug("[H1ZONE] %s/%s zones refreshed S1=%s D1=%s",
                     pair, ps.variant, s1, d1)

    # ─── Signal evaluation ────────────────────────────────────────────────
    def _maybe_fire(self, ps: PairState, *, direction: str, level: float,
                    opposing: Optional[float], current_price: float,
                    atr5: float, offset_price: float,
                    active: Optional[set] = None):
        if level is None:
            return
        if opposing is None:
            logger.debug("[H1ZONE] %s/%s skip — no opposing zone",
                         ps.pair, ps.variant)
            return

        # Hard dedup: if Oanda already has ANY pending limit OR open trade
        # tagged for (pair+variant+direction), do not fire another bundle.
        # This survives bot restarts and the 1-hour in-memory dedup boundary.
        if active is not None and (ps.pair, ps.variant, direction) in active:
            return

        # Reject if price is already past the level (we'd be entering late)
        if direction == "BUY" and current_price < level:
            return
        if direction == "SELL" and current_price > level:
            return

        # Reject if price is more than 6×ATR from the level — we don't want
        # to camp a limit miles away that may never fill before the zone goes
        # stale. (6 × 5m-ATR is generous on a strategy that prizes wicks.)
        if abs(current_price - level) > 6 * atr5:
            return

        # Compute entry first
        if direction == "BUY":
            entry_price = level + offset_price        # limit ABOVE level (above demand)
            opp_dist = opposing - entry_price
        else:  # SELL
            entry_price = level - offset_price        # limit BELOW level (below supply)
            opp_dist = entry_price - opposing

        if opp_dist <= 0:
            return  # opposing zone not on the trade side — defensive

        # Stop sizing: start with default 3×ATR(5m). If T1 distance (25% of
        # opp_dist) is smaller than that, tighten the stop so T1 R:R ≥ 1.2.
        # If even the tightened stop falls below the ATR noise floor, skip.
        default_stop_distance = ATR_STOP_MULT * atr5
        t1_dist = TARGET_FRACTIONS[0] * opp_dist  # 0.25 * opp_dist

        if t1_dist < default_stop_distance:
            tight_stop_distance = t1_dist / MIN_T1_RR
            if tight_stop_distance < ATR_FLOOR_MULT * atr5:
                logger.debug(
                    "[H1ZONE] %s/%s skip — opp too close (T1=%.5f, even tight "
                    "stop %.5f < %.1fx ATR(5m) %.5f)",
                    ps.pair, ps.variant, t1_dist, tight_stop_distance,
                    ATR_FLOOR_MULT, atr5)
                return
            stop_distance = tight_stop_distance
        else:
            stop_distance = default_stop_distance

        if direction == "BUY":
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        r_unit = stop_distance                        # 1R in price units

        # Dedup: don't re-fire on the same level within 1 hour
        if (ps.last_fire_zone is not None
                and abs(ps.last_fire_zone - level) < r_unit * 0.25
                and (time.time() - ps.last_fire_ts) < 3600):
            return

        # ─── Place 4 legs ────────────────────────────────────────────────
        bundle = self._open_bundle(
            ps, direction=direction, level=level, opposing=opposing,
            entry_price=entry_price, stop_price=stop_price,
            r_unit=r_unit, atr5=atr5)
        if bundle is not None:
            ps.bundles.append(bundle)
            ps.last_fire_zone = level
            ps.last_fire_ts = time.time()

    # ─── Order placement ──────────────────────────────────────────────────
    def _open_bundle(self, ps, *, direction, level, opposing,
                     entry_price, stop_price, r_unit, atr5) -> Optional[SignalBundle]:
        pair = ps.pair
        variant = ps.variant
        pip, precision = get_pip_precision(pair)

        # Position sizing: $10 risk per leg → units = 10 / (stop_pips × $/pip/unit)
        stop_pips = abs(entry_price - stop_price) / pip
        usd_pip_unit = _usd_per_pip_per_unit(pair, entry_price)
        if stop_pips <= 0 or usd_pip_unit <= 0:
            return None
        units_per_leg = int(RISK_PER_TRADE / (stop_pips * usd_pip_unit))
        if units_per_leg < 1:
            logger.info("[H1ZONE] %s/%s units came out 0 (stop_pips=%.2f) — skip",
                        pair, variant, stop_pips)
            return None

        bundle = SignalBundle(
            pair=pair, variant=variant, direction=direction,
            zone_price=level, opposing_zone=opposing,
            stop_distance=abs(entry_price - stop_price),
            atr_5m_at_entry=atr5,
        )

        # Compute target prices as fractions of (entry → opposing zone)
        # distance. T4 = opposing zone itself. r_unit is the stop distance.
        opp_dist = abs(opposing - entry_price)
        if direction == "BUY":
            t_prices = {
                "T1": entry_price + TARGET_FRACTIONS[0] * opp_dist,
                "T2": entry_price + TARGET_FRACTIONS[1] * opp_dist,
                "T3": entry_price + TARGET_FRACTIONS[2] * opp_dist,
                "T4": opposing,
            }
            signed_units = units_per_leg
        else:
            t_prices = {
                "T1": entry_price - TARGET_FRACTIONS[0] * opp_dist,
                "T2": entry_price - TARGET_FRACTIONS[1] * opp_dist,
                "T3": entry_price - TARGET_FRACTIONS[2] * opp_dist,
                "T4": opposing,
            }
            signed_units = -units_per_leg

        any_filled = False
        for label, target_price in t_prices.items():
            tag = f"scalp_h1zone:{variant}:{pair}:{label}"
            comment = (f"H1Zone {variant} {direction} level={level:.5f} "
                       f"R={r_unit:.5f} atr5m={atr5:.5f}")
            order_data = {
                "type": "LIMIT",
                "instrument": pair,
                "units": str(signed_units),
                "price": format_price(entry_price, precision),
                "timeInForce": "GTC",
                "stopLossOnFill": {"price": format_price(stop_price, precision)},
                "takeProfitOnFill": {"price": format_price(target_price, precision)},
                # Order-level clientExtensions — visible on the LIMIT_ORDER
                # transaction but NOT propagated to the resulting trade
                # when the limit fills.
                "clientExtensions": {"tag": tag, "comment": comment},
                # tradeClientExtensions DOES propagate to the trade record on
                # fill, so the trade itself carries the strategy tag. Without
                # this, oanda_trade_sync sees an empty tag and misattributes
                # the trade (was being labeled as 2n20 by accident).
                "tradeClientExtensions": {"tag": tag, "comment": comment},
            }
            try:
                result = self.oanda.create_order(order_data)
            except Exception as e:
                logger.error("[H1ZONE] order place failed %s/%s %s: %s",
                             pair, variant, label, e)
                continue

            order_id = ((result.get("orderCreateTransaction") or {}).get("id"))
            fill = result.get("orderFillTransaction") or {}
            trade_id = ((fill.get("tradeOpened") or {}).get("tradeID")) if fill else None

            leg = TradeLeg(
                target_label=label,
                order_id=str(order_id) if order_id else None,
                trade_id=str(trade_id) if trade_id else None,
                units=units_per_leg,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                state="FILLED" if trade_id else "PENDING",
            )
            bundle.legs.append(leg)
            if trade_id:
                any_filled = True

        if not bundle.legs:
            return None

        logger.info(
            "[H1ZONE] OPEN %s/%s %s @ %.5f  stop=%.5f  level=%.5f opp=%.5f  "
            "R=%.5f units/leg=%d atr5m=%.5f",
            pair, variant, direction, entry_price, stop_price,
            level, opposing, r_unit, units_per_leg, atr5,
        )
        if self.signal_callback:
            try:
                self.signal_callback({
                    "strategy": f"scalp_h1zone_{variant}",
                    "pair": pair, "instrument": pair, "direction": direction,
                    "entry": entry_price, "stop": stop_price,
                    "level": level, "opposing": opposing,
                    "r_unit": r_unit, "units_per_leg": units_per_leg,
                    "atr_5m": atr5,
                    "targets": {l: t_prices[l] for l in t_prices},
                })
            except Exception:
                pass
        return bundle

    # ─── Open-bundle management (T3 detection + T4 trail) ─────────────────
    def _manage_bundles(self, ps: PairState):
        if not ps.bundles:
            return
        # Refresh status of each leg's trade
        try:
            resp = self.oanda._request("GET",
                f"/v3/accounts/{self.oanda.account_id}/openTrades")
            open_tids = {str(t.get("id")) for t in resp.get("trades", [])}
        except Exception as e:
            logger.debug("[H1ZONE] open trades fetch failed: %s", e)
            return

        live_bundles: List[SignalBundle] = []
        for bundle in ps.bundles:
            # Update leg state: if a leg's trade_id is no longer in openTrades,
            # it has closed (hit SL or TP).
            for leg in bundle.legs:
                if leg.trade_id and leg.trade_id not in open_tids and leg.state == "FILLED":
                    leg.state = "CLOSED"

            # Detect T3 fill → start T4 trailing
            t3 = next((l for l in bundle.legs if l.target_label == "T3"), None)
            t4 = next((l for l in bundle.legs if l.target_label == "T4"), None)
            if (t3 is not None and t3.state == "CLOSED" and not bundle.t3_filled
                    and t4 is not None and t4.state == "FILLED"):
                bundle.t3_filled = True
                self._move_t4_stop_to_lock(bundle, t4)

            # If T4 is still alive, run the trail step
            if bundle.t3_filled and t4 is not None and t4.state == "FILLED":
                self._trail_t4(bundle, t4)

            # Keep the bundle around while any leg is still open
            if any(l.state == "FILLED" for l in bundle.legs):
                live_bundles.append(bundle)
            else:
                logger.info("[H1ZONE] bundle done %s/%s %s — all legs closed",
                            bundle.pair, bundle.variant, bundle.direction)

        ps.bundles = live_bundles

    def _move_t4_stop_to_lock(self, bundle: SignalBundle, t4: TradeLeg):
        """Move T4's stop to entry + 1R (or entry - 1R for shorts)."""
        r_unit = bundle.stop_distance
        if r_unit <= 0:
            return
        if bundle.direction == "BUY":
            new_stop = t4.entry_price + TRAIL_AFTER_T3_LOCK_R * r_unit
        else:
            new_stop = t4.entry_price - TRAIL_AFTER_T3_LOCK_R * r_unit
        self._update_trade_stop(bundle.pair, t4, new_stop)

    def _trail_t4(self, bundle: SignalBundle, t4: TradeLeg):
        """On each new 5m close, raise (BUY) or lower (SELL) T4's stop
        to current_close ∓ 1×ATR(5m), provided it improves the existing stop.
        """
        m5 = self._fetch_5m_bars(bundle.pair)
        if len(m5) < 16:
            return
        atr5 = _atr(m5, 14)
        if atr5 is None:
            return
        last_close = m5[-1]["close"]
        if bundle.direction == "BUY":
            candidate = last_close - TRAIL_ATR_MULT * atr5
            # Only raise the stop; never lower
            if candidate > t4.stop_price:
                self._update_trade_stop(bundle.pair, t4, candidate)
        else:
            candidate = last_close + TRAIL_ATR_MULT * atr5
            if candidate < t4.stop_price:
                self._update_trade_stop(bundle.pair, t4, candidate)

    def _update_trade_stop(self, pair: str, leg: TradeLeg, new_stop: float):
        _, precision = get_pip_precision(pair)
        body = {"stopLoss": {"price": format_price(new_stop, precision),
                              "timeInForce": "GTC"}}
        try:
            self.oanda._request(
                "PUT",
                f"/v3/accounts/{self.oanda.account_id}/trades/{leg.trade_id}/orders",
                body=body)
            logger.info("[H1ZONE] trail %s leg=%s trade=%s stop %.5f → %.5f",
                        pair, leg.target_label, leg.trade_id,
                        leg.stop_price, new_stop)
            leg.stop_price = new_stop
        except Exception as e:
            logger.debug("[H1ZONE] update_stop failed %s leg=%s: %s",
                         pair, leg.target_label, e)

    # ─── Candle fetchers ──────────────────────────────────────────────────
    def _fetch_h1_bars(self, pair: str) -> List[dict]:
        try:
            resp = self.oanda._request(
                "GET",
                f"/v3/instruments/{pair}/candles"
                f"?granularity=H1&count={H1_CANDLE_COUNT}&price=M")
            return _parse_oanda_candles(resp)
        except Exception as e:
            logger.debug("[H1ZONE] H1 fetch failed %s: %s", pair, e)
            return []

    def _fetch_5m_bars(self, pair: str) -> List[dict]:
        try:
            resp = self.oanda._request(
                "GET",
                f"/v3/instruments/{pair}/candles"
                f"?granularity=M5&count={TRIGGER_CANDLE_COUNT}&price=M")
            return _parse_oanda_candles(resp)
        except Exception as e:
            logger.debug("[H1ZONE] 5m fetch failed %s: %s", pair, e)
            return []

    def _fetch_adx_direction(self, pair: str, variant: str) -> str:
        """Direction for the variant's trend TF.

        Name kept for backward compatibility; under the hood this now uses
        N=15 swing structure (HH+HL vs LH+LL) for FX, via the unified
        calculate_trend_direction switch. Direction-only output preserved.
        """
        gran = VARIANT_TF[variant]
        count = VARIANT_CANDLE_COUNT[variant]
        try:
            resp = self.oanda._request(
                "GET",
                f"/v3/instruments/{pair}/candles"
                f"?granularity={gran}&count={count}&price=M")
            bars = _parse_oanda_candles(resp)
        except Exception as e:
            logger.debug("[H1ZONE] trend fetch failed %s/%s: %s", pair, variant, e)
            return "SIDE"
        if len(bars) < 32:  # 2N+2 = 32 minimum for N=15 structure
            return "SIDE"

        # calculate_trend_direction expects objects with .high/.low/.close
        class _C:
            __slots__ = ("high", "low", "close")
            def __init__(self, h, l, c):
                self.high = h; self.low = l; self.close = c
        cs = [_C(b["high"], b["low"], b["close"]) for b in bars]
        direction, _val = calculate_trend_direction(cs, instrument=pair)
        return direction


def _iso_to_epoch(iso: str) -> float:
    """Parse Oanda ISO timestamps (which include nanoseconds) to epoch seconds."""
    if not iso:
        return 0.0
    try:
        # Oanda format: "2026-05-14T20:38:00.123456789Z"
        s = iso.replace("Z", "+00:00")
        # Strip nanoseconds beyond microseconds for fromisoformat
        if "." in s:
            head, rest = s.split(".", 1)
            tz_split = rest.find("+") if "+" in rest else rest.find("-")
            if tz_split > 0:
                frac, tz = rest[:tz_split], rest[tz_split:]
                frac = frac[:6]
                s = f"{head}.{frac}{tz}"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0
