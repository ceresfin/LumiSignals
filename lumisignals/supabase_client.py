"""Supabase client for LumiSignals bot — dual-write layer.

The bot writes to both Redis (for the Flask dashboard) and Supabase
(for the React Native app). Once the mobile app is live and the Flask
dashboard retired, the Redis writes can be removed.

Uses the service_role key to bypass RLS (server-side writes only).
"""

import json
import logging
import os
import urllib.request
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
    """Upsert a closed trade row in the trades table.

    Idempotent on (user_id, broker, broker_trade_id) — calling twice for
    the same close updates the existing row instead of inserting a new
    one. This prevents the "zombie close" failure mode we hit with the
    SPX vertical spreads, where a silently-failing broker close was
    retried thousands of times and each retry wrote a fresh row.

    Callers MUST supply a stable broker_trade_id (the original entry's
    broker order/perm/trade id). When the id is missing or empty we fall
    back to plain INSERT to avoid masking the bug — but those rows can't
    be deduped on retry, so the proper fix at the call site is to wire
    in the entry id.
    """
    sb = get_client()
    if not sb:
        return
    try:
        broker = trade.get("broker", "oanda")
        broker_trade_id = str(trade.get("id", trade.get("broker_trade_id", "")))

        row = {
            "user_id": user_id,
            "broker": broker,
            "broker_trade_id": broker_trade_id,
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
        opened = trade.get("time_opened", trade.get("opened_at", ""))
        closed = trade.get("time_closed", trade.get("closed_at", ""))
        if opened:
            row["opened_at"] = opened
        if closed:
            row["closed_at"] = closed
        row = {k: v for k, v in row.items() if v is not None}

        if broker_trade_id:
            # Idempotent path: look up the existing row by the natural
            # business key. UPDATE if present, INSERT if not. Two close
            # writes for the same trade converge on one row.
            existing = (sb.table("trades")
                          .select("id")
                          .eq("user_id", user_id)
                          .eq("broker", broker)
                          .eq("broker_trade_id", broker_trade_id)
                          .limit(1)
                          .execute())
            rows_found = existing.data or []
            if rows_found:
                trade_pk = rows_found[0]["id"]
                # Don't overwrite user_id/broker/broker_trade_id since
                # they're the lookup key — the rest of the columns get
                # the latest close-time values.
                update_payload = {k: v for k, v in row.items()
                                  if k not in ("user_id", "broker", "broker_trade_id")}
                sb.table("trades").update(update_payload).eq("id", trade_pk).execute()
                logger.info("Supabase: updated trade %s/%s/%s (id=%s)",
                            broker, trade.get("instrument"), broker_trade_id, trade_pk)
                return
        # Fallback: no broker_trade_id supplied OR no existing row → INSERT.
        sb.table("trades").insert(row).execute()
        logger.info("Supabase: recorded trade %s/%s/%s",
                    broker, trade.get("instrument"), broker_trade_id or "<no-id>")
    except Exception as e:
        # Surface as warning, not debug — silent failure here cost us a
        # day of debugging the SPX zombie flood.
        logger.warning("Supabase trade write error: %s", e)


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
            "take_profit": position.get("take_profit", position.get("target", None)),
            "unrealized_pl": position.get("unrealized_pl", 0),
            "pips": position.get("pips", 0),
            "strategy": position.get("strategy", ""),
            "model": position.get("model", ""),
            "metadata": position.get("metadata", None),
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


def send_push_notification(user_id: str, title: str, body: str, data: dict = None):
    """Send push notification via Expo Push API.

    Looks up the user's push_token from profiles table, then sends
    via Expo's push service (no server key needed for Expo tokens).
    """
    sb = get_client()
    if not sb:
        return
    try:
        # Get push token from profiles
        result = sb.table("profiles").select("push_token").eq("id", user_id).single().execute()
        token = result.data.get("push_token") if result.data else None
        if not token:
            return

        # Send via Expo Push API
        message = {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data or {},
        }
        req = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=json.dumps(message).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        logger.debug("Push sent to %s: %s", user_id[:8], title)
    except Exception as e:
        logger.debug("Push notification error: %s", e)


def send_telegram_message(text: str):
    """Send a Telegram message to TELEGRAM_CHAT_ID via TELEGRAM_BOT_TOKEN.

    Both must be set in the environment. No-op otherwise so we don't
    crash when Telegram isn't configured.

    Tries Markdown first for nice formatting; if Telegram rejects it
    (typically a 400 from an unescaped _ or * in user-supplied text),
    retries the same body without parse_mode so the alert still lands.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def _post(payload: dict):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)

    try:
        _post({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        logger.debug("Telegram sent: %s", text[:60])
    except urllib.error.HTTPError as e:
        if e.code == 400:
            # Markdown parse failed (likely a stray _ or * in user content).
            # Retry as plain text so the alert is never silently dropped.
            try:
                _post({
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                })
                logger.info("Telegram sent (plain-text fallback): %s", text[:60])
            except Exception as e2:
                logger.warning("Telegram plain-text fallback failed: %s", e2)
        else:
            logger.warning("Telegram send error: HTTP %s", e.code)
    except Exception as e:
        logger.warning("Telegram send error: %s", e)


def notify_trade_opened(
    user_id: str,
    instrument: str,
    direction: str,
    entry_price: float,
    strategy: str = "",
    stop: float = None,
    target: float = None,
    risk_dollars: float = None,
    reward_dollars: float = None,
    rr_ratio: float = None,
):
    """Send push + Telegram when a trade opens.

    Pass stop/target/risk/reward when available (HTF trades) and the message
    will include the full plan. Bare entries (2n20 scalps without pre-known
    targets) still work — those fields just stay out of the message.
    """
    dir_label = "BUY" if direction in ("BUY", "LONG") else "SELL"
    emoji = "🟢" if dir_label == "BUY" else "🔴"

    send_push_notification(
        user_id,
        f"{dir_label} {instrument}",
        f"Entry @ {entry_price:.5f} | {strategy}",
        {"type": "trade_opened", "instrument": instrument},
    )

    lines = [
        f"{emoji} *{dir_label} {instrument}*",
        f"Entry: `{entry_price:.5f}`",
    ]
    if target is not None:
        lines.append(f"Target: `{target:.5f}`")
    if stop is not None:
        lines.append(f"Stop: `{stop:.5f}`")
    if risk_dollars is not None:
        lines.append(f"Risk: `${risk_dollars:.2f}`")
    if reward_dollars is not None:
        lines.append(f"Reward: `${reward_dollars:.2f}`")
    if rr_ratio is not None:
        lines.append(f"R:R: `{rr_ratio:.2f}`")
    if strategy:
        lines.append(f"Strategy: {strategy}")
    send_telegram_message("\n".join(lines))


def notify_trade_closed(user_id: str, instrument: str, direction: str, pl: float, pips: float, reason: str = ""):
    """Send push + Telegram when a trade closes."""
    dir_label = "LONG" if direction in ("BUY", "LONG") else "SHORT"
    result = "WIN" if pl > 0 else "LOSS"
    emoji = "✅" if pl > 0 else "❌"
    send_push_notification(
        user_id,
        f"Closed {instrument} {dir_label} — {result}",
        f"P&L: ${pl:+.2f} | {pips:+.1f} pips | {reason}",
        {"type": "trade_closed", "instrument": instrument, "pl": pl},
    )
    send_telegram_message(
        f"{emoji} *Closed {instrument} {dir_label} — {result}*\n"
        f"P&L: `${pl:+.2f}` ({pips:+.1f} pips)\n"
        f"Reason: {reason}"
    )
