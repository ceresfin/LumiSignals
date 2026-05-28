"""Position size guard.

Refuses any BUY / SELL entry that would push the projected net contracts
beyond a configured ceiling. Defense-in-depth against runaway loops or
mis-configured strategies that try to stack into a position past sane
limits.

CLOSE_LONG / CLOSE_SHORT signals are never blocked — they reduce or
flatten exposure, which is always desirable.

Config + state in Redis. Single-user for now.
"""

import json
import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

CFG_KEY = "risk:position_guard:config"

DEFAULT_CONFIG = {
    "enabled": True,
    "default_limit": 2,           # contracts ceiling when no per-ticker override
    "limits": {},                 # {ticker: int} — empty by default, all tickers
                                  # fall back to default_limit
}


def _rdb() -> redis.Redis:
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def get_config() -> dict:
    raw = _rdb().get(CFG_KEY)
    if not raw:
        return dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(raw)
        return {
            "enabled": bool(saved.get("enabled", DEFAULT_CONFIG["enabled"])),
            "default_limit": int(saved.get("default_limit",
                                           DEFAULT_CONFIG["default_limit"])),
            "limits": dict(saved.get("limits", {})),
        }
    except Exception:
        return dict(DEFAULT_CONFIG)


def set_config(updates: dict) -> dict:
    merged = {**get_config(), **(updates or {})}
    try:
        merged["default_limit"] = max(0, int(merged.get("default_limit", 2)))
    except (TypeError, ValueError):
        merged["default_limit"] = 2
    merged["enabled"] = bool(merged.get("enabled", True))
    cleaned: dict = {}
    for k, v in (merged.get("limits") or {}).items():
        try:
            cleaned[str(k).upper()] = max(0, int(v))
        except (TypeError, ValueError):
            continue
    merged["limits"] = cleaned
    _rdb().set(CFG_KEY, json.dumps(merged))
    return merged


def get_limit_for(ticker: str) -> int:
    cfg = get_config()
    return cfg["limits"].get(ticker.upper(), cfg["default_limit"])


def current_net_contracts(ticker: str) -> int:
    """Read the current net position from the IB sync snapshot in Redis.
    Positive = long, negative = short, 0 = flat. Returns 0 on any error
    (fail-open — the per-trade bracket SL bounds the exposure anyway)."""
    raw = _rdb().get("ibkr:data:1")
    if not raw:
        return 0
    try:
        data = json.loads(raw)
        positions = data.get("positions", []) or []
        for p in positions:
            sym = (p.get("symbol") or p.get("contractDesc") or "").upper()
            if sym == ticker.upper() or ticker.upper() in sym:
                return int(p.get("position", 0))
    except Exception:
        return 0
    return 0


def _project_net(current: int, direction: str, contracts: int) -> Optional[int]:
    """Compute the net contracts that would result if a BUY/SELL signal of
    the given size were fully processed (including close-and-reverse).

    Returns None for non-entry directions (which we never block)."""
    direction = direction.upper()
    if direction == "BUY":
        if current >= 0:
            return current + contracts   # stacking same side
        return contracts                  # reversal: ends up +contracts long
    if direction == "SELL":
        if current <= 0:
            return current - contracts
        return -contracts
    return None


def check(ticker: str, direction: str, contracts: int) -> dict:
    """Run the guard. Returns a dict that's safe to merge into the webhook
    response: {blocked: bool, reason, current_net, projected_net, limit}."""
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"blocked": False}
    try:
        contracts = max(1, int(contracts))
    except (TypeError, ValueError):
        contracts = 1
    current = current_net_contracts(ticker)
    projected = _project_net(current, direction, contracts)
    if projected is None:
        # CLOSE_* — never blocked
        return {"blocked": False, "current_net": current}
    limit = get_limit_for(ticker)
    blocked = abs(projected) > limit
    out = {
        "blocked": blocked,
        "ticker": ticker.upper(),
        "direction": direction.upper(),
        "contracts": contracts,
        "current_net": current,
        "projected_net": projected,
        "limit": limit,
    }
    if blocked:
        out["reason"] = "position_size_guard"
    return out
