# 0DTE Options Strategies — SPY & NDX

## Goal
$1,000/day profit from 5-25 trades using same-day expiration (0DTE) options on SPY and NDX.

## The Math
- $1,000/day with 10-17 trades = $60-100 per trade average
- SPY $1-wide credit spread collects ~$0.30-0.50 ($30-50 per contract)
- SPY $1-wide debit spread costs ~$0.40-0.60, profits $0.40-0.60
- 2-3 contracts per trade at $40-60 profit = ~$100/trade

---

## Strategy 1: VWAP Bounce/Fade
**Concept:** VWAP is the day's "fair value." Price reverts to VWAP ~65% of the time during the first 2 hours.

**Entry:**
- Price drops 0.3-0.5% below VWAP → buy call spread (bounce expected)
- Price rises 0.3-0.5% above VWAP → buy put spread (fade expected)
- Confirm with volume declining (exhaustion)

**Exit:** Close when price returns to VWAP or +0.1% beyond

**Best time:** 10:00 AM - 12:00 PM ET

**Win rate:** ~65% on range-bound days

**Data needed:** Real-time VWAP, 1m/5m price bars

---

## Strategy 2: Gamma Exposure (GEX) Pin
**Concept:** Market makers hedge options, creating "gravity" at high open interest strikes. SPY gravitates toward these levels.

**Entry:**
- Identify largest GEX level (highest open interest strike)
- SPY within $1 of GEX pin → sell iron condor around it
- Collect premium as price gravitates toward pin

**Exit:** Let expire if within range, close if price breaks $2 beyond pin

**Best time:** All day, strongest last 2 hours

**Win rate:** ~60%, better on low-VIX days (VIX < 18)

**Data needed:** Options open interest by strike, GEX calculation

---

## Strategy 3: Opening Range Breakout (ORB)
**Concept:** First 15-30 minutes establish the day's range. Breakout above/below leads to a trending move.

**Entry:**
- Mark high/low of first 15 minutes (9:30-9:45 AM)
- Break above with volume → buy call spread
- Break below with volume → buy put spread
- Volume must be > 1.5x average to confirm

**Exit:** TP at 1.5x opening range width. SL if price re-enters range.

**Best time:** 9:45 - 11:00 AM ET

**Win rate:** ~55-60%, higher on trending days

**Data needed:** 1m/5m bars, volume

---

## Strategy 4: VIX Divergence
**Concept:** When SPY moves but VIX doesn't react proportionally, the move is exhausted.

**Entry:**
- SPY drops -0.5% but VIX only up +2% (normally +5-8%) → buy call spread (reversal coming)
- SPY up +0.5% but VIX flat or rising → buy put spread (distribution)

**Exit:** Close when VIX/SPY ratio normalizes, or after 30-60 minutes

**Best time:** 10:00 AM - 2:00 PM ET

**Win rate:** ~60%, strong institutional signal

**Data needed:** Real-time VIX (I:VIX), SPY price, historical VIX/SPY ratio

---

## Strategy 5: Stacked EMA Momentum
**Concept:** When 9, 21, 50 EMA are stacked in order on 5m chart, trend is strong. Ride it with pullback entries.

**Entry:**
- Bullish stack (9 > 21 > 50) → buy call spread on pullback to 9 EMA
- Bearish stack (9 < 21 < 50) → buy put spread on bounce to 9 EMA
- Don't chase — wait for the pullback

**Exit:** Close when 9 EMA crosses 21 EMA

**Best time:** 10:00 AM - 3:00 PM ET

**Win rate:** ~55%, but R:R is high (small risk, big gamma moves)

**Data needed:** 5m bars, EMA calculations (9, 21, 50)

---

## Strategy 6: Expected Move Iron Condor
**Concept:** Options market prices in a daily expected move. Sell iron condor outside this range.

**Entry:**
- Calculate expected move from ATM straddle price
- Sell iron condor 0.5x beyond expected move on each side
- Example: SPY 530, expected move $3 → sell 527/526P + 533/534C

**Exit:** Let expire for full credit, or close at 50% profit

**Best time:** 10:00 - 11:00 AM (after opening IV settles)

**Win rate:** ~68% (1 standard deviation containment)

**Data needed:** Options chain (ATM straddle price), expected move calculation

---

## Strategy 7: Volume Profile / Point of Control (POC)
**Concept:** POC is the price with most volume traded. Price reverts to it like a magnet.

**Entry:**
- Identify previous day's POC and today's developing POC
- Price above POC + declining volume → buy put spread (revert)
- Price below POC + declining volume → buy call spread (revert)

**Exit:** Close at POC or when volume surges

**Best time:** 11:00 AM - 2:00 PM (midday reversion)

**Win rate:** ~60%, HFT-grade signal

**Data needed:** Volume profile, POC calculation from tick/1m data

---

## Strategy 8: Power Hour Momentum (3:00-3:45 PM)
**Concept:** Last hour sees institutional rebalancing. Direction at 3:00-3:15 continues into close.

**Entry:**
- At 3:00 PM, trending day → buy debit spread in trend direction
- Range-bound day → sell credit spread (stay in range)
- Use 3:00-3:15 candle as trigger

**Exit:** Hold until 3:50 PM, close regardless

**Best time:** 3:00 - 3:50 PM ET only

**Win rate:** ~55%, but massive gamma = small moves → big P&L

**Data needed:** 5m bars, trend detection (EMA stack)

---

## Strategy 9: Sector Rotation / Relative Strength
**Concept:** Money rotates between sectors. Trade the leader.

**Entry:**
- Compare SPY vs QQQ vs IWM at 10:00 AM
- Strongest (highest %) → buy call spread
- Weakest → buy put spread
- Only if divergence > 0.3%

**Exit:** Close when relative strength flips

**Best time:** 10:00 AM - 1:00 PM

**Win rate:** ~55%, institutional rotation signal

**Data needed:** Real-time SPY, QQQ, IWM prices, % change comparison

---

## Strategy 10: Fade the Gap
**Concept:** SPY gaps up/down at open but fills the gap 70% of the time (gaps < 0.5%).

**Entry:**
- Gap up > 0.3% → buy put spread (expect fill)
- Gap down > 0.3% → buy call spread (expect fill)
- SKIP gaps > 1% (those continue, don't fill)
- SKIP if VIX spiking or major news

**Exit:** Close when gap fills (price returns to previous close), SL at 1.5x gap

**Best time:** 9:30 - 10:30 AM ET

**Win rate:** ~70% on small gaps

**Data needed:** Previous close, opening price, VIX

---

## Daily Playbook

| Time | Strategy | Trades | Target |
|------|----------|--------|--------|
| 9:30-9:45 | Fade the Gap (#10) | 1-2 | $100-200 |
| 9:45-10:15 | Opening Range Breakout (#3) | 1-2 | $100-200 |
| 10:00-12:00 | VWAP Bounce (#1) + VIX Divergence (#4) | 3-5 | $200-300 |
| 12:00-2:00 | Volume Profile Reversion (#7) | 2-3 | $100-150 |
| 2:00-3:00 | EMA Momentum (#5) + Sector Rotation (#9) | 2-3 | $100-200 |
| 3:00-3:50 | Power Hour Momentum (#8) | 1-2 | $100-200 |
| **Total** | | **10-17 trades** | **$700-1,250** |

---

## Risk Management for 0DTE

- Max loss per trade: $100 (2 contracts × $50 max loss)
- Max daily loss: $500 (stop trading after 5 consecutive losses)
- Position size: 1-3 contracts per trade
- Never hold through last 10 minutes (3:50+ PM) — gamma explosion
- Always use spreads, never naked options
- Adjust size based on VIX: high VIX (>25) = half size

---

## Data Requirements

| Data | Source | Frequency |
|------|--------|-----------|
| SPY/NDX real-time price | Polygon/IB | 1-second |
| VWAP | Calculate from tick data | Continuous |
| VIX | Polygon (I:VIX) | 15-second delayed |
| Volume | Polygon/IB | 1-minute bars |
| EMA (9/21/50) | Calculate from 5m bars | Every 5 min |
| Options chain (GEX) | Polygon/IB | Every 5 min |
| Previous close / gap | Polygon | Daily |
| Sector ETFs (SPY/QQQ/IWM) | Polygon | 1-minute |

---

## TradingView Integration Options

1. **Webhook alerts** — TradingView sends POST to our server when indicator triggers
2. **Pine Script signals** — custom scripts that fire alerts based on strategy logic
3. **TradingView data export** — pull indicator values via API (requires Premium+)
4. **Hybrid:** Use TradingView for visualization/backtesting, our bot for execution

The most practical integration: **TradingView webhook → LumiSignals API → IB execution**. Your TradingView Pine Script detects the setup, sends an alert webhook, our server receives it, analyzes the options spread, and places it on IB.

---

## Implementation Priority

1. **VWAP Bounce** — easiest, we have price data
2. **Fade the Gap** — simple logic, high win rate
3. **EMA Momentum** — straightforward calculation
4. **VIX Divergence** — we already have VIX data from indices client
5. **Opening Range Breakout** — needs 15-min tracking
6. **Expected Move Iron Condor** — needs options chain
7. **Power Hour Momentum** — time-based trigger
8. **Sector Rotation** — needs multi-ETF comparison
9. **Volume Profile** — needs tick-level data
10. **GEX Pin** — needs options OI data + calculation
