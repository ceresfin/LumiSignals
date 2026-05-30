#!/usr/bin/env python3
"""ORB place_order payload smoke test — iterate on payload variations
without waiting for real signals.

Why this exists: the ORB butterfly handler's `_place_leg` intermittently
fails with `{'error': 'Combo key is not complete'}` from IB CPAPI even
though the payload is structurally identical to the working 2n20 single-
leg payload. This script picks a far-OTM SPX 0DTE option and submits a
1-lot LMT at an unfillable price, captures the response, and cancels
immediately if accepted. Run repeatedly + with payload variations to
identify what triggers the rejection.

Usage (from lumi-prod):
    sudo bash -c "set -a; . /etc/lumisignals/ibkr-sync.env; set +a; \\
        /opt/lumisignals/venv/bin/python3 /opt/lumisignals/app/bin/orb_place_smoke.py"

Variants tested (in order):
  1. baseline ORB payload (same as _place_leg in production)
  2. baseline + 250ms gap between calls (simulates Phase 3 mitigation)
  3. baseline + 2s gap (much larger gap — does the gap matter at all?)
  4. baseline with `secType: OPT` field (in case CPAPI needs the hint)
  5. baseline with `tif: GTC` instead of DAY

After each variant, prints the response and whether order_id came back.
Cancels any accepted order immediately."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumisignals.ibkr_cpapi import CPAPIClient
from lumisignals.orb_butterfly_handler import _lookup_option_conid
from lumisignals.orb_quote_source import (
    get_quote_source, build_occ_symbol, OPTION_ROOT_MAP,
)


# Pick a far-OTM strike that won't accidentally fill at any reasonable
# market — for a typical SPX around 7,580, 6,500 puts are way out of
# the money and won't have a marketable bid. Buy them at $0.05 (won't
# happen).
FAR_OTM_STRIKE = 6500.0
FAR_OTM_RIGHT = "P"
LIMIT_PRICE = 0.05
QTY = 1


def _next_business_day_yyyymmdd():
    """Today's 0DTE if it's a trading day, else next trading day. Skips
    weekends; doesn't try to skip holidays."""
    from datetime import datetime, timedelta, timezone
    et = datetime.now(timezone.utc) - timedelta(hours=4)
    d = et.date()
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d = d + timedelta(days=1)
    return d.strftime("%Y%m%d")


def _try_payload(client, payload, label):
    print(f"\n--- {label} ---")
    print(f"payload: {json.dumps(payload)}")
    t0 = time.time()
    try:
        result = client.place_order(payload)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"EXCEPTION in {elapsed:.2f}s: {type(e).__name__}: {e}")
        return
    elapsed = time.time() - t0
    print(f"response in {elapsed:.2f}s: {json.dumps(result, default=str)[:400]}")

    # Walk any confirmation prompts
    walked = 0
    while isinstance(result, list) and result and "id" in result[0] and "order_id" not in result[0]:
        walked += 1
        if walked > 5:
            print(f"  too many reply prompts ({walked}); bailing")
            break
        try:
            result = client._request(
                "POST", "/iserver/reply/" + result[0]["id"],
                json_data={"confirmed": True},
            )
            print(f"  reply {walked}: {json.dumps(result, default=str)[:300]}")
        except Exception as e:
            print(f"  reply walk failed: {e}")
            break

    # Extract order_id, cancel if accepted
    oid = None
    if isinstance(result, list) and result and result[0].get("order_id"):
        oid = result[0]["order_id"]
    elif isinstance(result, dict) and result.get("order_id"):
        oid = result["order_id"]
    if oid:
        print(f"ACCEPTED order_id={oid} — cancelling immediately")
        try:
            cancel_resp = client.cancel_order(oid)
            print(f"  cancel response: {cancel_resp}")
        except Exception as e:
            print(f"  cancel failed: {e}")
    else:
        # Extract error string for easy grepping
        err = None
        candidates = result if isinstance(result, list) else [result]
        for item in candidates:
            if isinstance(item, dict):
                for k in ("error", "errorMessage", "message"):
                    if item.get(k):
                        err = item[k]
                        break
        if err:
            print(f"REJECTED — error: {err!r}")
        else:
            print(f"NO order_id returned (no error string either)")


def main():
    client = CPAPIClient(base_url="https://localhost:5000/v1/api")
    if not client.account_id:
        # ensure_session populates account_id
        client.ensure_session()
    print(f"account_id: {client.account_id}")

    # Build the OCC + look up the conid
    expiry = _next_business_day_yyyymmdd()
    root = OPTION_ROOT_MAP.get("SPX", "SPXW")
    occ = build_occ_symbol(root, expiry, FAR_OTM_RIGHT, FAR_OTM_STRIKE)
    print(f"target option: {occ} (expiry {expiry}, strike {FAR_OTM_STRIKE} {FAR_OTM_RIGHT})")

    conid = _lookup_option_conid(client, "SPX", expiry, FAR_OTM_STRIKE, FAR_OTM_RIGHT)
    print(f"conid: {conid}")
    if not conid:
        print("ERROR: conid lookup failed; can't continue")
        return

    base_order = {
        "conid": conid,
        "orderType": "LMT",
        "side": "BUY",
        "quantity": QTY,
        "price": LIMIT_PRICE,
        "tif": "DAY",
    }

    # Variant 1: baseline (production payload)
    _try_payload(client, {"orders": [dict(base_order)]}, "1. BASELINE")

    # Variant 2: baseline twice back-to-back (the production failure scenario)
    _try_payload(client, {"orders": [dict(base_order)]}, "2. BASELINE rapid (no gap)")

    # Variant 3: after a 250ms gap
    time.sleep(0.25)
    _try_payload(client, {"orders": [dict(base_order)]}, "3. AFTER 250ms gap")

    # Variant 4: after a 2s gap
    time.sleep(2.0)
    _try_payload(client, {"orders": [dict(base_order)]}, "4. AFTER 2s gap")

    # Variant 5: explicit secType
    p5 = dict(base_order); p5["secType"] = "OPT"
    _try_payload(client, {"orders": [p5]}, "5. WITH secType=OPT")

    # Variant 6: GTC instead of DAY
    p6 = dict(base_order); p6["tif"] = "GTC"
    _try_payload(client, {"orders": [p6]}, "6. WITH tif=GTC")

    # Variant 7: explicit acctId in order
    p7 = dict(base_order); p7["acctId"] = client.account_id
    _try_payload(client, {"orders": [p7]}, "7. WITH explicit acctId in order")

    # Variant 8: explicit cOID
    p8 = dict(base_order); p8["cOID"] = f"lumi_smoke_{int(time.time())}"
    _try_payload(client, {"orders": [p8]}, "8. WITH cOID")

    print("\n=== SMOKE COMPLETE ===")
    print("Look for: which variant(s) returned an order_id vs which failed,")
    print("and what the specific error string was for failures. The first")
    print("variant to fail under repeated runs tells us where the boundary is.")


if __name__ == "__main__":
    main()
