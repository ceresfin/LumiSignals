"""Redis key cleanup — purges stale orders, old closed trades, and orphaned refs.

Run as a cron job daily, or manually:
    python3 -m lumisignals.redis_cleanup

Keeps:
- Closed trades < 30 days old
- Active/entry futures orders
- Live sync data (ibkr:data:*)
- TV levels cache

Purges:
- Pending orders older than 24 hours (Filled, skipped, expired, superseded)
- Perm ID refs older than 7 days
- Order details older than 7 days
- Closed trade exec dedup older than 7 days
- Futures dedup keys (auto-expire via TTL, but clean stragglers)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CLOSED_TRADE_DAYS = 30  # Keep closed trades for 30 days
ORDER_STALE_HOURS = 24  # Purge processed orders after 24 hours
REF_STALE_DAYS = 7      # Purge perm/detail refs after 7 days


def cleanup(dry_run: bool = False) -> dict:
    """Run Redis cleanup. Returns stats dict."""
    rdb = redis.from_url(REDIS_URL)
    now = datetime.now(timezone.utc)
    stats = {"scanned": 0, "purged": 0, "kept": 0, "errors": 0}

    def is_older_than(iso_str: str, days: int = 0, hours: int = 0) -> bool:
        """Check if an ISO timestamp is older than the given threshold."""
        if not iso_str:
            return True  # No timestamp = assume stale
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            cutoff = now - timedelta(days=days, hours=hours)
            return dt < cutoff
        except Exception:
            return False

    def should_purge_order(data: dict) -> bool:
        """Should this order key be purged?"""
        status = data.get("status", "")
        queued_at = data.get("queued_at", data.get("opened_at", ""))

        # Keep active entries (futures position tracking)
        if status == "entry":
            return is_older_than(queued_at, days=REF_STALE_DAYS)

        # Purge completed/failed/expired orders older than 24h
        if status in ("Filled", "skipped", "expired", "superseded",
                      "cancelled", "Cancelled", "failed", "closed"):
            return is_older_than(queued_at, hours=ORDER_STALE_HOURS)

        # Queued orders older than 24h are stale
        if status == "queued":
            return is_older_than(queued_at, hours=ORDER_STALE_HOURS)

        # Unknown status older than 7 days
        return is_older_than(queued_at, days=REF_STALE_DAYS)

    # --- Clean ibkr:order:pending:* ---
    for key in rdb.scan_iter("ibkr:order:pending:*"):
        stats["scanned"] += 1
        try:
            raw = rdb.get(key)
            if not raw:
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
                continue
            data = json.loads(raw)
            if should_purge_order(data):
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            else:
                stats["kept"] += 1
        except Exception:
            stats["errors"] += 1

    # --- Clean ibkr:order:futures_entry_* ---
    for key in rdb.scan_iter("ibkr:order:futures_entry_*"):
        stats["scanned"] += 1
        try:
            raw = rdb.get(key)
            if not raw:
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
                continue
            data = json.loads(raw)
            opened_at = data.get("opened_at", "")
            status = data.get("status", "")
            # Keep active entries, purge closed/old ones
            if status == "closed" and is_older_than(opened_at, hours=ORDER_STALE_HOURS):
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            elif is_older_than(opened_at, days=REF_STALE_DAYS):
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            else:
                stats["kept"] += 1
        except Exception:
            stats["errors"] += 1

    # --- Clean ibkr:order:perm:* and ibkr:order:details:* ---
    for pattern in ["ibkr:order:perm:*", "ibkr:order:details:*"]:
        for key in rdb.scan_iter(pattern):
            stats["scanned"] += 1
            try:
                ttl = rdb.ttl(key)
                # If no TTL set and key exists, check age from data
                if ttl == -1:  # No expiry
                    raw = rdb.get(key)
                    if raw:
                        data = json.loads(raw)
                        ts = data.get("queued_at", data.get("opened_at", ""))
                        if is_older_than(ts, days=REF_STALE_DAYS):
                            if not dry_run:
                                rdb.delete(key)
                            stats["purged"] += 1
                        else:
                            stats["kept"] += 1
                    else:
                        if not dry_run:
                            rdb.delete(key)
                        stats["purged"] += 1
                else:
                    stats["kept"] += 1
            except Exception:
                stats["errors"] += 1

    # --- Clean ibkr:closed:* older than 30 days ---
    for key in rdb.scan_iter("ibkr:closed:*"):
        stats["scanned"] += 1
        try:
            raw = rdb.get(key)
            if not raw:
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
                continue
            data = json.loads(raw)
            closed_at = data.get("closed_at", "")
            if is_older_than(closed_at, days=CLOSED_TRADE_DAYS):
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            else:
                stats["kept"] += 1
        except Exception:
            stats["errors"] += 1

    # --- Clean ibkr:closed_exec:* older than 7 days ---
    for key in rdb.scan_iter("ibkr:closed_exec:*"):
        stats["scanned"] += 1
        try:
            ttl = rdb.ttl(key)
            if ttl == -1:  # No expiry set
                if not dry_run:
                    rdb.expire(key, 604800)  # Set 7-day TTL
                stats["kept"] += 1
            else:
                stats["kept"] += 1
        except Exception:
            stats["errors"] += 1

    # --- Clean ibkr:order:futures_stop_* older than 7 days ---
    for key in rdb.scan_iter("ibkr:order:futures_stop_*"):
        stats["scanned"] += 1
        try:
            raw = rdb.get(key)
            if not raw:
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
                continue
            data = json.loads(raw)
            ts = data.get("queued_at", data.get("opened_at", ""))
            status = data.get("status", "")
            # Purge filled/cancelled stops immediately if older than 24h
            if status in ("Filled", "Cancelled", "cancelled"):
                if is_older_than(ts, hours=ORDER_STALE_HOURS):
                    if not dry_run:
                        rdb.delete(key)
                    stats["purged"] += 1
                else:
                    stats["kept"] += 1
            # Purge any stop older than 7 days regardless of status
            elif is_older_than(ts, days=REF_STALE_DAYS):
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            else:
                stats["kept"] += 1
        except Exception:
            stats["errors"] += 1

    # --- Clean stale dedup keys ---
    for pattern in ["tv:futures:*", "tv:traded:*", "swing:traded:*"]:
        for key in rdb.scan_iter(pattern):
            stats["scanned"] += 1
            ttl = rdb.ttl(key)
            if ttl == -1:  # No expiry
                if not dry_run:
                    rdb.delete(key)
                stats["purged"] += 1
            else:
                stats["kept"] += 1

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Dry run first
    print("=== DRY RUN ===")
    stats = cleanup(dry_run=True)
    print(f"Scanned: {stats['scanned']}, Would purge: {stats['purged']}, Keep: {stats['kept']}, Errors: {stats['errors']}")

    if stats["purged"] > 0:
        confirm = input(f"\nPurge {stats['purged']} keys? (y/n): ").strip().lower()
        if confirm == "y":
            print("\n=== PURGING ===")
            stats = cleanup(dry_run=False)
            print(f"Scanned: {stats['scanned']}, Purged: {stats['purged']}, Kept: {stats['kept']}, Errors: {stats['errors']}")
            print("Done!")
        else:
            print("Cancelled.")
    else:
        print("Nothing to purge.")
