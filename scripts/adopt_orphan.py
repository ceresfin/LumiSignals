"""Adopt an untracked IB position into a named strategy.

Use when the bot has a real position at IB that strat_pos / diary have lost
track of (the "ALL ORPHAN (IB open, no strat_pos)" warning on mobile).
Adoption attaches it to a strategy so the bot resumes managing it
normally — closes will route through the correct CLOSE_LONG / CLOSE_SHORT
path, the mobile UI stops showing "ALL ORPHAN", and the diary gets a
proper OPEN event for analytics.

Usage:
    # Dry-run — show what would happen
    python3 -m scripts.adopt_orphan MES --strategy 2n20

    # Actually adopt
    python3 -m scripts.adopt_orphan MES --strategy 2n20 --execute

    # Adopt with an explicit stop (highly recommended for fresh adoptions)
    python3 -m scripts.adopt_orphan MES --strategy 2n20 --stop 7510 --execute

What it does (on --execute):
  1. Pulls IB position for the ticker (must exist, qty != 0)
  2. Finds the most recent matching trade fill — uses its order_id as the
     bot-facing perm_id for the new strat_pos
  3. Creates the Redis strat_pos row keyed on (ticker, strategy)
  4. Writes a diary OPEN event to Supabase
  5. Optionally attaches a protective stop via /iserver bracket if --stop given

Safety:
  - Refuses to adopt if a strat_pos already exists for (ticker, strategy)
  - Refuses if IB doesn't show a position for the ticker
  - Stop placement is best-effort; if it fails, adoption still completes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.environ.get("LUMISIGNALS_PATH", "/opt/lumisignals/app"))
sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("adopt_orphan")


def _connect_redis():
    import redis
    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    return redis.Redis(host=host, port=port, decode_responses=True)


def _find_ib_position(client, ticker: str) -> Optional[dict]:
    for p in client.get_positions() or []:
        if (p.get("symbol") or p.get("ticker")) != ticker:
            continue
        try:
            if int(p.get("quantity") or p.get("position") or 0) != 0:
                return p
        except (TypeError, ValueError):
            continue
    return None


def _find_matching_recent_fill(client, ticker: str, side: str) -> Optional[dict]:
    """Most recent trade for this ticker matching side (B/S)."""
    trades = client.get_trades() or []
    best = None
    for t in trades:
        if t.get("symbol") != ticker:
            continue
        if t.get("side") != side:
            continue
        tt = int(t.get("trade_time_r") or 0)
        if best is None or tt > int(best.get("trade_time_r") or 0):
            best = t
    return best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", help="Ticker symbol (e.g. MES)")
    parser.add_argument("--strategy", required=True, help="Strategy name to adopt under (e.g. 2n20)")
    parser.add_argument("--stop", type=float, default=0,
                        help="Optional stop price to place a protective MKT-stop after adopting")
    parser.add_argument("--execute", action="store_true",
                        help="Actually adopt. Without this, dry-run only.")
    parser.add_argument(
        "--cpapi-url",
        default=os.environ.get("CPAPI_BASE_URL", "https://localhost:5000/v1/api"),
    )
    args = parser.parse_args()

    from lumisignals.ibkr_cpapi import CPAPIClient
    client = CPAPIClient(base_url=args.cpapi_url)
    try:
        client.ensure_session()
    except Exception as e:
        logger.error("CPAPI not reachable: %s", e)
        return 2

    # 1. Confirm IB position exists
    pos = _find_ib_position(client, args.ticker)
    if not pos:
        logger.error("No IB position for %s. Nothing to adopt.", args.ticker)
        return 1
    qty = int(pos.get("quantity") or pos.get("position") or 0)
    direction = "BUY" if qty > 0 else "SELL"
    contracts = abs(qty)
    sec_type = pos.get("sec_type", "")
    conid = pos.get("conid")
    raw_avg_cost = float(pos.get("avg_cost") or 0)

    # IB returns avg_cost as notional (qty × multiplier × price) for futures.
    # Get the underlying entry price by reading the most recent matching fill.
    fill = _find_matching_recent_fill(
        client, args.ticker, "B" if direction == "BUY" else "S",
    )
    if not fill:
        logger.error("No matching recent fill found for %s %s. Try --strategy untracked instead.",
                     args.ticker, direction)
        return 1
    try:
        entry_price = float(fill.get("price") or 0)
    except (TypeError, ValueError):
        entry_price = 0
    if not entry_price:
        logger.error("Could not parse entry_price from matching fill.")
        return 1
    perm_id = str(fill.get("order_id") or "")
    fill_time = fill.get("trade_time", "")

    # 2. Confirm strat_pos doesn't already exist
    rdb = _connect_redis()
    key = f"ibkr:strat_pos:{args.ticker}:{args.strategy}"
    if rdb.get(key):
        logger.error("strat_pos %s already exists. Adoption refused — clear it first if you really want.",
                     key)
        return 1

    summary = (
        f"Would adopt:\n"
        f"  ticker:    {args.ticker} (sec={sec_type} conid={conid})\n"
        f"  qty:       {qty:+d} contracts\n"
        f"  direction: {direction}\n"
        f"  entry:     {entry_price} (from fill at {fill_time}, order_id={perm_id})\n"
        f"  strategy:  {args.strategy}\n"
        f"  stop:      {args.stop or '(none — set with --stop)'}"
    )
    logger.info(summary)

    if not args.execute:
        logger.info("Dry run — pass --execute to actually adopt.")
        return 0

    # 3. Optionally place a protective stop FIRST so adoption never leaves
    #    the position unprotected.
    stop_order_id = ""
    if args.stop and sec_type == "FUT" and conid:
        try:
            stop_side = "SELL" if direction == "BUY" else "BUY"
            stop_payload = {
                "orders": [{
                    "conid": int(conid),
                    "orderType": "STP",
                    "price": float(args.stop),
                    "side": stop_side,
                    "quantity": contracts,
                    "tif": "GTC",
                }]
            }
            r = client.place_order(stop_payload)
            if isinstance(r, list) and r and isinstance(r[0], dict):
                stop_order_id = str(r[0].get("order_id", "") or "")
            elif isinstance(r, dict):
                stop_order_id = str(r.get("order_id", "") or "")
            logger.info("Protective stop placed: %s STP @ %s (id=%s)",
                        stop_side, args.stop, stop_order_id or "(no id)")
        except Exception as e:
            logger.warning("Protective stop placement failed: %s — proceeding without stop", e)

    # 4. Create the strat_pos row
    multiplier = 5.0 if args.ticker == "MES" else (
        2.0 if args.ticker == "MNQ" else
        10.0 if args.ticker == "MGC" else
        100.0 if args.ticker == "MCL" else 1.0
    )
    strat_pos = {
        "ticker": args.ticker,
        "strategy": args.strategy,
        "direction": direction,
        "contracts": contracts,
        "entry_price": entry_price,
        "perm_id": perm_id,
        "stop_order_id": stop_order_id or "",
        "stop_price": float(args.stop or 0),
        "target_order_id": "",
        "target_price": 0,
        "multiplier": multiplier,
        "metadata": {"adopted": True, "adopted_at": datetime.now(timezone.utc).isoformat()},
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    rdb.setex(key, 7 * 24 * 3600, json.dumps(strat_pos))
    logger.info("strat_pos written: %s", key)

    # 5. Write diary OPEN
    try:
        from lumisignals import diary
        diary.record_event(
            broker="ib",
            broker_trade_id=perm_id,
            strategy_id=(diary.strategy_slug(args.strategy) or args.strategy),
            ticker=args.ticker,
            state=diary.State.OPEN,
            reason=f"adopted from IB orphan (script)",
            expected_qty=qty,
            entry_price=entry_price,
            stop_price=float(args.stop or 0) or None,
            meta={
                "adopted": True,
                "stop_order_id": stop_order_id or None,
                "multiplier": multiplier,
            },
        )
        logger.info("Diary OPEN event recorded for broker_trade_id=%s", perm_id)
    except Exception as e:
        logger.warning("Diary write failed (strat_pos still adopted): %s", e)

    # 6. Telegram summary
    try:
        from lumisignals.supabase_client import send_telegram_message
        send_telegram_message(
            f"🪝 *Orphan adopted* — {args.ticker} {direction} {contracts}× "
            f"@ {entry_price} attached to `{args.strategy}`."
        )
    except Exception:
        pass

    logger.info("Adoption complete. The bot will now manage this position normally.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
