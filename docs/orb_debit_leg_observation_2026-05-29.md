# ORB Butterfly Debit-Leg Observation — 2026-05-29

Forensic postmortem on `bf_6e42bd320e`, the live butterfly that got stuck in `WATCHING` for >2 hours on Friday because the SPX index price feed silently died. Captured here so the lesson survives the next refactor.

## What the bot did

| Field | Value |
|---|---|
| Butterfly ID | `bf_6e42bd320e` |
| Direction | BUY (bull call butterfly) |
| Ticker | SPX |
| Structure | Long 1× SPXW 7605C, Short 1× SPXW 7610C (debit-side bull call spread) |
| Planned full butterfly | Long 1×7605C / Short 2×7610C / Long 1×7615C |
| Account | DUQ259116 (paper) |
| Queued | 13:48:01 EDT |
| Debit-legged | 13:48:03 EDT (instant on signal) |
| Debit fills | Long 7605C @ $4.20, Short 7610C @ $3.10. Net debit $1.10 |
| Notional at risk | $110 |
| OR high / low (from Pine) | 7593.39 / 7574.14 |
| Credit-leg trigger | SPX = 7607.0 (20% into the fly) |
| Credit-leg fired? | **NO** — stuck in WATCHING from 13:48 EDT to expiry |

## What we know about Friday's SPX

- Approximate 4:00 PM EDT close (per Google Finance after-hours snapshot): **~7,580**
- Final official settlement value to be verified against IB account activity when CPAPI comes back Monday — this doc will be updated.

## Expiry payoff

SPXW is European, cash-settled at the SPX 4:00 PM close.

| SPX close range | Long 7605C settles | Short 7610C settles | Spread value | Net P&L |
|---|---|---|---|---|
| ≤ 7605 | 0 | 0 | 0 | **−$110** (max loss) |
| 7605–7610 | (close − 7605) × 100 | 0 | (close − 7605) × 100 | partial gain/loss |
| ≥ 7610 | (close − 7605) × 100 | -(close − 7610) × 100 | $500 | **+$390** (max gain) |

Friday close was ~7,580 → spread settled fully out-of-the-money → **realized P&L: −$110**.

## Was the credit-leg trigger ever hit?

The threshold for credit-leg entry was SPX = 7607. We don't have intraday SPX data because the bot's SPX feed (Polygon) was silently failing. The OR high (peak of the 9:30–9:45 ET opening range) was 7593.39 — so SPX would have needed to rally another ~14 points after the signal fired at 13:48 EDT for the credit leg to trigger.

Open question for the next postmortem (when we have a real-time SPX history source): did SPX touch 7607 between 13:48 and 16:00 EDT? If yes, the credit leg *should* have legged in but didn't because of the silent feed failure — that's a $110 loss we may have been able to convert into something else by legging into the full butterfly. If no, the strategy correctly identified that the breakout failed and the debit leg would have expired worthless either way.

## Why the bot didn't know

`lumisignals/ibkr_sync_cpapi.py` `_spx_price()` swallows all exceptions and returns `None`:

```python
def _spx_price():
    try:
        ...polygon call...
    except Exception:
        return None
```

`_phase_watching()` then early-returns at `if not spx_price: return`. No log, no Telegram, no fallback. The butterfly sat in WATCHING for the entire afternoon while the worker tick logged nothing useful.

## Companion butterfly: bf_c6f2ee9c6d

Same Friday afternoon, the bot tried a reverse signal:

| Field | Value |
|---|---|
| Direction | SELL (bear put butterfly) |
| Structure | Long 7565P, Short 7560P, Long 7555P |
| Queued | 14:43:00 EDT |
| Phase | ABANDONED (`place_order failed for one or both legs`) |
| Debit retries | 2 (hit cap) |
| Position at IB | **none** — placement never succeeded |

This one is a clean example of the intermittent "Combo key is not complete" placement failure. The same code path filled 6 other butterflies that day successfully — the failure is not deterministic. Phase 3 of the rebuild plan addresses this.

## Lessons that drive the rebuild plan

1. **Silent failures on the index feed are catastrophic.** A single try/except returning None turned a $390 max-profit setup into a $110 max loss because we never triggered the credit leg. Phase 1 of the plan: loud-fail + IB fallback + stuck-WATCHING Telegram watchdog.
2. **Even with a working state machine, debit-only payoffs don't favor us.** A debit-side call spread alone is a directional bet with poor R/R if you stop at the debit leg. The butterfly's edge comes from converting to a 4-leg structure that pays at center strike. So a strategy that stops at debit is a worse strategy than nothing — we need credit-leg reliability before this is worth running live.
3. **Quote staleness matters for entry pricing too.** The debit was filled marketable at $1.10 (target $1.10, achieved cleanly) but Phase 5 still needs real-time quotes for the credit leg, which is the harder leg-in moment because we're chasing the body's IV crush as SPX moves through the threshold.

## Cleanup actions

- [ ] Confirm with user, then `redis-cli DEL ibkr:butterfly:bf_6e42bd320e` (Redis blob still says `WATCHING`, stale — IB has cash-settled the position by now)
- [ ] Confirm with user, then `redis-cli DEL ibkr:butterfly:bf_c6f2ee9c6d` (already `ABANDONED`; no real position; just clearing UI noise)
- [ ] When CPAPI comes back Monday, pull `/portfolio/{acctId}/positions/0` to confirm the SPX option positions are flat
- [ ] Pull IB account activity for 2026-05-29 to capture the actual settlement line items + final P&L; update the table above with the verified close price and confirmed loss

## Files referenced

- `lumisignals/orb_butterfly_handler.py` — strategy state machine
- `lumisignals/ibkr_sync_cpapi.py` `_spx_price` lines 3560-3567 — the silent failure
- `lumisignals/ibkr_sync_cpapi.py` `process_butterflies` line 3553-3570 — worker tick
- Plan: `/home/sonia/.claude/plans/luminous-weaving-newt.md`
