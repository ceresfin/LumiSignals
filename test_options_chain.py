"""Test the full options auto-trade chain: analyze → size → queue."""
import sys, json, uuid
sys.path.insert(0, ".")

from lumisignals.polygon_options import analyze_spreads_polygon
from lumisignals.options_sizing import OptionsRiskConfig, calculate_spread_contracts

# Step 1: Polygon Analysis for XLF (supply zone at 52.84)
print("=== Step 1: Polygon Analysis for XLF ===")
result = analyze_spreads_polygon("iuT5Pj3thRCf6dRliPm4cGlzolW99E2n", "XLF", "supply", 52.84, 52.93)
credit = result.get("credit_spread")
debit = result.get("debit_spread")

if credit:
    print(f"Credit: {credit['type']} — {credit['verdict']}")
    print(f"  SELL {credit['short_strike']} / BUY {credit['long_strike']} {credit['option_type']}")
    print(f"  Credit: ${credit['net_credit']:.2f} | Width: ${credit['width']} | {credit['days_to_expiry']}d | IV: {credit['iv_rank']}")
    print(f"  Max Profit: ${credit['max_profit']:.0f} | Max Loss: ${credit['max_loss']:.0f} | R:R: {credit['risk_reward']}")
else:
    print("Credit: none")

if debit:
    print(f"Debit: {debit['type']} — {debit['verdict']}")
    print(f"  BUY {debit['long_strike']} / SELL {debit['short_strike']} {debit['option_type']}")
    print(f"  Debit: ${debit['net_debit']:.2f} | Width: ${debit['width']} | {debit['days_to_expiry']}d")
    print(f"  Max Profit: ${debit['max_profit']:.0f} | Max Loss: ${debit['max_loss']:.0f} | R:R: {debit['risk_reward']}")
else:
    print("Debit: none")

# Step 2: Position Sizing
print("\n=== Step 2: Position Sizing ===")
risk_config = OptionsRiskConfig(max_risk_per_spread=200, max_contracts=5, max_total_risk=2000, min_credit_pct=25)

if credit and credit.get("verdict") in ("GOOD", "FAIR"):
    sizing = calculate_spread_contracts(
        spread_width=credit["width"],
        credit_or_debit=credit["net_credit"],
        is_credit=True,
        risk_config=risk_config,
    )
    print(f"Credit sizing: {sizing['contracts']} contracts, risk ${sizing.get('total_risk', 0):.0f}")
    if sizing.get("reason"):
        print(f"  Reason: {sizing['reason']}")
else:
    sizing = {"contracts": 0}
    print("Credit spread not GOOD/FAIR — skipped")

if debit and debit.get("verdict") in ("GOOD", "FAIR"):
    dsizing = calculate_spread_contracts(
        spread_width=debit["width"],
        credit_or_debit=debit["net_debit"],
        is_credit=False,
        risk_config=risk_config,
    )
    print(f"Debit sizing: {dsizing['contracts']} contracts, risk ${dsizing.get('total_risk', 0):.0f}")
    if dsizing.get("reason"):
        print(f"  Reason: {dsizing['reason']}")

# Step 3: Queue Order
print("\n=== Step 3: Queue Order ===")
if credit and sizing["contracts"] > 0:
    order = {
        "order_id": str(uuid.uuid4())[:8],
        "user_id": 1,
        "ticker": "XLF",
        "spread_type": credit["type"],
        "buy_strike": credit["long_strike"],
        "sell_strike": credit["short_strike"],
        "right": "C" if "Call" in credit["option_type"] else "P",
        "expiration": credit["expiration"],
        "quantity": sizing["contracts"],
        "limit_price": credit["net_credit"],
        "status": "queued",
        "auto": True,
    }
    print(f"Would queue: {order['spread_type']} {order['ticker']}")
    print(f"  SELL {order['sell_strike']} / BUY {order['buy_strike']} {order['right']}")
    print(f"  {order['quantity']}x @ ${order['limit_price']:.2f}")
    print(f"  Expiration: {order['expiration']}")
    print("\nFull order JSON:")
    print(json.dumps(order, indent=2))
else:
    print("No order to queue — sizing rejected or no GOOD/FAIR spread")
