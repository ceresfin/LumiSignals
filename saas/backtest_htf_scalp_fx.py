"""HTF SCALP FX backtester — 12-variant grid.

The HTF Levels SCALP model fires entries when a TA-Lib reversal pattern
fires on the trigger TF at a zone touch (15m/1h supply-or-demand level)
AND the bias+candle composite score clears 50/100.  Risk is sized to
0.25% of account; stop = 3 × trigger-TF ATR; target = next opposite-side
S/R level pulled back half an ATR (with 2:1 R:R fallback).

This script runs every combination of:
  trigger TF   ∈ {5m, 15m}
  filter state ∈ {off, on}       (the strength+body gates we just shipped)
  exit/RR mode ∈ {1.5R fixed,
                  2.0R fixed,
                  next S/R level (live behavior)}

Per pair we fetch enough bar history once, build approximate untouched
levels at the zone TFs, and replay each combination against the same
bars.

Approximate untouched-S/R detector:
  - Pivot high = bar high greater than the highest of the prior N bars
    AND greater than the highest of the next N bars (look-ahead capped
    so we don't peek into bars we'd backtest against).
  - Pivot low mirror.
  - "Untouched" = price hasn't traded back through the pivot level
    between when it formed and the current bar.

This is good enough for relative comparison across the 12 variants.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumisignals.oanda_client import OandaClient
from lumisignals.candle_classifier import classify_for_zone, CandleData
from saas.backtest_fx_4h import (
    fetch_h4_range,          # candle fetcher (parameterized)
    rolling_atr, rolling_ema,
    pip_factor, pip_dollars_per_unit, position_size_units,
    to_et, FRIDAY_CUTOFF_HOUR_ET,
)

# ─── Spec ──────────────────────────────────────────────────────────────────
PAIRS = ["EUR_USD", "USD_JPY", "GBP_USD", "USD_CHF",
         "AUD_USD", "USD_CAD", "NZD_USD"]
ZONE_TFS = ["15m", "1h"]            # SCALP model zone TFs
TRIGGER_TFS = ["M5", "M15"]         # Oanda granularity strings
ATR_PERIOD = 14
ATR_STOP_MULT = 3.0                  # SCALP uses 3× trigger-TF ATR
MIN_SCORE = 50
MIN_RR = 1.5
RISK_PCT = 0.0025                    # 0.25% per SCALP trade
ACCOUNT_NOTIONAL = 250_000.0         # for risk-$ sizing
PIVOT_LOOKBACK = 5                   # bars on each side for pivot
ZONE_TOLERANCE_PCT = {"15m": 0.0015, "1h": 0.0020}

# Variants to test
EXIT_MODES = ["1.5R", "2.0R", "next_sr"]
FILTER_STATES = [False, True]

# ─── Bar shape ─────────────────────────────────────────────────────────────
@dataclass
class Bar:
    ts: datetime
    o: float
    h: float
    l: float
    c: float
    volume: int = 0
    def to_dict(self):
        return {"open": self.o, "high": self.h, "low": self.l, "close": self.c}


# ─── Oanda fetch with arbitrary granularity ────────────────────────────────
def fetch_range(client: OandaClient, instrument: str,
                granularity: str, start: datetime, end: datetime) -> list[Bar]:
    """Paginated fetch.  Modeled on fetch_h4_range but parameterized by
    granularity so we can pull M5 / M15 / H1 with the same code."""
    client.session.headers["Accept-Datetime-Format"] = "RFC3339"
    out: list[Bar] = []
    cursor = start
    # Granularity → maximum span per page so we stay under 5000 bars.
    span_days = {"M5": 14, "M15": 40, "M30": 80, "H1": 160,
                   "H4": 800, "D": 1500}.get(granularity, 14)
    while cursor < end:
        page_end = min(end, cursor + timedelta(days=span_days))
        url = (f"/v3/instruments/{instrument}/candles?"
               f"granularity={granularity}&price=M&"
               f"from={cursor.strftime('%Y-%m-%dT%H:%M:%SZ')}&"
               f"to={page_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        resp = client._request("GET", url)
        candles = resp.get("candles", []) if isinstance(resp, dict) else []
        page_last: Optional[datetime] = None
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
                out.append(Bar(
                    ts=ts,
                    o=float(mid.get("o", 0)), h=float(mid.get("h", 0)),
                    l=float(mid.get("l", 0)), c=float(mid.get("c", 0)),
                    volume=int(c.get("volume", 0)),
                ))
                page_last = ts
            except Exception:
                continue
        if page_last is None:
            cursor = page_end + timedelta(seconds=1)
        else:
            # Granularity-aware step forward
            step = {"M5":  timedelta(minutes=5),
                    "M15": timedelta(minutes=15),
                    "H1":  timedelta(hours=1),
                    "H4":  timedelta(hours=4),
                    "D":   timedelta(days=1)}.get(
                        granularity, timedelta(minutes=5))
            cursor = page_last + step
    return out


# ─── Untouched S/R detector (approximation) ────────────────────────────────
@dataclass
class Level:
    """A pivot-derived S/R level, plus the timestamp at which it became
    a 'level' (PIVOT_LOOKBACK bars after the pivot bar), plus the bar
    indices in the *trigger* timeframe at which it became active and
    later got touched.  The bar-index arrays are O(1) lookups inside
    the simulator's inner loop."""
    ts: datetime
    price: float
    kind: str       # "resistance" or "support"
    tf: str         # "15m" or "1h"
    active_from_idx: int = -1  # Index into trigger bars when confirmed
    touched_at_idx: int = -1   # First index where price touched the level


def detect_levels(bars: list[Bar], tf: str,
                   lookback: int = PIVOT_LOOKBACK) -> list[Level]:
    out: list[Level] = []
    for i in range(lookback, len(bars) - lookback):
        window_h = [b.h for b in bars[i - lookback:i + lookback + 1]]
        window_l = [b.l for b in bars[i - lookback:i + lookback + 1]]
        if bars[i].h == max(window_h):
            out.append(Level(
                ts=bars[i + lookback].ts,
                price=bars[i].h, kind="resistance", tf=tf,
            ))
        if bars[i].l == min(window_l):
            out.append(Level(
                ts=bars[i + lookback].ts,
                price=bars[i].l, kind="support", tf=tf,
            ))
    return out


def index_levels_against_bars(levels: list[Level],
                               trigger_bars: list[Bar]) -> list[Level]:
    """Precompute, for each level, the trigger-bar index at which it
    becomes active (first trigger bar with ts >= level.ts) and the
    first index at which price touches the level (level becomes used).
    Replaces the O(B × L × B) per-call active_zones scan with O(1)
    membership tests downstream.

    Returns the same list mutated in place AND sorted by active_from_idx
    so the simulator can advance through it efficiently.
    """
    # Sort trigger bars by ts (already in order, but be safe)
    ts_list = [b.ts for b in trigger_bars]
    n = len(trigger_bars)
    for lvl in levels:
        # Binary search for first index >= lvl.ts
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if ts_list[mid] < lvl.ts:
                lo = mid + 1
            else:
                hi = mid
        lvl.active_from_idx = lo
        # Walk forward to find the first bar that touches/penetrates
        lvl.touched_at_idx = n   # sentinel = never touched in window
        for j in range(lo, n):
            b = trigger_bars[j]
            if lvl.kind == "resistance" and b.h >= lvl.price:
                lvl.touched_at_idx = j
                break
            if lvl.kind == "support" and b.l <= lvl.price:
                lvl.touched_at_idx = j
                break
    levels.sort(key=lambda l: l.active_from_idx)
    return levels


def levels_intersecting(levels_by_kind: dict[str, list[Level]],
                          idx: int, price: float,
                          tolerance: float) -> Optional[Level]:
    """Return the first level whose price is within `tolerance` of
    `price` AND is active at `idx` AND has been touched at exactly this
    bar (so we trigger on the touch bar itself, not subsequent bars).

    `levels_by_kind` should have separate sorted lists for "support"
    and "resistance" — caller decides which to scan.
    """
    # Hot path — keep cheap
    for lvl in levels_by_kind:
        if lvl.active_from_idx > idx:
            break   # remaining levels aren't active yet
        if lvl.touched_at_idx != idx:
            continue   # only fire on the touch bar
        if abs(lvl.price - price) / lvl.price > tolerance:
            continue
        return lvl
    return None


# ─── ADX (used as the bias-direction signal) ───────────────────────────────
def rolling_adx(bars: list[Bar], period: int = 14
                 ) -> list[Optional[tuple[float, str]]]:
    """Returns (adx, direction) per bar. direction = 'up'/'down'/'flat'
    based on +DI vs -DI.  Used for trend score."""
    n = len(bars)
    if n < period + 1:
        return [None] * n
    tr_list = [0.0] * n
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        tr_list[i] = max(bars[i].h - bars[i].l,
                          abs(bars[i].h - bars[i - 1].c),
                          abs(bars[i].l - bars[i - 1].c))
        up_move = bars[i].h - bars[i - 1].h
        dn_move = bars[i - 1].l - bars[i].l
        plus_dm[i]  = up_move if (up_move > dn_move and up_move > 0) else 0.0
        minus_dm[i] = dn_move if (dn_move > up_move and dn_move > 0) else 0.0
    # Wilder smoothing
    atr_s = sum(tr_list[1:period + 1])
    plus_s = sum(plus_dm[1:period + 1])
    minus_s = sum(minus_dm[1:period + 1])
    out: list[Optional[tuple[float, str]]] = [None] * n
    dx_history: list[float] = []
    adx = None
    for i in range(period + 1, n):
        atr_s = atr_s - atr_s / period + tr_list[i]
        plus_s = plus_s - plus_s / period + plus_dm[i]
        minus_s = minus_s - minus_s / period + minus_dm[i]
        pdi = 100 * plus_s / atr_s if atr_s else 0
        mdi = 100 * minus_s / atr_s if atr_s else 0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0
        dx_history.append(dx)
        if len(dx_history) == period:
            adx = sum(dx_history) / period
        elif len(dx_history) > period:
            adx = (adx * (period - 1) + dx) / period
        if adx is not None:
            if pdi > mdi and adx > 20:
                direction = "up"
            elif mdi > pdi and adx > 20:
                direction = "down"
            else:
                direction = "flat"
            out[i] = (adx, direction)
    return out


# ─── Bias score (mirrors levels_strategy.py: 60% trend + 40% candle) ───────
def bias_score(zone_dir: str,
                trends_at: tuple[str, str],
                last_candles: list[Bar]) -> int:
    """trends_at = (15m_trend, 1h_trend) from ADX.  last_candles = the
    most recent ~5 bars on the bias TF used for candle scoring.  Returns
    a 0-100 score that mirrors what the live bot computes."""
    want = "up" if zone_dir == "BUY" else "down"
    trend_agree = sum(1 for d in trends_at if d == want)
    trend_pct = trend_agree / len(trends_at) if trends_at else 0
    # Candle agreement: % of last candles whose close matches direction
    if not last_candles:
        candle_pct = 0
    else:
        agree = 0
        for b in last_candles:
            green = b.c > b.o
            red = b.c < b.o
            if want == "up" and green:
                agree += 1
            elif want == "down" and red:
                agree += 1
        candle_pct = agree / len(last_candles)
    return int(round(trend_pct * 60 + candle_pct * 40))


# ─── Simulator ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    pair: str
    direction: str
    entry_ts: datetime
    entry_price: float
    stop_price: float
    target_price: float
    units: int
    exit_ts: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_dollars: float = 0.0
    pnl_pips: float = 0.0


def find_next_sr_target(level_list: list[Level], direction: str,
                         entry: float, stop_distance: float,
                         atr: float) -> Optional[float]:
    """Walk known levels for the nearest opposite-side level past
    entry + stop_distance.  Returns None when no qualifying level exists
    (caller falls back to fixed R:R)."""
    pullback = atr * 0.5
    if direction == "BUY":
        candidates = [l.price for l in level_list
                      if l.kind == "resistance" and l.price > entry + stop_distance]
        if candidates:
            return min(candidates) - pullback
    else:
        candidates = [l.price for l in level_list
                      if l.kind == "support" and l.price < entry - stop_distance]
        if candidates:
            return max(candidates) + pullback
    return None


def simulate_variant(pair: str,
                      trigger_bars: list[Bar], trigger_tf: str,
                      bias_bars: list[Bar],
                      level_lists: dict[str, list[Level]],   # tf → levels
                      filter_on: bool,
                      exit_mode: str) -> list[Trade]:
    """Walk forward through trigger_bars, generating trades.

    Maintains an "active pool" of confirmed-but-unbroken levels.  As we
    advance through bars:
      - New levels get added to the pool when their active_from_idx ≤ i.
      - Levels get pruned when price closes beyond them by more than
        zone tolerance (level is broken — drop it).
      - A trigger fires when a still-active level has price within
        tolerance of bar.close.  The level is consumed on first fire
        (matches the bot's _placed_setups dedup).
    """
    if len(trigger_bars) < 60:
        return []
    closes = [b.c for b in trigger_bars]
    atrs = rolling_atr(trigger_bars, ATR_PERIOD)
    # Bias ADX series on the BIAS TF (15m for SCALP).
    # We approximate by aligning each trigger bar's nearest bias-TF bar.
    bias_adx = rolling_adx(bias_bars, 14)
    # Map bias-bar timestamp → (adx, direction)
    bias_idx: list[tuple[datetime, str]] = []
    for i, b in enumerate(bias_bars):
        if bias_adx[i] is not None:
            bias_idx.append((b.ts, bias_adx[i][1]))

    def trend_at(ts: datetime) -> str:
        # Largest bias-TF ts <= trigger ts
        lo, hi = 0, len(bias_idx) - 1
        best = "flat"
        while lo <= hi:
            mid = (lo + hi) // 2
            if bias_idx[mid][0] <= ts:
                best = bias_idx[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    # Build combined zone-level pool sorted by active_from_idx so we
    # can advance with a single cursor.
    zone_entries: list[tuple[Level, str, float]] = []
    for zone_tf in ZONE_TFS:
        tol = ZONE_TOLERANCE_PCT[zone_tf]
        for lvl in level_lists[zone_tf]:
            zone_entries.append((lvl, zone_tf, tol))
    zone_entries.sort(key=lambda x: x[0].active_from_idx)
    active_pool: list[tuple[Level, str, float]] = []
    next_to_add = 0
    consumed: set[int] = set()

    trades: list[Trade] = []
    open_trade: Optional[Trade] = None

    for i, bar in enumerate(trigger_bars):
        # Advance active pool with newly-confirmed levels
        while next_to_add < len(zone_entries) and \
                zone_entries[next_to_add][0].active_from_idx <= i:
            active_pool.append(zone_entries[next_to_add])
            next_to_add += 1

        # Exit checks
        if open_trade is not None:
            t = open_trade
            hit_stop = (t.direction == "BUY" and bar.l <= t.stop_price) or \
                        (t.direction == "SELL" and bar.h >= t.stop_price)
            hit_target = (t.direction == "BUY" and bar.h >= t.target_price) or \
                          (t.direction == "SELL" and bar.l <= t.target_price)
            et = to_et(bar.ts)
            friday_close = (et.weekday() == 4 and et.hour >= 16)
            if hit_stop:
                t.exit_price = t.stop_price; t.exit_reason = "STOP"
            elif hit_target:
                t.exit_price = t.target_price; t.exit_reason = "TARGET"
            elif friday_close:
                t.exit_price = bar.c; t.exit_reason = "WEEKEND_FLAT"
            else:
                continue
            t.exit_ts = bar.ts
            move = (t.exit_price - t.entry_price) if t.direction == "BUY" \
                   else (t.entry_price - t.exit_price)
            t.pnl_pips = move / pip_factor(pair)
            t.pnl_dollars = move * t.units
            quote = pair.split("_")[1]
            if quote != "USD":
                t.pnl_dollars = t.pnl_dollars / (t.exit_price or 1)
            trades.append(t)
            open_trade = None

        if open_trade is not None or atrs[i] is None:
            continue
        if i < 30:
            continue

        et = to_et(bar.ts)
        if et.weekday() == 4 and et.hour >= FRIDAY_CUTOFF_HOUR_ET:
            continue

        # Sweep active pool: prune broken levels, find first match.
        matched: Optional[tuple[Level, str, float]] = None
        new_pool: list[tuple[Level, str, float]] = []
        for entry in active_pool:
            lvl, ztf, tol = entry
            if id(lvl) in consumed:
                continue
            # Penetration check: level no longer holds
            if lvl.kind == "resistance" and bar.c > lvl.price * (1 + tol):
                consumed.add(id(lvl)); continue
            if lvl.kind == "support" and bar.c < lvl.price * (1 - tol):
                consumed.add(id(lvl)); continue
            new_pool.append(entry)
            # Touch check (only first match per bar)
            if matched is None and abs(bar.c - lvl.price) / lvl.price <= tol:
                matched = entry
        active_pool = new_pool
        if matched is None:
            continue
        lvl, zone_tf, tol = matched
        consumed.add(id(lvl))   # one fire per level
        direction = "BUY" if lvl.kind == "support" else "SELL"
        zone_price = lvl.price

        # Trigger pattern check — only allowed reversal patterns at
        # the zone, with the new strength+body filters toggleable.
        candles = trigger_bars[max(0, i - 11):i + 1]
        cdata = [CandleData(open=b.o, high=b.h, low=b.l, close=b.c)
                 for b in candles]
        if filter_on:
            classification = classify_for_zone(
                cdata, "demand" if direction == "BUY" else "supply")
            if classification is None:
                continue
            if (direction == "BUY" and classification.direction != "bullish") or \
               (direction == "SELL" and classification.direction != "bearish"):
                continue
        else:
            # Filters OFF: still require *some* TA-Lib hit, but temporarily
            # relax the global MIN_PATTERN_STRENGTH / MIN_TRIGGER_BODY_PCT.
            # Implemented by monkey-patching the module constants for the
            # call, then restoring.
            from lumisignals import candle_classifier as cc
            old_s, old_b = cc.MIN_PATTERN_STRENGTH, cc.MIN_TRIGGER_BODY_PCT
            cc.MIN_PATTERN_STRENGTH = 1
            cc.MIN_TRIGGER_BODY_PCT = 0.0
            try:
                classification = classify_for_zone(
                    cdata, "demand" if direction == "BUY" else "supply")
            finally:
                cc.MIN_PATTERN_STRENGTH = old_s
                cc.MIN_TRIGGER_BODY_PCT = old_b
            if classification is None:
                continue

        # Score (must clear 50)
        trends_at = (trend_at(bar.ts), trend_at(bar.ts))  # simple: same on bias TF
        score = bias_score(direction, trends_at, candles[-5:])
        if score < MIN_SCORE:
            continue

        atr = atrs[i]
        stop_distance_price = ATR_STOP_MULT * atr
        entry = bar.c
        stop = entry - stop_distance_price if direction == "BUY" \
               else entry + stop_distance_price

        # Target per exit mode
        if exit_mode == "1.5R":
            target = entry + 1.5 * stop_distance_price * (1 if direction == "BUY" else -1)
        elif exit_mode == "2.0R":
            target = entry + 2.0 * stop_distance_price * (1 if direction == "BUY" else -1)
        else:  # next_sr
            # Union of zone TF levels
            union = level_lists[ZONE_TFS[0]] + level_lists[ZONE_TFS[1]]
            tgt = find_next_sr_target(union, direction, entry,
                                       stop_distance_price, atr)
            if tgt is None:
                # Fallback to 2R
                target = entry + 2.0 * stop_distance_price * (
                    1 if direction == "BUY" else -1)
            else:
                target = tgt

        # R:R floor
        rr = abs(target - entry) / abs(stop - entry) if abs(stop - entry) > 0 else 0
        if rr < MIN_RR:
            continue

        # Position size
        stop_pips = abs(entry - stop) / pip_factor(pair)
        pdu = pip_dollars_per_unit(pair, entry)
        risk_dollar = ACCOUNT_NOTIONAL * RISK_PCT
        units = position_size_units(risk_dollar, stop_pips, pdu)
        if units <= 0:
            continue

        open_trade = Trade(
            pair=pair, direction=direction, entry_ts=bar.ts,
            entry_price=entry, stop_price=stop, target_price=target,
            units=units,
        )

    return trades


# ─── Run grid ──────────────────────────────────────────────────────────────
def run_grid(end: datetime, months: int = 12,
              pairs: list[str] = PAIRS) -> dict:
    """Run all 12 variants, return per-variant stats."""
    start = end - timedelta(days=months * 30)
    # Credentials
    import psycopg2
    api_key = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if not api_key:
        with psycopg2.connect(os.environ.get(
            "DATABASE_URL",
            "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db")) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT oanda_api_key, oanda_account_id, oanda_environment "
                             "FROM users WHERE bot_active=true AND oanda_api_key IS NOT NULL "
                             "ORDER BY id LIMIT 1")
                row = cur.fetchone()
                if row:
                    api_key, account_id, environment = row[0], row[1], row[2] or "practice"
    if not api_key:
        print("ERROR: no Oanda credentials", file=sys.stderr); sys.exit(2)
    client = OandaClient(account_id=account_id, api_key=api_key,
                         environment=environment)

    # Per-pair: fetch each granularity ONCE
    pair_bars: dict[str, dict[str, list[Bar]]] = {}
    for pair in pairs:
        print(f"[{pair}] fetching M5 / M15 / H1 ...", flush=True)
        pair_bars[pair] = {
            "M5": fetch_range(client, pair, "M5", start, end),
            "M15": fetch_range(client, pair, "M15", start, end),
            "H1": fetch_range(client, pair, "H1", start, end),
        }
        print(f"[{pair}] bars: M5={len(pair_bars[pair]['M5'])} "
              f"M15={len(pair_bars[pair]['M15'])} "
              f"H1={len(pair_bars[pair]['H1'])}", flush=True)

    # Pre-build levels per pair (zone TFs are 15m + 1h).  Then index
    # them against EACH trigger TF (M5, M15) so the simulator's inner
    # loop becomes O(1) per bar instead of O(L × B).
    pair_levels_raw: dict[str, dict[str, list[Level]]] = {}
    for pair in pairs:
        pair_levels_raw[pair] = {
            "15m": detect_levels(pair_bars[pair]["M15"], "15m"),
            "1h":  detect_levels(pair_bars[pair]["H1"],  "1h"),
        }
        print(f"[{pair}] levels: 15m={len(pair_levels_raw[pair]['15m'])} "
              f"1h={len(pair_levels_raw[pair]['1h'])}", flush=True)

    # pair_levels_indexed[(pair, trigger_tf)][zone_tf] → list[Level]
    pair_levels_indexed: dict[tuple, dict[str, list[Level]]] = {}
    import copy
    for pair in pairs:
        for trig in TRIGGER_TFS:
            print(f"[{pair}] indexing levels for trigger={trig} ...", flush=True)
            indexed = {}
            for zone_tf, levels in pair_levels_raw[pair].items():
                # Deep-copy so per-trigger indexing doesn't clobber other variants
                copies = [copy.copy(l) for l in levels]
                indexed[zone_tf] = index_levels_against_bars(
                    copies, pair_bars[pair][trig])
            pair_levels_indexed[(pair, trig)] = indexed

    # Run variants
    results: list[dict] = []
    for trigger_tf in TRIGGER_TFS:
        for filter_on in FILTER_STATES:
            for exit_mode in EXIT_MODES:
                variant_id = (f"trig={trigger_tf} "
                              f"filt={'ON' if filter_on else 'OFF'} "
                              f"exit={exit_mode}")
                print(f"\n--- {variant_id} ---", flush=True)
                all_trades: list[Trade] = []
                for pair in pairs:
                    # bias bars = M15 for SCALP (matches live)
                    trades = simulate_variant(
                        pair=pair,
                        trigger_bars=pair_bars[pair][trigger_tf],
                        trigger_tf=trigger_tf,
                        bias_bars=pair_bars[pair]["M15"],
                        level_lists=pair_levels_indexed[(pair, trigger_tf)],
                        filter_on=filter_on,
                        exit_mode=exit_mode,
                    )
                    all_trades.extend(trades)
                n = len(all_trades)
                wins = sum(1 for t in all_trades if t.pnl_dollars > 0)
                losses = sum(1 for t in all_trades if t.pnl_dollars < 0)
                net = sum(t.pnl_dollars for t in all_trades)
                avg_w = (sum(t.pnl_dollars for t in all_trades if t.pnl_dollars > 0)
                          / wins) if wins else 0
                avg_l = (sum(t.pnl_dollars for t in all_trades if t.pnl_dollars < 0)
                          / losses) if losses else 0
                results.append({
                    "variant": variant_id,
                    "trigger_tf": trigger_tf, "filter": filter_on,
                    "exit_mode": exit_mode,
                    "trades": n, "wins": wins, "win_pct": (wins / n * 100 if n else 0),
                    "net": net, "avg_w": avg_w, "avg_l": avg_l,
                    "trade_list": all_trades,
                })
                print(f"  {n} trades  win {wins/n*100:.1f}%  "
                      f"net ${net:+,.0f}  avg_w ${avg_w:+,.0f}  avg_l ${avg_l:+,.0f}"
                      if n else f"  no trades")

    # Print summary table
    print()
    print("=" * 96)
    print("HTF SCALP FX backtest — variant grid")
    print("=" * 96)
    print(f"{'VARIANT':45s} {'N':>5s} {'WIN%':>6s} "
          f"{'AVG W':>9s} {'AVG L':>9s} {'NET $':>10s}")
    results.sort(key=lambda r: -r["net"])
    for r in results:
        print(f"{r['variant']:45s} {r['trades']:>5d} "
              f"{r['win_pct']:>5.1f}% {r['avg_w']:>+8.0f}  "
              f"{r['avg_l']:>+8.0f}  {r['net']:>+9.0f}")
    return {"variants": results, "pair_bars": None, "pair_levels": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=None,
                    help="YYYY-MM-DD (default: today)")
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--pairs", default=",".join(PAIRS))
    args = ap.parse_args()
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) \
            if args.end else datetime.now(timezone.utc)
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    run_grid(end=end, months=args.months, pairs=pairs)


if __name__ == "__main__":
    main()
