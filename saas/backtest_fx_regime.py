"""Per-pair regime analyzer.

Why does the same entry signal (overwhelm + EMA + weekly VWAP + monthly
VWAP) make money on USD_CAD and lose on AUD_USD?  This script measures
the *structural* properties of each pair over the same 24-month window
to identify what differentiates the profitable instruments.

Reuses the data-fetch and indicator math from backtest_fx_4h so any
finding here applies directly to the same window we backtested.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumisignals.oanda_client import OandaClient
from lumisignals.overwhelm_detector import detect_overwhelm
from saas.backtest_fx_4h import (
    PAIRS as DEFAULT_PAIRS, fetch_h4_range, rolling_ema, rolling_atr,
    anchored_vwap_series, week_anchor, month_anchor, pip_factor,
    to_et, FRIDAY_CUTOFF_HOUR_ET, EMA_PERIOD, ATR_PERIOD, ATR_STOP_MULT,
)

# Include AUD_USD here so we can compare the bad pair head-to-head
PAIRS = list(DEFAULT_PAIRS) + ["AUD_USD"]
LOOKFORWARD_BARS = 12  # 48 hours — typical hold window in v1/v3


def analyze_pair(pair: str, bars):
    """Return a dict of regime + signal-quality stats for this pair."""
    if len(bars) < EMA_PERIOD + 20:
        return None

    closes = [b.c for b in bars]
    ema = rolling_ema(closes, EMA_PERIOD)
    atr = rolling_atr(bars, ATR_PERIOD)
    vwap_w = anchored_vwap_series(bars, week_anchor)
    vwap_m = anchored_vwap_series(bars, month_anchor)
    pf = pip_factor(pair)

    # ── 1. Trend persistence: average run length above / below EMA20 ──
    runs_above = []          # in bars
    runs_below = []
    current_run = 0
    current_side = None      # "above" or "below"
    for i in range(EMA_PERIOD, len(bars)):
        if ema[i] is None: continue
        side = "above" if bars[i].c > ema[i] else "below"
        if side == current_side:
            current_run += 1
        else:
            if current_side == "above": runs_above.append(current_run)
            elif current_side == "below": runs_below.append(current_run)
            current_side = side
            current_run = 1
    avg_run_above = sum(runs_above) / len(runs_above) if runs_above else 0
    avg_run_below = sum(runs_below) / len(runs_below) if runs_below else 0
    avg_run_overall = (sum(runs_above) + sum(runs_below)) / max(len(runs_above) + len(runs_below), 1)

    # ── 2. Volatility ratio: avg ATR / price ──
    valid_atr = [a for a in atr if a is not None]
    valid_close_for_atr = [bars[i].c for i, a in enumerate(atr) if a is not None]
    if valid_atr:
        atr_pct = sum(a / c for a, c in zip(valid_atr, valid_close_for_atr)) \
                  / len(valid_atr) * 100
    else:
        atr_pct = 0
    # ATR in pips
    atr_pips = sum(a for a in valid_atr) / len(valid_atr) / pf if valid_atr else 0

    # ── 3. Net drift over the window ──
    first = bars[0].c
    last = bars[-1].c
    drift_pct = (last - first) / first * 100
    drift_pips = (last - first) / pf

    # ── 4. Signal quality: when overwhelm passes all filters, does the
    #     trade direction reach +1R before reversing by stop_distance? ──
    signal_count = 0
    signal_to_1r = 0           # reached +1R favorable
    signal_to_2r = 0           # reached +2R favorable
    signal_stopped_first = 0   # stop hit before +1R
    holding_periods = []

    for i in range(max(EMA_PERIOD + 5, ATR_PERIOD + 5, 12), len(bars) - LOOKFORWARD_BARS):
        if ema[i] is None or atr[i] is None or vwap_w[i] is None or vwap_m[i] is None:
            continue
        et = to_et(bars[i].ts)
        if et.weekday() == 4 and et.hour >= FRIDAY_CUTOFF_HOUR_ET:
            continue
        window = [b.to_ohlc_dict() for b in bars[max(0, i - 11):i + 1]]
        green, red = detect_overwhelm(window)
        if not green and not red:
            continue
        c = bars[i].c
        if green:
            if not (c > ema[i] and c > vwap_w[i] and c > vwap_m[i]):
                continue
            direction = 1
        else:
            if not (c < ema[i] and c < vwap_w[i] and c < vwap_m[i]):
                continue
            direction = -1

        stop_dist = ATR_STOP_MULT * atr[i]
        entry = c
        target_1r = entry + direction * stop_dist
        target_2r = entry + direction * 2 * stop_dist
        stop_price = entry - direction * stop_dist

        signal_count += 1
        reached_1r = False
        reached_2r = False
        bars_to_outcome = LOOKFORWARD_BARS
        for j in range(i + 1, min(i + 1 + LOOKFORWARD_BARS, len(bars))):
            b = bars[j]
            # Did stop hit first this bar?
            stopped = (direction == 1 and b.l <= stop_price) or \
                       (direction == -1 and b.h >= stop_price)
            hit_2r = (direction == 1 and b.h >= target_2r) or \
                      (direction == -1 and b.l <= target_2r)
            hit_1r = (direction == 1 and b.h >= target_1r) or \
                      (direction == -1 and b.l <= target_1r)
            if stopped and not reached_1r:
                signal_stopped_first += 1
                bars_to_outcome = j - i
                break
            if hit_2r and not reached_2r:
                reached_2r = True
                signal_to_2r += 1
                if not reached_1r:
                    reached_1r = True
                    signal_to_1r += 1
                bars_to_outcome = j - i
                break
            if hit_1r and not reached_1r:
                reached_1r = True
                signal_to_1r += 1
                # Keep looking for 2R within remaining window
        if reached_1r:
            holding_periods.append(bars_to_outcome)

    return {
        "bars_in_window": len(bars),
        "drift_pct": drift_pct,
        "drift_pips": drift_pips,
        "atr_pct": atr_pct,
        "atr_pips": atr_pips,
        "avg_run_above": avg_run_above,
        "avg_run_below": avg_run_below,
        "avg_run_overall": avg_run_overall,
        "signal_count": signal_count,
        "to_1r": signal_to_1r,
        "to_2r": signal_to_2r,
        "stopped_first": signal_stopped_first,
        "to_1r_pct": signal_to_1r / signal_count * 100 if signal_count else 0,
        "to_2r_pct": signal_to_2r / signal_count * 100 if signal_count else 0,
        "stopped_pct": signal_stopped_first / signal_count * 100 if signal_count else 0,
        "avg_bars_to_1r": sum(holding_periods) / len(holding_periods) if holding_periods else 0,
    }


def main():
    # Same window the backtester uses
    end = datetime(2026, 5, 13, tzinfo=timezone.utc)
    start = end - timedelta(days=730)

    # Credentials from DB (same path as backtester)
    api_key = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    environment = os.environ.get("OANDA_ENVIRONMENT", "practice")
    if not api_key:
        import psycopg2
        with psycopg2.connect(os.environ.get(
            "DATABASE_URL",
            "postgresql://lumisignals:LumiBot2026@localhost/lumisignals_db")) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT oanda_api_key, oanda_account_id, oanda_environment "
                    "FROM users WHERE bot_active=true AND oanda_api_key IS NOT NULL "
                    "ORDER BY id LIMIT 1")
                row = cur.fetchone()
                if row:
                    api_key, account_id, environment = row[0], row[1], row[2] or "practice"

    client = OandaClient(account_id=account_id, api_key=api_key,
                          environment=environment)

    results = {}
    for pair in PAIRS:
        print(f"[{pair}] fetching...", flush=True)
        bars = fetch_h4_range(client, pair, start, end)
        if not bars:
            print(f"[{pair}] no data, skipping")
            continue
        print(f"[{pair}] analyzing {len(bars)} bars...", flush=True)
        r = analyze_pair(pair, bars)
        if r:
            results[pair] = r

    # ── Report ──
    print()
    print("=" * 110)
    print("FX 4H regime fingerprint — 2024-05-13 to 2026-05-13")
    print("=" * 110)
    print()
    print("Volatility & drift")
    print(f"  {'PAIR':9s} {'BARS':>5s} {'NET DRIFT':>12s} {'ATR%':>7s} {'ATR pips':>10s}")
    for pair in sorted(results):
        r = results[pair]
        print(f"  {pair:9s} {r['bars_in_window']:>5d} "
              f"{r['drift_pct']:>+7.1f}% / {r['drift_pips']:>+6.0f}p  "
              f"{r['atr_pct']:>5.2f}%  {r['atr_pips']:>8.1f}p")

    print()
    print("Trend persistence (avg bars consecutive on one side of EMA20)")
    print(f"  {'PAIR':9s} {'ABOVE':>7s} {'BELOW':>7s} {'OVERALL':>8s}")
    for pair in sorted(results):
        r = results[pair]
        print(f"  {pair:9s} {r['avg_run_above']:>6.1f}  {r['avg_run_below']:>6.1f}  "
              f"{r['avg_run_overall']:>7.1f}")

    print()
    print("Signal quality — when overwhelm fires and passes all filters")
    print(f"  {'PAIR':9s} {'N':>5s} {'→ +1R':>8s} {'→ +2R':>8s} {'STOPPED':>9s} "
          f"{'AVG BARS→1R':>13s}")
    for pair in sorted(results):
        r = results[pair]
        print(f"  {pair:9s} {r['signal_count']:>5d}  "
              f"{r['to_1r_pct']:>5.1f}%  {r['to_2r_pct']:>5.1f}%  "
              f"{r['stopped_pct']:>6.1f}%  {r['avg_bars_to_1r']:>10.1f}")

    # ── The verdict: which numbers separate USD_CAD from the losers? ──
    print()
    print("=" * 110)
    print("Compared: USD_CAD (best) vs AUD_USD (worst)")
    print("=" * 110)
    if "USD_CAD" in results and "AUD_USD" in results:
        cad = results["USD_CAD"]
        aud = results["AUD_USD"]
        comparisons = [
            ("Net drift (pips)",       "drift_pips",  "{:+.0f}"),
            ("Avg ATR (pips)",         "atr_pips",    "{:.1f}"),
            ("ATR / price (%)",        "atr_pct",     "{:.2f}"),
            ("Avg run above EMA",      "avg_run_above","{:.1f}"),
            ("Avg run below EMA",      "avg_run_below","{:.1f}"),
            ("Overall trend persist.", "avg_run_overall","{:.1f}"),
            ("Signal count",           "signal_count","{:d}"),
            ("Signal → +1R %",         "to_1r_pct",   "{:.1f}%"),
            ("Signal → +2R %",         "to_2r_pct",   "{:.1f}%"),
            ("Signal → stopped %",     "stopped_pct", "{:.1f}%"),
        ]
        print(f"  {'METRIC':25s} {'USD_CAD':>12s} {'AUD_USD':>12s} {'EDGE':>10s}")
        for label, key, fmt in comparisons:
            cv = cad[key]; av = aud[key]
            cstr = fmt.format(cv)
            astr = fmt.format(av)
            if isinstance(cv, (int, float)) and isinstance(av, (int, float)) and av:
                edge = (cv - av) / abs(av) * 100 if av else 0
                edge_str = f"{edge:+.0f}%"
            else:
                edge_str = ""
            print(f"  {label:25s} {cstr:>12s} {astr:>12s} {edge_str:>10s}")


if __name__ == "__main__":
    main()
