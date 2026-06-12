# Submitting Options Orders via IB (IBeam / CPAPI)

How option **spreads** are placed and closed through the IBeam Client Portal
API gateway (`https://localhost:5000/v1/api`). IB is the primary feed for
both the options chain and order execution.

## The one rule: spreads are COMBOS, never legs

**Always submit a spread as a single combo order. Never leg in or out with
separate single-leg orders.** Two hard reasons:

1. **Account permissions.** The trading account is *spread-permissioned*. A
   lone option leg (e.g. a single `SELL` put) is rejected:
   `"You are not able to submit this order because you do not have trading
   permissions for this options strategy."` A defined-risk combo is allowed.
2. **Atomicity.** A combo fills or doesn't as one unit. Legging risks a
   half-filled spread (a naked leg) or, with retries, **double-fills**.

(Exception: the ORB butterfly deliberately *legs into* a butterfly — debit
spread first, then the credit spread after the debit fills — but each of
those steps is itself a defined-risk spread.)

## The conidex combo format

A combo order uses `conidex` instead of `conid`:

```
conidex = "{SPREAD_CONID};;;{leg_conid}/{±ratio},{leg_conid}/{±ratio}[,...]"
```

- **`SPREAD_CONID`** is the currency's spread id. **USD = `28812380`**
  (full table in `lumisignals/ibkr_cpapi.py` `SPREAD_CONID`).
- **`±ratio`**: the sign is the side (**`+` = BUY leg, `-` = SELL leg**),
  the number is the per-leg quantity multiplier.
- The order's top-level `side` is **always `"BUY"`**; direction is carried by
  the leg signs and the price sign (below).

Build it with `CPAPIClient.build_combo_order(legs, quantity, limit_price,
order_type, ...)` — do **not** hand-assemble the conidex (the older builders
got it wrong three ways: missing the spread-conid prefix, `;;;`-separated bare
conids, and a stray `legs` array → `"Combo key is not complete"`).

## Price sign (critical)

`limit_price` is the **net** price of the whole combo:
- **POSITIVE = pay a debit** (you're buying the spread).
- **NEGATIVE = receive a credit** (you're selling the spread).

## Order type: LMT, never MKT

**Use `orderType="LMT"` with a marketable limit. Never `MKT` on a combo.**
A MKT combo "submits" (HTTP 200 + order_id) but **never reaches IB** — it
ghosts, and cancels return `400 "OrderID doesn't exist"`. This is what
accumulated 84 phantom orders historically. (Single-leg MKT *does* work — see
"Emergency leg cleanup" — but spreads must be LMT combos.)

## Open a debit spread

Legs: **BUY the long `/+1`, SELL the short `/-1`**. Price = **positive** debit.

```python
debit = (long_ask - short_bid)            # marketable; pad +0.05 to ensure fill
payload = client.build_combo_order(
    legs=[(long_conid, "BUY", 1), (short_conid, "SELL", 1)],
    quantity=contracts, limit_price=round(debit, 2),
    order_type="LMT", tif="DAY", coid=f"lumi_swing_{uuid4().hex[:12]}")
result = client.place_order(payload)
# walk the confirmation prompt loop (see below)
```

This is the live path behind `POST /api/option-spread/order` (`saas/app.py`),
which the dashboard "Open Trade" button calls. That endpoint is
**`login_required`** (mobile Flask session) — you can't drive it with the
sync key; for scripted/server-side placement build the combo directly.

## Close a spread (combo)

Reverse the leg signs; price flips to a **credit**.

- **Debit spread close** → `SELL long /-1, BUY short /+1`, **negative** price
  (you receive a credit ≈ `long_bid - short_ask`).
- **Credit spread close** → `BUY long /+1, SELL short /-1`, **positive** price.

```python
credit = max(0.01, long_bid - short_ask)
payload = client.build_combo_order(
    legs=[(long_conid, "SELL", 1), (short_conid, "BUY", 1)],
    quantity=qty, limit_price=-round(credit, 2),
    order_type="LMT", tif="DAY", coid=f"lumi_close_{uuid4().hex[:10]}")
```

This is what `_close_spread()` in `lumisignals/ibkr_sync_cpapi.py` does: price
the legs, place one marketable-LMT combo, poll the fill, and re-price once
more aggressively (cancel-then-replace — safe because it's a single atomic
combo) if needed.

## The confirmation-reply loop

`place_order` often returns a confirmation prompt instead of an order id. Walk
it:

```python
r = client.place_order(payload)
while isinstance(r, list) and r and "id" in r[0] and "order_id" not in r[0]:
    r = client._request("POST", "/iserver/reply/" + r[0]["id"],
                        json_data={"confirmed": True})
order_id = r[0]["order_id"] if isinstance(r, list) and r and r[0].get("order_id") else None
```

Then tag the perm id for the reconciler: `record_strategy_for_perm(r, strategy)`.

## Resolving leg conids

Use `_resolve_option_conid(client, symbol, "YYYYMMDD", strike, "C"|"P")`
(`ibkr_sync_cpapi.py`): tries `search_option_contract` (STK underlying), and
for index roots (SPX/NDX/RUT…) falls back to IND search. For **SPX prefer the
`SPXW`** trading class (PM-settled weekly) over the AM-settled monthly. The
options *chain* (strikes + greeks) is pulled in `lumisignals/ib_options_chain.py`.

## Confirming a fill

Don't trust the place response. Poll the order, and verify the **position**:
- `client.get_order_fill(order_id, max_wait=12)` → `{filled, avg_price, status}`.
- Then re-read `/portfolio/{acct}/positions/0` and confirm the leg quantities
  changed. Position truth > order status.

## Market data

- During **regular hours**, option quotes/greeks are **real-time**
  (`6509` field starts with `R`, e.g. `RpBd`). Greeks: field `7308` = delta
  (signed), `7283` = IV, `84`/`86` = bid/ask, `31` = last.
- **After hours** options are **frozen** (`6509` starts with `Z`) — last-known
  values, fine for selection but not for live pricing.

## Emergency single-leg cleanup

If a spread ends up half-open (one naked leg), you can flatten **that one leg**
with a single-leg order — and single-leg **MKT works** here (it's how a stuck
long leg got closed once). But this is cleanup only; never *build* a spread by
legging.

## Paper-account caveat (DUP888072)

The paper account fills option orders **unreliably** — clearly-marketable
limits (and even the proven entry combo) can sit unfilled for minutes or not
at all, and some orders can't be cancelled (`"OrderID doesn't exist"` while
still showing live). This makes paper a poor place to validate fills. Prefer a
tiny **real-money** round-trip (where marketable combos fill instantly) to
verify close behaviour before enabling the auto-exit monitor.

## Auto-exit monitor kill switch

The spread exit monitor (`monitor_spreads`) is gated behind a Redis flag,
**default OFF**, and only runs when the reconcile gate is clear:
```bash
redis-cli set ibkr:spread_monitor:enabled 1   # enable (after a live close is verified)
redis-cli del ibkr:spread_monitor:enabled     # instant kill
```

## Key files

- `lumisignals/ibkr_cpapi.py` — `build_combo_order`, `SPREAD_CONID`,
  `place_order`, `get_order_fill`, `search_option_contract`.
- `lumisignals/ibkr_sync_cpapi.py` — `_close_spread` (combo close),
  `_resolve_option_conid`, `monitor_spreads`, `check_order_requests`.
- `saas/app.py` — `/api/option-spread/order` (entry), manual `options_close`.
- `lumisignals/ib_options_chain.py` — strikes + greeks chain provider.
