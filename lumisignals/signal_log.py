"""Local signal log — stores strategy metadata for each order placed."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOG_FILE = "signal_log.json"


class SignalLog:
    """Persists signal metadata keyed by Oanda order ID."""

    def __init__(self, path: str = LOG_FILE):
        self.path = Path(path)
        self._entries = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._entries = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._entries = {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self._entries, indent=2, default=str))
        except OSError as e:
            logger.error("Failed to save signal log: %s", e)

    def record(self, order_id: str, data: dict):
        """Record signal metadata for an order."""
        data["logged_at"] = datetime.now(timezone.utc).isoformat()
        self._entries[order_id] = data
        self._save()

    def get(self, order_id: str) -> Optional[dict]:
        """Get signal metadata for an order ID."""
        return self._entries.get(order_id)

    def get_all(self) -> dict:
        """Get all logged entries."""
        return self._entries


# Global instance
_log = None


def get_signal_log(path: str = LOG_FILE) -> SignalLog:
    global _log
    if _log is None:
        _log = SignalLog(path)
    return _log
