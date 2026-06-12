"""Runtime-tunable parameters for the multi-timeframe (MTF) swing setups.

The shares-vehicle stop distance, the entry proximity gate, and the target
R:R floors used by ``swing_setup.compute_setup`` live here so they can be
tuned from the Settings tab (``PUT /api/strategies/mtf-config``) without a
redeploy. Code defaults apply until a Redis override is written.

Distances are expressed as multiples of the bottom-TF ATR (5m for scalp,
15m for intraday, daily for swing), so a single number adapts to each
symbol's volatility instead of a fixed percentage.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_CFG_KEY = "mtf:config"

_MODES = ("scalp", "intraday", "swing")

DEFAULT_CONFIG = {
    # Shares stop = stop_atr_mult_<mode> × bottom-TF ATR beyond the entry zone.
    "stop_atr_mult_scalp": 2.0,
    "stop_atr_mult_intraday": 2.0,
    "stop_atr_mult_swing": 2.0,
    # Tradeable only when price is within proximity_atr_mult_<mode> × bottom-TF
    # ATR of the entry zone; farther away → prospective (Open Trade disabled).
    "proximity_atr_mult_scalp": 1.0,
    "proximity_atr_mult_intraday": 1.0,
    "proximity_atr_mult_swing": 1.0,
    # Target R:R floor per mode when no opposite zone is visible.
    "rr_floor_scalp": 1.5,
    "rr_floor_intraday": 2.0,
    "rr_floor_swing": 3.0,
}

# Keys that must stay > 0 when set.
_POSITIVE_KEYS = set(DEFAULT_CONFIG.keys())

# Legacy flat keys (pre per-mode) → per-mode prefix. Migrated on read so a
# stored flat value carries into all three modes instead of being dropped.
_LEGACY_PREFIX = {
    "stop_atr_mult": "stop_atr_mult",
    "proximity_atr_mult": "proximity_atr_mult",
}


def _rdb():
    try:
        import redis
        return redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def get_config() -> dict:
    """Merged config: code DEFAULT_CONFIG ← Redis override."""
    cfg = dict(DEFAULT_CONFIG)
    rdb = _rdb()
    if rdb is not None:
        try:
            raw = rdb.get(_CFG_KEY)
            if raw:
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    # Migrate any legacy flat key onto all three per-mode keys
                    # (a stored flat value shouldn't silently vanish).
                    for legacy, prefix in _LEGACY_PREFIX.items():
                        if legacy in stored:
                            for m in _MODES:
                                stored.setdefault(f"{prefix}_{m}", stored[legacy])
                    cfg.update({k: v for k, v in stored.items()
                                if k in DEFAULT_CONFIG})
        except Exception as e:
            logger.debug("mtf_config get failed: %s", e)
    return cfg


def set_config(updates: dict) -> dict:
    """Apply a subset of config keys and persist. Ignores unknown keys;
    clamps known numeric keys to a sane positive floor."""
    cfg = get_config()
    for k, v in (updates or {}).items():
        if k not in DEFAULT_CONFIG:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if k in _POSITIVE_KEYS:
            fv = max(0.1, fv)   # never zero/negative — would disable the gate
        cfg[k] = fv
    rdb = _rdb()
    if rdb is not None:
        try:
            rdb.set(_CFG_KEY, json.dumps(cfg))
        except Exception as e:
            logger.warning("mtf_config set failed: %s", e)
    return cfg


def stop_mult(mode: str, cfg: Optional[dict] = None) -> float:
    """Shares stop multiplier (× bottom-TF ATR) for a mode."""
    cfg = cfg or get_config()
    return float(cfg.get(f"stop_atr_mult_{mode}",
                         DEFAULT_CONFIG.get(f"stop_atr_mult_{mode}", 2.0)))


def proximity_mult(mode: str, cfg: Optional[dict] = None) -> float:
    """Entry proximity threshold (× bottom-TF ATR) for a mode."""
    cfg = cfg or get_config()
    return float(cfg.get(f"proximity_atr_mult_{mode}",
                         DEFAULT_CONFIG.get(f"proximity_atr_mult_{mode}", 1.0)))


def rr_floor(mode: str, cfg: Optional[dict] = None) -> float:
    """Target R:R floor for a mode (scalp/intraday/swing)."""
    cfg = cfg or get_config()
    return float(cfg.get(f"rr_floor_{mode}",
                         DEFAULT_CONFIG.get(f"rr_floor_{mode}", 2.0)))
