"""Interactive Brokers (IBeam/CPAPI) options-chain provider.

Mirrors the (chain, error) output of swing_setup._fetch_schwab_chain so it
can be a drop-in source for the MTF trade-setup spread builder — sourcing
strikes + greeks from the same IBeam gateway we already use for orders and
positions (removes the separate Schwab-OAuth dependency).

Each chain row: {expiry:"YYYY-MM-DD", strike:float, delta:float (SIGNED:
+ calls, - puts), bid:float, ask:float, iv:float, oi:int}. _pick_options_spread
reads only expiry/strike/delta/bid/ask.

Efficiency-first: resolve the underlying once, pick the SINGLE target month,
band the strikes to the OTM region we actually trade (~20-45 strikes), then
one secdef/info per strike (each returns all expiries, filtered to one) and a
single batched marketdata snapshot for greeks.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
           "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
# Cash/index underlyings resolve under IND (and SPX uses the SPXW weekly
# class). Mirrors swing_setup._POLYGON_INDEX_SYMBOLS.
_INDEX_SYMBOLS = {"SPX", "NDX", "RUT", "VIX", "DJI", "XSP", "XND"}
_BAND_PCT = 0.18          # how far OTM (fraction of price) to scan strikes
_MAX_STRIKES = 45         # hard cap on snapshot size
# snapshot fields: 31 last, 84 bid, 86 ask, 7308 delta, 7283 implied vol
SNAP_FIELDS = "31,84,86,7308,7283"


def _month_token_to_date(tok):
    """'JUN26' -> date(2026, 6, 1) (first of month). None on parse failure."""
    tok = (tok or "").strip().upper()
    if len(tok) < 5:
        return None
    mon = _MONTHS.get(tok[:3])
    try:
        yy = int(tok[3:5])
    except ValueError:
        return None
    if mon is None:
        return None
    return datetime(2000 + yy, mon, 1, tzinfo=timezone.utc).date()


def _to_float(v):
    """Snapshot values arrive as strings, sometimes with a leading marker
    (e.g. 'C0.49'). Strip non-numeric leaders; '' / None -> None."""
    try:
        if v is None or v == "":
            return None
        return float(str(v).lstrip("CHc "))
    except (TypeError, ValueError):
        return None


def _resolve_underlying(client, ticker):
    """(conid, [MMMYY months]) for the option root. IND-first for index
    symbols, STK otherwise, with a cross-fallback."""
    primary = "IND" if ticker.upper() in _INDEX_SYMBOLS else "STK"
    other = "STK" if primary == "IND" else "IND"
    results = client.search_contract(ticker, primary) or []
    if not results:
        results = client.search_contract(ticker, other) or []
    if not results:
        return None, None
    row = results[0]
    conid = row.get("conid")
    months = []
    for sec in (row.get("sections") or []):
        if sec.get("secType") == "OPT" and sec.get("months"):
            months = [m for m in str(sec["months"]).split(";") if m]
            break
    return conid, months


def _pick_month(months, cfg, today):
    """MMMYY token whose calendar month contains (today + dte_target).
    Falls back to the month anchor nearest the target."""
    want = today + timedelta(days=cfg.dte_target)
    by_ym = {}
    for tok in months:
        d = _month_token_to_date(tok)
        if d:
            by_ym[(d.year, d.month)] = tok
    if (want.year, want.month) in by_ym:
        return by_ym[(want.year, want.month)]
    cands = [(tok, abs((_month_token_to_date(tok) - want).days))
             for tok in months if _month_token_to_date(tok)]
    return min(cands, key=lambda c: c[1])[0] if cands else None


def _band_strikes(strikes, price, is_call):
    """OTM strikes around price (~_BAND_PCT wide), capped to _MAX_STRIKES
    nearest the money."""
    if not price:
        return []
    lo, hi = (price, price * (1 + _BAND_PCT)) if is_call \
        else (price * (1 - _BAND_PCT), price)
    band = sorted(k for k in strikes if lo <= k <= hi)
    if len(band) > _MAX_STRIKES:
        band = sorted(sorted(band, key=lambda k: abs(k - price))[:_MAX_STRIKES])
    return band


def _pick_maturity(info, cfg, today):
    """From one strike's contract list, pick the maturityDate (YYYYMMDD)
    nearest dte_target within [dte_min, dte_max]; else nearest overall."""
    mats = []
    for o in info:
        m = str(o.get("maturityDate") or "").replace("-", "")
        if len(m) != 8:
            continue
        try:
            d = datetime(int(m[:4]), int(m[4:6]), int(m[6:8]),
                         tzinfo=timezone.utc).date()
        except ValueError:
            continue
        mats.append((m, (d - today).days))
    if not mats:
        return None
    in_win = [m for m in mats if cfg.dte_min <= m[1] <= cfg.dte_max]
    pool = in_win or mats
    return min(pool, key=lambda m: abs(m[1] - cfg.dte_target))[0]


def _match_contract(info, target_mat, prefer_class):
    """Row at target maturity, preferring a trading class (SPXW for SPX)."""
    matches = [o for o in info
               if str(o.get("maturityDate") or "").replace("-", "") == target_mat]
    if prefer_class:
        pref = [o for o in matches if o.get("tradingClass") == prefer_class]
        if pref:
            return pref[0]
    return matches[0] if matches else None


def _batch_snapshot(client, conids):
    """Warm + poll one batched snapshot; return {conid_str: row}. Stops once
    ~80% of conids report a delta (CPAPI fills fields over a few polls)."""
    csv = ",".join(str(c) for c in conids)
    out = {}
    need = max(1, int(0.8 * len(conids)))
    for _ in range(6):
        try:
            r = client._request("GET", "/iserver/marketdata/snapshot",
                                 params={"conids": csv, "fields": SNAP_FIELDS})
        except Exception:
            r = None
        if isinstance(r, list):
            for row in r:
                cid = str(row.get("conid") or "")
                if cid:
                    out[cid] = row
            have = sum(1 for c in conids
                       if out.get(str(c), {}).get("7308") not in (None, ""))
            if have >= need:
                break
        time.sleep(0.5)
    return out


def fetch_ib_chain(ticker, cfg, spread_type, underlying_price
                   ) -> Tuple[Optional[List[dict]], Optional[str]]:
    """(chain, error) sourced from IBeam CPAPI. See module docstring for the
    row shape. `cfg` is duck-typed (reads dte_target/dte_min/dte_max)."""
    is_call = spread_type == "call_debit"
    right = "C" if is_call else "P"

    try:
        from .ibkr_cpapi import CPAPIClient
        client = CPAPIClient(base_url=os.environ.get(
            "CPAPI_BASE_URL", "https://localhost:5000/v1/api"))
    except Exception as e:
        return None, f"IB: client init failed: {e}"
    # ensure_session is best-effort: the bot's sync loop keeps the gateway
    # session warm, and a transient tickle/reauth timeout here must NOT abort
    # the fetch (the data endpoints below work as long as the gateway is
    # authenticated). If the gateway is truly down, the calls below fail and
    # we return an error → dispatcher falls back to the other source.
    try:
        client.ensure_session()
    except Exception:
        pass

    try:
        conid, months = _resolve_underlying(client, ticker)
    except Exception as e:
        return None, f"IB: underlying lookup failed: {e}"
    if not conid:
        return None, f"IB: underlying {ticker} not found"
    if not months:
        return None, f"IB: no option months for {ticker}"

    today = datetime.now(timezone.utc).date()
    month_tok = _pick_month(months, cfg, today)
    if not month_tok:
        return None, "IB: no usable option month"

    try:
        st = client._request("GET", "/iserver/secdef/strikes",
                             params={"conid": conid, "secType": "OPT",
                                     "month": month_tok})
    except Exception as e:
        return None, f"IB: strikes lookup failed: {e}"
    raw_strikes = (st or {}).get("call" if is_call else "put") or []
    if not raw_strikes:
        return None, f"IB: no {right} strikes for {month_tok}"

    band = _band_strikes([float(s) for s in raw_strikes], underlying_price, is_call)
    if not band:
        return None, "IB: no strikes in OTM band"

    prefer_class = "SPXW" if ticker.upper() == "SPX" else None
    target_mat = None
    strike_conid = {}
    # Resolve ATM-first so target_mat is set from a near-the-money strike,
    # which lists every (daily/weekly) expiry. A far-OTM strike can be missing
    # the near-dated expiries and would skew the maturity pick.
    for k in sorted(band, key=lambda s: abs(s - underlying_price)):
        try:
            info = client._request("GET", "/iserver/secdef/info",
                params={"conid": conid, "sectype": "OPT", "month": month_tok,
                        "strike": k, "right": right, "exchange": "SMART"})
        except Exception:
            continue
        if not isinstance(info, list) or not info:
            continue
        if target_mat is None:
            target_mat = _pick_maturity(info, cfg, today)
            if not target_mat:
                continue
        row = _match_contract(info, target_mat, prefer_class)
        if row and row.get("conid"):
            strike_conid[k] = row["conid"]
    if not strike_conid or not target_mat:
        return None, "IB: no contracts resolved in OTM band"

    expiry_iso = f"{target_mat[:4]}-{target_mat[4:6]}-{target_mat[6:8]}"
    snap = _batch_snapshot(client, list(strike_conid.values()))

    rows = []
    for k, cid in strike_conid.items():
        d = snap.get(str(cid)) or {}
        delta_raw = _to_float(d.get("7308"))
        if delta_raw is not None:
            delta = abs(delta_raw) if is_call else -abs(delta_raw)
        else:
            delta = 0.0   # selection falls back to its OTM heuristic on 0Δ
        rows.append({
            "expiry": expiry_iso,
            "strike": float(k),
            "delta": delta,
            "bid": _to_float(d.get("84")) or 0.0,
            "ask": _to_float(d.get("86")) or 0.0,
            "iv": _to_float(d.get("7283")) or 0.0,
            "oi": 0,
        })

    if not rows or all(r["delta"] == 0 for r in rows):
        return None, "IB: snapshot returned no greeks"
    logger.info("IB chain %s %s: %d strikes @ %s (delta-priced)",
                ticker, spread_type, len(rows), expiry_iso)
    return rows, None
