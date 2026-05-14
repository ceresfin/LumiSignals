"""HTF backtester — no candle-pattern trigger.

Strategy:
  - For each 5m bar, check whether close is within zone tolerance of an
    untouched supply OR demand level (computed using the LIVE algorithm,
    find_untouched_levels from lumisignals/untouched_levels.py).
  - Require HTF (1H or 4H) ADX direction to support the trade:
       demand touch  + HTF trend UP   → BUY
       supply touch  + HTF trend DOWN → SELL
  - No candle pattern. No body filter. No bias score.
  - Stop = N × 5m ATR(14).  Target = R × stop distance.

Variants run (12 total):
  htf_trend_tf ∈ {H1, H4}
  stop_mult    ∈ {1.5, 3.0}   (3.0 matches live SCALP)
  target_R     ∈ {1.5, 2.0, 3.0}

Goal: see if "near level + HTF trend" alone has edge, with no candle
pattern requirement.  Comparison baseline is the previous backtester's
best (M5/OFF/1.5R = +$7,523 over 12 months × 7 pairs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumisignals.oanda_client import OandaClient
from lumisignals.untouched_levels import find_untouched_levels, calculate_adx_direction
from lumisignals.candle_classifier import CandleData
from saas.backtest_htf_scalp_fx import (
    Bar, fetch_range, PAIRS, ATR_PERIOD,
)
from saas.backtest_fx_4h import (
    rolling_atr, pip_factor, pip_dollars_per_unit, position_size_units,
    to_et, FRIDAY_CUTOFF_HOUR_ET,
)

# ─── Strategy constants ────────────────────────────────────────────────────
ZONE_TFS = ["15m", "1h"]
ZONE_GRAN = {"15m": "M15", "1h": "H1"}
ZONE_TOLERANCE_PCT = {"15m": 0.0015, "1h": 0.0020}
LEVEL_LOOKBACK = 10
RISK_PCT = 0.0025
ACCOUNT_NOTIONAL = 250_000.0
ADX_PERIOD = 14

# Locked-in values for this run (best-of from prior backtest)
STOP_MULT = 3.0
TARGET_R = 1.5

# Confluence variants — the three "higher-TF" rules.  Each value is a
# tuple of (required_tfs, mode) where mode is 'all' or 'any'.  The
# 15m TF is deliberately excluded — it's too close to 5m to tell us
# anything meaningfully different about the macro direction.
TREND_VARIANTS = {
    "STRICT  (1H + 4H both agree)":  (["H1", "H4"], "all"),
    "RELAXED (1H or 4H agrees)":      (["H1", "H4"], "any"),
    "EXTENDED (1H + 4H + 1D agree)":  (["H1", "H4", "D"], "all"),
}


# ─── Helpers ──────────────────────────────────────────────────────────────
def bar_to_candle(b: Bar) -> CandleData:
    return CandleData(open=b.o, high=b.h, low=b.l, close=b.c)


def precompute_zone_levels(zone_bars: list[Bar], lookback: int = LEVEL_LOOKBACK
                              ) -> dict[int, tuple[float, float, float, float]]:
    """For each zone-TF bar index, compute (S1, S2, D1, D2) using the
    last `lookback+1` bars ending at that index.  Same call shape the
    live bot makes — find_untouched_levels(highs, lows, current_price)."""
    out: dict[int, tuple[float, float, float, float]] = {}
    n = len(zone_bars)
    for i in range(lookback, n):
        window = zone_bars[i - lookback:i + 1]
        # find_untouched_levels expects MOST RECENT FIRST
        highs = [b.h for b in reversed(window)]
        lows = [b.l for b in reversed(window)]
        s1, s2, d1, d2 = find_untouched_levels(highs, lows, zone_bars[i].c,
                                                 lookback=lookback)
        out[i] = (s1, s2, d1, d2)
    return out


def precompute_trend(htf_bars: list[Bar], period: int = ADX_PERIOD
                       ) -> dict[int, tuple[str, float]]:
    """For each HTF bar index, compute (direction, ADX) using all
    completed bars up to and including that index."""
    out: dict[int, tuple[str, float]] = {}
    n = len(htf_bars)
    for i in range(period + 2, n):
        candles = [bar_to_candle(b) for b in htf_bars[:i + 1]]
        out[i] = calculate_adx_direction(candles, period)
    return out


def index_by_ts(bars: list[Bar]) -> list[datetime]:
    return [b.ts for b in bars]


# Bar duration per Oanda granularity — used to find the latest CLOSED
# bar before a trigger timestamp.  Without this, the lookup returns the
# in-progress bar and we get look-ahead bias from its future high/low.
_GRAN_DURATION = {
    "M5":  timedelta(minutes=5),
    "M15": timedelta(minutes=15),
    "H1":  timedelta(hours=1),
    "H4":  timedelta(hours=4),
    "D":   timedelta(days=1),
}


def lookup_closed_bar_idx(zone_ts: list[datetime], target_ts: datetime,
                            granularity: str) -> int:
    """Return the largest index i such that zone_ts[i] + duration <= target_ts.

    Guarantees the bar at index i has fully closed by target_ts, so its
    high/low/close are knowable at the time of the trigger.  Without this
    correction the simulator peeks at future price action."""
    duration = _GRAN_DURATION.get(granularity, timedelta(minutes=5))
    cutoff = target_ts - duration
    lo, hi = 0, len(zone_ts) - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        # bar i is closed at target_ts iff its start time + duration <= target_ts
        # equivalent to bar.start_time <= target_ts - duration
        if zone_ts[mid] <= cutoff:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


# ─── Trade dataclass ──────────────────────────────────────────────────────
@dataclass
class Trade:
    pair: str
    direction: str
    entry_ts: datetime
    entry_price: float
    stop_price: float
    target_price: float
    units: int
    zone_tf: str
    zone_price: float
    exit_ts: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_dollars: float = 0.0
    pnl_pips: float = 0.0


# ─── Simulator ───────────────────────────────────────────────────────────
def simulate_variant(pair: str,
                       trigger_bars: list[Bar],
                       zone_bars_by_tf: dict[str, list[Bar]],
                       zone_levels_by_tf: dict[str, dict],
                       zone_ts_by_tf: dict[str, list[datetime]],
                       trend_by_tf: dict[str, dict[int, tuple[str, float]]],
                       trend_ts_by_tf: dict[str, list[datetime]],
                       confluence_tfs: list[str],
                       confluence_mode: str,
                       stop_mult: float,
                       target_r: float) -> list[Trade]:
    """One pass through the 5m bars."""
    if len(trigger_bars) < 60:
        return []
    atrs = rolling_atr(trigger_bars, ATR_PERIOD)
    open_trade: Optional[Trade] = None
    trades: list[Trade] = []

    # Track which (level_price, zone_tf) pairs already fired so we
    # don't re-fire on the same level repeatedly.
    fired: set[tuple[str, float]] = set()

    for i, bar in enumerate(trigger_bars):
        # ── Exit checks ──
        if open_trade is not None:
            t = open_trade
            hit_stop = (t.direction == "BUY" and bar.l <= t.stop_price) or \
                        (t.direction == "SELL" and bar.h >= t.stop_price)
            hit_target = (t.direction == "BUY" and bar.h >= t.target_price) or \
                          (t.direction == "SELL" and bar.l <= t.target_price)
            et = to_et(bar.ts)
            friday = (et.weekday() == 4 and et.hour >= 16)
            if hit_stop:
                t.exit_price = t.stop_price; t.exit_reason = "STOP"
            elif hit_target:
                t.exit_price = t.target_price; t.exit_reason = "TARGET"
            elif friday:
                t.exit_price = bar.c; t.exit_reason = "WEEKEND"
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
            continue

        if atrs[i] is None or i < 30:
            continue
        et = to_et(bar.ts)
        if et.weekday() == 4 and et.hour >= FRIDAY_CUTOFF_HOUR_ET:
            continue

        # ── Higher-TF trend confluence ──
        # For each of the confluence TFs (e.g. 1H, 4H), look up the
        # direction from the latest CLOSED bar.  Without "closed" we'd
        # be peeking into the in-progress higher-TF bar's future move.
        tf_directions: list[str] = []
        for tf in confluence_tfs:
            ts_list = trend_ts_by_tf.get(tf)
            data = trend_by_tf.get(tf)
            if not ts_list or not data:
                tf_directions.append("SIDE"); continue
            idx = lookup_closed_bar_idx(ts_list, bar.ts, tf)
            if idx < 0 or idx not in data:
                tf_directions.append("SIDE"); continue
            tf_directions.append(data[idx][0])  # (direction, adx) tuple

        # Determine which trade direction the confluence supports
        ups = sum(1 for d in tf_directions if d == "UP")
        downs = sum(1 for d in tf_directions if d == "DOWN")
        n_tfs = len(confluence_tfs)
        if confluence_mode == "all":
            if ups == n_tfs:
                supported_dir = "BUY"
            elif downs == n_tfs:
                supported_dir = "SELL"
            else:
                continue   # not full agreement → no trade
        else:  # 'any'
            # At least one TF must agree, AND no TF disagrees outright
            if ups > 0 and downs == 0:
                supported_dir = "BUY"
            elif downs > 0 and ups == 0:
                supported_dir = "SELL"
            else:
                continue

        # ── Zone match (β: touched-and-rejected) ──
        # Use only CLOSED zone bars for the level snapshot — otherwise
        # the precomputed (S1,S2,D1,D2) for an in-progress bar reflect
        # future high/low.
        triggered: Optional[tuple[str, str, float]] = None
        for zone_tf in ZONE_TFS:
            zone_gran = ZONE_GRAN[zone_tf]
            zone_idx = lookup_closed_bar_idx(zone_ts_by_tf[zone_tf],
                                               bar.ts, zone_gran)
            if zone_idx < 0 or zone_idx not in zone_levels_by_tf[zone_tf]:
                continue
            s1, s2, d1, d2 = zone_levels_by_tf[zone_tf][zone_idx]
            # BUY: support level touched (bar.low ≤ demand) AND closed above
            if supported_dir == "BUY":
                for lvl in (d1, d2):
                    if lvl is None or lvl == 0:
                        continue
                    if (zone_tf, lvl) in fired:
                        continue
                    # β rule — physically touched the level and closed above
                    if bar.l <= lvl <= bar.c:
                        triggered = (zone_tf, "BUY", lvl)
                        break
            # SELL: resistance touched AND closed below
            else:
                for lvl in (s1, s2):
                    if lvl is None or lvl == 0:
                        continue
                    if (zone_tf, lvl) in fired:
                        continue
                    if bar.c <= lvl <= bar.h:
                        triggered = (zone_tf, "SELL", lvl)
                        break
            if triggered:
                break
        if not triggered:
            continue
        zone_tf, direction, zone_price = triggered
        fired.add((zone_tf, zone_price))

        atr = atrs[i]
        stop_dist = stop_mult * atr
        entry = bar.c
        stop = entry - stop_dist if direction == "BUY" else entry + stop_dist
        target = entry + target_r * stop_dist * (1 if direction == "BUY" else -1)
        # R:R floor 1.0 (we already configure via target_r)
        stop_pips = abs(entry - stop) / pip_factor(pair)
        pdu = pip_dollars_per_unit(pair, entry)
        units = position_size_units(ACCOUNT_NOTIONAL * RISK_PCT, stop_pips, pdu)
        if units <= 0:
            continue
        open_trade = Trade(
            pair=pair, direction=direction,
            entry_ts=bar.ts, entry_price=entry,
            stop_price=stop, target_price=target, units=units,
            zone_tf=zone_tf, zone_price=zone_price,
        )

    return trades


# ─── Grid runner ──────────────────────────────────────────────────────────
def run_grid(end: datetime, months: int = 12, pairs: list[str] = None):
    pairs = pairs or PAIRS
    start = end - timedelta(days=months * 30)
    # Creds (same path as other backtesters)
    api_key = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if not api_key:
        import psycopg2
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
    client = OandaClient(account_id=account_id, api_key=api_key,
                         environment=environment)

    # Need M5 (trigger) + M15/H1 (zones) + H1/H4/D (trend confluence)
    granularities = ["M5", "M15", "H1", "H4", "D"]
    pair_bars: dict[str, dict[str, list[Bar]]] = {}
    for pair in pairs:
        print(f"[{pair}] fetching {'/'.join(granularities)} ...", flush=True)
        pair_bars[pair] = {}
        for gran in granularities:
            pair_bars[pair][gran] = fetch_range(client, pair, gran, start, end)
        sizes = " ".join(f"{g}={len(pair_bars[pair][g])}" for g in granularities)
        print(f"[{pair}] bars: {sizes}", flush=True)

    # Precompute zone levels (one-time) and trend on every TF that any
    # variant might need (union of all confluence_tfs across variants).
    zone_levels: dict[str, dict[str, dict]] = {p: {} for p in pairs}
    zone_ts: dict[str, dict[str, list[datetime]]] = {p: {} for p in pairs}
    trend_data: dict[str, dict[str, dict]] = {p: {} for p in pairs}
    trend_ts: dict[str, dict[str, list[datetime]]] = {p: {} for p in pairs}
    trend_tfs_needed = sorted({tf for tfs, _ in TREND_VARIANTS.values() for tf in tfs})
    for pair in pairs:
        for ztf in ZONE_TFS:
            gran = ZONE_GRAN[ztf]
            zone_levels[pair][ztf] = precompute_zone_levels(pair_bars[pair][gran])
            zone_ts[pair][ztf] = index_by_ts(pair_bars[pair][gran])
        for tf in trend_tfs_needed:
            trend_data[pair][tf] = precompute_trend(pair_bars[pair][tf])
            trend_ts[pair][tf] = index_by_ts(pair_bars[pair][tf])
        print(f"[{pair}] precomputed zone levels + trend on {trend_tfs_needed}",
              flush=True)

    # Run the grid (3 variants)
    results = []
    for variant_name, (tfs, mode) in TREND_VARIANTS.items():
        print(f"\n--- {variant_name} ---", flush=True)
        all_trades: list[Trade] = []
        for pair in pairs:
            trades = simulate_variant(
                pair=pair,
                trigger_bars=pair_bars[pair]["M5"],
                zone_bars_by_tf={ztf: pair_bars[pair][ZONE_GRAN[ztf]] for ztf in ZONE_TFS},
                zone_levels_by_tf=zone_levels[pair],
                zone_ts_by_tf=zone_ts[pair],
                trend_by_tf=trend_data[pair],
                trend_ts_by_tf=trend_ts[pair],
                confluence_tfs=tfs,
                confluence_mode=mode,
                stop_mult=STOP_MULT,
                target_r=TARGET_R,
            )
            all_trades.extend(trades)
        n = len(all_trades)
        if n == 0:
            print("  no trades")
            results.append({"variant": variant_name, "trades": 0,
                            "wins": 0, "win_pct": 0, "avg_w": 0, "avg_l": 0,
                            "net": 0, "by_pair": {}})
            continue
        wins = [t for t in all_trades if t.pnl_dollars > 0]
        losses = [t for t in all_trades if t.pnl_dollars < 0]
        net = sum(t.pnl_dollars for t in all_trades)
        avg_w = sum(t.pnl_dollars for t in wins) / len(wins) if wins else 0
        avg_l = sum(t.pnl_dollars for t in losses) / len(losses) if losses else 0
        # Per-pair breakdown for the top-line variant
        by_pair = {}
        for p in pairs:
            ptrades = [t for t in all_trades if t.pair == p]
            if not ptrades: continue
            pw = [t for t in ptrades if t.pnl_dollars > 0]
            pn = len(ptrades); pwn = len(pw)
            by_pair[p] = {
                "n": pn,
                "win_pct": pwn / pn * 100 if pn else 0,
                "net": sum(t.pnl_dollars for t in ptrades),
            }
        print(f"  {n} trades  win {len(wins)/n*100:.1f}%  "
              f"net ${net:+,.0f}  avg_w ${avg_w:+,.0f}  avg_l ${avg_l:+,.0f}")
        results.append({"variant": variant_name, "trades": n,
                        "wins": len(wins), "win_pct": len(wins)/n*100,
                        "avg_w": avg_w, "avg_l": avg_l, "net": net,
                        "by_pair": by_pair})

    # Final report
    print()
    print("=" * 96)
    print("HTF no-trigger FX backtest")
    print("=" * 96)
    print(f"  Spec: 5m trigger, β touched-rejected, find_untouched_levels live algo,")
    print(f"        stop={STOP_MULT}x ATR, target={TARGET_R}R, 7 USD majors")
    print()
    print(f"{'VARIANT':45s} {'N':>5s} {'WIN%':>6s} {'AVG W':>8s} {'AVG L':>8s} {'NET $':>10s}")
    sorted_results = sorted(results, key=lambda x: -x["net"])
    for r in sorted_results:
        print(f"{r['variant']:45s} {r['trades']:>5d} "
              f"{r['win_pct']:>5.1f}% {r['avg_w']:>+7.0f}  {r['avg_l']:>+7.0f}  "
              f"{r['net']:>+9.0f}")

    # Per-pair breakdown of the best variant
    if sorted_results and sorted_results[0]["by_pair"]:
        best = sorted_results[0]
        print()
        print(f"Per-pair detail — {best['variant']}")
        print(f"  {'PAIR':9s} {'N':>5s} {'WIN%':>6s} {'NET $':>10s}")
        for p, s in sorted(best["by_pair"].items(), key=lambda x: -x[1]["net"]):
            print(f"  {p:9s} {s['n']:>5d} {s['win_pct']:>5.1f}% {s['net']:>+9.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=None)
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
