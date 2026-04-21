"""Options position sizing — no broker dependencies, safe to import anywhere."""

from dataclasses import dataclass


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
