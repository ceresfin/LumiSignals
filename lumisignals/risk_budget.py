"""Daily risk budget tracking via Redis.

Records risk amount at entry time (worst-case loss) so the daily budget
is consumed as trades are placed, not when they close.
"""

import os
from datetime import datetime, timezone

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_rdb = None


def _get_redis():
    global _rdb
    if _rdb is None:
        _rdb = redis.from_url(REDIS_URL)
    return _rdb


def _today_key(user_id, model: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"daily_loss:{user_id}:{model}:{today}"


def record_loss(user_id, model: str, amount: float):
    """Record a risk amount against today's budget for a model."""
    rdb = _get_redis()
    key = _today_key(user_id, model)
    rdb.incrbyfloat(key, amount)
    rdb.expire(key, 172800)  # 48h TTL


def get_daily_loss(user_id, model: str) -> float:
    """Get total risk amount consumed today for a model."""
    rdb = _get_redis()
    val = rdb.get(_today_key(user_id, model))
    return float(val) if val else 0.0


def is_budget_exceeded(user_id, model: str, budget: float) -> bool:
    """Check if the daily loss budget has been exceeded.

    Args:
        budget: Daily loss limit in dollars. 0 means no limit (never exceeded).
    """
    if budget <= 0:
        return False
    return get_daily_loss(user_id, model) >= budget
