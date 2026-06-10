#!/usr/bin/env python3
"""Background MTF scanner daemon.

Re-scans a curated universe on a loop and writes the shortlist to Redis; the
Flask read endpoint (GET /api/mtf-scan) and the frontends just read that cache.

Fetch strategy is per asset:
  - stocks / crypto / indices → PER-TICKER (MassiveClient.get_candles). For a
    curated list this is far cheaper than grouped (one small call per symbol vs
    ~1000 grouped days that each return every US ticker) and avoids the ~11k-row
    grouped parse that OOM'd the 2GB box.
  - fx → GROUPED. get_candles' forex session-daily only carries ~40 days of
    history (built from hourly), too few for monthly levels, so FX still warms
    years of daily from the grouped global/fx endpoint.

Stocks are a hand-curated ~100 best-for-options names, tagged by `group`
(high_vol / megacap / largecap / etf) so the UI can filter to e.g. only the
high-volatility setups.

Env: MASSIVE_API_KEY (req), REDIS_URL, SCANNER_NEAR_PCT/_FX/_CRYPTO,
SCANNER_MIN_HV, SCANNER_YEARS, SCANNER_WORKERS.
"""
import concurrent.futures as cf
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import redis as _redis  # noqa: E402

from lumisignals.mtf_scan import (  # noqa: E402
    pooled_session, _grouped, most_recent_trading_day, warm_store,
    scan_market, bars_from_candles, compact_bar, MARKET_PREFIX,
)
from lumisignals.massive_client import get_shared_client, TICKER_NAMES  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scanner] %(levelname)s %(message)s",
)
log = logging.getLogger("scanner")

REDIS_KEY = "mtf:scan:latest"
REDIS_TTL = 1800                       # 30 min — staleness is detectable
WORKERS = int(os.environ.get("SCANNER_WORKERS", "8"))
NEAR_PCT = float(os.environ.get("SCANNER_NEAR_PCT", "0.03"))
YEARS = float(os.environ.get("SCANNER_YEARS", "4"))

# Proximity band is asset-aware: a 3% band that's tight for a stock is days of
# range for FX (so it would flag every pair) and loose for crypto.
NEAR_BY_ASSET = {
    "stock": NEAR_PCT,
    "index": NEAR_PCT,
    "fx": float(os.environ.get("SCANNER_NEAR_FX", "0.0025")),     # ~25 pips
    "crypto": float(os.environ.get("SCANNER_NEAR_CRYPTO", "0.02")),
}
# Annualized-HV floor for stocks: drops near-zero-vol money-market / T-bill
# ETFs (SGOV/SHV/BIL) that sit "at" a level every day. Real names run >10%.
MIN_HV_STOCK = float(os.environ.get("SCANNER_MIN_HV", "0.05"))

# ── Curated ~100 best-for-options stocks, grouped. Liquid options first
#    (tight spreads / deep OI), then volatility. ───────────────────────────
STOCK_GROUPS = {
    "high_vol": [
        "NVDA", "MU", "AMD", "TSLA", "SMCI", "COIN", "MSTR", "MARA", "PLTR",
        "ARM", "MRVL", "AVGO", "AFRM", "SOFI", "CVNA", "DKNG", "NET", "CRWD",
        "SHOP", "RBLX", "ENPH", "FSLR",
        # leveraged / vol ETFs
        "TQQQ", "SQQQ", "SOXL", "SOXS", "TNA", "NVDL", "TSLL", "UVXY",
    ],
    "megacap": [
        "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NFLX", "ORCL", "ADBE",
        "CRM", "QCOM", "TXN", "INTC", "CSCO", "AMAT", "LRCX", "NOW", "PYPL",
        "UBER", "ABNB", "SNOW",
    ],
    "largecap": [
        "JPM", "BAC", "GS", "MS", "WFC", "V", "MA",
        "XOM", "CVX", "OXY", "SLB", "COP",
        "UNH", "LLY", "PFE", "MRK", "ABBV", "JNJ",
        "WMT", "COST", "HD", "NKE", "DIS", "SBUX", "MCD",
        "BA", "CAT", "GE", "F", "GM",
    ],
    "etf": [
        "SPY", "QQQ", "IWM", "DIA", "SMH", "SOXX",
        "XLF", "XLE", "XLK", "XLV", "XLU", "XLI",
        "GLD", "SLV", "USO", "TLT", "HYG", "ARKK", "EEM", "FXI",
    ],
}
# Flatten to [(ticker, group)].
STOCK_SYMBOLS = [(t, g) for g, ts in STOCK_GROUPS.items() for t in ts]

# Crypto + indices: per-ticker via get_candles (X: / I: prefixes).
CRYPTO_SYMBOLS = [
    "X:BTCUSD", "X:ETHUSD", "X:SOLUSD", "X:XRPUSD", "X:DOGEUSD", "X:ADAUSD",
    "X:AVAXUSD", "X:DOTUSD", "X:LINKUSD", "X:LTCUSD", "X:BCHUSD", "X:UNIUSD",
    "X:ATOMUSD", "X:ETCUSD",
]
INDEX_SYMBOLS = [
    "I:SPX", "I:NDX", "I:RUT", "I:DJI", "I:COMP", "I:RUI",
    "I:XSP", "I:XND", "I:SOX",
]
# FX stays grouped (get_candles forex daily is too shallow).
FX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "AUDJPY", "EURAUD", "GBPAUD",
    "EURCAD", "GBPCAD", "AUDNZD", "AUDCAD", "NZDJPY", "CADJPY", "CHFJPY",
    "USDMXN", "USDSGD", "USDNOK", "USDSEK", "USDZAR",
]


class PerTickerMarket:
    """Curated symbols fetched one-per-ticker via get_candles (cheap, no big
    grouped parse). `symbols` is a list of bare tickers or (ticker, group)
    tuples. Stateless: each scan re-fetches (MassiveClient TTL-caches dailies)."""

    def __init__(self, massive_key, symbols, asset_class, min_hv=0.0,
                 approx=False, default_group=None):
        self.client = get_shared_client(massive_key)
        self.symbols = [s if isinstance(s, tuple) else (s, default_group or asset_class)
                        for s in symbols]
        self.asset_class = asset_class
        self.label = asset_class
        self.min_hv = min_hv
        self.approx = approx

    def scan(self):
        need = int(YEARS * 252) + 40
        store, names, groups = {}, {}, {}

        def fetch(sg):
            sym, grp = sg
            try:
                candles = self.client.get_candles(sym, "1d", need)
            except Exception as e:
                log.warning("%s %s fetch failed: %s", self.asset_class, sym, e)
                return sym, grp, None
            return sym, grp, bars_from_candles(candles)

        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for sym, grp, bars in ex.map(fetch, self.symbols):
                if bars and len(bars) >= 30:
                    store[sym] = bars
                    groups[sym] = grp
                    names[sym] = TICKER_NAMES.get(sym, "")
        return scan_market(store, list(store),
                           NEAR_BY_ASSET.get(self.asset_class, NEAR_PCT),
                           asset_class=self.asset_class, names=names,
                           groups=groups, approx=self.approx, min_hv=self.min_hv)


class GroupedMarket:
    """Grouped warm store (FX only). Keeps the store warm in memory and
    refreshes the last few days each cycle."""

    def __init__(self, session, key, market, asset_class, approx):
        self.session, self.key = session, key
        self.market, self.asset_class, self.approx = market, asset_class, approx
        self.label = market
        self.store = {}
        self.uni = set()

    def ensure_warm(self):
        if self.store:
            return
        universe = [MARKET_PREFIX[self.market] + p for p in FX_PAIRS]
        self.uni = set(universe)
        self.store, warm = warm_store(self.session, self.key, universe,
                                      YEARS, WORKERS, self.market)
        log.info("warmed %s: %d/%d tickers, %d calls in %.0fs (%d errors)",
                 self.market, len(self.store), len(universe),
                 warm["calls"], warm["secs"], warm.get("errors", 0))

    def _refresh_recent(self, days_back=10):
        end = datetime.now(timezone.utc).date()
        dates, d = [], end
        while len(dates) < days_back and d > end - timedelta(days=days_back * 2):
            if d.weekday() < 5:
                dates.append(d.isoformat())
            d -= timedelta(days=1)
        for ds in dates:
            rows = _grouped(self.session, self.key, ds, self.market)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if row["T"] in self.uni:
                    bars = self.store.setdefault(row["T"], [])
                    rt = datetime.fromtimestamp(row["t"] / 1000, tz=timezone.utc).date()
                    for i in range(len(bars) - 1, max(-1, len(bars) - 30), -1):
                        bd = datetime.fromtimestamp(bars[i]["t"] / 1000, tz=timezone.utc).date()
                        if bd == rt:
                            bars[i] = compact_bar(row)
                            break
                        if bd < rt:
                            bars.append(compact_bar(row))
                            break
                    else:
                        bars.append(compact_bar(row))
        for t in self.store:
            self.store[t].sort(key=lambda b: b["t"])

    def scan(self):
        self.ensure_warm()
        self._refresh_recent()
        return scan_market(self.store, list(self.uni),
                           NEAR_BY_ASSET.get(self.asset_class, NEAR_PCT),
                           asset_class=self.asset_class, approx=self.approx)


def _is_rth():
    """Rough US cash session (weekday ~13:30–21:00 UTC). Cadence only."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 13 * 60 + 30 <= mins <= 21 * 60


def run_cycle(rdb, markets):
    rows, counts = [], {}
    for m in markets:
        try:
            r = m.scan()
            rows.extend(r)
            counts[m.asset_class] = len(r)
        except Exception as e:
            log.exception("scan failed for %s: %s", m.label, e)
            counts[m.asset_class] = -1

    rows.sort(key=lambda x: x["dist"])
    payload = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "near_pct": NEAR_PCT,
        "counts": counts,
        "results": rows,
    }
    rdb.setex(REDIS_KEY, REDIS_TTL, json.dumps(payload, default=str))
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
        PerTickerMarket(massive_key, STOCK_SYMBOLS, "stock", min_hv=MIN_HV_STOCK),
        PerTickerMarket(massive_key, INDEX_SYMBOLS, "index", default_group="index"),
        PerTickerMarket(massive_key, CRYPTO_SYMBOLS, "crypto", approx=True,
                        default_group="crypto"),
        GroupedMarket(session, massive_key, "fx", "fx", approx=True),
    ]

    log.info("scanner daemon starting (%d stocks, %d crypto, %d indices, %d fx; "
             "years=%g, near=%.1f%%)", len(STOCK_SYMBOLS), len(CRYPTO_SYMBOLS),
             len(INDEX_SYMBOLS), len(FX_PAIRS), YEARS, NEAR_PCT * 100)
    while True:
        t0 = time.time()
        try:
            counts, total = run_cycle(rdb, markets)
            log.info("cycle done in %.1fs: %d hits %s", time.time() - t0,
                     total, counts)
        except Exception as e:
            log.exception("cycle error: %s", e)
        time.sleep(300 if _is_rth() else 1800)


if __name__ == "__main__":
    main()
