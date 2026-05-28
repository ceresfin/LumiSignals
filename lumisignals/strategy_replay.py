"""Replay strategy signal logic over historical bars.

Used by /api/strategies/expected-signals to surface what Pine *should*
have fired vs. what actually arrived as INTENT_OPEN events — the
"missed signals" detector.

Currently supports 2n20 (VWAP + overwhelm). Mirrors the Pine 2n20.pine
script bar-for-bar so the comparison is apples-to-apples.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = timezone(timedelta(hours=-4))  # EDT fallback

from .overwhelm_detector import detect_overwhelm, detect_vwap_cross


def _bar_time_utc(bar: dict) -> Optional[datetime]:
    """Normalize a bar's timestamp to a tz-aware UTC datetime."""
    t = bar.get("time", None)
    if t is None:
        return None
    if isinstance(t, (int, float)):
        try:
            return datetime.fromtimestamp(int(t), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def replay_2n20_signals(bars: list, *,
                        vwap_anchor_hour_et: int = 18,
                        window_start_et: int = 0,
                        window_end_et: int = 24,
                        min_body_pct: float = 30.0) -> list:
    """Run 2n20 entry+exit logic across bars, return every signal that fires.

    Bars must be ordered oldest-first and carry OHLC + volume + a time field
    that's either unix-seconds (int) or an ISO-8601 string in UTC.

    Returns list of dicts:
        {bar_time:   ISO UTC string,
         direction:  BUY | SELL | CLOSE_LONG | CLOSE_SHORT,
         reason:     'VWAP+Green Overwhelm' | 'VWAP+Red Overwhelm'
                     | 'Red Takeout Green' | 'Green Takeout Red'
                     | 'VWAP Cross',
         close:      bar close,
         vwap:       VWAP value at this bar}

    Tracks inLong / inShort state across bars so entries don't re-fire while
    already in a position — mirrors Pine's `freq_once_per_bar_close` behavior.
    """
    signals: list = []
    in_long = False
    in_short = False

    # Session-anchored cumulative VWAP. Anchor resets daily at the configured
    # ET hour (default 18:00 = Globex open).
    vwap_num = 0.0
    vwap_den = 0.0
    last_anchor_date = None

    # Build a parallel list of {**bar, _time_utc, _time_et} for fast access.
    normalized: list = []
    for b in bars:
        ut = _bar_time_utc(b)
        if ut is None:
            continue
        normalized.append({
            "open": float(b.get("open", 0)),
            "high": float(b.get("high", 0)),
            "low": float(b.get("low", 0)),
            "close": float(b.get("close", 0)),
            "volume": int(b.get("volume", 1) or 1),
            "_time_utc": ut,
            "_time_et": ut.astimezone(_ET),
        })

    for i, b in enumerate(normalized):
        bar_et = b["_time_et"]
        et_hour = bar_et.hour
        et_minute = bar_et.minute
        et_time_int = et_hour * 100 + et_minute
        weekday = bar_et.weekday()

        # CME maintenance break: 17:00 ≤ time < 18:00 ET → skip all logic.
        in_session = not (1700 <= et_time_int < 1800)
        # Weekend gates (matches Pine: Sat off, Fri post-17:00 off, Sun pre-18:00 off)
        if weekday == 5:                              # Saturday
            in_session = False
        elif weekday == 4 and et_hour >= 17:          # Friday post-close
            in_session = False
        elif weekday == 6 and et_hour < 18:           # Sunday pre-Globex
            in_session = False

        # Configured trading window (hour-bucket, with wrap support).
        if window_start_et < window_end_et:
            in_window = (window_start_et <= et_hour < window_end_et)
        else:
            in_window = (et_hour >= window_start_et) or (et_hour < window_end_et)

        # Anchor date = ET-date of the most recent 18:00 ET boundary at-or-before
        # this bar. So 14:00 ET on Tue → anchor = Mon's date.
        anchor_dt = bar_et.replace(hour=vwap_anchor_hour_et,
                                   minute=0, second=0, microsecond=0)
        if bar_et < anchor_dt:
            anchor_date = (bar_et - timedelta(days=1)).date()
        else:
            anchor_date = bar_et.date()
        if anchor_date != last_anchor_date:
            vwap_num = 0.0
            vwap_den = 0.0
            last_anchor_date = anchor_date

        vol = max(b["volume"], 1)
        hlc3 = (b["high"] + b["low"] + b["close"]) / 3
        vwap_num += hlc3 * vol
        vwap_den += vol
        vwap = vwap_num / vwap_den if vwap_den > 0 else None

        # Need vwap + session + 12 bars of history for overwhelm detection.
        if vwap is None or not in_session or i < 12:
            continue

        close = b["close"]
        above_vwap = close > vwap
        below_vwap = close < vwap

        # Build a plain dict slice for the detector (it expects the public keys).
        window = [{"open": x["open"], "high": x["high"],
                   "low": x["low"], "close": x["close"]}
                  for x in normalized[: i + 1]]
        green_ow, red_ow = detect_overwhelm(window, min_body_pct=min_body_pct)

        # VWAP cross — uses prev bar's close vs prev bar's vwap. We don't have
        # prev vwap stored, so approximate: VWAP changes are slow relative to
        # 2m bars; use current vwap as the crossing line. Pine does the same
        # (it tests close < vwap and close[1] >= vwap).
        prev_close = normalized[i - 1]["close"] if i > 0 else close
        crossed_below = (close < vwap and prev_close >= vwap)
        crossed_above = (close > vwap and prev_close <= vwap)

        out_iso = b["_time_utc"].isoformat()

        # EXIT LOGIC — clear state first so an entry can fire on the same bar
        # (Pine does state transitions sequentially: exit → entry within bar).
        if in_long:
            if red_ow:
                in_long = False
                signals.append({"bar_time": out_iso, "direction": "CLOSE_LONG",
                               "reason": "Red Takeout Green",
                               "close": close, "vwap": round(vwap, 2)})
            elif crossed_below:
                in_long = False
                signals.append({"bar_time": out_iso, "direction": "CLOSE_LONG",
                               "reason": "VWAP Cross",
                               "close": close, "vwap": round(vwap, 2)})
        elif in_short:
            if green_ow:
                in_short = False
                signals.append({"bar_time": out_iso, "direction": "CLOSE_SHORT",
                               "reason": "Green Takeout Red",
                               "close": close, "vwap": round(vwap, 2)})
            elif crossed_above:
                in_short = False
                signals.append({"bar_time": out_iso, "direction": "CLOSE_SHORT",
                               "reason": "VWAP Cross",
                               "close": close, "vwap": round(vwap, 2)})

        # ENTRY LOGIC (only if in_window — exits ignore the window, mirroring
        # Pine, but entries are window-gated).
        if not in_window:
            continue
        if not in_long and not in_short:
            if above_vwap and green_ow:
                in_long = True
                signals.append({"bar_time": out_iso, "direction": "BUY",
                               "reason": "VWAP+Green Overwhelm",
                               "close": close, "vwap": round(vwap, 2)})
            elif below_vwap and red_ow:
                in_short = True
                signals.append({"bar_time": out_iso, "direction": "SELL",
                               "reason": "VWAP+Red Overwhelm",
                               "close": close, "vwap": round(vwap, 2)})

    return signals


def diff_against_diary(expected: list, actual: list,
                       bar_secs: int = 120,
                       delivery_slack_secs: int = 60) -> dict:
    """Compare expected signals to actual INTENT_OPEN diary events.

    `bar_time` in the replay output is the bar's OPEN time (matches TV's
    chart label). Pine fires its alert at bar CLOSE — i.e. bar_time +
    bar_secs. Webhook delivery + bot processing add another ~5-30s. So an
    expected entry at bar T matches any INTENT_OPEN whose event_time is
    in [T + bar_secs, T + bar_secs + delivery_slack_secs].

    Defaults: bar_secs=120 (2m bars), delivery_slack_secs=60 → match window
    is [T+120s, T+180s].

    Args:
        expected: output of replay_2n20_signals()
        actual:   trade_events rows where state ∈ {INTENT_OPEN}
        window_seconds: matching tolerance after the bar close

    Returns:
        {missed:   expected signals with no matching INTENT_OPEN,
         matched:  expected signals that have a match (paired),
         extras:   INTENT_OPEN events with no matching expected signal}
    """
    # Index actuals by direction so we don't match BUY against SELL.
    actuals_by_dir: dict = {"BUY": [], "SELL": [], "CLOSE_LONG": [], "CLOSE_SHORT": []}
    for a in actual:
        reason = (a.get("reason") or "").upper()
        if "CLOSE_LONG" in reason or "X-LONG" in reason:
            actuals_by_dir["CLOSE_LONG"].append(a)
        elif "CLOSE_SHORT" in reason or "X-SHORT" in reason:
            actuals_by_dir["CLOSE_SHORT"].append(a)
        elif " BUY" in reason or reason.startswith("BUY"):
            actuals_by_dir["BUY"].append(a)
        elif " SELL" in reason or reason.startswith("SELL"):
            actuals_by_dir["SELL"].append(a)

    matched: list = []
    missed: list = []
    used_actual_indices: set = set()

    for e in expected:
        if e["direction"] not in ("BUY", "SELL"):
            # Only diff entries; exits are noisy and not the main concern.
            continue
        try:
            bar_dt = datetime.fromisoformat(e["bar_time"].replace("Z", "+00:00"))
        except Exception:
            continue
        candidates = actuals_by_dir.get(e["direction"], [])
        match = None
        for ai, a in enumerate(candidates):
            if id(a) in used_actual_indices:
                continue
            try:
                a_dt = datetime.fromisoformat(a["event_time"].replace("Z", "+00:00"))
            except Exception:
                continue
            delta = (a_dt - bar_dt).total_seconds()
            if bar_secs <= delta <= bar_secs + delivery_slack_secs:
                match = a
                used_actual_indices.add(id(a))
                break
        if match:
            matched.append({**e, "matched_event_time": match["event_time"]})
        else:
            missed.append(e)

    # Extras = entries we recorded but the replay didn't predict.
    extras: list = []
    for a in actual:
        reason = (a.get("reason") or "").upper()
        if not (" BUY" in reason or " SELL" in reason
                or reason.startswith("BUY") or reason.startswith("SELL")):
            continue
        if id(a) in used_actual_indices:
            continue
        extras.append(a)

    return {"missed": missed, "matched": matched, "extras": extras}
