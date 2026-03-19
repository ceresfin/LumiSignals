"""Order creation, position sizing, and risk management."""

import logging
from .models import Signal, OrderResult
from .oanda_client import OandaClient, resolve_instrument

logger = logging.getLogger(__name__)


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
    max_units: int = 100000,
) -> int:
    """Calculate position size in units based on risk management.

    Args:
        account_balance: Account balance in account currency.
        risk_percent: Percentage of account to risk (e.g. 1.0 for 1%).
        entry_price: Entry price.
        stop_price: Stop loss price.
        max_units: Maximum allowed position size.

    Returns:
        Position size in units (always positive).
    """
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        return 0

    risk_amount = account_balance * (risk_percent / 100)
    units = int(risk_amount / stop_distance)
    return min(units, max_units)


class OrderManager:
    """Manages order creation and execution against Oanda."""

    def __init__(self, client: OandaClient, risk_config: dict, dry_run: bool = False):
        self.client = client
        self.risk_percent = risk_config.get("risk_percent", 1.0)
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
        pip_value, precision = get_pip_precision(instrument)

        if self.dry_run:
            # Use a simulated balance for position sizing in dry-run mode
            balance = 10000.0
            units = calculate_position_size(
                account_balance=balance,
                risk_percent=self.risk_percent,
                entry_price=signal.entry,
                stop_price=signal.stop,
                max_units=self.max_units,
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
                max_units=self.max_units,
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
