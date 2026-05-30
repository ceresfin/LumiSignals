# ORB Butterfly — Plan Snapshot, 2026-05-30

Frozen snapshot of the ORB butterfly (`orb_butterfly`, SPX 0DTE leg-in)
debug + harden plan as it stood at the end of weekend session
2026-05-30. Preserved here in version control so it survives outside
this droplet's `~/.claude` and is accessible from any device with
GitHub auth.

This was a single-session, multi-phase rebuild that took the strategy
from "silently broken on stale paper-account quotes with no diagnostics"
to "real-time-quoted, fully diagnosed, atomically-placed, risk-gated,
diary-integrated" — pending one Tuesday smoke validation before Phase
10b cutover.

## Context (when work started)

The SPX 0DTE leg-in butterfly had been running on paper since being
built but had **never reached COMPLETE state** (all four legs filled).
Two structural issues:

1. **Quote staleness.** IB paper-account quotes are 15-min delayed
   (field `6509="D"`). Butterfly leg pricing computed on delayed bids
   /asks is wrong by construction.
2. **Silent failures everywhere.** SPX index price feed (`_spx_price()`
   in `ibkr_sync_cpapi.py`) swallowed every Polygon exception and
   returned None. Stuck `WATCHING` butterflies sat for hours with no
   log, no alert, no fallback.
3. **Intermittent `Combo key is not complete` CPAPI rejections** on
   single-leg LMT placements — root cause turned out to be a
   payload-format bug in the long-disabled combo builder, *not* a
   CPAPI limitation as the docstring claimed.

Reference: `docs/orb_debit_leg_observation_2026-05-29.md` — postmortem
on `bf_6e42bd320e`, the Friday-stuck butterfly that motivated the
rebuild.

## Phases shipped

All on branch `orb-debug` (off `main`), 10 commits, all pushed to
`github.com:ceresfin/LumiSignals`. The `2n20-stable-2026-05-29` tag
on `main` is the rollback point — no commit on this branch touched
2n20 code paths.

| Phase | Status | Commit | What |
|------:|:------:|---|---|
| 0  | done | (postmortem doc) | Friday's `bf_6e42bd320e` debit-spread postmortem. Settled max-loss $110 at SPX ~7,580 close. |
| 1  | done | `7a940df` | SPX feed loud-fail + Polygon→IB fallback + Telegram at 5 consecutive fails + stuck-WATCHING > 30min watchdog + startup cleanup of orphaned Redis blobs. |
| 1-fix | done | `d67da88` | Discovered in deploy verification: `get_snapshot` → `get_market_snapshot` typo + missing IB-snapshot warmup retry loop + `MASSIVE_API_KEY` was missing from `/etc/lumisignals/ibkr-sync.env`. |
| 2  | done | `bccf8fb` | Schwab refresh-token visibility: `refresh_token_issued_at` tracking (separate from `saved_at`), `token_status()` helper, 48h-Telegram alert with 23h self-dedupe, `GET /api/schwab/status` endpoint. Defensive 6509 gate in `_fetch_quote` (env-gated). |
| 3  | done | `bcf853c` | `_place_leg` returns `(order_id, err_msg)` tuple with full payload+response logging at WARN on every failure. 250ms gap between consecutive `_place_leg` calls. Fast-abandon on permanent CPAPI errors. `bin/orb_place_smoke.py` for repeatable payload-variation testing. |
| 5  | done | `96bcc22` | New `lumisignals/orb_quote_source.py` with `QuoteSource` abstract interface. `SchwabQuoteSource` (bridge implementation), `IBCpapiQuoteSource` (destination, always-on 6509 fail-closed), `TastytradeQuoteSource` stub. Selected via Redis `orb:quote_source` (default `schwab`). Dead `_fetch_quote`/`_warm_quotes` removed from handler. |
| 8  | done | `d22a114` | Per-leg diary integration: INTENT_OPEN → OPEN → CANCELLED/CLOSED lifecycle events on each of 4 butterfly legs. Idempotency via `diary_milestones` list in state. New `orb_butterfly` row in `strategies` table. SALVAGE close events recorded too. |
| 9  | done | `d22a114` | ORB webhook risk-gate parity with futures: `reconcile_gate` → `kill_switch` → `runaway_guard` → ORB-specific cooldown. Skipped `position_guard` (vega-not-delta exposure). `runaway_guard.record_entry()` called after queue so ORB-spam counts toward the shared daily cap. |
| 10a | done | `b63a1ce` | Critical correction: the "combo broken" claim from the original docstring was wrong. The old `build_spread_order` emitted a malformed `conidex` (missing `spread_conid` prefix, wrong separator, extraneous `legs:` array). New `build_combo_order(legs, qty, price, ...)` produces the correct format per ibind issue #110 (production user `salsasepp` confirmed atomic-fill 2025-06-04). Plus `SPREAD_CONID` table + hardened `_lookup_option_conid` to prefer SPXW class. Zero behavior change until Phase 10b cutover. |

Plus 1 helper commit: `f02ff23` — `print-schwab-auth-url.py` for
headless-friendly Schwab OAuth (script that prints the auth URL without
trying to `webbrowser.open()`, since the droplet has no browser).

## Phases pending (Tuesday open)

| Phase | Status | Why pending |
|------:|---|---|
| 10b | pending validation | Cut over the ORB handler from per-leg `_place_leg` pairs to single atomic `_place_debit_spread` / `_place_credit_spread` calls. Delete all partial-fill handling (no longer possible with atomic spreads). Delete `_close_leg_at_market` calls in `_phase_salvage` (per user's "let it cash-settle" rule). Update diary to record per-leg events tagged with the same combo `order_id`. Gated on the smoke test in `bin/orb_place_smoke.py` confirming variants 9-12 (combo via `build_combo_order`) return order_ids when run against live CPAPI Tuesday morning. |
| 4 | pending (optional) | Debit-leg-only test mode. Redis key `orb:test_mode = "debit_only"` would short-circuit the credit leg-in so a fresh signal places only the debit and holds to expiry. Useful for cautious first-run validation. May be redundant after Phase 10b lands. |

## Tuesday morning smoke procedure

```
ssh lumi-prod
sudo bash -c 'set -a; . /etc/lumisignals/ibkr-sync.env; set +a; \
  /opt/lumisignals/venv/bin/python3 /opt/lumisignals/app/bin/orb_place_smoke.py'
```

Expected outcome of variant 9 (`COMBO via build_combo_order`): an
order_id returned, immediate cancel succeeds. If yes → Phase 10b is
greenlit. If no → check the rejection string against variants 10/11/12
(unsigned ratios, no outsideRTH, manualIndicator) for which payload
field is the actual differentiator.

## Files modified across the effort

- `lumisignals/ibkr_sync_cpapi.py` — Phase 1 (SPX feed)
- `lumisignals/orb_butterfly_handler.py` — Phases 1/3/5/8/10a
- `lumisignals/schwab_client.py` — Phase 2
- `saas/app.py` — Phase 2 (endpoint), Phase 9 (gates)
- `lumisignals/diary.py` — Phase 8 (strategy slug)
- new `lumisignals/orb_quote_source.py` — Phase 5
- new `bin/orb_place_smoke.py` — Phase 3 + Phase 10a combo variants
- new `print-schwab-auth-url.py` — Schwab reconnect helper
- new `docs/orb_debit_leg_observation_2026-05-29.md` — Phase 0
- `lumisignals/ibkr_cpapi.py` — Phase 10a (`build_combo_order` + `SPREAD_CONID`)

Plus DB writes:
- `strategies` table: inserted row for `orb_butterfly`
- `/etc/lumisignals/ibkr-sync.env` on lumi-prod: appended `MASSIVE_API_KEY` (was missing)

## Deploy + verification state at session end

- All 10 commits deployed to `/opt/lumisignals/app/` on lumi-prod
- Backup of pre-deploy state preserved at
  `/opt/lumisignals/app.bak-pre-orbdebug-20260530/`
- All 3 services (`lumisignals`, `lumisignals-bot`, `lumisignals-ibkr-sync`)
  restarted, all active, no errors in tick loop
- `GET /api/schwab/status` returns HTTP 302 (login-required redirect = route alive)
- `SchwabQuoteSource.get_option_quote('SPX', '20260602', 7600, 'C')`
  returns real bid/ask (verified Saturday afternoon against Friday's close)
- `_spx_price_with_fallback()` returns 7580.06 from Polygon, fallback path
  also functional
- Schwab token refreshed by user 2026-05-30 18:00 UTC; expires 2026-06-06.
  48h Telegram alert will fire automatically before that.
- Existing MES position correctly adopted by reconciler on the last restart.
- No 2n20 regression at any deploy step.

## Where to look for full implementation detail

| Source | What it has |
|---|---|
| `git log orb-debug --oneline` (10 commits) | Phase-level summary |
| `git log orb-debug -p` (full diffs) | Line-level change with multi-paragraph commit messages explaining *why* each change was made |
| Code docstrings in the files above | Live-with-the-code explanations |
| `docs/orb_debit_leg_observation_2026-05-29.md` | Friday postmortem |
| Task list tasks #84-96 in Claude Code's `TaskList` | Per-phase status + descriptions |
| `print-schwab-auth-url.py` | The OAuth refresh helper script |
| `bin/orb_place_smoke.py` | The Tuesday smoke script with 12 payload variants |

## Open question for whenever ORB resumes

1. Phase 10b cutover decision (gated on smoke; see above)
2. Phase 4 debit-only test mode (defensive belt-and-suspenders, may not be needed if 10b lands clean)
3. The "natural 0DTE cash settlement leaves diary OPENs that never close" gap — needs a separate end-of-day watcher to record CLOSED events for COMPLETE butterflies (no hook today for "IB cash-settled at 4 PM")
4. When the live IB account opens, flip `orb:quote_source` Redis key from `schwab` to `ib_cpapi` after the 24h propagation completes. The 6509 fail-closed gate ensures we don't accidentally fly on delayed quotes during the transition.
5. When the user funds Tastytrade, implement `TastytradeQuoteSource` (parallel to `SchwabQuoteSource`) and flip the Redis key to `tastytrade` — Schwab can then be retired as the bot's quote source.
