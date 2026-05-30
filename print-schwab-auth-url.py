#!/usr/bin/env python3
"""Print Schwab OAuth authorization URL (no browser open).
Run from ~/projects/LumiSignals with venv activated."""

import yaml
from lumisignals.schwab_client import SchwabAuth


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    auth = SchwabAuth(
        client_id=cfg["schwab"]["client_id"],
        client_secret=cfg["schwab"]["client_secret"],
        redirect_uri=cfg["schwab"]["redirect_uri"],
    )

    print()
    print("=" * 70)
    print("Schwab OAuth Authorization URL")
    print("=" * 70)
    print()
    print(auth.get_authorization_url())
    print()
    print("=" * 70)
    print("Open the URL above in your browser, log in to Schwab, click Allow.")
    print("You'll get a 'connection refused' page — copy the FULL redirect URL")
    print("from the address bar and paste it back into the schwab_auth.py prompt.")
    print("Auth codes expire in 30 seconds — be quick.")
    print("=" * 70)


if __name__ == "__main__":
    main()
