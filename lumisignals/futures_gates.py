"""Shared futures-order risk gates.

Both the TradingView webhook (saas/app.py) and the native 2n20 generator
(futures_scalp_2n20.py) must pass the same risk checks before queuing an MES
order, so neither path can bypass the kill-switch / runaway / cooldown /
position / reconcile / sync gates. The native generator used to write straight
to the order queue, skipping all of these — this module closes that gap.

Each underlying gate already lives in its own module (reconcile_gate,
kill_switch, runaway_guard, cooldown, position_guard); this just orchestrates
them in the same order + fail-open/closed semantics as the webhook handler.

`check_futures_action()` applies to ALL futures actions: reconcile_gate +
IB-sync-alive gate every action (entries AND closes); the kill-switch /
CME-maintenance / runaway / cooldown / position-size gates apply to ENTRIES
only (BUY/SELL) — closes always pass them so a position can always exit.
"""
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _rdb():
    import redis
    return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def check_futures_action(strategy, ticker, direction, contracts=1, rdb=None):
    """Return (allowed: bool, reason: str|None, detail: dict).

    `direction` ∈ BUY/SELL (entry) or CLOSE_LONG/CLOSE_SHORT (exit). Entries run
    every gate; closes run only reconcile_gate + sync-alive.
    """
    rdb = rdb or _rdb()
    is_entry = direction in ("BUY", "SELL")

    # 1. Restart-safety reconcile gate — fail-CLOSED, all actions. Don't act on
    #    uncertain state between a restart and the first reconcile pass.
    try:
        from lumisignals import reconcile_gate
        if reconcile_gate.is_locked():
            st = reconcile_gate.get_state()
            return False, "reconcile_gate_locked", {"gate_status": st.get("status")}
    except Exception as e:
        logger.warning("reconcile_gate check failed (fail-closed): %s", e)
        return False, "reconcile_gate_check_failed", {}

    if is_entry:
        # 2. Daily-loss kill switch — entries only, fail-open.
        try:
            from lumisignals import kill_switch
            if kill_switch.is_blocking_entry():
                st = kill_switch.get_state()
                return False, "kill_switch_tripped", {"day_pnl": round(st.get("day_pnl", 0.0), 2)}
        except Exception as e:
            logger.warning("kill switch check failed (fail-open): %s", e)

        # 3. CME maintenance window 17:00–18:00 ET.
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
            if now_et.hour == 17:
                return False, "cme_maintenance_window", {"et_time": now_et.strftime("%H:%M")}
        except Exception as e:
            logger.warning("CME maintenance check failed: %s", e)

        # 4. Runaway guard — daily entry cap + consecutive-loss streak, fail-open.
        try:
            from lumisignals import runaway_guard
            if runaway_guard.is_blocking_entry(strategy):
                st = runaway_guard.get_state(strategy)
                return False, "runaway_guard_tripped", {"trip_reason": st.get("trip_reason")}
        except Exception as e:
            logger.warning("runaway_guard check failed (fail-open): %s", e)

        # 5. Post-stop cooldown — armed by ibkr-sync when a bracket SL fires,
        #    fail-open. This is the real "don't immediately re-enter a stopped
        #    level" guard (replaces the old blanket 3-min dedup).
        try:
            from lumisignals import cooldown
            if cooldown.is_active(strategy, ticker):
                return False, "cooldown_active", {"ttl_seconds": cooldown.ttl(strategy, ticker)}
        except Exception as e:
            logger.warning("cooldown check failed (fail-open): %s", e)

        # 6. Position-size guard — refuse entries past the net-contract ceiling.
        try:
            from lumisignals import position_guard
            pg = position_guard.check(ticker, direction, int(contracts or 1))
            if pg.get("blocked"):
                return False, "position_size_guard", {
                    "projected_net": pg.get("projected_net"), "limit": pg.get("limit")}
        except Exception as e:
            logger.warning("position guard check failed (fail-open): %s", e)

    # 7. IB sync alive — all actions. Better to skip than pile up stale orders.
    try:
        ib_raw = rdb.get("ibkr:data:1")
        alive = False
        if ib_raw:
            last = json.loads(ib_raw).get("last_synced", "")
            if last:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
                alive = age < 90
        if not alive:
            return False, "ib_sync_offline", {}
    except Exception:
        return False, "ib_sync_offline", {}

    return True, None, {}
