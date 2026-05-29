"""Account-type detection for paper-vs-live separation.

IB uses the same login for paper (DUxxxxxxx) and live (Uxxxxxxx) accounts.
We need to tag every trade / position / event with the account it came
from so the dashboard can keep paper performance separate from live —
otherwise the moment we switch to live, paper history pollutes the live
P&L stats.

Source of truth: the IB CPAPI `account_id` string. Paper accounts always
start with "DU" (demo user). Anything else is live.

The ibkr-sync service writes the detected type to a Redis key
`ibkr:account_type` at startup; the saas service and diary writes read
from there. Falls back to env var IB_ACCOUNT_TYPE if Redis is empty.
Final fallback is 'paper' so a misconfigured deploy never accidentally
tags live (you'd see paper-tagged trades in the live dashboard and
notice the mismatch).
"""

import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

REDIS_KEY = "ibkr:account_type"


def detect_from_account_id(account_id: str) -> str:
    """Map an IB account id to 'paper' or 'live'.

    Paper accounts always start with 'DU' (case-insensitive). Anything
    else is treated as live — IB doesn't publish a comprehensive list of
    live-account prefixes, so this is the safest classification.
    """
    if not account_id:
        return "unknown"
    return "paper" if account_id.strip().upper().startswith("DU") else "live"


def _rdb() -> Optional[redis.Redis]:
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def set_account_type(account_type: str) -> None:
    """Write the detected account type to Redis. Called by ibkr-sync at startup.

    No TTL — the value is overwritten on every sync restart and serves as
    the persistent reference for all subsequent diary writes.
    """
    rdb = _rdb()
    if rdb is None:
        logger.warning("account_type: cannot persist — Redis unreachable")
        return
    try:
        rdb.set(REDIS_KEY, account_type)
    except Exception as e:
        logger.warning("account_type: persist failed: %s", e)


def current_account_type() -> str:
    """Return the account type currently in use by the bot.

    Order of resolution:
      1. Redis key `ibkr:account_type` (set by ibkr-sync at startup)
      2. Env var IB_ACCOUNT_TYPE
      3. Default 'paper' (safest — avoids accidentally tagging live)
    """
    rdb = _rdb()
    if rdb is not None:
        try:
            raw = rdb.get(REDIS_KEY)
            if raw:
                val = raw.decode() if isinstance(raw, bytes) else str(raw)
                val = val.strip().lower()
                if val in ("paper", "live"):
                    return val
        except Exception:
            pass
    env = os.environ.get("IB_ACCOUNT_TYPE", "").strip().lower()
    if env in ("paper", "live"):
        return env
    return "paper"
