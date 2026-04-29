# LumiSignals — Session Summary (April 17-22, 2026)

## What Was Built

### Options Auto-Trading Pipeline (End-to-End)
Full automated options trading: signal detection → spread analysis → position sizing → order placement → monitoring → auto-close.

**Flow:**
1. Bot detects stock at S/R zone (weekly/monthly for swing, 4h/daily for intraday, 1h/4h for scalp)
2. Trigger candle confirms on the model's timeframe
3. Polygon API analyzes credit + debit spreads (1-2 seconds)
4. Position sizing calculates contracts (max risk, max contracts, min credit %)
5. Order queued in Redis → sync script places on IB Gateway
6. Monitor checks every 30 seconds for TP/SL/time stop → auto-closes

**First automated profits:** CMCSA +$55, HD +$363 (auto-closed at 75% TP)

### Options Exit Monitoring
- Credit TP: close when X% of credit captured (default 50%)
- Credit SL: close when loss = X% of credit (default 100% = 2x)
- Debit TP: close when X% gain (default 75%)
- Debit SL: close when X% loss (default 50%)
- Time stop: close all spreads at X DTE (default 7 days)
- Settings in card 6 on Settings page

### Multi-Model Options Trading
All 3 models now trade options on stocks:
| Model | Zones | Trigger | Options DTE |
|-------|-------|---------|-------------|
| Scalp | 1h + 4h | 15m | 7-14 days |
| Intraday | 4h + Daily | 1h | 14-30 days |
| Swing | Weekly + Monthly | Daily/4h | 25-40 days |

### Spread Width Auto-Adjust
Bot tries preferred width ($5) first, falls back to $2.50 then $1 if risk per contract exceeds max risk per spread ($500).

### Interactive Brokers Integration
- IB Gateway connection via ib_insync
- Paper trading account ($100K)
- Combo (BAG) orders for credit/debit spreads
- Credit spreads use negative limit price
- permId tracking through full lifecycle
- Sync runs server-side as the `lumisignals-sync` systemd service

### Trades Page Restructure
- Tab toggle: Forex (Oanda) | Options (IB)
- Pending Options Orders with full metadata
- Open Spreads with real-time P&L (from ib.portfolio())
- Closed Options Trades with realized P&L, close reason, WIN/LOSS
- All tables show: Ticker, Type, Strikes, Exp, Qty, Premium, Max Profit, Max Risk, R:R, Model, Signal

### Other Features Built
- **Email alerts** via Gmail SMTP for signals, trades, budget limits, auto-closes
- **Dashboard connection status** — Oanda, Schwab, Polygon, IB Gateway with Schwab token expiry warning
- **Per-model strategy settings** — min score, min R:R, ATR multiplier per model (scalp/intraday/swing)
- **Separate dry-run toggles** for forex and stocks/options
- **Schwab + Polygon side-by-side** options analysis on watchlist
- **Strategy Guide page** — 10-section documentation of full trading logic, dynamically pulls user settings
- **Active tickers sorted to top** of watchlist
- **Trade duration/timestamps** on open and closed trades
- **Instrument + price + SL fallback** for trade enrichment when Oanda IDs don't match
- **Signal log fallback** for spread metadata when stored order details missing
- **80 indices data client** — equity, volatility, options strategy benchmarks, commodities
- **API keys in Settings** — LumiTrade, Massive/Polygon, Schwab
- **Auto-cleanup** of cancelled/failed orders after 24 hours
- **Deploy script** preserves systemd service and nginx SSL configs
- **Bot runner as systemd service** (auto-restart on crash/reboot)

---

## Architecture

### Server (Digital Ocean Droplet)
- **Web app** (gunicorn) — dashboard, API endpoints, settings
- **Bot runner** (systemd) — 4 models scanning forex + stocks, auto-trade options
- **Redis** — watchlist zones, order queue, IB data, closed trades
- **PostgreSQL** — user settings, credentials

### Server (also)
- **IB Gateway** — Docker container `ib-gateway` (image `ghcr.io/gnzsnz/ib-gateway`), port 4002 (TWS API), port 5900 (VNC)
- **noVNC** — Docker container `ib-novnc`, accessible at `bot.lumitrade.ai/ib-vnc/` for browser-based IB re-auth
- **Sync** — `lumisignals-sync.service`, talks to local Docker IB Gateway, places orders, monitors spreads, pushes MES bars

### Mac dependency
- None for runtime. IB session re-authentication (~24h cycle) is done via the noVNC browser URL above from any device.

### Data Flow
```
Bot Runner (server) → queues order in Redis
  ↓
Sync Script (local) → fetches from /api/ibkr/orders/pending
  ↓
IB Gateway (local) → places combo order
  ↓
Sync Script → pushes position/P&L data to /api/ibkr/sync
  ↓
Trades Page → displays pending, open, closed trades
```

---

## Settings Overview (Settings Page)

1. **Broker Connection** — Oanda credentials
2. **API Keys** — LumiTrade, Polygon, Schwab
3. **Strategy Settings** — per-model min score, min R:R, ATR multiplier, dry-run toggles
4. **Position Sizing & Risk** — per-model risk mode (% or $), daily budgets
5. **Options Auto-Trading & Position Sizing** — auto-trade toggle, spread type pref, trigger TF, min verdict, max risk/contracts/spreads, spread width, min credit %
6. **Options Exit Rules** — credit TP/SL %, debit TP/SL %, time stop DTE

---

## Known Issues / Next Priorities

### Critical
1. **Order deduplication** — bot places duplicate orders for same stock on each scan cycle (VZ hit 15+ orders). Need to track which tickers already have open orders/positions and skip.
2. **Single legs from partial closes** — monitor's market close orders sometimes fill one leg but not the other, leaving orphaned positions.

### Important
3. ~~Sync script dependency~~ — RESOLVED. IB Gateway runs in Docker on the server; sync runs as `lumisignals-sync` systemd service. Mac is no longer required.
4. **SNR API rate limiting** — 429 errors when scanning 120 stocks + 27 forex × 3 models. Need throttling or caching.
5. **Schwab token expiry** — 7-day refresh cycle, requires manual re-auth via browser.

### Nice to Have
6. **Gap strategy** — second strategy type alongside HTF Levels
7. **VIX-based entry timing** — use VIX regime to filter signals
8. **Performance tracking** — daily P&L chart, win rate over time
9. **Multi-user** — encrypted API keys, admin dashboard, Stripe billing
10. **Commodity trade setups** — run S/R analysis on indices

---

## Key Files Modified

| File | Purpose |
|------|---------|
| `saas/app.py` | Routes, API endpoints, User model |
| `saas/bot_runner.py` | Signal handling, options auto-trade, alerts |
| `saas/templates/trades.html` | FX + Options trades with tabs |
| `saas/templates/watchlist.html` | Analyze button, spread display |
| `saas/templates/setup.html` | All settings cards |
| `saas/templates/strategy.html` | Strategy Guide page |
| `saas/templates/dashboard.html` | Connection status, account balance |
| `lumisignals/ibkr_client.py` | IB Gateway client, position sizing |
| `lumisignals/ibkr_sync.py` | Sync script, spread monitoring, order placement |
| `lumisignals/ibkr_analyzer.py` | IB-based options analysis |
| `lumisignals/polygon_options.py` | Polygon-based options analysis |
| `lumisignals/options_sizing.py` | Spread contract calculation |
| `lumisignals/alerts.py` | Email alerts via Gmail SMTP |
| `lumisignals/risk_budget.py` | Daily loss tracking via Redis |
| `lumisignals/indices_data.py` | 80 indices from Polygon |
| `lumisignals/trade_tracker.py` | Trade enrichment, P&L calculation |
| `lumisignals/levels_strategy.py` | Zone scanning, trigger detection |
| `lumisignals/order_manager.py` | Forex position sizing, order execution |

---

## Database Columns Added

### Per-model strategy
`scalp_min_score`, `scalp_min_rr`, `scalp_atr_multiplier` (same for intraday/swing)
`dry_run_stocks`

### Per-model risk
`scalp_risk_mode`, `scalp_risk_value`, `scalp_daily_budget` (same for intraday/swing)

### Options
`options_max_risk_per_spread`, `options_max_contracts`, `options_max_total_risk`, `options_spread_width`, `options_min_credit_pct`, `options_max_spreads`, `options_auto_trade`, `options_auto_spread_type`, `options_trigger_tf`, `options_min_verdict`

### Options exits
`credit_tp_pct`, `credit_sl_pct`, `debit_tp_pct`, `debit_sl_pct`, `options_time_stop_dte`

### API keys
`lumitrade_api_key`, `massive_api_key` (schwab_client_id/secret already existed)

---

## Server Management

```bash
# SSH
ssh root@174.138.46.187

# Services
systemctl status lumisignals        # web app
systemctl status lumisignals-bot    # bot runner
systemctl restart lumisignals-bot   # restart bot

# Deploy from Mac
cd /Users/sonia/Documents/LumiTrade/LumiSignals
bash saas/deploy.sh

# Database
ssh root@174.138.46.187 "sudo -u postgres psql -d lumisignals_db"

# Logs
ssh root@174.138.46.187 "tail -50 /var/log/lumisignals_bot.log"
journalctl -u lumisignals -f       # web app logs

# IB Sync (server-side systemd, no manual start needed)
ssh root@174.138.46.187 "systemctl status lumisignals-sync"
ssh root@174.138.46.187 "systemctl restart lumisignals-sync"
ssh root@174.138.46.187 "journalctl -u lumisignals-sync -f"

# IB Gateway re-auth (when session expires ~24h)
# Open in any browser: https://bot.lumitrade.ai/ib-vnc/vnc_lite.html
```

---

## Commits (April 17-22)
```
09ed236 Enrich IB orders with stored order pricing
e3526f5 Signal log fallback for order/spread enrichment
cb88bee Fix field name mismatches for pending/open/closed options
495ca95 Enrich IB sync orders with stored metadata
db2d51d Fix fmtTime to handle space-separated ISO timestamps
9c4de6a Show 'Submitted' instead of 'PreSubmitted'
25a993a Add Strategy Guide page
51848d7 Fix time format in closed trades
2ffee22 Track spreads by permId through full lifecycle
8290280 Reconstruct max profit/risk from width + entry cost
6d3ad88 Add Max Profit, Max Risk, R:R to Closed Options Trades
049cc83 Fix spread pairing, add closed trades section
99bcf5c Enable options auto-trading on scalp, intraday, and swing
92ac5dd Auto-adjust spread width to fit max risk
d4b7144 Options exit monitoring: auto-close spreads at TP/SL/time stop
7dd1ab7 Sort watchlist: ACTIVE tickers first
ec22e4d Add opened date/duration to Open Spreads
6de56c2 Add real-time P&L to Open Spreads
c996a9b Use random clientId for sync script
919a288 Store order details on placement
5622ea1 Fix spread type detection
51c022e Restructure Trades page: FX and Options sections
... and 30+ more commits
```
