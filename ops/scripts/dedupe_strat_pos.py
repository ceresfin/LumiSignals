"""One-shot cleanup: normalize strategy labels + dedupe strat_pos.

Two distinct issues to fix:

1. STRAT_POS DEDUPE — `strat_pos:<TICKER>:<RAW>` and
   `strat_pos:<TICKER>:<CANONICAL>` for the same perm_id. The bot
   created BOTH because the webhook used the raw Pine slug while
   the reconciler decoded the canonical slug from the order_ref.
   Action: merge per (ticker, canonical_slug, perm_id), keep the
   row with the correct multiplier, rewrite under canonical key.

2. ibkr:closed LABEL NORMALIZATION — closed-trade blobs have
   `strategy="2n20"` mixed with `strategy="futures_2n20"`. Both are
   real fills, just labeled inconsistently. Mobile UI groups by
   strategy, so the same logical strategy appears as two cards.
   Action: for any blob whose strategy maps to a canonical slug,
   rewrite the strategy field to the canonical. No deletion.

APPLY=1 env to actually mutate.
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/opt/lumisignals/app")
from lumisignals.diary import strategy_slug  # noqa

import redis

APPLY = os.environ.get("APPLY", "0") == "1"
rdb = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
prefix = "[APPLY]" if APPLY else "[DRY]"

def log(msg=""):
    print(f"{prefix} {msg}")

# ════════════════════════════════════════════════════════════════════
# Step 1: strat_pos dedupe — group by (ticker, canonical_slug)
# ════════════════════════════════════════════════════════════════════
log("═══ strat_pos dedupe ═══")
sp_keys = [k.decode() for k in rdb.scan_iter("ibkr:strat_pos:*")]
log(f"total strat_pos keys: {len(sp_keys)}")

by_canon = defaultdict(list)
for k in sp_keys:
    parts = k.split(":")
    if len(parts) != 4:
        continue
    _, _, ticker, strat = parts
    canon = strategy_slug(strat) or strat
    by_canon[(ticker, canon)].append((k, strat))

dups_found = 0
for (ticker, canon), members in by_canon.items():
    if len(members) <= 1:
        continue
    dups_found += 1
    log(f"\nDUP {ticker}/{canon} → {len(members)} keys:")
    rows = []
    for k, strat in members:
        raw = rdb.get(k)
        if not raw:
            continue
        try:
            d = json.loads(raw)
        except Exception:
            continue
        rows.append((k, strat, d))
        meta_coid = (d.get("metadata") or {}).get("entry_coid", "")
        log(f"  {k}: contracts={d.get('contracts')} mult={d.get('multiplier')} "
            f"perm={d.get('perm_id')} coid={meta_coid}")

    # Pick winner: prefer correct-multiplier + has entry_coid
    KNOWN_MULTS = {"MES": 5, "MNQ": 2, "MYM": 0.5, "M2K": 5,
                   "ES": 50, "NQ": 20, "YM": 5, "RTY": 50}
    expected_mult = KNOWN_MULTS.get(ticker)
    def score(r):
        _, _, d = r
        try:
            m = float(d.get("multiplier") or 0)
        except (TypeError, ValueError):
            m = 0
        mult_match = (expected_mult is not None and m == expected_mult)
        has_coid = bool((d.get("metadata") or {}).get("entry_coid"))
        return (mult_match, has_coid)
    rows.sort(key=score, reverse=True)
    winner_key, winner_strat, winner_data = rows[0]
    losers = rows[1:]
    log(f"  → KEEP {winner_key}")

    canon_key = f"ibkr:strat_pos:{ticker}:{canon}"
    new_data = dict(winner_data)
    new_data["strategy"] = canon
    log(f"  → WRITE {canon_key} (mult={new_data.get('multiplier')})")
    if APPLY:
        ttl = rdb.ttl(winner_key)
        rdb.setex(canon_key, max(60, ttl), json.dumps(new_data))

    to_delete = [r[0] for r in losers]
    if winner_key != canon_key:
        to_delete.append(winner_key)
    for k in to_delete:
        log(f"  → DELETE {k}")
        if APPLY:
            rdb.delete(k)

log(f"\nstrat_pos dup groups: {dups_found}")

# ════════════════════════════════════════════════════════════════════
# Step 2: ibkr:closed label normalization
# ════════════════════════════════════════════════════════════════════
log("\n═══ ibkr:closed label normalization ═══")
closed_keys = [k.decode() for k in rdb.scan_iter("ibkr:closed:*")]
log(f"total ibkr:closed:* rows: {len(closed_keys)}")

rewrites_by_strat = defaultdict(int)
no_change = 0
empty_strat = 0
for k in closed_keys:
    raw = rdb.get(k)
    if not raw:
        continue
    try:
        d = json.loads(raw)
    except Exception:
        continue
    cur = d.get("strategy") or ""
    if not cur:
        empty_strat += 1
        continue
    canon = strategy_slug(cur)
    if canon is None or canon == cur:
        no_change += 1
        continue
    rewrites_by_strat[(cur, canon)] += 1
    if APPLY:
        new_d = dict(d)
        new_d["strategy"] = canon
        ttl = rdb.ttl(k)
        # ibkr:closed:* are typically permanent (no expiry). Preserve.
        if ttl < 0:
            rdb.set(k, json.dumps(new_d))
        else:
            rdb.setex(k, ttl, json.dumps(new_d))

log(f"no-change rows: {no_change}")
log(f"empty-strategy rows (skipped): {empty_strat}")
log(f"rewrites:")
for (old, new), n in sorted(rewrites_by_strat.items()):
    log(f"  {old:25s} → {new:25s}  ({n} rows)")
if not APPLY:
    log("\nDRY-RUN. Re-run with APPLY=1 to mutate.")
