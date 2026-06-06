#!/usr/bin/env python3
"""Prototype + benchmark: run the MTF level scan over ~700 tickers, fast.

Validates the two-tier architecture against the live Massive (Polygon) API:

  TIER 1 — SWING (1d / 1w / 1mo)
    Uses the GROUPED DAILY endpoint:
        /v2/aggs/grouped/locale/us/market/stocks/{date}
    One request returns EVERY US stock's daily bar for that date. We warm a
    local {ticker: [daily bars]} store over the trailing window (one call per
    trading day — concurrent), then derive Daily/Weekly/Monthly for all 700
    tickers IN-MEMORY (no per-ticker calls) and run find_htf_levels.
    Steady-state this is 1 call/day to append "today".

  TIER 2 — INTRADAY (15m / 1h / 4h)
    No grouped intraday endpoint exists, so this is per-ticker. We fan out
    700 tickers through a thread pool over the REAL MassiveClient (so the
    5m->1h/4h aggregation matches production) and time it. This is the test
    of the "paid plan = unlimited requests" claim.

Levels come from the production algorithm (lumisignals.untouched_levels.
find_htf_levels) and the production lookback table (HTF_TF_LOOKBACK), so the
numbers this prints ARE the numbers the app would produce.

Run:
    MASSIVE_API_KEY=... python3 scripts/bench_mtf_scan.py [--universe 700] \
        [--years 5] [--workers 50] [--skip-intraday]
"""
import argparse
import concurrent.futures as cf
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

# Production algorithm + lookbacks — import the real thing.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lumisignals.untouched_levels import find_htf_levels, HTF_TF_LOOKBACK  # noqa: E402

BASE_URL = "https://api.polygon.io"
# Grouped-daily path per market. Stocks=weekdays only; crypto=24/7.
MARKETS = {
    "stocks": "/v2/aggs/grouped/locale/us/market/stocks/{date}",
    "crypto": "/v2/aggs/grouped/locale/global/market/crypto/{date}",
    "fx":     "/v2/aggs/grouped/locale/global/market/fx/{date}",
}


def pooled_session(pool):
    """A Session whose connection pool matches our worker count. Default
    urllib3 pool_maxsize is 10 — the real cap behind '19 req/s on 50 threads'.
    Production MassiveClient has the same default; this is the fix it needs."""
    s = requests.Session()
    a = requests.adapters.HTTPAdapter(pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", a)
    return s


# ─────────────────────────── grouped-daily warm ──────────────────────────

def _grouped(session, key, date_str, market="stocks"):
    """One grouped-daily call → list of {T,o,h,l,c,v,t} rows (empty on holiday)."""
    r = session.get(BASE_URL + MARKETS[market].format(date=date_str),
                    params={"adjusted": "true", "apiKey": key}, timeout=30)
    if r.status_code == 429:
        return "throttled"
    if r.status_code == 403:           # beyond the plan's history window
        return "forbidden"
    r.raise_for_status()
    return r.json().get("results", [])


def most_recent_trading_day(session, key, market="stocks"):
    """Walk back from today until a grouped call returns rows."""
    d = datetime.now(timezone.utc).date()
    for _ in range(7):
        rows = _grouped(session, key, d.isoformat(), market)
        if rows and rows != "throttled":
            return d, rows
        d -= timedelta(days=1)
    raise RuntimeError("no trading day found in last 7 days")


def pick_universe(rows, n):
    """Top-N liquid names by dollar-volume (close*volume), price > $5."""
    liquid = [(row["T"], row["c"] * row.get("v", 0))
              for row in rows if row.get("c", 0) > 5 and row.get("v", 0) > 0]
    liquid.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in liquid[:n]]


def warm_store(session, key, universe, years, workers, market="stocks"):
    """Concurrently pull grouped-daily for the trailing window, keep only the
    universe. Returns {ticker: [bars sorted oldest->newest]}, plus stats."""
    uni = set(universe)
    end, _ = most_recent_trading_day(session, key, market)
    all_days = market != "stocks"   # crypto/fx trade weekends (crypto 24/7)
    dates, d = [], end
    while d > end - timedelta(days=int(years * 365.25)):
        if all_days or d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)

    store = defaultdict(list)
    throttled = [0]
    forbidden = [0]
    earliest = [None]
    t0 = time.time()

    def fetch(ds):
        rows = _grouped(session, key, ds, market)
        if rows == "throttled":
            throttled[0] += 1
            return []
        if rows == "forbidden":
            forbidden[0] += 1
            return []
        if rows and (earliest[0] is None or ds < earliest[0]):
            earliest[0] = ds
        return [(ds, row) for row in rows if row["T"] in uni]

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for chunk in ex.map(fetch, dates):
            for ds, row in chunk:
                store[row["T"]].append(row)

    # Each ticker's bars arrived out of date-order (threads); sort by ts.
    for t in store:
        store[t].sort(key=lambda b: b["t"])
    return store, dict(calls=len(dates), secs=time.time() - t0,
                       throttled=throttled[0], forbidden=forbidden[0],
                       earliest=earliest[0])


# ──────────────────── daily → weekly / monthly (prod logic) ───────────────

def to_weekly(daily):
    """Monday-start ISO weeks — mirrors _get_monday_weekly_candles."""
    weeks = defaultdict(list)
    for b in daily:
        dt = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc)
        iso = dt.isocalendar()
        weeks[(iso[0], iso[1])].append(b)
    return _agg(weeks)


def to_monthly(daily):
    """Calendar months — mirrors _get_calendar_monthly_candles."""
    months = defaultdict(list)
    for b in daily:
        dt = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc)
        months[(dt.year, dt.month)].append(b)
    return _agg(months)


def _agg(groups):
    out = []
    for key in sorted(groups):
        bars = groups[key]
        out.append(dict(o=bars[0]["o"],
                        h=max(b["h"] for b in bars),
                        l=min(b["l"] for b in bars),
                        c=bars[-1]["c"], t=bars[0]["t"]))
    return out


def levels_for(bars, tf):
    """find_htf_levels on a chronological bar list. Returns (s1,s2,d1,d2)."""
    if len(bars) < 3:
        return None
    lb = HTF_TF_LOOKBACK.get(tf, 50)
    price = bars[-1]["c"]
    highs = [b["h"] for b in reversed(bars)]   # most-recent-first
    lows = [b["l"] for b in reversed(bars)]
    return find_htf_levels(highs, lows, price, lookback=lb)


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


# ─────────────────────────────────── main ────────────────────────────────

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

    If grouped == SRV, the grouped path is a faithful substitute (SRV already
    matches TV on the compare page). The TV column is the end-to-end check.

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
    args = ap.parse_args()

    key = os.environ.get("MASSIVE_API_KEY", "")
    if not key:
        sys.exit("MASSIVE_API_KEY not set")
    session = pooled_session(args.workers)

    if args.verify:
        verify_vs_tv(session, key, [t.strip().upper() for t in args.verify.split(",")],
                     args.years, args.workers, args.market)
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
