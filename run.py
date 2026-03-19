#!/usr/bin/env python3
"""
LumiSignals Bot — Entry point.

DISCLAIMER: For educational and informational purposes only.
This is NOT investment advice. Use at your own risk.
Test thoroughly with paper trading before using real funds.
"""

import argparse
import sys

from lumisignals.bot import LumiSignalsBot, load_config


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
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print(f"Error: Config file not found: {args.config}")
        print("Copy config.example.yaml to config.yaml and fill in your credentials.")
        sys.exit(1)

    bot = LumiSignalsBot(config=config, mode=args.mode, dry_run=args.dry_run)
    bot.start()


if __name__ == "__main__":
    main()
