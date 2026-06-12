"""HTF Supply/Demand Level Finder — Python port of pinescripts/htf_strategy.pine.

Computes untouched supply (S1/S2) + demand (D1/D2) levels and ADX trend
across Q, M, W, D, 4H, 1H, 30M, 15M timeframes using the same algorithm
the Pine script runs in TradingView.

Layout:
  - compute_levels()      — pure algorithm, takes a DataFrame, returns TFLevels
  - fetch_and_compute()   — convenience wrapper that pulls all 8 TFs from Polygon
  - CLI: `python htf_levels.py SPY`           → printed table
         `python htf_levels.py SPY --json`    → JSON for piping

Notes vs. Pine:
  - Pine uses request.security with lookahead_on (Q/M) and lookahead_off
    (W and below). This script uses the live latest bar for ALL TFs, so the
    `close` filter on supply candidates reflects current intraday price.
    Practical numbers match Pine very closely for live use; historical bar-
    by-bar replay may differ slightly.
  - ADX/DMI use Wilder smoothing matching Pine's ta.dmi/ta.rma. Minor
    numerical differences are possible due to series seeding.

Usage examples:
  POLYGON_API_KEY=xxx python scripts/htf_levels.py SPY
  POLYGON_API_KEY=xxx python scripts/htf_levels.py I:SPX --json
  POLYGON_API_KEY=xxx python scripts/htf_levels.py C:EURUSD
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd


# ─── Per-TF lookback (matches the Pine constants) ──────────────────────────
TF_LOOKBACK = {
    "Q":   60,    # ~15 years of quarters
    "M":   60,    # ~5 years of months
    "W":   100,   # ~2 years of weeks
    "D":   100,   # ~5 months of trading days
    "4H":  120,   # ~4 weeks of 4-hour bars
    "1H":  200,   # ~8 weeks (stocks) / ~1.5 weeks (forex 24/5) of hourly
    "30M": 300,   # ~6 weeks (stocks) / ~1.3 weeks (forex) of 30m
    "15M": 500,   # ~5 weeks (stocks) / ~1.0 week (forex) of 15m
}

# ─── Polygon aggregation params per TF ─────────────────────────────────────
POLYGON_AGG = {
    "Q":   ("1",  "quarter"),
    "M":   ("1",  "month"),
    "W":   ("1",  "week"),
    "D":   ("1",  "day"),
    "4H":  ("4",  "hour"),
    "1H":  ("1",  "hour"),
    "30M": ("30", "minute"),
    "15M": ("15", "minute"),
}

# Calendar days back to fetch from Polygon for each TF (enough to cover the
# lookback window comfortably)
POLYGON_DAYS_BACK = {
    "Q":   365 * 6,    # 6 years
    "M":   365 * 3,    # 3 years
    "W":   365,        # 1 year
    "D":   180,        # 6 months
    "4H":  90,         # 3 months
    "1H":  60,         # 2 months
    "30M": 30,         # 1 month
    "15M": 21,         # 3 weeks
}

# TF display order (matches the dashboard table in the Pine script)
TF_ORDER = ["Q", "M", "W", "D", "4H", "1H", "30M", "15M"]


@dataclass
class TFLevels:
    """Computed levels + trend for a single timeframe."""
    tf: str
    direction: str          # "UP" | "DOWN" | "SIDE"
    adx: float
    atr: float
    s1: Optional[float] = None
    s2: Optional[float] = None
    d1: Optional[float] = None
    d2: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# Indicators — Wilder smoothing matches Pine ta.dmi / ta.atr / ta.rma
# ============================================================================

def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (a.k.a. RMA, Pine's ta.rma).

    Seed = SMA of the first `period` values. After that:
      rma[i] = (rma[i-1] * (period - 1) + value[i]) / period
    """
    n = len(series)
    out = [float("nan")] * n
    if n < period:
        return pd.Series(out, index=series.index)

    seed = series.iloc[:period].mean()
    out[period - 1] = seed

    for i in range(period, n):
        prev = out[i - 1]
        val = series.iloc[i]
        if math.isnan(val):
            out[i] = prev
        else:
            out[i] = (prev * (period - 1) + val) / period

    return pd.Series(out, index=series.index)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    pc = close.shift(1)
    return pd.concat([
        (high - low),
        (high - pc).abs(),
        (low - pc).abs(),
    ], axis=1).max(axis=1)


def compute_dmi_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return DI+, DI-, ADX series (Wilder-smoothed)."""
    tr = _true_range(high, low, close)

    up = high.diff()
    down = -low.diff()

    dm_plus = pd.Series(0.0, index=high.index)
    dm_minus = pd.Series(0.0, index=high.index)
    dm_plus[(up > down) & (up > 0)] = up[(up > down) & (up > 0)]
    dm_minus[(down > up) & (down > 0)] = down[(down > up) & (down > 0)]

    tr_s = _wilder_rma(tr, period)
    dmp_s = _wilder_rma(dm_plus, period)
    dmm_s = _wilder_rma(dm_minus, period)

    di_plus = 100 * dmp_s / tr_s.replace(0, float("nan"))
    di_minus = 100 * dmm_s / tr_s.replace(0, float("nan"))

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, float("nan"))
    adx = _wilder_rma(dx, period)
    return di_plus, di_minus, adx


def compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14,
) -> pd.Series:
    return _wilder_rma(_true_range(high, low, close), period)


# ============================================================================
# Core level-finding algorithm — matches Pine findAll() exactly
# ============================================================================

def compute_levels(
    df: pd.DataFrame, lookback: int, adx_period: int = 14,
) -> TFLevels:
    """Find untouched supply/demand + ADX trend for the LAST row in df.

    df: DataFrame with columns 'high', 'low', 'close' (case-sensitive),
        sorted oldest → newest. The last row is the "current bar".

    Algorithm (mirror of pinescripts/htf_strategy.pine findAll):
      Supply: maxH = current bar's high. Walk i=1..lookback; candidate
              must satisfy high[i] > maxH AND high[i] > close. First two
              qualifying peaks become S1 / S2. No fallback — sup1 stays
              None when no past peak exceeds the current bar's high.
      Demand: minL = low[-1] (include current bar). Walk i=1..lookback;
              candidate must satisfy low[i] < minL. First two become D1/D2.
              Falls back to current bar's low if no past trough.
      Post-find: any supply at or below close → None (matches the Pine
                  defensive line that drops fake "supply at price").
    """
    n = len(df)
    blank = TFLevels(tf="", direction="SIDE", adx=float("nan"), atr=float("nan"))
    if n < 2:
        return blank

    di_plus, di_minus, adx_series = compute_dmi_adx(
        df["high"], df["low"], df["close"], period=adx_period,
    )
    atr_series = compute_atr(df["high"], df["low"], df["close"], period=14)

    dp = di_plus.iloc[-1]
    dm = di_minus.iloc[-1]
    if pd.isna(dp) or pd.isna(dm):
        direction = "SIDE"
    elif dp > dm + 2:
        direction = "UP"
    elif dp < dm - 2:
        direction = "DOWN"
    else:
        direction = "SIDE"

    adx_val = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else float("nan")
    atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else float("nan")
    close_now = float(df["close"].iloc[-1])

    # ─── Supply scan — seed maxH at the in-progress bar's high so the
    # immediately-preceding bar can qualify as S1. The "high[i] > close"
    # filter + no fallback keep a bullish bar at new highs from showing
    # its own high as supply.
    max_h = float(df["high"].iloc[-1])
    sup1: Optional[float] = None
    sup2: Optional[float] = None
    for i in range(1, lookback + 1):
        idx = n - 1 - i
        if idx < 0:
            break
        h_i = float(df["high"].iloc[idx])
        if h_i > max_h and h_i > close_now:
            if sup1 is None:
                sup1 = h_i
            elif sup2 is None:
                sup2 = h_i
        max_h = max(max_h, h_i)

    # ─── Demand scan (includes in-progress bar) ───
    min_l = float(df["low"].iloc[-1])
    dem1: Optional[float] = None
    dem2: Optional[float] = None
    for i in range(1, lookback + 1):
        idx = n - 1 - i
        if idx < 0:
            break
        l_i = float(df["low"].iloc[idx])
        if l_i < min_l:
            if dem1 is None:
                dem1 = l_i
            elif dem2 is None:
                dem2 = l_i
        min_l = min(min_l, l_i)

    if dem1 is None:
        dem1 = float(df["low"].iloc[-1])

    # Post-find: drop supply at or below close (Pine defensive line)
    if sup1 is not None and sup1 <= close_now:
        sup1 = None
    if sup2 is not None and sup2 <= close_now:
        sup2 = None

    return TFLevels(
        tf="",
        direction=direction,
        adx=adx_val,
        atr=atr_val,
        s1=sup1, s2=sup2,
        d1=dem1, d2=dem2,
    )


# ============================================================================
# Polygon convenience wrapper (optional; only used by the CLI)
# ============================================================================

def _fetch_polygon_aggs(
    ticker: str, multiplier: str, timespan: str, days_back: int, api_key: str,
) -> pd.DataFrame:
    """Pull OHLC bars from Polygon /v2/aggs, returned oldest → newest."""
    import requests  # imported here so the core module has no hard dep

    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}"
        f"/range/{multiplier}/{timespan}/{start}/{end}"
    )
    params = {
        "apiKey": api_key,
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return pd.DataFrame(columns=["high", "low", "close"])

    df = pd.DataFrame(results).rename(
        columns={"h": "high", "l": "low", "c": "close", "o": "open", "v": "volume", "t": "ts"},
    )
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("ts").sort_index()[["high", "low", "close"]]


def fetch_and_compute(
    ticker: str, api_key: Optional[str] = None, adx_period: int = 14,
) -> dict[str, TFLevels]:
    """Fetch all 8 TFs from Polygon and run compute_levels on each.

    Ticker prefixes:
      stocks:  no prefix  (e.g. "SPY", "AAPL")
      indices: "I:"       (e.g. "I:SPX", "I:NDX")
      forex:   "C:"       (e.g. "C:EURUSD")
    """
    api_key = (
        api_key
        or os.environ.get("POLYGON_API_KEY")
        or os.environ.get("MASSIVE_API_KEY")
    )
    if not api_key:
        raise RuntimeError(
            "No Polygon API key — set POLYGON_API_KEY or MASSIVE_API_KEY, "
            "or pass api_key=...",
        )

    results: dict[str, TFLevels] = {}
    for tf in TF_ORDER:
        multiplier, timespan = POLYGON_AGG[tf]
        df = _fetch_polygon_aggs(
            ticker, multiplier, timespan, POLYGON_DAYS_BACK[tf], api_key,
        )
        if df.empty or len(df) < 2:
            results[tf] = TFLevels(tf=tf, direction="SIDE", adx=float("nan"), atr=float("nan"))
            continue
        lvls = compute_levels(df, TF_LOOKBACK[tf], adx_period=adx_period)
        lvls.tf = tf
        results[tf] = lvls
    return results


# ============================================================================
# CLI
# ============================================================================

def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.2f}"


def _print_table(results: dict[str, TFLevels], ticker: str) -> None:
    print(f"\nHTF Levels — {ticker}")
    print("=" * 72)
    hdr = f"{'TF':<5} {'Trend':<6} {'ADX':>5}  {'S1':>10} {'S2':>10}  {'D1':>10} {'D2':>10}"
    print(hdr)
    print("-" * 72)
    for tf in TF_ORDER:
        lvl = results.get(tf)
        if lvl is None:
            continue
        adx_str = f"{lvl.adx:.0f}" if not math.isnan(lvl.adx) else "—"
        print(
            f"{tf:<5} {lvl.direction:<6} {adx_str:>5}  "
            f"{_fmt(lvl.s1):>10} {_fmt(lvl.s2):>10}  "
            f"{_fmt(lvl.d1):>10} {_fmt(lvl.d2):>10}"
        )
    print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute HTF supply/demand levels via Polygon.",
    )
    parser.add_argument(
        "ticker",
        help="Polygon ticker. Stocks: SPY/AAPL. Indices: I:SPX/I:NDX. Forex: C:EURUSD",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of a table")
    parser.add_argument(
        "--api-key",
        help="Polygon API key (otherwise reads POLYGON_API_KEY / MASSIVE_API_KEY env var)",
    )
    args = parser.parse_args(argv)

    try:
        results = fetch_and_compute(args.ticker.upper(), api_key=args.api_key)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({tf: lvl.to_dict() for tf, lvl in results.items()}, indent=2))
    else:
        _print_table(results, args.ticker.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
