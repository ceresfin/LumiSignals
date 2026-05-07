# LumiSignals Trading Strategies

## Strategy 1: 2n20 VWAP Overwhelm Scalp

**ID:** `vwap_2n20`, `scalp_2n20`, `2n20`
**Instruments:** EUR_USD, USD_JPY (active); all USD majors (available)
**Execution:** Oanda (FX), IB (MES futures via TradingView webhook)
**Candle:** 2-minute

### Entry Logic
Both conditions must be true simultaneously:
1. **VWAP Bias:** Price above VWAP → BUY only. Price below VWAP → SELL only.
2. **Overwhelm:** Current candle body > most recent opposite candle body (3-bar lookback), AND close beyond opposite candle's open, AND body ≥ 30% of range, AND body ≥ 80% of 10-bar avg body.

### Exit Logic (any one triggers)
- Opposite overwhelm (red overwhelm exits long, green exits short)
- VWAP cross (price crosses to other side of VWAP)
- Friday 4:50 PM ET flatten (FX only)

### VWAP Anchor (per-pair)
| Pair | Anchor | Rationale |
|------|--------|-----------|
| USD_JPY | 7 PM ET | Tokyo open |
| EUR_USD | 3 AM ET | London open |
| Default | 6 PM ET | Standard forex session |

### Trading Window (entries only, exits always fire)
| Pair | Hours (ET) | Skip |
|------|-----------|------|
| USD_JPY | 7PM–midnight, midnight–noon | Noon–7PM dead zone |
| EUR_USD | 3AM–2PM | 2PM–3AM (quiet Asian hours) |

### Risk
- Stop loss: Fixed $25 per trade
- Position sizing: $25 ÷ (stop_pips × pip_cost)

### Chart Display
- **VWAP** line (orange)
- **Entry** line (green=long, red=short, solid)
- **Stop Loss** line (red, dotted)
- **Exit** line (orange, solid) — closed trades only
- NO HTF S/R levels

---

## Strategy 2: Opening Range Breakout (ORB)

**ID:** `orb_breakout`
**Instruments:** MES (Micro E-mini S&P 500)
**Execution:** IB via TradingView webhook
**Candle:** 1-minute (detection), displayed on 15-minute chart

### Opening Range
- **Period:** 9:30–9:45 AM ET (first 15-min bar)
- **OR High / OR Low:** High and low of that bar, static for the day

### Entry Logic
**First breakout (one per day):**
- BUY: Close > OR High + 0.50 pts, between 9:45–11:00 AM ET
- SELL: Close < OR Low − 0.50 pts, between 9:45–11:00 AM ET

**Fakeout reversal (max 1 per day):**
- First trade stopped out → enter opposite direction if price reaches other OR boundary
- Allowed until 11:15 AM ET

### Exit Logic
- **Take Profit:** +20 points from entry
- **Stop Loss (VIX-based):**
  - VIX < 25: 4.0 points
  - VIX ≥ 25, OR range > 20 pts: OR range ÷ 2
  - VIX ≥ 25, OR range ≤ 20 pts: full OR range

### Risk
- Max 2 trades per day (initial + one fakeout reversal)
- Target: 20 points fixed
- Stop: 4–20 points depending on VIX

### Chart Display
- **OR High / OR Low** lines (cyan, solid)
- **Target +20 / Target −20** lines (green, dotted)
- **Entry** line (green=long, red=short)
- **Stop Loss** line (red, dotted)
- **Exit** line (orange) — closed trades only
- NO VWAP, NO HTF S/R levels

---

## Strategy 3: HTF Untouched Levels

**ID:** `htf_levels`, `htf_supply_demand`
**Instruments:** 7 USD FX majors + 124 stocks/ETFs/crypto
**Execution:** Oanda (FX), IB (options spreads for stocks)

### Three Models

| Model | Trigger TF | Zone TFs | Bias TF | Risk % | Scan Cadence |
|-------|-----------|----------|---------|--------|-------------|
| **Scalp** | 15m | 1H, 4H | 4H | 0.25% | Every 5 min |
| **Intraday** | 1H | 4H, Daily | Daily | 0.5% | Every 15 min |
| **Swing** | Daily | Weekly, Monthly | Monthly | 1.0% | Every 24 hr |

### Entry Logic (3-Phase)
1. **Watchlist:** Find untouched S/R levels (highs/lows not revisited in 10-bar lookback). Score by ADX trend alignment (0–100).
2. **Monitor:** Watch for price to approach within zone tolerance (ATR-based). Zone becomes "activated."
3. **Trigger:** On activated zone, check trigger TF candle for reversal pattern (TA-Lib: hammer, engulfing, morning star, etc.) aligned with trade direction.

### Exit Logic
- Target: Next S/R level in trade direction, or 2:1 R:R fallback
- Stop: Zone price ± (ATR × atr_stop_multiplier)
- Time stop: 4 hours (scalp), 1 day (intraday), 2 weeks (swing)

### Options Auto-Trade
When a stock signal fires, automatically analyzes and queues credit/debit spreads via IB:
- DTE: Scalp 3–7d, Intraday 7–14d, Swing 25–40d
- Width, max risk, max contracts configurable per user

### Chart Display
- **S/R Level lines** colored by timeframe:
  - Monthly: orange
  - Weekly: yellow
  - Daily: blue
  - 4H: light purple
  - 1H: green
- **Entry** line (green=long, red=short)
- **Stop Loss** line (red, dotted)
- **Exit** line (orange) — closed trades only
- NO VWAP (not used in this strategy)

---

## Chart Overlay Rules by Strategy

### 2n20 VWAP Overwhelm Scalp
| Element | Show | Details |
|---------|------|---------|
| VWAP | Yes | Orange line, anchored at pair-specific session open |
| S/R Levels | No | — |
| ORB Range | No | — |
| Entry line | Yes | Green (long) / Red (short), solid |
| Exit line | Yes | Orange, solid — closed trades only |
| Stop Loss | Yes | Red, dotted |

**Direction logic on chart:**
- Price above VWAP → bullish bias (background tint green)
- Price below VWAP → bearish bias (background tint red)
- BUY signal: green overwhelm candle while above VWAP
- SELL signal: red overwhelm candle while below VWAP
- Exit: opposite overwhelm or VWAP cross

### Opening Range Breakout (ORB)
| Element | Show | Details |
|---------|------|---------|
| VWAP | No | — |
| S/R Levels | No | — |
| ORB High | Yes | Cyan solid line — top of 9:30–9:45 bar |
| ORB Low | Yes | Cyan solid line — bottom of 9:30–9:45 bar |
| Target +20 | Yes | Green dotted — OR High + 20 pts (long target) |
| Target −20 | Yes | Green dotted — OR Low − 20 pts (short target) |
| Entry line | Yes | Green (long) / Red (short), solid |
| Exit line | Yes | Orange, solid — closed trades only |
| Stop Loss | Yes | Red, dotted — VIX-dependent distance |

**Direction logic on chart:**
- BUY: price breaks above OR High + 0.50 pts → entry line above cyan OR High
- SELL: price breaks below OR Low − 0.50 pts → entry line below cyan OR Low
- Target: always 20 pts from entry in trade direction
- Stop: 4 pts (VIX<25) or OR range ÷ 2 (VIX≥25, wide range) or full OR range (VIX≥25, narrow)
- Fakeout: if stopped out, reverse at opposite OR boundary

### HTF Untouched Levels
| Element | Show | Details |
|---------|------|---------|
| VWAP | No | — |
| ORB Range | No | — |
| Monthly S/R | Yes | Orange dashed lines, labeled "M S1" / "M D1" |
| Weekly S/R | Yes | Yellow dashed lines, labeled "W S1" / "W D1" |
| Daily S/R | Yes | Blue dashed lines, labeled "D S1" / "D D1" |
| 4H S/R | Yes | Purple dashed lines, labeled "4H S1" / "4H D1" |
| 1H S/R | Yes | Green dashed lines, labeled "1H S1" / "1H D1" |
| Entry line | Yes | Green (long) / Red (short), solid |
| Exit line | Yes | Orange, solid — closed trades only |
| Stop Loss | Yes | Red, dotted — ATR × multiplier below/above zone |

**Direction logic on chart:**
- BUY at demand zone: price approaches D1 (support) from above → bullish candle pattern triggers entry
- SELL at supply zone: price approaches S1 (resistance) from below → bearish candle pattern triggers entry
- Entry line sits near the zone level that triggered it
- Stop sits on the other side of the zone (ATR distance)
- Target is the next S/R level in trade direction

---

## Webhook Signal Format

```json
{
  "key": "lumisignals2026",
  "ticker": "MES",
  "direction": "BUY",
  "strategy": "orb_breakout",
  "type": "futures",
  "contracts": 1
}
```

Processed at: `POST /api/webhook/tradingview`
- Futures → queued to Redis → IB sync places order
- Options → analyzed → credit/debit spread queued
- Levels sync → stored in Redis for compare dashboard
