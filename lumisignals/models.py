"""Data structures for signals and order results."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    """A trade signal received from LumiTrade or webhook."""
    action: str          # "BUY" or "SELL"
    symbol: str          # e.g. "EURUSD"
    entry: float         # Entry price
    stop: float          # Stop loss price
    target: float        # Take profit price
    timeframe: str = ""  # e.g. "15", "1H"
    risk_reward: float = 0.0
    target_num: int = 1
    signal_version: str = "Fib1"
    duration: str = ""
    momentum: str = ""

    def __post_init__(self):
        self.action = self.action.upper()
        self.symbol = self.symbol.upper().replace("/", "").replace("_", "")

    def validate(self) -> list[str]:
        """Return a list of validation errors, empty if valid."""
        errors = []
        if self.action not in ("BUY", "SELL"):
            errors.append(f"Invalid action: {self.action}. Must be BUY or SELL")
        if not self.symbol:
            errors.append("Symbol is required")
        if self.entry <= 0:
            errors.append("Entry price must be positive")
        if self.stop <= 0:
            errors.append("Stop price must be positive")
        if self.target <= 0:
            errors.append("Target price must be positive")
        return errors


@dataclass
class OrderResult:
    """Result of an order placement attempt."""
    success: bool
    order_id: Optional[str] = None
    # When a market order fills immediately, Oanda also returns a trade_id
    # distinct from the order_id (the trade is the resulting open position).
    # Capturing it here lets us key the signal_log under both IDs so later
    # lookups (mobile sync, /api/oanda/trades enrichment) can resolve a
    # trade back to its strategy without fuzzy matching.
    trade_id: Optional[str] = None
    details: dict = field(default_factory=dict)
    error: Optional[str] = None
