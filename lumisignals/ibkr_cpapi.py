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
            # Options fields
            if entry["sec_type"] == "OPT":
                entry["expiration"] = pos.get("expiry", "")
                entry["strike"] = float(pos.get("strike", 0))
                entry["right"] = pos.get("putOrCall", "")
                entry["multiplier"] = int(pos.get("multiplier", 100))
            elif entry["sec_type"] == "FUT":
                entry["multiplier"] = int(pos.get("multiplier", 5))

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
                            tif: str = "GTC") -> dict:
        """Build a futures order payload.

        Args:
            conid: Contract ID
            action: "BUY" or "SELL"
            quantity: Number of contracts
            order_type: "MKT", "LMT", or "STP"
            price: Required for LMT and STP orders
            tif: Time in force ("GTC", "DAY")
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
        return {"orders": [order]}

    @staticmethod
    def build_spread_order(sell_conid: int, buy_conid: int, quantity: int,
                           limit_price: float, is_credit: bool,
                           tif: str = "GTC") -> dict:
        """Build a vertical spread (combo) order payload.

        Args:
            sell_conid: conId of the short leg
            buy_conid: conId of the long leg
            quantity: Number of spreads
            limit_price: Absolute price (will be negated for credits)
            is_credit: True for credit spreads
            tif: Time in force
        """
        price = -abs(limit_price) if is_credit else abs(limit_price)
        return {
            "orders": [{
                "conidex": f"{sell_conid};;;{buy_conid}",
                "orderType": "LMT",
                "side": "BUY",
                "quantity": quantity,
                "price": round(price, 2),
                "tif": tif,
                "legs": [
                    {"conid": sell_conid, "side": "SELL", "ratio": 1},
                    {"conid": buy_conid, "side": "BUY", "ratio": 1},
                ],
            }]
        }

    @staticmethod
    def build_close_spread_order(long_conid: int, short_conid: int,
                                  quantity: int) -> dict:
        """Build a market order to close an existing spread."""
        return {
            "orders": [{
                "conidex": f"{long_conid};;;{short_conid}",
                "orderType": "MKT",
                "side": "BUY",
                "quantity": quantity,
                "tif": "DAY",
                "legs": [
                    {"conid": long_conid, "side": "SELL", "ratio": 1},
                    {"conid": short_conid, "side": "BUY", "ratio": 1},
                ],
            }]
        }
