"""Supabase client for LumiSignals bot — dual-write layer.

The bot writes to both Redis (for the Flask dashboard) and Supabase
(for the React Native app). Once the mobile app is live and the Flask
dashboard retired, the Redis writes can be removed.

Uses the service_role key to bypass RLS (server-side writes only).
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://cgomksatarqqehekrumk.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

_client = None


def get_client():
    """Lazy-init Supabase client. Returns None if not configured."""
    global _client
    if _client is not None:
        return _client
    if not SUPABASE_SERVICE_KEY:
        return None
    try:
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        logger.info("Supabase client initialized")
        return _client
    except Exception as e:
        logger.warning("Supabase init failed: %s", e)
        return None


def record_closed_trade(user_id: str, trade: dict):
    """Write a closed trade to the trades table."""
    sb = get_client()
    if not sb:
        return
    try:
        row = {
            "user_id": user_id,
            "broker": trade.get("broker", "oanda"),
            "broker_trade_id": str(trade.get("id", trade.get("broker_trade_id", ""))),
            "instrument": trade.get("instrument", ""),
            "asset_type": trade.get("asset_type", "forex"),
            "direction": trade.get("direction", ""),
            "units": trade.get("units", 0),
            "contracts": trade.get("contracts", 1),
            "entry_price": trade.get("entry", trade.get("entry_price", 0)),
            "exit_price": trade.get("close_price", trade.get("exit_price", 0)),
            "stop_loss": trade.get("stop_loss", None),
            "take_profit": trade.get("take_profit", None),
            "realized_pl": trade.get("realized_pl", 0),
            "pips": trade.get("pips", None),
            "planned_rr": trade.get("planned_rr", None),
            "achieved_rr": trade.get("achieved_rr", None),
            "strategy": trade.get("strategy", trade.get("strategy_id", "")),
            "model": trade.get("model", ""),
            "close_reason": trade.get("close_reason", ""),
            "won": trade.get("won", False),
            "spread_type": trade.get("spread_type", None),
            "sell_strike": trade.get("sell_strike", None),
            "buy_strike": trade.get("buy_strike", None),
            "duration_mins": trade.get("duration_mins", None),
        }
        # Parse timestamps
        opened = trade.get("time_opened", trade.get("opened_at", ""))
        closed = trade.get("time_closed", trade.get("closed_at", ""))
        if opened:
            row["opened_at"] = opened
        if closed:
            row["closed_at"] = closed

        # Remove None values
        row = {k: v for k, v in row.items() if v is not None}

        sb.table("trades").insert(row).execute()
        logger.debug("Supabase: recorded trade %s %s", trade.get("instrument"), trade.get("direction"))
    except Exception as e:
        logger.debug("Supabase trade write error: %s", e)


def upsert_position(user_id: str, position: dict):
    """Insert or update an open position."""
    sb = get_client()
    if not sb:
        return
    try:
        row = {
            "user_id": user_id,
            "broker": position.get("broker", "oanda"),
            "broker_trade_id": str(position.get("id", position.get("broker_trade_id", ""))),
            "instrument": position.get("instrument", ""),
            "asset_type": position.get("asset_type", "forex"),
            "direction": position.get("direction", ""),
            "units": position.get("units", 0),
            "entry_price": position.get("entry", position.get("entry_price", 0)),
            "stop_loss": position.get("stop_loss", None),
            "unrealized_pl": position.get("unrealized_pl", 0),
            "pips": position.get("pips", 0),
            "strategy": position.get("strategy", ""),
            "model": position.get("model", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        opened = position.get("time_opened", position.get("opened_at", ""))
        if opened:
            row["opened_at"] = opened
        row = {k: v for k, v in row.items() if v is not None}

        sb.table("positions").upsert(row, on_conflict="user_id,broker,broker_trade_id").execute()
    except Exception as e:
        logger.debug("Supabase position write error: %s", e)


def remove_position(user_id: str, broker: str, broker_trade_id: str):
    """Remove a position when it's closed."""
    sb = get_client()
    if not sb:
        return
    try:
        sb.table("positions").delete().eq(
            "user_id", user_id
        ).eq("broker", broker).eq("broker_trade_id", str(broker_trade_id)).execute()
    except Exception as e:
        logger.debug("Supabase position delete error: %s", e)


def record_signal(user_id: str, signal_key: str, signal: dict):
    """Write a signal to the signals table."""
    sb = get_client()
    if not sb:
        return
    try:
        row = {
            "user_id": user_id,
            "signal_key": signal_key,
            "instrument": signal.get("instrument", signal.get("symbol", "")),
            "action": signal.get("action", signal.get("direction", "")),
            "strategy": signal.get("strategy", ""),
            "strategy_id": signal.get("strategy_id", ""),
            "model": signal.get("model", ""),
            "entry_price": signal.get("entry_price", signal.get("entry", None)),
            "stop_price": signal.get("stop_price", signal.get("stop", None)),
            "target_price": signal.get("target_price", signal.get("target", None)),
            "risk_reward": signal.get("risk_reward", None),
            "bias_score": signal.get("bias_score", signal.get("final_score", None)),
            "zone_type": signal.get("zone_type", signal.get("level_type", None)),
            "zone_timeframe": signal.get("zone_timeframe", signal.get("level_timeframe", None)),
            "trigger_pattern": signal.get("trigger_pattern", None),
        }
        row = {k: v for k, v in row.items() if v is not None}
        sb.table("signals").upsert(row, on_conflict="user_id,signal_key").execute()
    except Exception as e:
        logger.debug("Supabase signal write error: %s", e)


def record_account_snapshot(user_id: str, broker: str, snapshot: dict):
    """Write periodic account snapshot for equity curve."""
    sb = get_client()
    if not sb:
        return
    try:
        row = {
            "user_id": user_id,
            "broker": broker,
            "nav": snapshot.get("nav", None),
            "cash": snapshot.get("cash", None),
            "unrealized_pl": snapshot.get("unrealized_pl", None),
            "realized_pl": snapshot.get("realized_pl", None),
            "buying_power": snapshot.get("buying_power", None),
            "open_positions": snapshot.get("open_positions", None),
        }
        row = {k: v for k, v in row.items() if v is not None}
        sb.table("account_snapshots").insert(row).execute()
    except Exception as e:
        logger.debug("Supabase snapshot write error: %s", e)
