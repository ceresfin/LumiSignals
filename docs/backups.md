# State persistence + backups

Live-readiness audit gaps #17 + #18.

## Redis (lumi-prod droplet)

**Status: AOF + RDB enabled (2026-05-29).** Persistence config in `/etc/redis/redis.conf`:

```
appendonly yes
appendfsync everysec
save 3600 1 300 100 60 10000
```

This combines:

- **AOF append-only log** with `everysec` fsync. Worst-case data loss on crash = 1 second of writes.
- **RDB snapshots** at the default intervals (every hour if any change; every 5 min if 100+ changes; every 60 s if 10000+ changes).

What this protects:

- `risk:*` — kill switch state, position guard config, runaway guard counters, cooldown TTL keys
- `ibkr:strat_pos:*` — per-strategy position tracking
- `ibkr:bars:*` — 2-min bar cache (ephemeral; recovered on next sync push)
- `ibkr:data:1` — IB position snapshot (ephemeral; recovered on next sync push)
- `ibkr:account_type` — paper/live detection

After a power loss or droplet reboot, Redis will reload the AOF and recover state up to ~1 s before the crash. The reconciler still runs at startup and validates against IB — anything Redis missed gets re-adopted from broker state.

**Verification (one-liner):**

```bash
ssh lumi-prod 'redis-cli config get appendonly; ls -lh /var/lib/redis/appendonlydir/'
```

## Supabase (cgomksatarqqehekrumk project)

**Action required: confirm tier + retention before going live.**

What Supabase provides automatically per tier:

| Tier | Daily backups | Retention | PITR |
|---|---|---|---|
| Free | yes | 7 days rolling | no |
| Pro ($25/mo) | yes | 7-30 days configurable | optional add-on |
| Pro + PITR | yes | up to 30 days | yes, recovery to any point in last 7-28 days |

Tables we depend on:

- `trade_events` — full diary (state machine for every trade)
- `trades` — closed trade rollup (dashboard P&L source)
- `positions` — currently-open positions
- `live_prices` — last-tick cache for mobile P&L (cheap to lose)
- `profiles`, `symbol_metadata`, `strategies` — config

**Before going live:**

1. Log into Supabase dashboard → Project → Database → Backups
2. Confirm daily backups are listed and recent
3. If still on Free tier, upgrade to Pro and enable PITR. The audit recommendation is **30-day retention + PITR** — a stop-loss audit dispute or tax inquiry can easily reach back ~30 days, and the migration to PITR is a settings toggle.

**Disaster recovery procedure (in event of corruption):**

1. Open Supabase dashboard → Project → Database → Backups
2. Click the most-recent backup before the corruption window
3. Restore — Supabase creates a new project; copy `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` to `/etc/lumisignals/web-app.env`
4. `sudo systemctl restart lumisignals lumisignals-ibkr-sync`

## Future hardening (deferred)

- Hourly export of `trade_events` to S3 (long-term archive beyond Supabase retention)
- Weekly snapshot of `/var/lib/redis/appendonlydir/` to S3 (Redis AOF can grow large; an offsite copy is cheap insurance)
- Automated `supabase db dump` cron for human-readable SQL backups

None of these are required for live-readiness; Redis AOF + Supabase managed daily backups cover the realistic failure modes.
