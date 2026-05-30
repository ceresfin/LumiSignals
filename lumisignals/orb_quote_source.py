"""Pluggable option-quote source for the ORB butterfly handler.

The motivating constraint: IB paper-account quotes are 15-min delayed
(field 6509="D"), which makes the butterfly's leg-pricing math wrong by
construction. Until the user's live IB account opens and real-time data
sharing propagates to paper, we need an alternative source of live
SPX 0DTE bid/ask. Once IB real-time is live, we want to switch back
without redeploying.

Implementations:

  SchwabQuoteSource   — bridge. Real-time SPX 0DTE quotes via Schwab's
                        /marketdata/v1/quotes endpoint. Free on a funded
                        Schwab brokerage account. Requires a 7-day OAuth
                        re-auth dance, instrumented by Phase 2.

  IBCpapiQuoteSource  — destination after the live-account / real-time
                        data sharing path opens. Refuses delayed quotes
                        (field 6509='D') — fails closed instead of
                        silently pricing on stale data.

  TastytradeQuoteSource — future. Refresh tokens never expire — best
                        operational profile of any broker for an
                        unattended bot. Stub today; implemented when the
                        user funds the Tastytrade account.

Source is selected via Redis key `orb:quote_source` (overridable by
ORB_QUOTE_SOURCE env var). Default 'schwab' for the bridge window.

The interface intentionally takes a (ticker, expiry, strike, right)
spec rather than a native symbol — each source converts internally.
That way the handler never has to care about OCC vs. conid vs. dxFeed.
"""

import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

QUOTE_SOURCE_KEY = "orb:quote_source"
DEFAULT_SOURCE = "schwab"

# IB's "ticker" for SPX is "SPX" but the OCC option root for 0DTE/weekly
# SPX contracts is "SPXW". Without this mapping, Schwab would look for
# "SPX  260530C07600000" which doesn't exist — SPX (3rd-Friday monthly)
# AM-settles, SPXW (daily PM-settled) is what 0DTE trades on.
OPTION_ROOT_MAP = {"SPX": "SPXW"}


def build_occ_symbol(root: str, expiry_yyyymmdd: str, right: str,
                     strike: float) -> str:
    """OCC 21-char option symbol.

    Format: 6-char root (space-padded right) + YYMMDD + C/P + strike
    times 1000 zero-padded to 8 digits.

    Example: SPXW + 2026-05-30 + C + 7600 → 'SPXW  260530C07600000'

    Schwab's /marketdata/v1/quotes accepts this format; the two-space
    pad on the root is required (it gets URL-encoded by requests when
    passed via the symbols query param)."""
    root_padded = root.ljust(6)
    yymmdd = expiry_yyyymmdd[2:]
    strike_int = int(round(strike * 1000))
    return f"{root_padded}{yymmdd}{right}{strike_int:08d}"


class QuoteSource:
    """Abstract interface. All implementations return (bid, ask) as a
    tuple of floats, or (None, None) if the quote couldn't be fetched
    or was refused (e.g., delayed when fresh data was required)."""

    def get_option_quote(self, ticker: str, expiry_yyyymmdd: str,
                         strike: float, right: str
                         ) -> Tuple[Optional[float], Optional[float]]:
        raise NotImplementedError

    def name(self) -> str:
        return type(self).__name__


class SchwabQuoteSource(QuoteSource):
    """Real-time SPX 0DTE quotes via Schwab's /marketdata/v1/quotes.

    Caches the SchwabMarketData instance across calls (auth is lazy and
    refresh_access_token() handles the 30-min access token rollover
    automatically). The 7-day refresh-token wall is surfaced via
    Phase 2's Telegram alert + /api/schwab/status endpoint, not here."""

    def __init__(self, token_file: Optional[str] = None):
        self._md = None
        self._token_file = token_file or os.environ.get(
            "SCHWAB_TOKEN_FILE", "/opt/lumisignals/schwab_tokens.json"
        )

    def _ensure_md(self):
        if self._md is not None:
            return self._md
        from .schwab_client import SchwabAuth, SchwabMarketData
        client_id = os.environ.get("SCHWAB_CLIENT_ID", "")
        client_secret = os.environ.get("SCHWAB_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise RuntimeError(
                "SCHWAB_CLIENT_ID/SECRET not set; can't auth Schwab"
            )
        auth = SchwabAuth(client_id, client_secret,
                          token_file=self._token_file)
        if not auth.is_authenticated:
            raise RuntimeError(
                "Schwab token file missing or empty — run schwab_auth.py"
            )
        self._md = SchwabMarketData(auth)
        return self._md

    def get_option_quote(self, ticker, expiry_yyyymmdd, strike, right):
        try:
            md = self._ensure_md()
            root = OPTION_ROOT_MAP.get(ticker, ticker)
            sym = build_occ_symbol(root, expiry_yyyymmdd, right, strike)
            # Use /quotes (plural) with the symbols query param —
            # /marketdata/v1/{symbol}/quotes path-injects the symbol and
            # the OCC root's trailing spaces don't path-encode cleanly.
            resp = md.get_quotes([sym])
            if not resp:
                return (None, None)
            row = resp.get(sym)
            if row is None:
                # Schwab sometimes strips trailing spaces in keys
                row = resp.get(sym.rstrip(), None) or next(iter(resp.values()), None)
            if not row:
                return (None, None)
            q = row.get("quote", row)
            bid = q.get("bidPrice")
            ask = q.get("askPrice")
            if bid is None or ask is None or bid <= 0 or ask <= 0:
                return (None, None)
            return (float(bid), float(ask))
        except Exception as e:
            logger.warning(
                "schwab_quote: %s %s %s%s failed: %s",
                ticker, expiry_yyyymmdd, strike, right, e,
            )
            return (None, None)


class IBCpapiQuoteSource(QuoteSource):
    """CPAPI snapshot via the existing client. Refuses delayed quotes —
    field 6509 prefix 'D' means delayed; we return (None,None) so the
    handler abandons instead of pricing on stale data.

    Costs an extra conid lookup per quote (the handler still does its
    own lookup for placement). ~100ms each on warm IBeam; negligible
    compared to the 15-min staleness it prevents."""

    def __init__(self, client):
        self._client = client

    def get_option_quote(self, ticker, expiry_yyyymmdd, strike, right):
        try:
            from .orb_butterfly_handler import _lookup_option_conid
            conid = _lookup_option_conid(
                self._client, ticker, expiry_yyyymmdd, strike, right
            )
            if not conid:
                return (None, None)
            # Up to 6 attempts with 500ms gap — matches the warm-up
            # pattern in the legacy _fetch_quote helper.
            for _ in range(6):
                r = self._client._request(
                    "GET", "/iserver/marketdata/snapshot",
                    params={"conids": str(conid),
                            "fields": "84,86,6509"},
                )
                if isinstance(r, list) and r:
                    row = r[0]
                    if str(row.get("6509", "")).startswith("D"):
                        logger.warning(
                            "ib_quote: %s %s%s delayed (6509=%s) — refusing",
                            expiry_yyyymmdd, strike, right, row.get("6509"),
                        )
                        return (None, None)
                    b = row.get("84") or 0
                    a = row.get("86") or 0
                    try:
                        bid = float(b)
                        ask = float(a)
                    except (TypeError, ValueError):
                        bid = ask = 0
                    if bid > 0 and ask > 0:
                        return (bid, ask)
                time.sleep(0.5)
            return (None, None)
        except Exception as e:
            logger.warning(
                "ib_quote: %s %s %s%s failed: %s",
                ticker, expiry_yyyymmdd, strike, right, e,
            )
            return (None, None)


class TastytradeQuoteSource(QuoteSource):
    """Stub — implemented when the user funds the Tastytrade account."""

    def get_option_quote(self, ticker, expiry_yyyymmdd, strike, right):
        raise NotImplementedError(
            "TastytradeQuoteSource not yet implemented; account not "
            "funded. See ORB plan 'Future' phase."
        )


def get_quote_source(client=None, rdb=None) -> QuoteSource:
    """Resolve the configured quote source.

    Resolution order: ORB_QUOTE_SOURCE env var → Redis orb:quote_source
    → default 'schwab'.

    The IB CPAPI path requires a CPAPI client; pass it through. Schwab
    and Tastytrade don't use the client."""
    name = os.environ.get("ORB_QUOTE_SOURCE")
    if not name and rdb is not None:
        try:
            raw = rdb.get(QUOTE_SOURCE_KEY)
            if raw:
                name = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
        except Exception:
            pass
    name = (name or DEFAULT_SOURCE).lower().strip()
    if name == "schwab":
        return SchwabQuoteSource()
    if name == "ib_cpapi":
        if client is None:
            raise RuntimeError("ib_cpapi quote source requires a CPAPI client")
        return IBCpapiQuoteSource(client)
    if name == "tastytrade":
        return TastytradeQuoteSource()
    raise ValueError(f"Unknown orb:quote_source value: {name!r}")
