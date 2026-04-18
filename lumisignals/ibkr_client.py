"""Interactive Brokers client — options paper trading via IB Gateway."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, ComboLeg, Contract, Order

logger = logging.getLogger(__name__)


@dataclass
class OptionsRiskConfig:
    """Options position sizing settings."""
    max_risk_per_spread: float = 200.0
    max_contracts: int = 5
    max_total_risk: float = 2000.0
    spread_width: float = 5.0
    min_credit_pct: float = 25.0
    max_spreads: int = 10


def calculate_spread_contracts(
    spread_width: float,
    credit_or_debit: float,
    is_credit: bool,
    risk_config: OptionsRiskConfig,
    current_total_risk: float = 0.0,
    current_spread_count: int = 0,
) -> dict:
    """Calculate how many contracts to trade for a spread.

    Args:
        spread_width: Width between strikes (e.g. 2.5 for a $2.50 wide spread).
        credit_or_debit: Premium received (credit) or paid (debit) per contract.
        is_credit: True for credit spreads, False for debit spreads.
        risk_config: User's options risk settings.
        current_total_risk: Total risk already deployed across open spreads.
        current_spread_count: Number of spreads already open.

    Returns:
        Dict with contracts, risk_per_contract, total_risk, and any rejection reason.
    """
    # Check spread count limit
    if current_spread_count >= risk_config.max_spreads:
        return {"contracts": 0, "reason": f"Max spreads reached ({risk_config.max_spreads})"}

    # Calculate risk per contract
    if is_credit:
        risk_per_contract = (spread_width - credit_or_debit) * 100
        credit_pct = (credit_or_debit / spread_width) * 100 if spread_width > 0 else 0

        # Check minimum credit threshold
        if credit_pct < risk_config.min_credit_pct:
            return {
                "contracts": 0,
                "reason": f"Credit {credit_pct:.0f}% below minimum {risk_config.min_credit_pct:.0f}%",
            }
    else:
        risk_per_contract = credit_or_debit * 100

    if risk_per_contract <= 0:
        return {"contracts": 0, "reason": "No risk calculated"}

    # Calculate max contracts from per-trade risk limit
    contracts_from_risk = int(risk_config.max_risk_per_spread / risk_per_contract)

    # Calculate max contracts from portfolio risk limit
    remaining_risk = risk_config.max_total_risk - current_total_risk
    if remaining_risk <= 0:
        return {"contracts": 0, "reason": f"Portfolio risk limit reached (${risk_config.max_total_risk:,.0f})"}
    contracts_from_portfolio = int(remaining_risk / risk_per_contract)

    # Take the most conservative
    contracts = min(
        contracts_from_risk,
        contracts_from_portfolio,
        risk_config.max_contracts,
    )
    contracts = max(contracts, 0)

    if contracts == 0:
        return {"contracts": 0, "reason": "Risk per contract exceeds max risk per spread"}

    total_risk = contracts * risk_per_contract
    max_profit = contracts * credit_or_debit * 100 if is_credit else contracts * (spread_width - credit_or_debit) * 100

    return {
        "contracts": contracts,
        "risk_per_contract": round(risk_per_contract, 2),
        "total_risk": round(total_risk, 2),
        "max_profit": round(max_profit, 2),
        "credit_pct": round((credit_or_debit / spread_width) * 100, 1) if is_credit and spread_width > 0 else None,
    }


class IBKRClient:
    """Client for Interactive Brokers API via IB Gateway / TWS."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4002, client_id: int = 1):
        """
        Args:
            host: IB Gateway host (localhost for local, or IP for remote).
            port: 4002 = paper trading, 4001 = live.
            client_id: Unique ID for this connection (use different IDs for multiple connections).
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def connect(self) -> bool:
        """Connect to IB Gateway."""
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            # Request delayed market data (free, no subscription needed)
            self.ib.reqMarketDataType(3)
            logger.info("Connected to IB Gateway at %s:%s", self.host, self.port)
            return True
        except Exception as e:
            logger.error("Failed to connect to IB Gateway: %s", e)
            return False

    def disconnect(self):
        """Disconnect from IB Gateway."""
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Disconnected from IB Gateway")

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account_summary(self) -> dict:
        """Get account balance, NAV, buying power."""
        summary = {}
        for item in self.ib.accountSummary():
            if item.tag in ("NetLiquidation", "TotalCashValue", "BuyingPower",
                            "GrossPositionValue", "UnrealizedPnL", "RealizedPnL"):
                summary[item.tag] = float(item.value)
        return summary

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------

    def get_stock_price(self, symbol: str) -> Optional[float]:
        """Get current mid price for a stock."""
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)  # wait for data
        self.ib.cancelMktData(contract)
        if ticker.midpoint() and ticker.midpoint() > 0:
            return ticker.midpoint()
        if ticker.last and ticker.last > 0:
            return ticker.last
        return None

    def get_option_chain(self, symbol: str) -> list:
        """Get available option expirations and strikes for a stock."""
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        chains = self.ib.reqSecDefOptParams(contract.symbol, "", contract.secType, contract.conId)
        return chains

    def get_option_expirations(self, symbol: str, min_dte: int = 7, max_dte: int = 60) -> list:
        """Get option expirations within a DTE range."""
        chains = self.get_option_chain(symbol)
        today = datetime.now().date()
        expirations = []
        for chain in chains:
            if chain.exchange != "SMART":
                continue
            for exp_str in chain.expirations:
                exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
                dte = (exp_date - today).days
                if min_dte <= dte <= max_dte:
                    expirations.append({"expiration": exp_str, "dte": dte, "strikes": sorted(chain.strikes)})
        return sorted(expirations, key=lambda x: x["dte"])

    # ------------------------------------------------------------------
    # Options Quotes
    # ------------------------------------------------------------------

    def get_option_quote(self, symbol: str, expiration: str, strike: float, right: str) -> dict:
        """Get quote for a single option contract.

        Args:
            symbol: e.g. "AAPL"
            expiration: e.g. "20260515" (YYYYMMDD)
            strike: e.g. 190.0
            right: "C" for call, "P" for put
        """
        contract = Option(symbol, expiration, strike, right, "SMART")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(2)
        self.ib.cancelMktData(contract)
        return {
            "symbol": symbol,
            "expiration": expiration,
            "strike": strike,
            "right": right,
            "bid": ticker.bid if ticker.bid > 0 else None,
            "ask": ticker.ask if ticker.ask > 0 else None,
            "mid": ticker.midpoint() if ticker.midpoint() > 0 else None,
            "last": ticker.last if ticker.last > 0 else None,
            "volume": ticker.volume if ticker.volume >= 0 else 0,
            "open_interest": getattr(ticker, "openInterest", 0),
        }

    # ------------------------------------------------------------------
    # Order Execution
    # ------------------------------------------------------------------

    def place_single_option(self, symbol: str, expiration: str, strike: float,
                            right: str, action: str, quantity: int = 1,
                            order_type: str = "MKT", limit_price: float = 0) -> dict:
        """Place a single option order.

        Args:
            action: "BUY" or "SELL"
            order_type: "MKT" or "LMT"
            limit_price: Required if order_type is "LMT"
        """
        contract = Option(symbol, expiration, strike, right, "SMART")
        self.ib.qualifyContracts(contract)

        if order_type == "LMT":
            order = LimitOrder(action, quantity, limit_price)
        else:
            order = MarketOrder(action, quantity)

        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)

        return {
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
            "symbol": symbol,
            "strike": strike,
            "right": right,
            "action": action,
            "quantity": quantity,
        }

    def place_vertical_spread(self, symbol: str, expiration: str,
                              buy_strike: float, sell_strike: float,
                              right: str, quantity: int = 1,
                              order_type: str = "LMT", limit_price: float = 0) -> dict:
        """Place a vertical spread (credit or debit spread).

        For a credit spread: sell the closer strike, buy the further strike.
        For a debit spread: buy the closer strike, sell the further strike.

        Args:
            buy_strike: Strike to buy
            sell_strike: Strike to sell
            right: "C" for call spread, "P" for put spread
            limit_price: Net credit (positive) or net debit (negative)
        """
        buy_contract = Option(symbol, expiration, buy_strike, right, "SMART")
        sell_contract = Option(symbol, expiration, sell_strike, right, "SMART")
        self.ib.qualifyContracts(buy_contract, sell_contract)

        # Build combo contract
        combo = Contract()
        combo.symbol = symbol
        combo.secType = "BAG"
        combo.currency = "USD"
        combo.exchange = "SMART"

        leg1 = ComboLeg()
        leg1.conId = buy_contract.conId
        leg1.ratio = 1
        leg1.action = "BUY"
        leg1.exchange = "SMART"

        leg2 = ComboLeg()
        leg2.conId = sell_contract.conId
        leg2.ratio = 1
        leg2.action = "SELL"
        leg2.exchange = "SMART"

        combo.comboLegs = [leg1, leg2]

        if order_type == "LMT":
            order = LimitOrder("BUY", quantity, limit_price)
        else:
            order = MarketOrder("BUY", quantity)

        trade = self.ib.placeOrder(combo, order)
        self.ib.sleep(1)

        return {
            "order_id": trade.order.orderId,
            "status": trade.orderStatus.status,
            "symbol": symbol,
            "expiration": expiration,
            "buy_strike": buy_strike,
            "sell_strike": sell_strike,
            "right": right,
            "quantity": quantity,
            "limit_price": limit_price,
            "spread_type": "credit" if limit_price > 0 else "debit",
        }

    # ------------------------------------------------------------------
    # Positions & Orders
    # ------------------------------------------------------------------

    def get_positions(self) -> list:
        """Get all current positions."""
        positions = []
        for pos in self.ib.positions():
            positions.append({
                "symbol": pos.contract.symbol,
                "sec_type": pos.contract.secType,
                "expiration": getattr(pos.contract, "lastTradeDateOrContractMonth", ""),
                "strike": getattr(pos.contract, "strike", 0),
                "right": getattr(pos.contract, "right", ""),
                "quantity": pos.position,
                "avg_cost": pos.avgCost,
                "market_value": pos.position * pos.avgCost,
            })
        return positions

    def get_open_orders(self) -> list:
        """Get all open orders."""
        orders = []
        for trade in self.ib.openTrades():
            orders.append({
                "order_id": trade.order.orderId,
                "symbol": trade.contract.symbol,
                "sec_type": trade.contract.secType,
                "action": trade.order.action,
                "quantity": trade.order.totalQuantity,
                "order_type": trade.order.orderType,
                "limit_price": trade.order.lmtPrice,
                "status": trade.orderStatus.status,
            })
        return orders

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an open order."""
        for trade in self.ib.openTrades():
            if trade.order.orderId == order_id:
                self.ib.cancelOrder(trade.order)
                self.ib.sleep(1)
                return True
        return False
