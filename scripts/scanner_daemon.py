#!/usr/bin/env python3
"""Background MTF scanner daemon.

Keeps the grouped-daily stores warm IN MEMORY (so the expensive 5-year warm
happens once at startup, not on every request) and re-scans the universe on a
loop, writing the shortlist to Redis. The Flask read endpoint
(GET /api/mtf-scan) and the frontends just read that cache.

Markets: stocks (top-N liquid via grouped us/stocks), fx (curated pairs via
grouped global/fx), crypto (curated via grouped global/crypto), and indices
(curated I: list — no grouped endpoint, so fetched per-symbol via MassiveClient
and folded into the same scan path).

Env:
  MASSIVE_API_KEY   — Polygon/Massive key (required)
  REDIS_URL         — default redis://localhost:6379/0
  SCANNER_NEAR_PCT  — proximity band, fraction (default 0.03 = 3%)
  SCANNER_UNIVERSE  — stock universe size (default 700)
  SCANNER_YEARS     — history to warm (default 5)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis as _redis  # noqa: E402

from lumisignals.mtf_scan import (  # noqa: E402
    pooled_session, _grouped, most_recent_trading_day, pick_universe,
    warm_store, scan_market, bars_from_candles, compact_bar, MARKET_PREFIX,
)
from lumisignals.massive_client import get_shared_client, TICKER_NAMES  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scanner] %(levelname)s %(message)s",
)
log = logging.getLogger("scanner")

REDIS_KEY = "mtf:scan:latest"
REDIS_TTL = 1800                       # 30 min — staleness is detectable
# Low worker count on purpose: each grouped call buffers a full ~11k-symbol
# response, so peak warm memory ≈ workers × response size. On the 2GB prod box
# a high count OOM'd; JSON parse is GIL-bound anyway so few workers barely
# changes wall time. Universe/years trimmed to cap the resident store.
WORKERS = int(os.environ.get("SCANNER_WORKERS", "4"))
NEAR_PCT = float(os.environ.get("SCANNER_NEAR_PCT", "0.03"))
UNIVERSE_N = int(os.environ.get("SCANNER_UNIVERSE", "500"))
YEARS = float(os.environ.get("SCANNER_YEARS", "4"))

# Proximity band is asset-aware: a 3% band that's tight for a stock is days of
# range for FX (so it would flag every pair) and loose for crypto. Tuned per
# asset class; falls back to NEAR_PCT.
NEAR_BY_ASSET = {
    "stock": NEAR_PCT,
    "index": NEAR_PCT,
    "fx": float(os.environ.get("SCANNER_NEAR_FX", "0.005")),     # ~50 pips
    "crypto": float(os.environ.get("SCANNER_NEAR_CRYPTO", "0.02")),
}

# Curated FX pairs (grouped fx keys are C:EURUSD).
FX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "AUDJPY", "EURAUD", "GBPAUD",
    "EURCAD", "GBPCAD", "AUDNZD", "AUDCAD", "NZDJPY", "CADJPY", "CHFJPY",
    "USDMXN", "USDSGD", "USDNOK", "USDSEK", "USDZAR",
]
# Curated crypto pairs (grouped crypto keys are X:BTCUSD).
CRYPTO_PAIRS = [
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "ADAUSD", "AVAXUSD",
    "DOTUSD", "LINKUSD", "LTCUSD", "BCHUSD", "UNIUSD", "ATOMUSD", "ETCUSD",
]
# Curated indices (no grouped endpoint — fetched per-symbol).
INDEX_SYMBOLS = [
    "I:SPX", "I:NDX", "I:RUT", "I:DJI", "I:COMP", "I:RUI",
    "I:XSP", "I:XND", "I:SOX",
]


def _market_universe(market):
    """(universe_keys, names) for a curated market. Stocks resolve at warm."""
    if market == "fx":
        return [MARKET_PREFIX["fx"] + p for p in FX_PAIRS], {}
    if market == "crypto":
        return [MARKET_PREFIX["crypto"] + p for p in CRYPTO_PAIRS], {}
    return [], {}


def _upsert_recent(bars, row):
    """Replace today's forming bar (same calendar day) or append a new day.
    Scans only the tail since refreshed days are always the most recent."""
    rt_day = datetime.fromtimestamp(row["t"] / 1000, tz=timezone.utc).date()
    for i in range(len(bars) - 1, max(-1, len(bars) - 30), -1):
        b_day = datetime.fromtimestamp(bars[i]["t"] / 1000, tz=timezone.utc).date()
        if b_day == rt_day:
            bars[i] = row
            return
        if b_day < rt_day:
            break
    bars.append(row)


def _refresh_recent(session, key, store, uni, market, days_back=10):
    """Cheap per-cycle update: pull the last few grouped days and upsert them
    into the warm store so 'today' is current without re-warming 5 years."""
    end = datetime.now(timezone.utc).date()
    all_days = market == "crypto"
    dates, d = [], end
    while len(dates) < days_back and d > end - timedelta(days=days_back * 2):
        if all_days or d.weekday() < 5:
            dates.append(d.isoformat())
        d -= timedelta(days=1)
    updated = 0
    for ds in dates:
        rows = _grouped(session, key, ds, market)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if row["T"] in uni:
                _upsert_recent(store.setdefault(row["T"], []), compact_bar(row))
                updated += 1
    for t in store:
        store[t].sort(key=lambda b: b["t"])
    return updated


class GroupedMarket:
    """A warm grouped store for one market, refreshed in place each cycle."""

    def __init__(self, session, key, market, asset_class, approx):
        self.session, self.key = session, key
        self.market, self.asset_class, self.approx = market, asset_class, approx
        self.store = {}
        self.uni = set()
        self.names = {}

    def ensure_warm(self):
        """Full warm if the store is empty (first cycle or after a failure)."""
        if self.store:
            return
        if self.market == "stocks":
            day, rows = most_recent_trading_day(self.session, self.key, "stocks")
            universe = pick_universe(rows, UNIVERSE_N)
        else:
            universe, _ = _market_universe(self.market)
        self.uni = set(universe)
        self.names = {t: TICKER_NAMES.get(t, "") for t in universe}
        self.store, warm = warm_store(self.session, self.key, universe,
                                      YEARS, WORKERS, self.market)
        log.info("warmed %s: %d/%d tickers, %d calls in %.0fs",
                 self.market, len(self.store), len(universe),
                 warm["calls"], warm["secs"])

    def scan(self):
        self.ensure_warm()
        _refresh_recent(self.session, self.key, self.store, self.uni, self.market)
        near = NEAR_BY_ASSET.get(self.asset_class, NEAR_PCT)
        return scan_market(self.store, list(self.uni), near,
                           asset_class=self.asset_class, names=self.names,
                           approx=self.approx)


class IndexMarket:
    """Indices have no grouped endpoint — fetch each per-symbol and reuse the
    same scan path via bars_from_candles."""

    def __init__(self, massive_key):
        self.client = get_shared_client(massive_key)

    def scan(self):
        store, names = {}, {}
        need = int(YEARS * 252) + 40       # enough dailies for monthly lookback
        for sym in INDEX_SYMBOLS:
            try:
                candles = self.client.get_candles(sym, "1d", need)
            except Exception as e:
                log.warning("index %s fetch failed: %s", sym, e)
                continue
            bars = bars_from_candles(candles)
            if len(bars) >= 30:
                store[sym] = bars
                names[sym] = TICKER_NAMES.get(sym, "")
        return scan_market(store, list(store), NEAR_BY_ASSET.get("index", NEAR_PCT),
                           asset_class="index", names=names, approx=False)


def _is_rth():
    """Rough US cash-session window (weekday ~13:30–21:00 UTC ≈ 9:30–16:00 ET,
    DST-agnostic). Governs the loop cadence only."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= mins <= 21 * 60


def run_cycle(rdb, markets, index_market):
    rows, counts = [], {}
    for m in markets:
        try:
            r = m.scan()
            rows.extend(r)
            counts[m.asset_class] = len(r)
        except Exception as e:
            log.exception("scan failed for %s: %s", m.market, e)
            counts[m.asset_class] = -1
    try:
        r = index_market.scan()
        rows.extend(r)
        counts["index"] = len(r)
    except Exception as e:
        log.exception("index scan failed: %s", e)
        counts["index"] = -1

    rows.sort(key=lambda x: x["dist"])
    payload = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "near_pct": NEAR_PCT,
        "counts": counts,
        "results": rows,
    }
    rdb.setex(REDIS_KEY, REDIS_TTL, json.dumps(payload, default=str))
    # Per-asset keys for cheap filtered reads.
    by_asset = {}
    for row in rows:
        by_asset.setdefault(row["asset_class"], []).append(row)
    for asset, arows in by_asset.items():
        rdb.setex(f"mtf:scan:{asset}", REDIS_TTL,
                  json.dumps({"scanned_at": payload["scanned_at"],
                              "results": arows}, default=str))
    return counts, len(rows)


def main():
    massive_key = os.environ.get("MASSIVE_API_KEY", "")
    if not massive_key:
        sys.exit("MASSIVE_API_KEY not set")
    rdb = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    session = pooled_session(WORKERS)

    markets = [
        GroupedMarket(session, massive_key, "stocks", "stock", approx=False),
        GroupedMarket(session, massive_key, "fx", "fx", approx=True),
        GroupedMarket(session, massive_key, "crypto", "crypto", approx=True),
    ]
    index_market = IndexMarket(massive_key)

    log.info("scanner daemon starting (universe=%d, years=%g, near=%.1f%%)",
             UNIVERSE_N, YEARS, NEAR_PCT * 100)
    while True:
        t0 = time.time()
        try:
            counts, total = run_cycle(rdb, markets, index_market)
            log.info("cycle done in %.1fs: %d hits %s", time.time() - t0,
                     total, counts)
        except Exception as e:
            log.exception("cycle error: %s", e)
        time.sleep(300 if _is_rth() else 1800)


if __name__ == "__main__":
    main()
