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


def _load_creds():
    """Schwab client_id/secret + token path. Prefer env (how the prod
    services are configured — SCHWAB_CLIENT_ID/SECRET in the systemd env
    files); fall back to config.yaml for local runs."""
    cid = os.environ.get("SCHWAB_CLIENT_ID", "")
    csec = os.environ.get("SCHWAB_CLIENT_SECRET", "")
    if not cid or not csec:
        try:
            schwab_cfg = load_config("config.yaml").get("schwab", {})
            cid = cid or schwab_cfg.get("client_id", "")
            csec = csec or schwab_cfg.get("client_secret", "")
        except Exception:
            pass
    # Save to the SAME file the bot reads (web/sync default this path).
    token_file = os.environ.get("SCHWAB_TOKEN_FILE", "/opt/lumisignals/schwab_tokens.json")
    return cid, csec, token_file


def main():
    cid, csec, token_file = _load_creds()
    if not cid or not csec:
        print("Error: no Schwab creds. Set SCHWAB_CLIENT_ID/SECRET env "
              "(source the systemd env file) or provide config.yaml.")
        sys.exit(1)

    auth = SchwabAuth(client_id=cid, client_secret=csec, token_file=token_file)
    auth_url = auth.get_authorization_url()

    print(f"""
==========================================================
  Schwab Authorization   (tokens will save to {token_file})
==========================================================

1. Open this URL in a browser (your Mac), log in, click 'Allow':

   {auth_url}

2. You'll be redirected to https://127.0.0.1?code=...
   The browser will say it 'cannot connect' — THAT'S OK.
3. Copy the FULL URL from the address bar.
4. Paste it below IMMEDIATELY (the code expires in ~30s).

""")

    try:
        webbrowser.open(auth_url)   # no-op on a headless server; URL is printed above
    except Exception:
        pass

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
