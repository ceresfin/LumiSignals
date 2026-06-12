#!/usr/bin/env python3
"""Fast multi-timeframe (MTF) level scanner — reusable core.

This is the production home of the grouped-daily scan that ``scripts/
bench_mtf_scan.py`` prototyped. The architecture:

  Warm a ``{ticker: [daily bars]}`` store from the GROUPED DAILY endpoint
  (one Massive/Polygon call returns EVERY symbol's bar for a date, so the
  whole ~700-name universe costs one call per trading day, not one per
  ticker). Derive Daily/Weekly/Monthly in-memory and run the production
  ``find_htf_levels`` to find untouched supply/demand levels. ``scan_market``
  then shortlists names sitting within ``near_pct`` of a level right now,
  closest-first, with a 1-5 volatility rank and a suggested spread.

Both the background daemon (``scripts/scanner_daemon.py``) and the CLI
benchmark import from here so there is a single source of truth.

Markets: ``stocks`` (grouped us/stocks), ``fx`` (grouped global/fx, keys are
``C:EURUSD``), ``crypto`` (grouped global/crypto, keys are ``X:BTCUSD``).
Indices (``I:SPX`` …) have no grouped endpoint — build their store per-symbol
via :func:`bars_from_candles` and pass it to :func:`scan_market` like any other.
"""
import concurrent.futures as cf
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from lumisignals.untouched_levels import find_htf_levels, HTF_TF_LOOKBACK

BASE_URL = "https://api.polygon.io"
# Grouped-daily path per market. Stocks=weekdays only; crypto=24/7; fx=24/5.
MARKETS = {
    "stocks": "/v2/aggs/grouped/locale/us/market/stocks/{date}",
    "crypto": "/v2/aggs/grouped/locale/global/market/crypto/{date}",
    "fx":     "/v2/aggs/grouped/locale/global/market/fx/{date}",
}
# Grouped-daily 'T' (ticker) prefix per market.
MARKET_PREFIX = {"crypto": "X:", "fx": "C:", "stocks": ""}


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
    """One grouped-daily call → list of {T,o,h,l,c,v,t} rows (empty on holiday).
    Network/HTTP failures return the "error" sentinel rather than raising, so a
    single flaky day (Polygon ReadTimeout) can't abort an entire multi-year
    warm — the caller just skips that day."""
    try:
        r = session.get(BASE_URL + MARKETS[market].format(date=date_str),
                        params={"adjusted": "true", "apiKey": key}, timeout=30)
    except requests.exceptions.RequestException:
        return "error"
    if r.status_code == 429:
        return "throttled"
    if r.status_code == 403:           # beyond the plan's history window
        return "forbidden"
    try:
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception:
        return "error"


def most_recent_trading_day(session, key, market="stocks"):
    """Walk back from today until a grouped call returns rows."""
    d = datetime.now(timezone.utc).date()
    for _ in range(9):
        rows = _grouped(session, key, d.isoformat(), market)
        # Only a non-empty list is real data; skip weekends/holidays (empty
        # list) and "throttled"/"forbidden" sentinels (strings).
        if isinstance(rows, list) and rows:
            return d, rows
        d -= timedelta(days=1)
    raise RuntimeError("no trading day found in last 9 days")


def compact_bar(row):
    """Minimal {o,h,l,c,t} bar — the only fields the scan reads. Drops the
    grouped row's T/v/vw/n to keep the warm store small on a 2GB box."""
    return {"o": row["o"], "h": row["h"], "l": row["l"],
            "c": row["c"], "t": row["t"]}


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
    all_days = market == "crypto"   # crypto trades 24/7; fx grouped is empty
                                    # on weekends, so treat fx like stocks.
    dates, d = [], end
    while d > end - timedelta(days=int(years * 365.25)):
        if all_days or d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)

    store = defaultdict(list)
    throttled = [0]
    forbidden = [0]
    errors = [0]
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
        if not isinstance(rows, list):     # "error" — flaky day, skip it
            errors[0] += 1
            return []
        if rows and (earliest[0] is None or ds < earliest[0]):
            earliest[0] = ds
        # Keep ONLY the universe and ONLY the 5 fields the scan reads. The
        # grouped response holds every US symbol (~11k) with ~9 fields each;
        # retaining the raw rows is what OOM'd a memory-tight box. Trimming
        # here lets the full response be GC'd as soon as fetch() returns.
        return [(row["T"], compact_bar(row)) for row in rows if row["T"] in uni]

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for chunk in ex.map(fetch, dates):
            for t, bar in chunk:
                store[t].append(bar)

    # Each ticker's bars arrived out of date-order (threads); sort by ts.
    for t in store:
        store[t].sort(key=lambda b: b["t"])
    return store, dict(calls=len(dates), secs=time.time() - t0,
                       throttled=throttled[0], forbidden=forbidden[0],
                       errors=errors[0], earliest=earliest[0])


def bars_from_candles(candles):
    """Convert a list of CandleData (from MassiveClient.get_candles) into the
    grouped-store bar shape ({o,h,l,c,t} with t in ms). Used to fold indices —
    which have no grouped endpoint — into the same scan path."""
    out = []
    for c in candles:
        try:
            t_ms = int(float(c.timestamp) * 1000)
        except (TypeError, ValueError):
            continue
        out.append(dict(o=float(c.open), h=float(c.high), l=float(c.low),
                        c=float(c.close), t=t_ms))
    out.sort(key=lambda b: b["t"])
    return out


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


# ──────────────── 5m → 15m / 1h / 4h (intraday/scalp, prod logic) ─────────
# RTH-open aligned, matching MassiveClient._get_market_aligned_candles so the
# scanner's intraday zones line up with the bot/TradingView: 1h = 9:30-10:29…,
# 4h = 9:30-1:29 / 1:30-3:59. Open hardcoded to 13:30 UTC (9:30 ET, EDT) like
# the rest of the module (off 1h in EST winter — known, file-wide).
_RTH_OPEN_MIN = 13 * 60 + 30

def _intraday_bucket(bars5m, bucket_min):
    """Aggregate RTH 5m bars into `bucket_min` buckets aligned to the session
    open. Input/output chronological. (get_candles already RTH-filters stock
    5m, so all bars here are in-session.)"""
    groups = defaultdict(list)
    for b in bars5m:
        dt = datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc)
        idx = ((dt.hour * 60 + dt.minute) - _RTH_OPEN_MIN) // bucket_min
        groups[(dt.date(), idx)].append(b)
    return _agg(groups)


def to_15m(b5):
    return _intraday_bucket(b5, 15)

def to_1h(b5):
    return _intraday_bucket(b5, 60)

def to_4h(b5):
    return _intraday_bucket(b5, 240)


def levels_for(bars, tf):
    """find_htf_levels on a chronological bar list. Returns (s1,s2,d1,d2)."""
    if len(bars) < 3:
        return None
    lb = HTF_TF_LOOKBACK.get(tf, 50)
    price = bars[-1]["c"]
    highs = [b["h"] for b in reversed(bars)]   # most-recent-first
    lows = [b["l"] for b in reversed(bars)]
    return find_htf_levels(highs, lows, price, lookback=lb)


# ─────────────────────────── volatility ranking ──────────────────────────

def hv_series(daily, window=20, lookback=252):
    """Rolling annualized HV(window) over the last `lookback` trading days —
    the ticker's OWN volatility history, from price alone. This is what we
    rank today's reading against until we've logged real IV history (then
    feed the logged IV series to rank_1_5 instead — same scale)."""
    closes = [b["c"] for b in daily]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    out = []
    for end in range(window, len(rets) + 1):
        w = rets[end - window:end]
        mean = sum(w) / window
        var = sum((r - mean) ** 2 for r in w) / (window - 1)
        out.append((var ** 0.5) * (252 ** 0.5))
    return out[-lookback:]


def rank_1_5(value, series):
    """Where does `value` sit in its own historical range → a 1-5 band.
    Classic IV-Rank style (min-max position): 1 = at/near its low, 5 = at/
    near its high. Works for any volatility series (realized now, implied
    once logged)."""
    if value is None or len(series) < 20:
        return None
    lo, hi = min(series), max(series)
    if hi <= lo:
        return 3
    pos = (value - lo) / (hi - lo)            # 0..1 within its own range
    return min(5, max(1, int(pos * 5) + 1))   # 1..5 bands of 20% each


# Vol band → which side of the options trade it favors.
VOL_LEAN = {1: "DEBIT", 2: "DEBIT", 3: "—", 4: "CREDIT", 5: "CREDIT"}


def spread_for(side, vol_rank):
    """direction (from the level scan) x vol band -> the spread to suggest.
    Low vol (rank 1-2) = buy premium (debit); high vol (4-5) = sell (credit)."""
    lean = VOL_LEAN.get(vol_rank) if vol_rank else None
    table = {
        ("LONG", "DEBIT"):  "bull call debit",
        ("LONG", "CREDIT"): "bull put credit",
        ("SHORT", "DEBIT"): "bear put debit",
        ("SHORT", "CREDIT"): "bear call credit",
    }
    return table.get((side, lean), "—")


# ─────────────────────────────── the scan ────────────────────────────────

# supply = resistance (short into it); demand = support (long off it).
_TF = [("D", "1d", lambda d: d),
       ("W", "1w", to_weekly),
       ("M", "1mo", to_monthly)]
# Fast stacks (built from a 5m base store): intraday = 15m/1h/4h,
# scalp = 5m/15m/1h. Same Russian-doll shape as swing, reusing levels_for.
_TF_INTRADAY = [("15m", "15m", to_15m), ("1h", "1h", to_1h), ("4h", "4h", to_4h)]
_TF_SCALP    = [("5m", "5m", lambda b: b), ("15m", "15m", to_15m), ("1h", "1h", to_1h)]
TF_STACKS = {"swing": _TF, "intraday": _TF_INTRADAY, "scalp": _TF_SCALP}
_LEVELS = [("S1", 0, "SHORT"), ("S2", 1, "SHORT"),
           ("D1", 2, "LONG"),  ("D2", 3, "LONG")]


def _alignment_score(side, near_levels, chosen_dist, near_pct, vol_rank):
    """Cheap 0-3 confluence score from data already gathered:
      +1 proximity  — sitting very close (within half the band)
      +1 multi-TF   — ≥2 timeframes show a same-side level in the band
      +1 vol read   — vol band is decisive (favors a clear debit/credit lean)
    `near_levels` = list of (tf, side, dist) candidates within near_pct."""
    score = 0
    if chosen_dist <= near_pct / 2:
        score += 1
    tfs_same_side = {tf for tf, s, _ in near_levels if s == side}
    if len(tfs_same_side) >= 2:
        score += 1
    if vol_rank in (1, 2, 4, 5):   # not the neutral 3
        score += 1
    return score


def scan_market(store, universe, near_pct, asset_class="stock",
                names=None, approx=False, min_hv=0.0, groups=None,
                tf_stack=None, mode="swing"):
    """For each ticker compute untouched D/W/M levels and flag any sitting
    within `near_pct` of price right now. Returns canonical rows, closest
    first. `asset_class` tags the rows; `approx` marks feeds (fx/crypto)
    whose levels drift slightly from TradingView/OANDA. `names` maps ticker
    → display name. `min_hv` drops near-zero-volatility instruments
    (money-market / T-bill ETFs like SGOV/SHV/BIL that barely move, so they
    sit microscopically 'at' a level every day and pollute the shortlist)."""
    names = names or {}
    tf_stack = tf_stack if tf_stack is not None else _TF
    rows = []
    for t in universe:
        daily = store.get(t, [])
        if len(daily) < 30:
            continue
        price = daily[-1]["c"]
        near_levels = []                       # (tf, side, dist) within band
        best = None                            # (dist, tf, name, level, side)
        for tf, gtf, derive in tf_stack:
            bars = derive(daily)
            lv = levels_for(bars, gtf)
            if not lv:
                continue
            cur_low = bars[-1]["l"]            # demand-fallback sentinel
            for lname, i, side in _LEVELS:
                L = lv[i]
                if L is None:
                    continue
                # You pull DOWN to demand (below price) and rally UP to supply
                # (above). A level on the wrong side isn't a setup.
                if side == "LONG" and L > price * 1.001:
                    continue
                if side == "SHORT" and L < price * 0.999:
                    continue
                # Drop the demand fallback (demand == this bar's own low =
                # "price at its low", not a pullback into a prior zone).
                if side == "LONG" and abs(L - cur_low) < 1e-9:
                    continue
                dist = abs(price - L) / price
                if dist <= near_pct:
                    near_levels.append((tf, side, dist))
                    if best is None or dist < best[0]:
                        best = (dist, tf, lname, L, side)
        if not best:
            continue
        dist, tf, lname, L, side = best
        series = hv_series(daily, 20, 252)
        today_hv = series[-1] if series else None
        # Volatility floor: a flat instrument (annualized HV below the floor)
        # is always "near" a level and never a real setup — drop it.
        if min_hv and today_hv is not None and today_hv < min_hv:
            continue
        vol_rank = rank_1_5(today_hv, series)
        rows.append(dict(
            ticker=_display_ticker(t), name=names.get(t, ""),
            asset_class=asset_class, group=((groups or {}).get(t) or asset_class),
            mode=mode,
            price=round(price, 4), side=side,
            tf=tf, level_name=lname, level=round(L, 4),
            dist=dist, dist_pct=round(dist * 100, 2),
            hv=(round(today_hv, 4) if today_hv is not None else None),
            vol_rank=vol_rank, vol_lean=(VOL_LEAN.get(vol_rank) if vol_rank else "—"),
            suggested_spread=spread_for(side, vol_rank),
            score=_alignment_score(side, near_levels, dist, near_pct, vol_rank),
            approx=approx,
        ))
    rows.sort(key=lambda r: r["dist"])
    return rows


def _display_ticker(t):
    """Strip the grouped-market prefix for display (C:EURUSD → EURUSD,
    X:BTCUSD → BTCUSD, I:SPX → SPX); plain stocks pass through."""
    for p in ("C:", "X:", "I:"):
        if t.startswith(p):
            return t[len(p):]
    return t


# Backwards-compatible alias for the benchmark script's original signature.
def scan_actionable(store, universe, near_pct):
    """Legacy entry point used by scripts/bench_mtf_scan.py --scan. Same rows
    as scan_market (stocks), retaining the `dist`/`hv`/`vol_rank` keys the
    benchmark's printer reads."""
    return scan_market(store, universe, near_pct, asset_class="stock")
