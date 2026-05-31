"""IB Client Portal REST API client.

Replaces ib_insync for headless server deployment. Connects to the CPAPI
gateway (runs in Docker) via REST instead of the TWS socket protocol.

Usage:
    client = CPAPIClient("https://localhost:5000/v1/api")
    client.ensure_session()
    positions = client.get_positions()
    client.place_order(client.build_futures_order(conid, "BUY", 1))
"""

import logging
import os
import time
from typing import Dict, List, Optional

import requests
import urllib3

# Suppress SSL warnings for self-signed CPAPI gateway cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class CPAPIClient:
    """IB Client Portal API REST client."""

    def __init__(self, base_url: str = None, verify_ssl: bool = False):
        self.base_url = (base_url or os.environ.get(
            "CPAPI_BASE_URL", "https://localhost:5000/v1/api")).rstrip("/")
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.account_id: Optional[str] = None

    def _request(self, method: str, path: str, json_data: dict = None,
                 params: dict = None) -> dict:
        """Central request method with error handling."""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.request(method, url, json=json_data, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json() if resp.text else {}
            logger.warning("CPAPI %s %s → %d: %s", method, path, resp.status_code, resp.text[:200])
            return {"error": resp.text[:200], "status_code": resp.status_code}
        except requests.exceptions.ConnectionError:
            logger.error("CPAPI connection failed — is the gateway running?")
            return {"error": "Connection refused"}
        except Exception as e:
            logger.error("CPAPI request error: %s", e)
            return {"error": str(e)}

    # ─── AUTH / SESSION ─────────────────────────────────────────────────

    def auth_status(self) -> dict:
        """Check authentication status."""
        return self._request("POST", "/iserver/auth/status")

    def tickle(self) -> dict:
        """Keep session alive. Call every sync cycle."""
        return self._request("POST", "/tickle")

    def reauthenticate(self) -> dict:
        """Attempt to re-authenticate without browser login."""
        return self._request("POST", "/iserver/reauthenticate")

    def ensure_session(self):
        """Verify session is active. Call at start of each sync cycle.

        Raises ConnectionError if manual browser login is needed.
        """
        self.tickle()
        status = self.auth_status()
        if not status.get("authenticated"):
            logger.warning("CPAPI session not authenticated — attempting reauthenticate")
            self.reauthenticate()
            time.sleep(5)
            status = self.auth_status()
            if not status.get("authenticated"):
                raise ConnectionError(
                    "CPAPI session expired — manual browser login required. "
                    "SSH tunnel: ssh -L 5000:localhost:5000 root@bot.lumitrade.ai "
                    "then open https://localhost:5000"
                )
        if not self.account_id:
            accounts = self.get_accounts()
            if accounts:
                self.account_id = accounts[0].get("accountId", accounts[0].get("id", ""))
                logger.info("CPAPI authenticated — account %s", self.account_id)

    def is_authenticated(self) -> bool:
        """Quick auth check without side effects."""
        status = self.auth_status()
        return status.get("authenticated", False)

    # ─── ACCOUNT ────────────────────────────────────────────────────────

    def get_accounts(self) -> list:
        """Get list of accounts."""
        result = self._request("GET", "/portfolio/accounts")
        if isinstance(result, list):
            return result
        return result.get("accounts", [result]) if not result.get("error") else []

    def get_account_summary(self) -> dict:
        """Get account summary. Returns dict with NetLiquidation, BuyingPower, etc.

        Matches the shape expected by collect_ib_data().
        """
        if not self.account_id:
            return {}
        result = self._request("GET", f"/portfolio/{self.account_id}/summary")
        if result.get("error"):
            return {}
        # CPAPI returns nested structure: {"netLiquidValue": {"amount": 100000}, ...}
        # Flatten to match ib_insync format
        summary = {}
        field_map = {
            "netliquidation": "NetLiquidation",
            "totalcashvalue": "TotalCashValue",
            "buyingpower": "BuyingPower",
            "grosspositionvalue": "GrossPositionValue",
            "unrealizedpnl": "UnrealizedPnL",
            "realizedpnl": "RealizedPnL",
            "availablefunds": "AvailableFunds",
            "initmarginreq": "InitMarginReq",
            "maintmarginreq": "MaintMarginReq",
        }
        for key, val in result.items():
            mapped = field_map.get(key.lower().replace("-", "").replace("_", ""))
            if mapped and isinstance(val, dict):
                summary[mapped] = float(val.get("amount", 0))
            elif mapped:
                summary[mapped] = float(val) if val else 0
        return summary

    # ─── POSITIONS ──────────────────────────────────────────────────────

    def get_positions(self) -> list:
        """Get all open positions. Returns list matching ib.portfolio() shape.

        Each item: {symbol, sec_type, quantity, avg_cost, market_price,
                    market_value, unrealized_pnl, realized_pnl, con_id,
                    expiration, strike, right, multiplier}
        """
        if not self.account_id:
            return []
        result = self._request("GET", f"/portfolio/{self.account_id}/positions/0")
        if not isinstance(result, list):
            return []

        positions = []
        for pos in result:
            quantity = float(pos.get("position", 0))
            if quantity == 0:
                continue
            entry = {
                "symbol": pos.get("ticker", pos.get("contractDesc", "")).split(" ")[0],
                "sec_type": self._map_sec_type(pos.get("assetClass", "")),
                "quantity": quantity,
                "avg_cost": float(pos.get("avgCost", 0)),
                "market_price": float(pos.get("mktPrice", 0)),
                "market_value": float(pos.get("mktValue", 0)),
                "unrealized_pnl": float(pos.get("unrealizedPnl", 0)),
                "realized_pnl": float(pos.get("realizedPnl", 0)),
                "con_id": int(pos.get("conid", 0)),
            }
            # Options fields. CPAPI sometimes returns "multiplier": null
            # (instead of omitting the key), so `dict.get(key, default)` would
            # pass None to int() — fall back via `or` to handle that.
            if entry["sec_type"] == "OPT":
                entry["expiration"] = pos.get("expiry", "")
                entry["strike"] = float(pos.get("strike", 0))
                entry["right"] = pos.get("putOrCall", "")
                entry["multiplier"] = int(pos.get("multiplier") or 100)
            elif entry["sec_type"] == "FUT":
                entry["multiplier"] = int(pos.get("multiplier") or 5)

            positions.append(entry)
        return positions

    @staticmethod
    def _map_sec_type(asset_class: str) -> str:
        """Map CPAPI asset class to ib_insync secType."""
        mapping = {"STK": "STK", "OPT": "OPT", "FUT": "FUT", "WAR": "WAR",
                   "BOND": "BOND", "CASH": "CASH", "FOP": "FOP"}
        return mapping.get(asset_class, asset_class)

    # ─── ORDERS ─────────────────────────────────────────────────────────

    def place_order(self, order_payload: dict) -> dict:
        """Place an order. Auto-confirms reply prompts.

        Args:
            order_payload: Dict with "orders" key (CPAPI format)

        Returns:
            Order response with orderId, status, etc.
        """
        if not self.account_id:
            return {"error": "No account ID"}

        result = self._request("POST",
                               f"/iserver/account/{self.account_id}/orders",
                               json_data=order_payload)

        # Handle confirmation prompts (up to 3 rounds)
        for _ in range(3):
            result = self._handle_reply(result)
            if not isinstance(result, list) or not any(r.get("id") for r in result if isinstance(r, dict)):
                break

        return result

    def _handle_reply(self, response) -> dict:
        """If response contains a confirmation prompt, auto-confirm it."""
        if isinstance(response, list):
            for item in response:
                if isinstance(item, dict) and item.get("id") and not item.get("order_id"):
                    reply_id = item["id"]
                    logger.info("CPAPI order confirmation prompt — auto-confirming %s", reply_id)
                    return self._request("POST", f"/iserver/reply/{reply_id}",
                                        json_data={"confirmed": True})
        return response

    def get_open_orders(self) -> list:
        """Get open/pending orders."""
        result = self._request("GET", "/iserver/account/orders")
        if isinstance(result, dict):
            return result.get("orders", [])
        return result if isinstance(result, list) else []

    def get_trades(self) -> list:
        """Get recent trades/fills. Maps to ib.fills()."""
        result = self._request("GET", "/iserver/account/trades")
        if isinstance(result, list):
            return result
        return []

    def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order."""
        if not self.account_id:
            return {"error": "No account ID"}
        return self._request("DELETE",
                             f"/iserver/account/{self.account_id}/order/{order_id}")

    def modify_order(self, order_id, conid: int, side: str,
                     quantity: int, order_type: str,
                     price: float = None, tif: str = "GTC") -> dict:
        """Modify an existing live order. Modifiable fields per CPAPI docs:
        conid, orderType, price, side, tif, quantity.

        The original order_id is preserved. Most useful pattern for this
        codebase: convert an existing STP (stop loss) into a MKT order so
        it fires immediately as the close — atomic stop-and-close in one
        REST call. Empirically validated 2026-05-22.

        Returns the modify response (same shape as place_order).
        """
        if not self.account_id:
            return {"error": "No account ID"}
        body = {
            "conid": conid,
            "orderType": order_type,
            "side": side,
            "quantity": quantity,
            "tif": tif,
        }
        if price is not None and order_type in ("LMT", "STP", "STP_LIMIT"):
            body["price"] = price
        result = self._request(
            "POST",
            f"/iserver/account/{self.account_id}/order/{order_id}",
            json_data=body,
        )
        # Modify may need confirmation prompts like place_order does.
        for _ in range(3):
            result = self._handle_reply(result)
            if not isinstance(result, list) or not any(r.get("id") for r in result if isinstance(r, dict)):
                break
        return result

    # ─── CONTRACT SEARCH ────────────────────────────────────────────────

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list:
        """Search for a contract by symbol."""
        result = self._request("POST", "/iserver/secdef/search",
                               json_data={"symbol": symbol, "secType": sec_type})
        if isinstance(result, list):
            return result
        return []

    def get_contract_info(self, conid: int) -> dict:
        """Get full contract details by conId."""
        return self._request("GET", f"/iserver/contract/{conid}/info")

    def search_futures(self, symbol: str, exchange: str = "CME") -> Optional[dict]:
        """Find the front-month futures contract.

        Returns: {conid, symbol, localSymbol, expiration, multiplier} or None
        """
        # Search for the underlying
        results = self.search_contract(symbol, "FUT")
        if not results:
            return None

        # Get the first result's conid and find available futures
        underlying = results[0]
        conid = underlying.get("conid", 0)

        # Get futures contracts for this underlying
        futures = self._request("GET", "/trsrv/futures",
                                params={"symbols": symbol})
        if not futures or symbol not in futures:
            # Fallback: use the search result directly
            return {
                "conid": conid,
                "symbol": symbol,
                "localSymbol": underlying.get("description", symbol),
                "expiration": underlying.get("maturityDate", ""),
                "multiplier": int(underlying.get("multiplier", 5)),
            }

        # Pick the nearest expiration (front month)
        contracts = futures[symbol]
        if not contracts:
            return None
        # Sort by expiration
        contracts.sort(key=lambda c: c.get("expirationDate", "99999999"))
        front = contracts[0]
        return {
            "conid": front.get("conid", 0),
            "symbol": symbol,
            "localSymbol": front.get("symbol", symbol),
            "expiration": front.get("expirationDate", ""),
            "multiplier": int(front.get("multiplier", 5)),
        }

    def search_option_contract(self, symbol: str, expiration: str,
                                strike: float, right: str) -> Optional[int]:
        """Find conId for a specific option contract.

        Args:
            symbol: Underlying (e.g. "AAPL")
            expiration: YYYYMMDD format
            strike: Strike price
            right: "C" or "P"

        Returns:
            conId or None
        """
        # First, find the underlying conid (secdef/info needs conid, not symbol)
        results = self.search_contract(symbol, "STK")
        if not results:
            return None
        underlying_conid = results[0].get("conid")
        if not underlying_conid:
            return None

        # Look up the specific option. /iserver/secdef/info is GET with query
        # params (not POST + JSON body — that returns 405).
        sec_def = self._request("GET", "/iserver/secdef/info",
                                params={
                                    "conid": underlying_conid,
                                    "sectype": "OPT",
                                    "month": expiration[:6],  # YYYYMM
                                    "strike": strike,
                                    "right": right,
                                    "exchange": "SMART",
                                })
        if isinstance(sec_def, list) and sec_def:
            for opt in sec_def:
                if (str(opt.get("maturityDate", "")).replace("-", "") == expiration
                        and float(opt.get("strike", 0)) == strike):
                    return opt.get("conid")
            # If exact match not found, return first result
            return sec_def[0].get("conid")
        return None

    # ─── MARKET DATA ────────────────────────────────────────────────────

    def get_order_fill(self, order_id: str, max_wait: int = 6) -> dict:
        """Wait for a specific order to fill and return its avg fill price.

        Returns {"filled": bool, "avg_price": float, "status": str}.

        Use this after place_order(...) to read the actual fill price for
        THIS specific order — avoids the trap of reading the last entry
        from client.get_trades(), which returns ALL recent fills across
        the account (so an options spread fill on TGT can be mistaken for
        a MES futures fill and produce a stop loss at the wrong price).
        """
        if not order_id:
            return {"filled": False, "avg_price": 0.0, "status": ""}
        oid = str(order_id)
        last_status = ""
        import time as _t
        for _ in range(max_wait):
            try:
                orders_resp = self._request("GET", "/iserver/account/orders")
                orders = (orders_resp or {}).get("orders", []) if isinstance(orders_resp, dict) else orders_resp
                for o in orders or []:
                    if str(o.get("orderId") or "") != oid:
                        continue
                    last_status = o.get("status", "")
                    if last_status == "Filled":
                        try:
                            avg = float(o.get("avgPrice") or 0)
                        except (TypeError, ValueError):
                            avg = 0.0
                        return {"filled": True, "avg_price": avg, "status": "Filled"}
                    break
            except Exception:
                pass
            _t.sleep(1)
        return {"filled": False, "avg_price": 0.0, "status": last_status}

    def get_historical_bars(self, conid: int, period: str = "1d",
                             bar: str = "2min", outside_rth: bool = True) -> list:
        """Fetch historical OHLCV bars for a contract.

        Returns a list of {time (unix seconds), open, high, low, close, volume}.

        Args:
            conid: Contract ID
            period: How far back. e.g. "1d", "8h", "1w"
            bar: Bar size. e.g. "1min", "2min", "5min", "1h", "1d"
            outside_rth: Include extended hours
        """
        params = {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": "true" if outside_rth else "false",
        }
        result = self._request("GET", "/iserver/marketdata/history", params=params)
        # CPAPI sometimes returns 202 with empty data on first call; the next
        # call usually works. The _request layer doesn't expose status, so we
        # detect empty + retry once.
        data = (result or {}).get("data") if isinstance(result, dict) else None
        if not data:
            import time as _t
            _t.sleep(1)
            result = self._request("GET", "/iserver/marketdata/history", params=params)
            data = (result or {}).get("data") if isinstance(result, dict) else None
        if not data:
            return []
        bars = []
        for d in data:
            try:
                # CPAPI timestamps are ms since epoch.
                ts = int(d.get("t", 0)) // 1000
                bars.append({
                    "time": ts,
                    "open": float(d.get("o", 0)),
                    "high": float(d.get("h", 0)),
                    "low": float(d.get("l", 0)),
                    "close": float(d.get("c", 0)),
                    "volume": int(d.get("v", 0)) if d.get("v") is not None else 0,
                })
            except (TypeError, ValueError):
                continue
        return bars

    def get_market_snapshot(self, conids: list, fields: list = None) -> dict:
        """Get market data snapshot for one or more contracts.

        Args:
            conids: List of conIds
            fields: List of field codes (default: bid, ask, last, volume, IV, delta)

        Returns:
            Dict keyed by conId with market data
        """
        if not fields:
            fields = ["31", "84", "85", "86", "87", "7283", "7311"]
        conid_str = ",".join(str(c) for c in conids)
        field_str = ",".join(fields)
        result = self._request("GET", "/iserver/marketdata/snapshot",
                               params={"conids": conid_str, "fields": field_str})
        if isinstance(result, list):
            return {item.get("conid", item.get("conidEx", 0)): item for item in result}
        return {}

    # ─── ORDER BUILDERS ─────────────────────────────────────────────────

    @staticmethod
    def build_futures_order(conid: int, action: str, quantity: int,
                            order_type: str = "MKT", price: float = None,
                            tif: str = "GTC",
                            parent_id: str = None) -> dict:
        """Build a futures order payload.

        Args:
            conid: Contract ID
            action: "BUY" or "SELL"
            quantity: Number of contracts
            order_type: "MKT", "LMT", or "STP"
            price: Required for LMT and STP orders
            tif: Time in force ("GTC", "DAY")
            parent_id: Optional IB order ID of the parent entry order.
                       When set, this order becomes a bracket child:
                         - status stays "PreSubmitted" until parent fills
                         - if two children share the same parent, IB enforces
                           OCO (one fills → IB cancels the other)
                         - cancelling the parent cascade-cancels the children
                       Use for SL/TP protection that should only activate
                       after the entry actually fills.
        """
        order = {
            "conid": conid,
            "orderType": order_type,
            "side": action,
            "quantity": quantity,
            "tif": tif,
        }
        if price is not None and order_type in ("LMT", "STP"):
            order["price"] = price
        if parent_id:
            order["parentId"] = str(parent_id)
        return {"orders": [order]}

    @staticmethod
    def build_futures_bracket(conid: int, entry_side: str, quantity: int,
                              stop_price: float,
                              entry_type: str = "MKT",
                              entry_price: float = None,
                              target_price: float = None,
                              tif: str = "GTC",
                              entry_coid: str = None,
                              child_quantity: int = None) -> dict:
        """Build an atomic 3-order bracket payload (parent + SL + optional TP).

        CPAPI wires children to the parent by a customer-supplied cOID so the
        whole bracket can be POSTed in one shot. IB then:
          - holds the children as PreSubmitted until the parent fills,
          - activates SL+TP as an OCA group on fill,
          - cancels the children if the parent is cancelled.

        Position is never unprotected — no race window between entry fill and
        SL placement, no "stop skipped" branch needed.

        Args:
            conid: Front-month futures contract id.
            entry_side: "BUY" or "SELL".
            quantity: Contracts.
            stop_price: Absolute price for the SL child (already
                computed by caller — Pine target or quote-derived).
            entry_type: "MKT" or "LMT". MKT is the default for 2n20-style
                signals where execution speed matters more than price.
            entry_price: Required when entry_type=="LMT". Ignored otherwise.
            target_price: When > 0, include a TP child (LMT). When None
                or 0, no TP is created — same behavior as the old code
                which only placed TPs when Pine sent one.
            tif: Time in force for all three orders.
            entry_coid: Customer order id for the parent so the children
                can reference it via parentId. Auto-generated if omitted.
            child_quantity: Size of SL/TP children when it differs from the
                parent quantity. Used by the close-and-reverse entry path:
                parent SELLs (existing_long + new_short_qty) to flip the net
                position in one fill, but the SL/TP should protect only the
                NEW position size, not the inflated close-and-open total.
                Defaults to `quantity` (the standard bracket case).

        Returns:
            dict suitable for place_order(): {"orders": [parent, sl, tp?]}.
        """
        import uuid as _uuid
        if entry_coid is None:
            entry_coid = f"lumi_{_uuid.uuid4().hex[:12]}"
        child_qty = child_quantity if child_quantity is not None else quantity

        exit_side = "SELL" if entry_side == "BUY" else "BUY"

        # Children get their own cOIDs derived from the parent's by glob-ing
        # a role marker into the trailing hash. Without this, SL/TP fills
        # come back from /iserver/account/trades with order_ref="" (an
        # IB-generated value, not our lumi tag) and the reconciler can't
        # decode the strategy from the fill — every bracket SL fire creates
        # an apparent orphan that mobile shows as "ALL ORPHAN".
        # Format chosen so the existing reconciler hash-stripping parser
        # (rsplit on '_', take the head) still decodes the strategy:
        #   parent:  lumi_futures_2n20_<hash>
        #   sl:      lumi_futures_2n20_<hash>sl
        #   tp:      lumi_futures_2n20_<hash>tp
        sl_coid = f"{entry_coid}sl"
        tp_coid = f"{entry_coid}tp"

        parent = {
            "cOID": entry_coid,
            "conid": conid,
            "orderType": entry_type,
            "side": entry_side,
            "quantity": quantity,
            "tif": tif,
        }
        if entry_type == "LMT" and entry_price is not None:
            parent["price"] = entry_price

        sl = {
            "cOID": sl_coid,
            "parentId": entry_coid,
            "conid": conid,
            "orderType": "STP",
            "side": exit_side,
            "quantity": child_qty,
            "price": stop_price,
            "tif": tif,
        }

        orders = [parent, sl]
        if target_price and target_price > 0:
            tp = {
                "cOID": tp_coid,
                "parentId": entry_coid,
                "conid": conid,
                "orderType": "LMT",
                "side": exit_side,
                "quantity": child_qty,
                "price": target_price,
                "tif": tif,
            }
            orders.append(tp)

        return {"orders": orders}

    @staticmethod
    def build_stock_order(conid: int, action: str, quantity: int,
                          order_type: str = "LMT", price: float = None,
                          tif: str = "DAY",
                          parent_id: str = None,
                          coid: str = None) -> dict:
        """Build a single-leg equity order payload.

        Mirrors build_futures_order — the CPAPI payload schema is
        identical for stocks vs futures (IB infers secType from the
        conid). Default TIF is DAY (vs GTC for futures) because swing
        equity positions held overnight rely on the bracket SL for
        gap protection rather than the order itself persisting.

        Args:
            conid: Equity conid (e.g. SPY = 756733).
            action: "BUY" or "SELL".
            quantity: Number of shares.
            order_type: "MKT" or "LMT" (STP also accepted but unusual
                for equity entries; brackets are how we protect).
            price: Required for LMT and STP.
            tif: "DAY" (default) or "GTC".
            parent_id: Optional parent cOID — makes this order a
                bracket child (same OCA semantics as futures).
            coid: Optional customer order id for reconciler tagging.
        """
        order = {
            "conid": conid,
            "orderType": order_type,
            "side": action,
            "quantity": quantity,
            "tif": tif,
        }
        if price is not None and order_type in ("LMT", "STP"):
            order["price"] = price
        if parent_id:
            order["parentId"] = str(parent_id)
        if coid:
            order["cOID"] = coid
        return {"orders": [order]}

    @staticmethod
    def build_stock_bracket(conid: int, entry_side: str, quantity: int,
                            stop_price: float,
                            entry_type: str = "LMT",
                            entry_price: float = None,
                            target_price: float = None,
                            tif: str = "DAY",
                            entry_coid: str = None) -> dict:
        """Atomic 3-order equity bracket (parent + SL + optional TP).

        Same OCA semantics as build_futures_bracket — children stay
        PreSubmitted until the parent fills, then activate as an OCA
        group. Position is never unprotected.

        Equity-specific notes vs the futures version:
          - Default entry_type is LMT (not MKT). Swing equity setups
            have a target entry price from the analyzer; we don't
            market-chase. Pass entry_type="MKT" only if you've decided
            slippage tolerance is high.
          - Default TIF is DAY. Overnight equity gap risk is handled
            by the SL child (IB triggers at next open if gapped
            through), not by the order persisting GTC.
          - No child_quantity flip-trick parameter — equity dashboard
            entries are simple fresh positions, not close-and-reverse.

        cOID naming follows the futures bracket convention so the
        existing reconciler hash-stripping parser can decode the
        strategy from any leg's fill: parent = lumi_<strategy>_<hash>,
        sl = ...<hash>sl, tp = ...<hash>tp.

        Args:
            conid: Equity conid.
            entry_side: "BUY" (going long) or "SELL" (going short).
            quantity: Shares.
            stop_price: Absolute price for the SL child.
            entry_type: "LMT" (default) or "MKT".
            entry_price: Required when entry_type=="LMT".
            target_price: When > 0, include a TP child (LMT). None or
                0 = no TP (rare for swing equity; usually you want one).
            tif: TIF for all three orders.
            entry_coid: Customer order id for the parent. Auto-
                generated if omitted (format: lumi_<uuid12>).

        Returns:
            dict for place_order(): {"orders": [parent, sl, tp?]}.
        """
        import uuid as _uuid
        if entry_coid is None:
            entry_coid = f"lumi_{_uuid.uuid4().hex[:12]}"
        exit_side = "SELL" if entry_side == "BUY" else "BUY"

        sl_coid = f"{entry_coid}sl"
        tp_coid = f"{entry_coid}tp"

        parent = {
            "cOID": entry_coid,
            "conid": conid,
            "orderType": entry_type,
            "side": entry_side,
            "quantity": quantity,
            "tif": tif,
        }
        if entry_type == "LMT" and entry_price is not None:
            parent["price"] = entry_price

        sl = {
            "cOID": sl_coid,
            "parentId": entry_coid,
            "conid": conid,
            "orderType": "STP",
            "side": exit_side,
            "quantity": quantity,
            "price": stop_price,
            "tif": tif,
        }

        orders = [parent, sl]
        if target_price and target_price > 0:
            tp = {
                "cOID": tp_coid,
                "parentId": entry_coid,
                "conid": conid,
                "orderType": "LMT",
                "side": exit_side,
                "quantity": quantity,
                "price": target_price,
                "tif": tif,
            }
            orders.append(tp)

        return {"orders": orders}

    # CPAPI combo-order prefix conids per quote currency. Used as the
    # leading segment of the conidex string when placing multi-leg
    # orders. USD covers SPX/SPY/equity options. Extend as new
    # currencies become relevant.
    #
    # Reference: ibind issue #110 (https://github.com/Voyz/ibind/issues/110),
    # production user salsasepp's working SPXW butterfly payload
    # confirmed atomic fill 2025-06-04. Same SPREAD_CONID table is in
    # ibind/examples/rest_06_options_chain.py.
    # Cherry-picked from orb-debug Phase 10a (commit b63a1ce) for the
    # dashboard options-spread placement path.
    SPREAD_CONID = {
        "USD": "28812380", "GBP": "58666491", "JPY": "61227069",
        "CAD": "61227082", "CHF": "61227087", "AUD": "61227077",
        "HKD": "61227072", "SGD": "426116555", "CNH": "136000441",
        "INR": "136000444", "KRW": "136000424", "MXN": "136000449",
        "SEK": "136000429",
    }

    @staticmethod
    def build_combo_order(legs, quantity: int, limit_price: float,
                          order_type: str = "LMT", tif: str = "DAY",
                          currency: str = "USD", coid: str = None,
                          outside_rth: bool = False) -> dict:
        """Build an N-leg combo (spread/butterfly/condor) order payload.

        This is the correct CPAPI conidex format — the previous builders
        in this file got it wrong on three counts (missing spread_conid
        prefix, bare conid pairs separated by ';;;' instead of
        comma-joined conid/ratio legs, and an extra 'legs' array that
        confused the parser into returning 'Combo key is not complete').

        Args:
            legs: list of (conid, side, ratio). side is "BUY" or "SELL",
                  ratio is a positive int (quantity multiplier per leg).
            quantity: number of combos to place.
            limit_price: net price of the combo. POSITIVE = pay debit
                  (you're the buyer of the spread), NEGATIVE = receive
                  credit (you're the seller). IB negates appropriately
                  on the wire.
            order_type: "LMT" or "MKT". Combos cannot be STP.
            tif: "DAY" (recommended for 0DTE) or "GTC".
            currency: selects the SPREAD_CONID prefix.
            coid: optional customer order id for reconciler tagging.
            outside_rth: include extended-hours fills.

        Returns a {"orders": [...]} payload ready for place_order().

        Format:
          conidex = "{spread_conid};;;{conid1}/{±r1},{conid2}/{±r2}[,...]"
          e.g. "28812380;;;783634289/+1,783941066/-2,783941086/+1"
                for a 1x long K1, 2x short K2, 1x long K3 butterfly.
        """
        spread_conid = CPAPIClient.SPREAD_CONID[currency]
        leg_parts = []
        for conid, side, ratio in legs:
            if side not in ("BUY", "SELL"):
                raise ValueError(f"leg side must be BUY/SELL, got {side!r}")
            signed = ratio if side == "BUY" else -ratio
            leg_parts.append(f"{conid}/{signed:+d}")
        conidex = f"{spread_conid};;;{','.join(leg_parts)}"

        order = {
            "conidex": conidex,        # mutually exclusive with `conid`
            "orderType": order_type,
            "side": "BUY",             # combos: always BUY; price sign = direction
            "quantity": int(quantity),
            "tif": tif,
            "outsideRTH": bool(outside_rth),
        }
        if order_type == "LMT":
            order["price"] = round(float(limit_price), 2)
        if coid:
            order["cOID"] = coid
        return {"orders": [order]}

    @staticmethod
    def build_spread_order(sell_conid: int, buy_conid: int, quantity: int,
                           limit_price: float, is_credit: bool,
                           tif: str = "DAY", coid: str = None) -> dict:
        """Vertical 2-leg spread. Wraps build_combo_order for backward
        compatibility with older call sites that pass leg conids
        positionally. limit_price is given as a positive number;
        is_credit=True negates it on the wire."""
        price = -abs(limit_price) if is_credit else abs(limit_price)
        return CPAPIClient.build_combo_order(
            legs=[(buy_conid, "BUY", 1), (sell_conid, "SELL", 1)],
            quantity=quantity, limit_price=price,
            order_type="LMT", tif=tif, coid=coid,
        )

    @staticmethod
    def build_close_spread_order(long_conid: int, short_conid: int,
                                  quantity: int, coid: str = None) -> dict:
        """Market close of an existing vertical spread. Reverses each leg."""
        return CPAPIClient.build_combo_order(
            legs=[(long_conid, "SELL", 1), (short_conid, "BUY", 1)],
            quantity=quantity, limit_price=0.0,
            order_type="MKT", tif="DAY", coid=coid,
        )
