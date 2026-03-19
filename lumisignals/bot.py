"""Main bot orchestrator — loads config, starts signal intake, executes orders."""

import logging
import signal
import sys
import threading

import yaml

from .oanda_client import OandaClient
from .order_manager import OrderManager
from .signal_receiver import run_polling, create_webhook_app, run_mock
from .snr_filter import SNRClient, get_relevant_timeframes, check_snr_confluence

logger = logging.getLogger(__name__)

DISCLAIMER = """
==========================================================================
  LumiSignals Bot v0.1.0

  DISCLAIMER: For educational and informational purposes only.
  This is NOT investment advice. Use at your own risk.
  Test thoroughly with paper trading before using real funds.
==========================================================================
"""


def load_config(config_path: str) -> dict:
    """Load configuration from a YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


class LumiSignalsBot:
    """Orchestrates signal intake and order execution."""

    def __init__(self, config: dict, mode: str = None, dry_run: bool = False):
        self.config = config
        self.mode = mode or config.get("signals", {}).get("mode", "polling")
        self.dry_run = dry_run or config.get("bot", {}).get("dry_run", False)
        self._stop_event = threading.Event()

        # Set up logging
        log_level = config.get("bot", {}).get("log_level", "INFO")
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Signal strategy
        self.strategy = config.get("signals", {}).get("strategy", "top-tickers")

        # Initialize Oanda client
        oanda_cfg = config["oanda"]
        self.client = OandaClient(
            account_id=oanda_cfg["account_id"],
            api_key=oanda_cfg["api_key"],
            environment=oanda_cfg.get("environment", "practice"),
        )

        # Initialize order manager
        risk_cfg = config.get("risk", {})
        self.order_manager = OrderManager(
            client=self.client,
            risk_config=risk_cfg,
            dry_run=self.dry_run,
        )

        # Initialize SNR client if strategy uses it
        sig_cfg = config.get("signals", {})
        self.snr_client = None
        if self.strategy in ("snr", "combined"):
            base_url = sig_cfg.get("api_url", "").rsplit("/partners/", 1)[0]
            if not base_url:
                base_url = sig_cfg.get("base_url", "https://app.lumitrade.ai")
            self.snr_client = SNRClient(
                base_url=base_url,
                api_key=sig_cfg.get("api_key", ""),
            )

        # Trading timeframe for SNR level selection
        self.trading_timeframe = sig_cfg.get("trading_timeframe", "1h")
        self.primary_tfs, self.alert_tfs = get_relevant_timeframes(self.trading_timeframe)

        # SNR filter settings
        snr_cfg = config.get("snr", {})
        self.snr_min_grade = snr_cfg.get("min_grade", "C")
        self.snr_tolerance_pct = snr_cfg.get("tolerance_pct", 0.002)
        self.snr_market_type = snr_cfg.get("market_type", "forex")

    def _handle_signal(self, sig):
        """Callback for top-tickers strategy — execute directly."""
        logger.info("Processing signal: %s %s", sig.action, sig.symbol)
        result = self.order_manager.execute_signal(sig)
        if result.success:
            logger.info("Order placed — ID: %s | %s", result.order_id, result.details)
        else:
            logger.warning("Order failed — %s", result.error)

    def _handle_signal_with_snr(self, sig):
        """Callback for snr/combined strategy — validate against SNR levels first."""
        logger.info("Processing signal: %s %s (with SNR validation)", sig.action, sig.symbol)

        # Fetch SNR levels for this ticker
        all_tfs = list(set(self.primary_tfs + self.alert_tfs))
        snr_data = self.snr_client.get_snr_levels(
            ticker=sig.symbol,
            intervals=all_tfs,
            market_type=self.snr_market_type,
        )

        if not snr_data:
            logger.warning("No SNR data for %s — skipping", sig.symbol)
            return

        # Check confluence
        confluence = check_snr_confluence(
            entry=sig.entry,
            stop=sig.stop,
            target=sig.target,
            action=sig.action,
            snr_data=snr_data,
            primary_tfs=self.primary_tfs,
            alert_tfs=self.alert_tfs,
            tolerance_pct=self.snr_tolerance_pct,
        )

        logger.info("SNR result for %s %s: %s", sig.action, sig.symbol, confluence["summary"])

        # Log alert-level matches regardless of grade
        for match in confluence["alert_matches"]:
            logger.info(
                "ALERT: %s %s near untouched %s %s @ %.5f (distance: %.5f)",
                sig.symbol, match["role"], match["timeframe"],
                match["level_type"], match["level_price"], match["distance"],
            )

        # Check if grade meets minimum
        grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3}
        min_rank = grade_order.get(self.snr_min_grade, 3)
        sig_rank = grade_order.get(confluence["grade"], 3)

        if sig_rank > min_rank:
            logger.info("Skipping %s %s — grade %s below minimum %s",
                        sig.action, sig.symbol, confluence["grade"], self.snr_min_grade)
            return

        # Execute
        result = self.order_manager.execute_signal(sig)
        if result.success:
            logger.info("Order placed — ID: %s | Grade: %s | %s",
                        result.order_id, confluence["grade"], result.details)
        else:
            logger.warning("Order failed — %s", result.error)

    def start(self):
        """Start the bot."""
        print(DISCLAIMER)

        if self.dry_run:
            logger.info("DRY RUN mode — no real orders will be placed")

        # Validate Oanda connection
        if not self.dry_run:
            if not self.client.validate_connection():
                logger.error("Could not connect to Oanda. Check your credentials.")
                sys.exit(1)
        else:
            logger.info("Skipping Oanda connection check (dry-run mode)")

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        logger.info("Starting in %s mode | strategy: %s", self.mode, self.strategy)

        if self.strategy in ("snr", "combined"):
            logger.info("Trading timeframe: %s | Primary SNR: %s | Alert SNR: %s",
                        self.trading_timeframe, self.primary_tfs, self.alert_tfs)
            logger.info("Min grade: %s | Tolerance: %.3f%%", self.snr_min_grade, self.snr_tolerance_pct * 100)

        # Pick the signal handler based on strategy
        if self.strategy in ("snr", "combined"):
            handler = self._handle_signal_with_snr
        else:
            handler = self._handle_signal

        # Start signal intake
        if self.mode == "mock":
            mock_file = self.config.get("signals", {}).get("mock_file", "test_signals.json")
            run_mock(mock_file, handler)

        elif self.mode == "webhook":
            sig_cfg = self.config.get("signals", {})
            port = sig_cfg.get("webhook_port", 8080)
            secret = sig_cfg.get("webhook_secret")
            app = create_webhook_app(handler, webhook_secret=secret)
            logger.info("Webhook server listening on port %d", port)
            app.run(host="0.0.0.0", port=port)

        elif self.mode == "polling":
            sig_cfg = self.config.get("signals", {})
            run_polling(
                api_url=sig_cfg.get("api_url", ""),
                api_key=sig_cfg.get("api_key", ""),
                interval=sig_cfg.get("poll_interval_seconds", 60),
                on_signal=handler,
                stop_event=self._stop_event,
                market_filter=sig_cfg.get("market_filter", ""),
                min_rr=float(sig_cfg.get("min_reward_risk", 0)),
            )
        else:
            logger.error("Unknown mode: %s", self.mode)
            sys.exit(1)

    def _shutdown(self, signum, frame):
        """Handle graceful shutdown."""
        logger.info("Shutting down...")
        self._stop_event.set()
