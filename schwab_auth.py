#!/usr/bin/env python3
"""Schwab OAuth2 authorization helper.

Run: python3 schwab_auth.py
No sudo needed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import webbrowser
from urllib.parse import urlparse, parse_qs
from lumisignals.schwab_client import SchwabAuth
from lumisignals.bot import load_config


def main():
    config = load_config("config.yaml")
    schwab_cfg = config.get("schwab", {})

    if not schwab_cfg.get("client_id"):
        print("Error: No Schwab client_id in config.yaml")
        sys.exit(1)

    auth = SchwabAuth(
        client_id=schwab_cfg["client_id"],
        client_secret=schwab_cfg["client_secret"],
    )

    auth_url = auth.get_authorization_url()

    print(f"""
==========================================================
  Schwab Authorization
==========================================================

1. Opening Schwab login in your browser...
2. Log in and click 'Allow'
3. You'll see 'Safari cannot connect' — THAT'S OK
4. Look at the ADDRESS BAR — copy the FULL URL
5. Come back here and paste it IMMEDIATELY (codes expire in 30s)

""")

    webbrowser.open(auth_url)

    redirect_url = input("Paste the redirect URL here → ").strip()

    # Extract code
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    if not code:
        code = redirect_url  # Maybe they pasted just the code

    print("Exchanging code for tokens...")
    if auth.exchange_code(code):
        print("\n✓ Authorization successful! Tokens saved to schwab_tokens.json")

        # Quick test
        from lumisignals.schwab_client import SchwabMarketData
        md = SchwabMarketData(auth)
        quote = md.get_quote("AAPL")
        if quote:
            print("✓ Market data connection verified!")
        else:
            print("⚠ Could not fetch test quote — but tokens are saved")
    else:
        print("\n✗ Failed. Try again — codes expire in ~30 seconds.")
        print("  Run: python3 schwab_auth.py")


if __name__ == "__main__":
    main()
