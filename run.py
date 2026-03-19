#!/usr/bin/env python3
"""
LumiSignals Bot — Entry point.

DISCLAIMER: For educational and informational purposes only.
This is NOT investment advice. Use at your own risk.
Test thoroughly with paper trading before using real funds.
"""

import argparse
import sys
import webbrowser
import threading


def main():
    parser = argparse.ArgumentParser(
        description="LumiSignals Bot — execute trade signals via Oanda",
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--mode", choices=["polling", "webhook", "mock"],
        help="Signal intake mode (overrides config)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log orders without executing them",
    )
    parser.add_argument(
        "--web", action="store_true", default=True,
        help="Launch web dashboard (default)",
    )
    parser.add_argument(
        "--no-web", action="store_true",
        help="Run in CLI mode without web dashboard",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Web dashboard port (default: 5000)",
    )
    args = parser.parse_args()

    if args.no_web:
        # CLI mode — original behavior
        from lumisignals.bot import LumiSignalsBot, load_config
        try:
            config = load_config(args.config)
        except FileNotFoundError:
            print(f"Error: Config file not found: {args.config}")
            print("Copy config.example.yaml to config.yaml and fill in your credentials.")
            sys.exit(1)

        bot = LumiSignalsBot(config=config, mode=args.mode, dry_run=args.dry_run)
        bot.start()
    else:
        # Web dashboard mode
        from lumisignals.web.app import create_web_app
        app = create_web_app()

        url = f"http://localhost:{args.port}"
        print(f"""
==========================================================================
  LumiSignals Bot v0.1.0

  Dashboard: {url}
  Opening in your browser...

  Press Ctrl+C to quit.
==========================================================================
""")
        # Open browser after a short delay
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
