# Dashboard Swing-Trade Panel

**Branch:** `dashboard-swing-panel` (off `main`, isolated from `orb-debug`)
**Status:** Shipped to prod, mobile feature-flagged, equity-order flag still off
**Last verified:** 2026-06-01

## What it does

New panel at the bottom of the mobile Dashboard. User picks a symbol,
mode (SCALP/INTRADAY/SWING), and vehicle (Options/Shares). Backend
analyzes higher-TF trend + finds a counter-move pullback, then
proposes an options debit spread (30-delta long, ~10–15 wide) or a
shares plan sized to the user's `max_risk_usd`. Includes a live chart
overlaid with the trade-specific lines and P&L zones.

## Architecture

```
Mobile (Expo)                  Backend (Flask)             Data
─────────────                  ──────────────              ────
SwingTradePanel  ─── GET ───>  /api/swing-setup    ──>     Polygon (Massive)
                                  └─> swing_setup.py        bars: 5m..1mo
                                       └─> Pine ADX dir     Schwab /chains
                                       └─> trigger zone     bid/ask + delta
                                       └─> 30-delta picker
                                       └─> Shares ATR stop

Open Trade  ──── POST ──>      /api/option-spread/order
                                  └─> CPAPI.build_combo_order
                                  └─> gated on equity:orders_enabled

Chart WebView  ─── GET ─>      /chart (mobile_chart.html)
                                  + long_strike/short_strike/breakeven
                                  + max_profit/max_loss/spread_type
                                  + trigger_level/direction
```

## Files

| File | Role |
|---|---|
| `lumisignals/swing_setup.py` | Setup analyzer (Pine ADX, trigger zone, spread/shares picker) |
| `lumisignals/ibkr_cpapi.py` | `build_stock_order` + `build_stock_bracket` + cherry-picked `build_combo_order` |
| `lumisignals/massive_client.py` | Trading-day-aware lookback for minute bars (fixed weekend gap) |
| `lumisignals/diary.py` | Added `swing_setup` to `STRATEGY_SLUG` |
| `saas/app.py` | Three new routes: `/api/swing-setup`, `/api/option-spread/order`, `/api/option-spread/close`; `/api/candles` handles `I:SPX/I:NDX` etc. |
| `saas/templates/mobile_chart.html` | `swing_setup` overlay: LONG/SHORT/BE/TRIGGER lines, P&L bands sized to $ ratio |
| `mobile/components/swing-trade-panel.tsx` | The panel UI |
| `mobile/app/(tabs)/index.tsx` | One-line mount of the panel |
| `docs/trend-direction-implementations.md` | Audit of the 4 ADX impls + fix-later plan |

## Endpoints

- **GET `/api/swing-setup?ticker=&mode=`** — no auth, 60s Redis cache. Returns full setup dict (direction, trends, options block, shares block).
- **POST `/api/option-spread/order`** — `X-Sync-Key` header, gated on Redis `equity:orders_enabled=1`.
- **POST `/api/option-spread/close`** — `X-Sync-Key` header.
- **GET `/chart?strategy=swing_setup&...`** — extends `mobile_chart.html` with trade-aware overlays.

## Mobile UI (top → bottom)

1. **Symbol picker** — two horizontally-scrollable rows. INDEXES (SPY/QQQ/IWM/SPX/NDX) + STOCKS (AAPL/AMD/AMZN/AVGO/GOOG/JPM/LLY/META/MSFT/MU/NFLX/NVDA/TSLA/WMT/XOM).
2. **Vehicle toggle** — Options / Shares.
3. **Mode segmented** — SCALP / INTRADAY / SWING.
4. **TF circles** — mode-aware (Russian dolls): SCALP→5M/15M/1H, INTRADAY→15M/1H/Daily, SWING→Daily/Weekly/Monthly. Chart display only; doesn't trigger recompute.
5. **Status banner** — green "TRADE READY" or amber "NO TRADE" with reason.
6. **Symbol header** — ticker + LONG/SHORT badge + Max Risk.
7. **TRADE PARAMETERS** — 2×2 grid: Direction / Duration / Momentum / Shares-or-Contracts.
8. **SPREAD** (options only) — strikes / width / DTE / breakeven / expiry.
9. **RETURN / RISK** — side-by-side cards.
10. **RETURN-TO-RISK RATIO** — big number + green/red bar.
11. **TRENDS** — mode-aware higher-TF stack with ▲ UP / ▼ DOWN per TF.
12. **ADJUST** (disabled, v2 placeholder).
13. **Open Trade / Close** buttons.
14. **CHART** — WebView. (i) info button explains markers.

## Chart overlay (when `strategy=swing_setup`)

- **LONG strike** — solid 3px amber line, label `LONG <K> · -$<max_loss>`
- **SHORT strike** — solid 3px teal (calls) / red (puts), label `SHORT <K> · +$<max_profit>`
- **BE** — dashed 2px yellow, label `BE <breakeven>`
- **TRIGGER** — dotted 1px magenta, label `TRIGGER <level>`
- **Profit ramp band** — light green between BE and SHORT (where P&L grows linearly)
- **Max profit band** — bright green past SHORT, sized by `MAX_PROFIT × scale`
- **Max loss band** — red past LONG, sized by `MAX_LOSS × scale`
- **R:R proportionality** — `scale` = `(35% × candle_range) / max($profit, $loss)`. The green band is taller than the red by the exact reward:risk ratio.
- **S/R clutter suppressed** — the W/D/H zone lines from `/api/levels` are filtered out when `IS_SWING_SETUP`.
- **DASHBOARD overlay + contractBadge pill hidden** via `dashboard=0` URL flag.

## Trend direction logic

Uses Pine `ta.dmi(14, 14)` with proper Wilder RMA + ±2 buffer. Direction from `+DI > -DI + buffer` → UP / `-DI > +DI + buffer` → DOWN / else NEUTRAL. Top+Mid TFs vote for bias direction (M+W weighted), bottom TF must be counter-moving to trigger an entry (pullback into the zone).

See `docs/trend-direction-implementations.md` — there's a separate
`calculate_adx_direction` in `untouched_levels.py` with a Wilder bug
that inflates the strength reading ~14×. Direction is correct; only
strength is broken. Marked for cleanup as task #104.

## Feature flags

| Flag | Where | Default | Purpose |
|---|---|---|---|
| `EXPO_PUBLIC_SWING_PANEL_ENABLED` | mobile `.env` | `1` (on droplet) | Panel renders only when set |
| `equity:orders_enabled` | Redis | unset → 503 | Backend gate on Open Trade |

## Bug fixes shipped (mid-stream)

- Polygon `I:` prefix needed for `SPX/NDX/RUT/VIX/DJI` (no bars without it).
- Pine ADX: replaced raw recurrence formula with proper `ta.rma` to match TradingView.
- Mobile temporal-dead-zone: `opt` referenced before `const` declaration in `chartUrl` useMemo — fixed by re-ordering.
- DASHBOARD overlay + green `SPX 4517:46` contract badge blocking the chart — added `dashboard=0` URL flag.
- TF circles: were labeled hourly/daily/weekly always; made mode-aware (Russian-doll stack).
- P&L bands: had arbitrary 5% width hard floor; now sized proportionally to `$max_profit/$max_loss` so the visual ratio matches the headline R:R.
- Minute bars on weekends: 5m/15m for stocks used wall-clock lookback (`count×multiplier×1.5` minutes) — returned zero bars on Monday morning. Switched to trading-day-aware calendar lookback.

## Verification status

- ✅ Backend `compute_setup()` returns sane dicts for all 20 tickers (smoke-tested NVDA, XOM, IWM, SPY).
- ✅ Chart renders P&L bands at correct proportions for a 5.54:1 IWM intraday setup.
- ✅ Mobile panel renders on the device, 20 chips scrollable, mode-aware TF circles work.
- ✅ 5m bars now load for SCALP mode after weekend lookback fix.
- ⏳ Live order placement (paper account) — pending; gated on `equity:orders_enabled=1` flip.
- ⏳ Live order placement on production account — pending verified paper smoke.

## What's NOT done

| Task # | Description |
|---|---|
| #102 | Live verification + equity flag-on (production) |
| #103 | SPX/NDX index option support (mostly subsumed — single-leg options already work; 4-leg butterflies stay in ORB) |
| #104 | Unify trend-direction impls (Wilder bug in `calculate_adx_direction`) |
| — | IV display on each ticker chip (deferred) |
| — | Search box for tickers beyond the curated 20 (deferred) |
| — | ADJUST functionality (manual stop/target override) |

## Branches in play

```
main                          ← 2n20 stable (tagged 2n20-stable-2026-05-29)
├── orb-debug                 ← ORB butterfly work (Tuesday smoke pending)
└── dashboard-swing-panel     ← THIS WORK (16+ commits ahead of main)
```

Merge to `main` after equity-order live verification.
