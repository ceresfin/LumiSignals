# Lumi — MTF Trade Setups + Scanner (handoff bundle)

Self-contained subset of the LumiSignals codebase for the **multiple-timeframe
(MTF) trade setups** and the **700-ticker scanner**. Levels are produced by a
Python port of a TradingView Pine script and have been validated bar-for-bar
against TradingView (stocks: exact; crypto: exact on Monthly/Quarterly).

**Scope:** levels, multi-timeframe direction, the trade setups, and the
scanner. **Options / implied-volatility are out of scope** and intentionally
not included (no Schwab client). `swing_setup` still returns the shares plan,
levels, and direction; its options spec just comes back empty.

## Install

```bash
pip install requests numpy
```

Python 3.10+. (`TA-Lib` is optional — `candle_classifier` falls back to a
built-in classifier if it's absent; you'll see a one-line notice, not an error.)

## Environment variables

| Var | Required for | Notes |
|-----|--------------|-------|
| `MASSIVE_API_KEY` | everything | Massive/Polygon REST key (Polygon-compatible API at api.polygon.io). |
| `COMPARE_API_BASE` | optional | Only for the scanner's `--verify` mode (diffs against a live compare endpoint). Leave unset otherwise. |

## What's here

| File | Job |
|------|-----|
| `lumisignals/untouched_levels.py` | The level algorithm — `find_htf_levels()` finds untouched supply/demand (S1/S2/D1/D2). Pure stdlib. |
| `lumisignals/massive_client.py` | Pulls OHLC bars from Massive/Polygon and aggregates them per asset class (stock RTH, FX 5pm-ET session, crypto UTC-day, index `I:` prefix). |
| `lumisignals/candle_classifier.py` | The `CandleData` container the others use. |
| `lumisignals/swing_setup.py` | The **trade setups** — for one ticker + mode (`scalp`/`intraday`/`swing`) builds direction, trigger, entry/stop/target, and a shares plan. (Options vehicle is out of scope; that path returns empty.) |
| `scripts/bench_mtf_scan.py` | The **scanner** + benchmark + a TradingView verify mode. |

## Run the scanner

From the bundle root:

```bash
export MASSIVE_API_KEY=...   # your Massive/Polygon key

# Actionable shortlist: which of the top-700 liquid stocks are sitting at an
# untouched Daily/Weekly/Monthly level right now (with direction LONG/SHORT).
python3 scripts/bench_mtf_scan.py --scan --universe 700 --years 2 --near 0.004

# Speed/throughput benchmark (swing tier + intraday tier).
python3 scripts/bench_mtf_scan.py --universe 700 --years 2

# Validate levels vs TradingView for specific tickers.
python3 scripts/bench_mtf_scan.py --verify SPY,QQQ,NVDA --market stocks --years 6
python3 scripts/bench_mtf_scan.py --verify BTCUSD     --market crypto --years 6
```

## How it fits together

```
swing_setup.compute_setup(ticker, mode)         # one ticker, full setup
  ├── massive_client.get_candles(...)           #   bars per timeframe
  │     └── candle_classifier.CandleData         #     container
  └── untouched_levels.find_htf_levels(...)      #   the S/D levels

bench_mtf_scan.py  --scan                        # 700 tickers, fast
  ├── grouped-daily store (one call/day → all tickers' daily bars)
  └── untouched_levels.find_htf_levels(...)      #   D/W/M levels, local
```

## Notes left in the code

- A placeholder was inserted for the handoff: the scanner's compare URL
  (`COMPARE_API_BASE`, default `https://your-domain.example`). Only matters
  for `--verify`.
- `massive_client` uses `requests.Session` with the default pool (maxsize 10) —
  bump `HTTPAdapter(pool_maxsize=~32)` for concurrent scans.
- `massive_client.get_candles` re-fetches 5m bars per intraday TF; pull 5m once
  and derive 1h/4h locally to cut calls.
