#!/usr/bin/env python3
"""Prototype + benchmark: run the MTF level scan over ~700 tickers, fast.

The reusable scan core now lives in ``lumisignals/mtf_scan.py`` (so the
background daemon and this benchmark share one implementation); this script
imports it and adds the benchmark-only tiers + the verify-vs-TradingView tool.

  TIER 1 — SWING (1d / 1w / 1mo)
    GROUPED DAILY endpoint: one request returns EVERY US stock's daily bar
    for a date. Warm a local {ticker: [daily bars]} store over the trailing
    window (one call per trading day — concurrent), derive D/W/M for all 700
    tickers IN-MEMORY and run find_htf_levels. Steady-state = 1 call/day.

  TIER 2 — INTRADAY (15m / 1h / 4h)
    No grouped intraday endpoint exists, so this is per-ticker. Fan out
    700 tickers through a thread pool to measure real concurrent throughput.

Run:
    MASSIVE_API_KEY=... python3 scripts/bench_mtf_scan.py [--universe 700] \
        [--years 5] [--workers 50] [--skip-intraday]
    MASSIVE_API_KEY=... python3 scripts/bench_mtf_scan.py --scan
    MASSIVE_API_KEY=... python3 scripts/bench_mtf_scan.py --verify SPY,QQQ
"""
import argparse
import concurrent.futures as cf
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# Reusable scan core — the production module both this and the daemon use.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lumisignals.untouched_levels import find_htf_levels, HTF_TF_LOOKBACK  # noqa: E402
from lumisignals.mtf_scan import (  # noqa: E402
    BASE_URL, MARKETS, pooled_session, _grouped, most_recent_trading_day,
    pick_universe, warm_store, to_weekly, to_monthly, _agg, levels_for,
    hv_series, rank_1_5, VOL_LEAN, scan_actionable,
)


# ───────────────────── benchmark tier 1: pure local compute ───────────────

def swing_scan(store, universe):
    """Pure local compute: D/W/M levels for every ticker. The ≤20s target."""
    t0 = time.time()
    results = {}
    for t in universe:
        daily = store.get(t, [])
        if len(daily) < 30:
            continue
        results[t] = {
            "1d":  levels_for(daily, "1d"),
            "1w":  levels_for(to_weekly(daily), "1w"),
            "1mo": levels_for(to_monthly(daily), "1mo"),
        }
    return results, time.time() - t0


# ─────────────────────────── intraday (per-ticker) ───────────────────────

def _aggs(session, key, ticker, mult, span, frm, to):
    """One per-ticker aggregate call → list of {o,h,l,c,t} (oldest-first)."""
    r = session.get(
        BASE_URL + f"/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{frm}/{to}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key},
        timeout=30)
    if r.status_code == 429:
        raise RuntimeError("throttled")
    r.raise_for_status()
    return r.json().get("results", [])


def intraday_scan(key, universe, workers):
    """Per-ticker fan-out for the intraday tier. OPTIMIZED shape: one 5m pull
    per ticker (derive 1h/4h locally) + one 15m pull = 2 HTTP calls/ticker,
    vs the 3 the current code makes. Measures real concurrent throughput —
    the test of 'paid plan = unlimited requests' once pooling is fixed."""
    session = pooled_session(workers)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d15 = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
    d5 = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
    stats = dict(ok=0, err=0, calls=0, throttled=0)
    t0 = time.time()

    def one(ticker):
        n = 0
        try:
            five = _aggs(session, key, ticker, 5, "minute", d5, now)   # -> 1h/4h
            bars15 = _aggs(session, key, ticker, 15, "minute", d15, now)
            n = 2
            ok = False
            for tf, bars in (("15m", bars15), ("5m", five)):
                if len(bars) >= 3:
                    lb = HTF_TF_LOOKBACK.get(tf, 50)
                    highs = [b["h"] for b in reversed(bars)]
                    lows = [b["l"] for b in reversed(bars)]
                    find_htf_levels(highs, lows, bars[-1]["c"], lookback=lb)
                    ok = True
            return ticker, n, ok, None
        except RuntimeError:
            return ticker, n, False, "throttled"
        except Exception:
            return ticker, n, False, "err"

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for _t, n, ok, err in ex.map(one, universe):
            stats["calls"] += n
            if ok:
                stats["ok"] += 1
            if err == "throttled":
                stats["throttled"] += 1
            elif err:
                stats["err"] += 1
    return stats, time.time() - t0


# ───────────────────── scan presentation (IV regime hints) ────────────────

def realized_vol(daily, window=20):
    """Annualized historical (realized) volatility from daily closes."""
    closes = [b["c"] for b in daily[-(window + 1):]]
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return (var ** 0.5) * (252 ** 0.5)


def iv_regime(iv, hv):
    """Given current IV and our HV baseline, classify the options regime.
      ratio >~1.3  IV rich  -> sell premium (CREDIT)
      ratio <~1.1  IV cheap -> buy premium  (DEBIT)
    """
    if not iv or not hv or hv <= 0:
        return None, None
    ratio = iv / hv
    if ratio >= 1.3:
        return "RICH", ratio
    if ratio <= 1.1:
        return "CHEAP", ratio
    return "FAIR", ratio


def spread_for(side, regime):
    """direction (from the level scan) x IV regime -> the spread to use."""
    table = {
        ("LONG", "CHEAP"): "bull call DEBIT",
        ("LONG", "RICH"):  "bull put CREDIT",
        ("SHORT", "CHEAP"): "bear put DEBIT",
        ("SHORT", "RICH"):  "bear call CREDIT",
    }
    return table.get((side, regime), "—")


def run_scan(session, key, n, years, workers, near_pct):
    print(f"\n=== MTF SWING SCAN — top {n} liquid stocks ===")
    day, rows = most_recent_trading_day(session, key)
    universe = pick_universe(rows, n)
    print(f"universe as of {day}; warming {years:g}y grouped store...")
    store, warm = warm_store(session, key, universe, years, workers)
    t0 = time.time()
    hits = scan_actionable(store, universe, near_pct)
    scan_ms = (time.time() - t0) * 1000
    print(f"warm {warm['secs']:.0f}s (one-time / 1 call-a-day after) · "
          f"SCAN {scan_ms:.0f} ms for {len(universe)} tickers\n")
    print(f"{len(hits)} of {len(universe)} sitting within {near_pct*100:.1f}% "
          f"of an untouched D/W/M level right now:\n")
    print("  Vol 1-5 = today's volatility vs the ticker's OWN 1yr range "
          "(realized-vol proxy until IV is logged).\n")
    print(f"  {'TICKER':7} {'PRICE':>9}  {'BIAS':5} {'LEVEL':13} "
          f"{'DIST':>5}  {'TF':2} {'HV20':>5}  {'VOL 1-5':9}  SUGGESTED SPREAD")
    print("  " + "-" * 64)
    for r in hits[:40]:
        hv, vr = r.get("hv"), r.get("vol_rank")
        bar = ("●" * vr + "○" * (5 - vr)) if vr else "  ?  "
        lean = VOL_LEAN.get(vr) if vr else None
        # The level scan gives LONG/SHORT; the vol band gives debit vs credit.
        spread = spread_for(r["side"], "CHEAP" if lean == "DEBIT"
                            else "RICH" if lean == "CREDIT" else None)
        print(f"  {r['ticker']:7} {r['price']:>9.2f}  {r['side']:5} "
              f"{r['level_name']+' '+format(r['level'], '.2f'):13} "
              f"{r['dist']*100:>4.1f}%  {r['tf']:2} "
              f"{(hv*100 if hv else 0):>4.0f}%  {bar} {vr or '?'}  {spread}")
    if len(hits) > 40:
        print(f"  ... +{len(hits)-40} more")


# ─────────────────────── verify vs SRV + TradingView ──────────────────────

def to_quarterly(daily):
    """Calendar quarters (Jan-Mar, Apr-Jun, ...) from daily bars."""
    q = defaultdict(list)
    for b in daily:
        dt = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc)
        q[(dt.year, (dt.month - 1) // 3)].append(b)
    return _agg(q)


def verify_vs_tv(session, key, tickers, years, workers, market="stocks"):
    """Compute D/W/M (+Q) via the grouped path, then diff against the live
    compare endpoint's SRV (per-ticker path) AND TradingView levels.

    market: 'stocks' | 'crypto' | 'fx'. Crypto grouped keys tickers as
    'X:BTCUSD', so we warm with the prefixed key but query the endpoint with
    the bare symbol ('BTCUSD')."""
    import urllib.request

    pfx = {"crypto": "X:", "fx": "C:"}.get(market, "")
    store_keys = [pfx + t for t in tickers]            # grouped 'T' form
    print(f"\n=== VERIFY grouped-daily levels vs SRV + TradingView "
          f"[{market}] ===")
    print(f"tickers: {', '.join(tickers)}  (warming {years:g}y grouped store)")
    store, warm = warm_store(session, key, store_keys, years, workers, market)
    print(f"warm: {warm['calls']} calls, earliest reachable day={warm['earliest']}, "
          f"{warm['forbidden']} forbidden (beyond plan history), "
          f"{warm['throttled']} throttled")

    # Live SRV + TV from production (per-ticker path + Pine-pushed levels).
    url = ("https://bot.lumitrade.ai/api/mobile/compare/levels?tickers="
           + ",".join(tickers))
    endpoint = {it["ticker"]: it for it in
                __import__("json").loads(urllib.request.urlopen(url, timeout=60).read())["tickers"]}

    # grouped TF -> derivation ; endpoint TF key ; (s1,s2,d1,d2)->endpoint fields
    tf_map = [("1d", "D"), ("1w", "W"), ("1mo", "M"), ("1q", "Q")]
    derive = {"1d": lambda d: d, "1w": to_weekly, "1mo": to_monthly, "1q": to_quarterly}
    fields = ["supply", "supply2", "demand", "demand2"]

    def close(a, b):
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return abs(a - b) <= max(0.01, 0.0005 * abs(b))   # 1c or 5bps

    total = ok_srv = ok_tv = n = 0
    for t in tickers:
        daily = store.get(pfx + t, [])
        ep = endpoint.get(t, {})
        srv, tv = ep.get("server", {}) or {}, ep.get("tradingview", {}) or {}
        print(f"\n{t}  ({len(daily)} daily bars, {len(daily)//21} mo):")
        for gtf, etf in tf_map:
            lv = levels_for(derive[gtf](daily), gtf)
            if lv is None:
                continue
            srow, trow = srv.get(etf, {}) or {}, tv.get(etf, {}) or {}
            for i, f in enumerate(fields):
                g, s, v = lv[i], srow.get(f), trow.get(f)
                ms = close(g, s); mv = close(g, v)
                total += 1; ok_srv += ms
                if etf in tv and trow:
                    n += 1; ok_tv += mv
                flag = "" if (ms and (mv or not trow)) else "  <-- MISMATCH"
                print(f"   {etf:2} {f:8} grouped={_fmt(g):>11} "
                      f"SRV={_fmt(s):>11}{'=' if ms else '!'} "
                      f"TV={_fmt(v):>11}{'=' if mv else '!'}{flag}")
    print(f"\n  grouped==SRV: {ok_srv}/{total}   "
          f"grouped==TV: {ok_tv}/{n} (only TFs with live TV alerts)")


def _fmt(x):
    return "None" if x is None else f"{x:.4f}"


# ─────────────────────────────────── main ────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=int, default=700)
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--workers", type=int, default=50)
    ap.add_argument("--skip-intraday", action="store_true")
    ap.add_argument("--verify", type=str, default="",
                    help="comma tickers to diff vs SRV+TV instead of benchmarking")
    ap.add_argument("--market", type=str, default="stocks",
                    choices=list(MARKETS), help="grouped market for --verify")
    ap.add_argument("--scan", action="store_true",
                    help="produce the actionable MTF swing shortlist for N tickers")
    ap.add_argument("--near", type=float, default=0.03,
                    help="flag tickers within this fraction of a level (default 3%%)")
    args = ap.parse_args()

    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        sys.exit("MASSIVE_API_KEY not set")
    session = pooled_session(args.workers)

    if args.verify:
        verify_vs_tv(session, key, [t.strip().upper() for t in args.verify.split(",")],
                     args.years, args.workers, args.market)
        return

    if args.scan:
        run_scan(session, key, args.universe, args.years, args.workers, args.near)
        return

    print(f"\n=== MTF scan benchmark — {args.universe} tickers ===")

    # Universe from the most recent grouped-daily response.
    t0 = time.time()
    day, rows = most_recent_trading_day(session, key)
    universe = pick_universe(rows, args.universe)
    print(f"universe: top {len(universe)} liquid US stocks as of {day} "
          f"({len(rows)} total in grouped response, {time.time()-t0:.2f}s)")
    print(f"  sample: {', '.join(universe[:12])} ...")

    # ── TIER 1: swing via grouped daily ──
    print(f"\n[TIER 1 — SWING]  warming {args.years:g}y grouped-daily store "
          f"({args.workers} workers)...")
    store, warm = warm_store(session, key, universe, args.years, args.workers)
    got = sum(1 for t in universe if len(store.get(t, [])) >= 30)
    print(f"  warm: {warm['calls']} grouped calls in {warm['secs']:.1f}s "
          f"({warm['calls']/max(warm['secs'],1e-9):.0f} req/s), "
          f"{warm['throttled']} throttled; {got}/{len(universe)} tickers have bars")
    results, scan_secs = swing_scan(store, universe)
    avg_daily = sum(len(store[t]) for t in results) / max(len(results), 1)
    print(f"  SCAN (local compute, D/W/M for {len(results)} tickers): "
          f"{scan_secs*1000:.0f} ms  (avg {avg_daily:.0f} daily bars/ticker)")
    # Show one real result so we can eyeball correctness.
    for t in universe:
        if t in results and results[t]["1d"]:
            s1, s2, d1, d2 = results[t]["1d"]
            print(f"  e.g. {t} Daily: S1={s1} S2={s2} D1={d1} D2={d2}")
            break

    # ── TIER 2: intraday per-ticker fan-out ──
    if not args.skip_intraday:
        print(f"\n[TIER 2 — INTRADAY]  {len(universe)} tickers x (15m,1h,4h) "
              f"via {args.workers} threads...")
        st, secs = intraday_scan(key, universe, args.workers)
        print(f"  {st['calls']} HTTP calls in {secs:.1f}s "
              f"({st['calls']/max(secs,1e-9):.0f} req/s), "
              f"{st['ok']} tickers OK, {st['err']} errors, "
              f"{st['throttled']} throttled (429)")

    print(f"\n=== TOTAL cold (warm+swing"
          f"{'' if args.skip_intraday else '+intraday'}): "
          f"{warm['secs']+scan_secs + (0 if args.skip_intraday else secs):.1f}s ===\n")


if __name__ == "__main__":
    main()
