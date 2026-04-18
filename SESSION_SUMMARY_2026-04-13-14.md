# LumiSignals — Session Summary (April 13-14, 2026)

## Multi-Model Concurrent Trading System

### Architecture

Built three independent trading models running simultaneously on the same 27 forex pairs:

| Model    | Trigger TF | Zone TFs (SNR) | Bias TF       | Risk % |
|----------|-----------|-----------------|---------------|--------|
| Scalp    | 15m       | 1h + 4h         | 4h trend      | 0.25%  |
| Intraday | 1h        | 4h + Daily      | Daily trend   | 0.5%   |
| Swing    | Daily     | Weekly + Monthly | Monthly trend | 1.0%   |

- `ModelConfig` dataclass defines each model's parameters
- Single `LevelsStrategy` class accepts any `ModelConfig` — no duplicate code
- All three share the same Oanda/Massive connections
- Bot runner spins up all 3 per user in a unified 30-second loop
- Per-model watchlists stored in Redis (`watchlist:user_id:scalp`, etc.)

### Files Changed

- `lumisignals/levels_strategy.py` — Refactored to dynamic `zone_tfs`, `bias_candle_tfs`, `trigger_tf` from ModelConfig instead of hardcoded monthly/weekly/daily
- `saas/bot_runner.py` — Creates 3 strategy instances per user, unified run loop, per-model signal handlers with model-specific risk %
- `saas/app.py` — API returns per-model watchlists, new `/watchlist` route

---

## Dashboard Restructure

### Navigation

Split into separate pages: **Dashboard | Watchlist | Trades | Settings | Log out**

### Watchlist Page (`/watchlist`)

- Three sections: Scalp Zones, Intraday Zones, Swing Zones
- Each section has tabs: All | Currencies | Stocks | Crypto
- Tabs always visible (even when a category has 0 zones)
- Stocks only appear in Swing model (scalp/intraday are forex-only)

### Trades Page (`/trades`)

- **Open Trades Stats:** Open count, Unrealized P&L, Open Pips, Pot. Profit, Pot. Loss, Avg R:R
- **Open Trades Table:** Pair (with FX/STOCK/CRYPTO badge), Dir, Entry, Current, SL (with $), TP (with $), R:R, Pips, P&L, Model badge (SCALP/INTRADAY/SWING), Signal details (trigger pattern, zone info, score)
- **Closed Trades Stats:** Closed count, Win Rate, Realized P&L, Total Pips, Avg Win, Avg Loss
- **Closed Trades Table:** Same enrichment with model/signal columns

### Templates Updated

- `saas/templates/watchlist.html` — New file, watchlist-only content
- `saas/templates/trades.html` — Rewritten, trades-only content
- `saas/templates/dashboard.html` — Updated nav
- `saas/templates/setup.html` — Updated nav

---

## Stock Candle Alignment (Massive/Polygon)

### Problem

Massive API returns candles that don't match TradingView:
- Weekly starts Sunday (TV starts Monday)
- Monthly doesn't align with calendar months
- Daily `count=500` returned stale data

### Solution

- **Weekly:** `_get_monday_weekly_candles()` — aggregates daily bars by ISO week (Monday start)
- **Monthly:** `_get_calendar_monthly_candles()` — aggregates daily bars by `(year, month)`
- **Daily:** Reduced count to 30 (keeps date range recent), labels use date format (`Apr 09`) not `Xd ago`
- **Routing:** `get_candles()` intercepts `1w`/`1mo` for stocks and builds from daily data

---

## JPY Position Sizing Fix

### Problem

JPY pairs getting ~1,000-3,000 units while non-JPY pairs got 67,000-100,000. Formula `units = risk_amount / stop_distance` didn't normalize for pip value difference (JPY pip = 0.01 vs non-JPY pip = 0.0001).

### Fix

Updated `calculate_position_size()` in `order_manager.py`:
1. Convert stop distance to pips: `stop_pips = stop_distance / pip_value`
2. Calculate pip cost per unit based on pair type (XXX_USD, USD_XXX, cross)
3. `units = risk_amount / (stop_pips * pip_cost_per_unit)`

**Result:** EUR_USD 48,499 units vs USD_JPY 51,410 units (proportional — was 100,000 vs 1,347)

---

## Signal Log / Trade Enrichment Fix

### Problem

Signal log keyed by `scalp_GBPNZD_1776138327` but trade tracker looks up by Oanda order ID (`16678`). Never matched.

### Fix

When order is placed successfully, also record the signal under the Oanda order ID AND `order_id + 1` (Oanda fill creates the next sequential ID). New trades will show model badge, trigger pattern, zone info, and score in the Trades page.

---

## Crypto Watchlist Expansion

Added 8 more crypto tickers: DOGE, ADA, AVAX, DOT, LINK, MATIC, LTC, UNI

**Total:** 12 crypto (was 4) + 108 stocks + 27 forex = 147 instruments

---

## Commits

- `2d80927` — Multi-model concurrent trading: scalp (15m) + intraday (1h) + swing (daily)
- `2d3d635` — JPY position sizing, dashboard restructure, crypto expansion, signal enrichment
