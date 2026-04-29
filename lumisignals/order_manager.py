"""Order creation, position sizing, and risk management."""

import logging
from .models import Signal, OrderResult
from .oanda_client import OandaClient, resolve_instrument

logger = logging.getLogger(__name__)

# USD major pairs — focused set for faster scanning
USD_MAJORS = {
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD",
}

# All major and major-cross forex pairs (kept for reference/future use)
ALL_MAJOR_PAIRS = {
    # 7 Majors
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD",
    # 20 Major crosses
    "EUR_GBP", "EUR_JPY", "GBP_JPY", "EUR_AUD", "AUD_JPY", "EUR_CHF", "GBP_CHF",
    "CAD_JPY", "AUD_NZD", "GBP_NZD", "EUR_NZD", "EUR_CAD", "GBP_CAD", "GBP_AUD",
    "NZD_CAD", "AUD_CAD", "NZD_CHF", "AUD_CHF", "CHF_JPY", "NZD_JPY",
}

# Active trading pairs — USD majors only for fast scan cycles
MAJOR_PAIRS = USD_MAJORS


def get_pip_precision(instrument: str) -> tuple[float, int]:
    """Get pip value and price decimal precision for an instrument.

    Returns:
        (pip_value, decimal_places)
    """
    if "JPY" in instrument:
        return 0.01, 3
    if instrument.startswith("XAU"):
        return 0.1, 2
    if instrument.startswith("XAG"):
        return 0.01, 4
    if any(instrument.startswith(idx) for idx in ("US30", "SPX", "NAS", "UK100", "DE30", "JP225")):
        return 1.0, 1
    return 0.0001, 5


def format_price(price: float, precision: int) -> str:
    """Format price to the required decimal precision."""
    return f"{price:.{precision}f}"


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    entry_price: float,
    stop_price: float,
    instrument: str = "",
    max_units: int = 100000,
    risk_dollar: float = 0.0,
) -> int:
    """Calculate position size in units based on risk management.

    For JPY pairs, the stop distance is in yen (e.g. 1.5) while for others
    it's in the 4th decimal (e.g. 0.0097). We normalize by converting
    the stop distance to pips and using pip value per unit.

    Args:
        account_balance: Account balance in account currency.
        risk_percent: Percentage of account to risk (e.g. 1.0 for 1%).
        entry_price: Entry price.
        stop_price: Stop loss price.
        instrument: e.g. "EUR_USD", "USD_JPY" — needed for pip normalization.
        max_units: Maximum allowed position size.
        risk_dollar: Fixed dollar amount to risk per trade (overrides risk_percent when > 0).

    Returns:
        Position size in units (always positive).
    """
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        return 0

    if risk_dollar > 0:
        risk_amount = risk_dollar
    else:
        risk_amount = account_balance * (risk_percent / 100)

    # Convert stop distance to pips
    pip_value, _ = get_pip_precision(instrument)
    stop_pips = stop_distance / pip_value if pip_value else stop_distance

    # Approximate pip cost per unit in USD
    # For XXX_USD pairs: 1 pip = pip_value per unit (e.g. $0.0001)
    # For USD_JPY: 1 pip = 0.01 / price per unit (e.g. 0.01/150 = $0.0000667)
    # For crosses: approximate using entry price
    parts = instrument.split("_") if instrument else []
    if len(parts) == 2:
        base, quote = parts
        if quote == "USD":
            pip_cost = pip_value  # Direct: 1 pip = pip_value USD per unit
        elif base == "USD":
            pip_cost = pip_value / entry_price if entry_price else pip_value
        else:
            # Cross pair — rough approximation
            pip_cost = pip_value / entry_price if entry_price else pip_value
    else:
        pip_cost = pip_value

    if pip_cost == 0:
        return 0

    # units = risk_amount / (stop_pips * pip_cost_per_unit)
    units = int(risk_amount / (stop_pips * pip_cost))
    return min(units, max_units)


class OrderManager:
    """Manages order creation and execution against Oanda."""

    def __init__(self, client: OandaClient, risk_config: dict, dry_run: bool = False):
        self.client = client
        self.risk_percent = risk_config.get("risk_percent", 1.0)
        self.risk_dollar = risk_config.get("risk_dollar", 0.0)
        self.max_units = risk_config.get("max_position_units", 100000)
        self.max_open = risk_config.get("max_open_positions", 5)
        self.dry_run = dry_run

    def execute_signal(self, signal: Signal) -> OrderResult:
        """Validate a signal, size the position, and place the order."""
        # Validate signal
        errors = signal.validate()
        if errors:
            return OrderResult(success=False, error="; ".join(errors))

        instrument = resolve_instrument(signal.symbol)

        # Filter to major/cross pairs only
        if instrument not in MAJOR_PAIRS:
            return OrderResult(success=False, error=f"{instrument} is not a major/cross pair — skipping exotic")

        # Check if instrument is tradeable on this account
        if not self.client.is_tradeable(instrument):
            return OrderResult(success=False, error=f"{instrument} is not tradeable on this account")

        pip_value, precision = get_pip_precision(instrument)

        if self.dry_run:
            # Use a simulated balance for position sizing in dry-run mode
            balance = 10000.0
            units = calculate_position_size(
                account_balance=balance,
                risk_percent=self.risk_percent,
                entry_price=signal.entry,
                stop_price=signal.stop,
                instrument=instrument,
                max_units=self.max_units,
                risk_dollar=self.risk_dollar,
            )
            if units == 0:
                return OrderResult(success=False, error="Calculated position size is 0 — check stop distance")
        else:
            # Check open position count
            try:
                positions = self.client.get_open_positions()
                open_count = len(positions.get("positions", []))
                if open_count >= self.max_open:
                    return OrderResult(
                        success=False,
                        error=f"Max open positions reached ({open_count}/{self.max_open})",
                    )
            except Exception as e:
                logger.warning("Could not check open positions: %s", e)

            # Get account balance for position sizing
            try:
                account_info = self.client.get_account()
                balance = float(account_info["account"]["balance"])
            except Exception as e:
                return OrderResult(success=False, error=f"Failed to get account info: {e}")

            # Calculate position size
            units = calculate_position_size(
                account_balance=balance,
                risk_percent=self.risk_percent,
                entry_price=signal.entry,
                stop_price=signal.stop,
                instrument=instrument,
                max_units=self.max_units,
                risk_dollar=self.risk_dollar,
            )

            if units == 0:
                return OrderResult(success=False, error="Calculated position size is 0 — check stop distance")

        if signal.action == "SELL":
            units = -units

        # Build the order
        order_data = {
            "type": "LIMIT",
            "instrument": instrument,
            "units": str(units),
            "price": format_price(signal.entry, precision),
            "timeInForce": "GTC",
            "stopLossOnFill": {"price": format_price(signal.stop, precision)},
            "takeProfitOnFill": {"price": format_price(signal.target, precision)},
        }

        details = {
            "action": signal.action,
            "instrument": instrument,
            "units": abs(units),
            "entry": signal.entry,
            "stop": signal.stop,
            "target": signal.target,
            "risk_reward": signal.risk_reward,
            "balance": balance,
        }

        if self.dry_run:
            logger.info("[DRY RUN] Would place order: %s", order_data)
            return OrderResult(success=True, order_id="DRY_RUN", details=details)

        # Place the order
        try:
            result = self.client.create_order(order_data)
        except Exception as e:
            return OrderResult(success=False, error=f"Order request failed: {e}")

        if "orderCreateTransaction" in result:
            order_id = result["orderCreateTransaction"]["id"]
            logger.info("Order %s created: %s %s %s units @ %s", order_id, signal.action, instrument, abs(units), signal.entry)
            return OrderResult(success=True, order_id=order_id, details=details)

        return OrderResult(success=False, error="Order may not have been created", details={"response": result})
