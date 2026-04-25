"""Swing Trade Auto-Scanner.

Periodically scans stocks for setups at Monthly/Weekly untouched levels,
then checks for candle confirmation (overwhelm/reclaim) before triggering
credit + debit spread trades via the options pipeline.

Flow:
1. Scan SWING_TICKERS for proximity to M/W S1/D1 levels
2. For each setup, pull 1H or 4H candles from Polygon
3. Check for overwhelm or wick rejection pattern
4. If confirmed + score >= 2 + no existing position → auto-trade
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

SERVER_URL = os.environ.get("LUMISIGNALS_URL", "https://bot.lumitrade.ai")
SCAN_INTERVAL_HOURS = 4  # Scan every 4 hours
MIN_SCORE = 2  # Minimum HTF alignment score to auto-trade
PROXIMITY_PCT = 2.0  # How close price must be to level (%)


def check_candle_confirmation(massive_client, ticker: str, level_price: float,
                               direction: str, timeframe: str = "1h") -> dict:
    """Check if the latest candles show a confirmation pattern at a level.

    Patterns checked:
    1. Overwhelm: current candle body > previous opposite candle body,
       and price reclaims the level
    2. Wick rejection: long wick touching the level with close away from it
       (hammer at demand, shooting star at supply)

    Args:
        massive_client: MassiveClient instance
        ticker: Stock ticker
        level_price: The S1 or D1 price level
        direction: "BUY" (at demand) or "SELL" (at supply)
        timeframe: "1h" or "4h"

    Returns:
        {"confirmed": bool, "pattern": str, "candle": dict} or {"confirmed": False}
    """
    try:
        candles = massive_client.get_candles(ticker, timeframe, 5)
        if len(candles) < 3:
            return {"confirmed": False, "reason": "Not enough candle data"}

        # Current (most recent completed) and previous candles
        curr = candles[-1]
        prev = candles[-2]

        curr_body = abs(curr.close - curr.open)
        prev_body = abs(prev.close - prev.open)
        curr_range = curr.high - curr.low
        curr_is_green = curr.close > curr.open
        curr_is_red = curr.close < curr.open
        prev_is_green = prev.close > prev.open
        prev_is_red = prev.close < prev.open

        # Minimum body size: avoid doji-overwhelms-doji
        avg_body = sum(abs(c.close - c.open) for c in candles[-5:]) / 5
        has_real_body = curr_body >= avg_body * 0.8

        if direction == "BUY":
            # At demand zone — looking for bullish confirmation

            # Pattern 1: Green overwhelms red + close above demand
            overwhelm = (curr_is_green and prev_is_red and has_real_body
                        and curr_body > prev_body
                        and curr.close > level_price)

            # Pattern 2: Hammer / wick rejection at demand
            # Long lower wick (>= 60% of range), small body, close near high
            lower_wick = min(curr.open, curr.close) - curr.low
            wick_rejection = (curr_range > 0
                             and lower_wick / curr_range >= 0.6
                             and curr.close > level_price
                             and curr.low <= level_price * 1.002)  # wick touched or pierced level

            if overwhelm:
                return {
                    "confirmed": True,
                    "pattern": "Green overwhelm + reclaim",
                    "candle": {"open": curr.open, "high": curr.high,
                              "low": curr.low, "close": curr.close},
                    "timeframe": timeframe,
                }
            elif wick_rejection:
                return {
                    "confirmed": True,
                    "pattern": "Wick rejection at demand",
                    "candle": {"open": curr.open, "high": curr.high,
                              "low": curr.low, "close": curr.close},
                    "timeframe": timeframe,
                }

        elif direction == "SELL":
            # At supply zone — looking for bearish confirmation

            # Pattern 1: Red overwhelms green + close below supply
            overwhelm = (curr_is_red and prev_is_green and has_real_body
                        and curr_body > prev_body
                        and curr.close < level_price)

            # Pattern 2: Shooting star / wick rejection at supply
            upper_wick = curr.high - max(curr.open, curr.close)
            wick_rejection = (curr_range > 0
                             and upper_wick / curr_range >= 0.6
                             and curr.close < level_price
                             and curr.high >= level_price * 0.998)

            if overwhelm:
                return {
                    "confirmed": True,
                    "pattern": "Red overwhelm + rejection",
                    "candle": {"open": curr.open, "high": curr.high,
                              "low": curr.low, "close": curr.close},
                    "timeframe": timeframe,
                }
            elif wick_rejection:
                return {
                    "confirmed": True,
                    "pattern": "Wick rejection at supply",
                    "candle": {"open": curr.open, "high": curr.high,
                              "low": curr.low, "close": curr.close},
                    "timeframe": timeframe,
                }

        # Check volume (above average = stronger signal)
        # Volume data may not be available for indices
        try:
            volumes = [float(getattr(c, 'volume', 0) or 0) for c in candles[-5:]]
            avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
            curr_vol = volumes[-1]
            if avg_vol > 0 and curr_vol > avg_vol * 1.2:
                # Above average volume but no pattern — not enough
                pass
        except Exception:
            pass

        return {"confirmed": False, "reason": "No confirmation pattern"}

    except Exception as e:
        logger.warning("Candle confirmation error for %s: %s", ticker, e)
        return {"confirmed": False, "reason": str(e)}


def check_existing_position(ticker: str, rdb) -> bool:
    """Check if we already have an open spread on this ticker."""
    try:
        # Check pending orders
        for key in rdb.scan_iter("ibkr:order:pending:*"):
            raw = rdb.get(key)
            if not raw:
                continue
            order = json.loads(raw)
            if (order.get("ticker", "").upper() == ticker.upper()
                    and order.get("status") in ("queued", "placing", "Submitted", "PreSubmitted")):
                return True

        # Check recent trades (don't re-enter same ticker within 24h)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dedup_key = f"swing:traded:{ticker}:{today}"
        if rdb.get(dedup_key):
            return True

    except Exception:
        pass
    return False


def run_swing_scan(massive_client, rdb, api_key: str, dry_run: bool = False) -> List[dict]:
    """Run a full swing scan cycle.

    1. Scan SWING_TICKERS for M/W level proximity
    2. Check candle confirmation on each setup
    3. Trigger options trades for confirmed setups

    Args:
        massive_client: MassiveClient instance
        rdb: Redis connection
        api_key: Polygon/Massive API key
        dry_run: If True, don't actually place trades

    Returns:
        List of triggered setups
    """
    from .untouched_levels import scan_ticker
    from .massive_client import SWING_TICKERS

    triggered = []
    scanned = 0
    near_level = 0

    logger.info("=== Swing scan starting — %d tickers ===", len(SWING_TICKERS))

    for ticker in SWING_TICKERS:
        try:
            # Get current price
            candles_1d = massive_client.get_candles(ticker, "1d", 2)
            if not candles_1d:
                continue
            price = candles_1d[-1].close
            scanned += 1

            # Scan M/W levels only
            levels = scan_ticker(massive_client, ticker, price, ["1mo", "1w"])

            for tf_label, lvl in levels.items():
                for level_type, level_price in [("D1", lvl.demand1), ("S1", lvl.supply1)]:
                    if level_price is None or level_price == 0:
                        continue

                    dist_pct = (price - level_price) / price * 100
                    is_demand = level_type == "D1"

                    # Check proximity
                    if is_demand and not (0 < dist_pct <= PROXIMITY_PCT):
                        continue
                    if not is_demand and not (-PROXIMITY_PCT <= dist_pct < 0):
                        continue

                    near_level += 1
                    direction = "BUY" if is_demand else "SELL"

                    # Score: trend alignment
                    score = 0
                    if (direction == "BUY" and lvl.trend == "UP") or (direction == "SELL" and lvl.trend == "DOWN"):
                        score += 1
                    if lvl.adx >= 25:
                        score += 1

                    if score < MIN_SCORE:
                        continue

                    # Check for existing position
                    clean_ticker = ticker.replace("I:", "")
                    if check_existing_position(clean_ticker, rdb):
                        logger.info("SKIP %s — already have position", ticker)
                        continue

                    # Check candle confirmation on both 1H and 4H
                    confirmation = check_candle_confirmation(
                        massive_client, ticker, level_price, direction, "4h"
                    )
                    if not confirmation["confirmed"]:
                        # Try hourly
                        confirmation = check_candle_confirmation(
                            massive_client, ticker, level_price, direction, "1h"
                        )

                    if not confirmation["confirmed"]:
                        continue

                    # CONFIRMED SETUP — trigger trade
                    setup = {
                        "ticker": ticker,
                        "clean_ticker": clean_ticker,
                        "price": round(price, 2),
                        "level": round(level_price, 2),
                        "level_type": level_type,
                        "tf": tf_label,
                        "direction": direction,
                        "score": score,
                        "trend": lvl.trend,
                        "adx": lvl.adx,
                        "distance_pct": round(dist_pct, 2),
                        "pattern": confirmation["pattern"],
                        "confirm_tf": confirmation["timeframe"],
                    }

                    logger.info("SWING TRIGGER: %s %s at %s %s (%.1f%% from %s level) — %s on %s",
                               direction, ticker, tf_label, level_type,
                               abs(dist_pct), level_type, confirmation["pattern"],
                               confirmation["timeframe"])

                    if not dry_run:
                        _execute_swing_trade(setup, rdb, api_key)

                    triggered.append(setup)

        except Exception as e:
            logger.debug("Swing scan error for %s: %s", ticker, e)
            continue

    logger.info("=== Swing scan complete: %d scanned, %d near levels, %d triggered ===",
                scanned, near_level, len(triggered))
    return triggered


def _execute_swing_trade(setup: dict, rdb, api_key: str):
    """Execute a swing trade by sending to the options webhook."""
    try:
        ticker = setup["clean_ticker"]
        direction = setup["direction"]
        zone_type = "demand" if direction == "BUY" else "supply"

        # Send to the TradingView webhook endpoint (reuses existing options pipeline)
        payload = {
            "ticker": ticker,
            "direction": direction,
            "strategy": "swing_scanner",
            "key": os.environ.get("TV_WEBHOOK_KEY", "lumisignals2026"),
            "type": "stock",
            "spread_type": "both",
            "trade_duration": "daily",
            "score": setup["score"],
            "level_price": setup["level"],
            "level_tf": setup["tf"],
            "dte": 7,  # 7 DTE for swing trades
        }

        resp = requests.post(f"{SERVER_URL}/api/webhook/tradingview",
                           json=payload, timeout=15)

        if resp.ok:
            result = resp.json()
            logger.info("Swing trade queued: %s %s — %s", direction, ticker, result.get("status"))

            # Mark as traded today to prevent re-entry
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            rdb.setex(f"swing:traded:{ticker}:{today}", 86400, "1")

            # Send email alert
            try:
                from .alerts import send_alert, AlertType
                alert_pass = os.environ.get("ALERT_EMAIL_PASSWORD", "")
                if alert_pass:
                    send_alert(
                        AlertType.TRADE_OPENED,
                        f"Swing {direction} {ticker} — {setup['tf']} {setup['level_type']}",
                        f"{setup['pattern']} on {setup['confirm_tf']}",
                        details={
                            "Ticker": ticker,
                            "Direction": direction,
                            "Level": f"{setup['tf']} {setup['level_type']} @ ${setup['level']}",
                            "Distance": f"{setup['distance_pct']:.1f}%",
                            "Pattern": setup["pattern"],
                            "Confirmation TF": setup["confirm_tf"],
                            "Score": str(setup["score"]),
                            "Trend": f"{setup['trend']} (ADX {setup['adx']:.0f})",
                        },
                        smtp_pass=alert_pass,
                    )
            except Exception:
                pass
        else:
            logger.error("Swing trade failed: %s — %s", resp.status_code, resp.text[:200])

    except Exception as e:
        logger.error("Swing trade execution error: %s", e)


def should_scan_now() -> bool:
    """Check if it's time to scan (market hours, every 4 hours)."""
    now = datetime.now(timezone.utc)
    et_hour = (now.hour - 4) % 24  # Rough ET conversion (EDT)

    # Market hours: 9:30 AM - 4:00 PM ET
    if et_hour < 9 or et_hour >= 16:
        return False

    # Weekend check
    if now.weekday() >= 5:
        return False

    # Scan at 9:30, 13:30 (1:30 PM), and 15:00 (3 PM) ET
    # In UTC that's roughly 13:30, 17:30, 19:00
    scan_hours_utc = [13, 17, 19]
    return now.hour in scan_hours_utc and now.minute < 35
