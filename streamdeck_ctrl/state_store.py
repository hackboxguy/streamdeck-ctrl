"""Runtime state persistence to JSON file with atomic writes."""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)


class StateStore:
    """Thread-safe state persistence backed by a JSON file.

    Uses atomic write (write to .tmp then os.replace) to prevent
    partial writes on crash.
    """

    def __init__(self, path):
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self):
        return self._path

    def load(self):
        """Load persisted state from file.

        Returns:
            dict: The persisted state, or empty dict if file doesn't exist
                  or is corrupt.
        """
        if not os.path.isfile(self._path):
            logger.debug("State file not found: %s, starting fresh", self._path)
            return {}
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            logger.info("Loaded persisted state from %s (%d entries)", self._path, len(data))
            return data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("Failed to load state file %s: %s", self._path, e)
            return {}

    def save(self, data):
        """Persist state atomically.

        Args:
            data: dict to serialize to JSON.
        """
        with self._lock:
            self._atomic_write(data)

    def _atomic_write(self, data):
        """Write data to a temp file, then atomically replace the target."""
        tmp_path = self._path + ".tmp"
        try:
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
            logger.debug("State persisted to %s", self._path)
        except IOError as e:
            logger.error("Failed to persist state to %s: %s", self._path, e)
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
