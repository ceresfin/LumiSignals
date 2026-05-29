"""Per-strategy/ticker cooldown after a stop-out.

When a bracket SL fires, the strategy's strat_pos clears and the bot
is immediately ready to take the next signal. In a whipsawing market
this means we can re-enter the same broken level multiple times in a
few minutes, compounding losses.

A cooldown sets a Redis TTL key when STOP_FIRED happens; the webhook
handler refuses BUY/SELL on the same (strategy, ticker) pair while the
key exists. TP fills and TV-initiated closes do NOT trigger cooldown
— only stop-outs do.
"""

import json
import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

CFG_KEY = "risk:cooldown:config"
KEY_PREFIX = "risk:cooldown:active:"

DEFAULT_CONFIG = {
    "enabled": True,
    "cooldown_secs": 120,    # 2 min — ~1 bar on a 2m chart
}


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def get_config() -> dict:
    raw = _rdb().get(CFG_KEY)
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        return {**DEFAULT_CONFIG, **json.loads(raw)}
    except Exception:
        return dict(DEFAULT_CONFIG)


def set_config(updates: dict) -> dict:
    merged = {**get_config(), **(updates or {})}
    try:
        merged["cooldown_secs"] = max(0, int(merged.get("cooldown_secs", 120)))
    except (TypeError, ValueError):
        merged["cooldown_secs"] = 120
    merged["enabled"] = bool(merged.get("enabled", True))
    _rdb().set(CFG_KEY, json.dumps(merged))
    return merged


def _key(strategy: str, ticker: str) -> str:
    return f"{KEY_PREFIX}{strategy.lower()}:{ticker.upper()}"


def start(strategy: str, ticker: str) -> Optional[int]:
    """Begin a cooldown for the given (strategy, ticker). Returns the
    seconds remaining if started, None if cooldown is disabled."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return None
    secs = int(cfg.get("cooldown_secs", 120))
    if secs <= 0:
        return None
    try:
        _rdb().setex(_key(strategy, ticker), secs, "1")
        logger.info("cooldown START %s/%s for %ds", strategy, ticker, secs)
    except Exception as e:
        logger.warning("cooldown start failed: %s", e)
        return None
    return secs


def is_active(strategy: str, ticker: str) -> bool:
    try:
        return _rdb().get(_key(strategy, ticker)) is not None
    except Exception:
        return False


def ttl(strategy: str, ticker: str) -> int:
    """Seconds remaining on the cooldown, or 0 if not active."""
    try:
        t = _rdb().ttl(_key(strategy, ticker))
        return max(0, int(t)) if t and t > 0 else 0
    except Exception:
        return 0


def clear(strategy: str, ticker: str) -> bool:
    """Manually clear a cooldown."""
    try:
        return _rdb().delete(_key(strategy, ticker)) > 0
    except Exception:
        return False
