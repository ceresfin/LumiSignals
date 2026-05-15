"""Periodic Oanda → Supabase trades-table sync.

Closes 2n20 already get recorded directly by fx_scalp_2n20.py's close
handler.  HTF Levels closes don't — they fire at Oanda via the native
stopLossOnFill / takeProfitOnFill bracket, and no bot code observes
the close.  Same for any other future strategy that places via Oanda
brackets and lets the broker do the exit.

This module fills that gap by walking Oanda's CLOSED trade history,
enriching each with strategy metadata from signal_log, and calling
record_closed_trade (which is upsert-by-broker_trade_id, so re-running
the sweep is harmless — same close → same row).

Intended to be called every few minutes from bot_runner.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .oanda_client import OandaClient
from .supabase_client import record_closed_trade, remove_position
from .trade_tracker import get_closed_trades

logger = logging.getLogger(__name__)


def sync_closed_trades(client: OandaClient,
                        user_id: Optional[str] = None,
                        count: int = 100) -> int:
    """Pull the last `count` closed Oanda trades, upsert each into the
    Supabase trades table.  Returns the number of trades processed.

    Upsert via record_closed_trade keys on (user_id, broker, broker_trade_id),
    so multiple runs converge on one row per Oanda trade id — no
    duplicates even if the sweep runs every 5 min.
    """
    user_id = user_id or os.environ.get("SUPABASE_USER_ID", "")
    if not user_id:
        return 0

    try:
        enriched = get_closed_trades(client, count=count)
    except Exception as e:
        logger.warning("oanda_trade_sync: get_closed_trades failed: %s", e)
        return 0
    if not enriched:
        return 0

    written = 0
    for t in enriched:
        try:
            # Strategy attribution: trade_tracker leaves "strategy" on
            # the trade when the signal_log lookup succeeded; otherwise
            # it falls back to "unknown".  htf_levels triggers set
            # strategy_id="htf_levels" + model when they fire.
            strat = (t.get("strategy") or t.get("strategy_id") or
                     "manual").lower()
            model = t.get("model") or ""
            # Map to the shape record_closed_trade expects.  The function
            # is permissive about field aliases (entry/entry_price,
            # close_price/exit_price, etc.).
            broker_trade_id = t.get("trade_id") or t.get("id")
            record_closed_trade(user_id, {
                "id": broker_trade_id,
                "broker": "oanda",
                "asset_type": "forex",
                "instrument": t.get("instrument"),
                "direction": ("LONG" if t.get("direction") == "BUY"
                              else "SHORT"),
                "units": t.get("units", 0),
                "entry_price": t.get("entry") or t.get("entry_price"),
                "exit_price": t.get("close_price") or t.get("exit_price"),
                "stop_loss": t.get("stop_loss") or t.get("planned_sl"),
                "take_profit": t.get("take_profit") or t.get("planned_tp"),
                "realized_pl": t.get("realized_pl", 0),
                "pips": t.get("pips", 0),
                "planned_rr": t.get("planned_rr"),
                "achieved_rr": t.get("achieved_rr"),
                "strategy": strat,
                "model": model,
                "close_reason": t.get("close_reason", ""),
                "won": (t.get("realized_pl", 0) or 0) > 0,
                "time_opened": t.get("open_time") or t.get("opened_at"),
                "time_closed": t.get("close_time") or t.get("closed_at"),
                "duration_mins": t.get("duration_mins"),
            })
            # Also remove the corresponding open-positions row. Strategies
            # that exit via Oanda's native bracket (HTF Levels, H1 Zone
            # Scalp, FX 4H) don't observe the close themselves, so without
            # this the positions table accumulates ghosts that the mobile
            # app can't close ("missing broker_trade_id" / "trade not
            # found"). Idempotent: no-op if the row was already removed.
            if broker_trade_id:
                try:
                    remove_position(user_id, "oanda", str(broker_trade_id))
                except Exception as e:
                    logger.debug("oanda_trade_sync: remove_position %s failed: %s",
                                 broker_trade_id, e)
            written += 1
        except Exception as e:
            logger.debug("oanda_trade_sync: record failed for %s: %s",
                         t.get("id"), e)
    if written:
        logger.info("oanda_trade_sync: upserted %d closed trades", written)
    return written
