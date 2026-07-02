"""Application logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mmu_control.core.config_manager import default_config_path


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def default_log_path() -> Path:
    """Return the default application log file path."""
    return default_config_path().with_name("mmu_control.log")


def configure_logging(log_path: Path | None = None, level: int = logging.INFO) -> Path:
    """Configure file and console logging for the application."""
    resolved_path = log_path or default_log_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    shutdown_logging()

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = RotatingFileHandler(
        resolved_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    logging.getLogger(__name__).info("Logging configured: %s", resolved_path)
    return resolved_path


def shutdown_logging() -> None:
    """Flush, close, and remove all root logging handlers."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.flush()
        handler.close()
        root_logger.removeHandler(handler)
