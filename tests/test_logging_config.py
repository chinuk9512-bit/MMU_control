"""Tests for logging configuration."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from mmu_control.core.logging_config import configure_logging, shutdown_logging


class LoggingConfigTest(unittest.TestCase):
    """Tests for application log setup."""

    def test_configure_logging_creates_log_file(self) -> None:
        """Configuring logging creates and writes the selected log file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "mmu_control.log"

            configured_path = configure_logging(log_path, level=logging.DEBUG)
            logging.getLogger("test").info("hello")
            for handler in logging.getLogger().handlers:
                handler.flush()

            self.assertEqual(configured_path, log_path)
            self.assertIn("hello", log_path.read_text(encoding="utf-8"))
            shutdown_logging()


if __name__ == "__main__":
    unittest.main()
