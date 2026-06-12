# Reconciler — fixes before re-enabling

**Status (2026-06-02):** disabled on prod via Redis kill switch `ibkr:reconciler:disabled = "1"`. To re-enable temporarily: `redis-cli DEL ibkr:reconciler:disabled`.

## Incident that triggered the kill

2026-06-02 09:40 ET. The mobile Positions tab showed a single `futures_2n20` strat_pos with `contracts: 15` MES BUY, $1012 risk. **No Pine signal fired near 9:40.** The bot opened no new bracket. The 15-contract strat_pos was a phantom record synthesized by the reconciler's adopt path (`reconciler.py:481-493`) — it saw +15 MES net at IB (accumulated orphan fills from earlier trades whose closing legs never cleared) and called `save_strat_pos(contracts=abs(broker_qty), ...)`.

Fingerprints that gave it away:
- `metadata: {}` — the live entry path always sets `entry_coid`; reconciler leaves it empty
- `multiplier: 1.0` — wrong for MES (correct is 5.0); live entry path passes the right value, reconciler accepts `save_strat_pos`'s default
- `opened_at` matched the reconciler tick time, not any trade event
- `perm_id` was one *contributing* fill's order_id, not a fresh entry's

## Fixes required before re-enabling

### 1. Don't bundle N orphan fills into one synthetic strat_pos
Net qty is the wrong unit. The +15 came from many separate fills, potentially from different strategies. Adopt should either:
- Create one strat_pos per source fill (1 contract each, traceable to its own order_id)
- Or refuse to adopt aggregate exposure and emit `RECONCILE_AGGREGATE_ORPHAN` for manual triage

### 2. Hard cap on adoption quantity per pass
Refuse to adopt anything where `abs(broker_qty) > MAX_ADOPT_QTY`. Default cap: `2 × user's per-strategy contract cap` (e.g. if `futures_contracts = 1`, max-adopt = 2). Above the cap: Telegram-alert hard, do nothing, do not write strat_pos.

### 3. Recency check
Only adopt when the contributing fill is recent (e.g. within last 60s). Stale aggregate exposure (positions left open from yesterday's session) should NOT be silently absorbed. Older orphans go to `RECONCILE_STALE_ORPHAN` — alert and require manual intervention.

### 4. Strategy attribution sanity
Today's adopt logic decodes strategy from `order_ref` of the *last* fill. If that fill's strategy is "futures_2n20" but the OTHER 14 contracts came from `htf_levels`, the bot will think 15 belong to 2n20. Either:
- Require ALL contributing fills to share the same decoded strategy, OR
- Adopt only the quantity attributable to that one fill, leave the rest as `manual` / phantom

### 5. Populate correct multiplier in `save_strat_pos`
Pass MES → 5, MNQ → 2, FX → 1, etc. The adopt call at `reconciler.py:481` doesn't pass `multiplier` so it falls back to default 1, which breaks downstream P&L and risk math.

### 6. Mark adopted strat_pos as adopted
Set `metadata: {"adopted": true, "adopted_at": <ts>, "source_order_id": ..., "source_order_ref": ...}` so downstream code (UI, close path, audit) can distinguish "real bot entry" from "reconciler-adopted." Mobile position card should show an `ADOPTED` badge for these.

### 7. Loud Telegram on every adopt
Today's adopt logs at INFO and sends a quiet Telegram. With the new gating it should be hard-alert (red badge, sound), because every adopt now means human-eyes-required.

### 8. UI surfaces adopted positions distinctly
Mobile Positions tab should render adopted strat_pos with a visible chip ("🪝 Reconciler-adopted — not from a strategy signal") and disable the auto-managed bracket exit logic for them. Right now they look identical to real entries.

### 9. Verification path before re-enabling
- Paper account: leave 1 orphan MES contract at IB without a strat_pos, turn reconciler back on, confirm it adopts at qty=1 with correct multiplier, metadata flagged, Telegram fired.
- Paper account: leave 5 orphan MES contracts, confirm cap triggers REFUSE+ALERT (no adopt).
- Live: dry-run mode — log "would have adopted" without actually writing strat_pos for one full session, manually verify each case before flipping to active.

## Why the orphans existed in the first place

The +15 net at IB suggests the bot's close path has its own leak — closing legs that don't actually close at IB, or stop fills that don't clear strat_pos. Worth tracing in parallel:
- Pre-fix audit: pull last 7 days of MES fills, plot net position over time vs strat_pos snapshots, find where they diverge
- Check `check_stop_fills` — does a stop-out always clear the strat_pos? Or are stale strat_pos entries piling up?
- Bracket OCA: when entry fills + stop fires, both legs go through; that's clean. But if entry fills + bot crashes before bracket is sent, we have an orphan. Look at `record_strategy_for_perm` write-then-place ordering.
