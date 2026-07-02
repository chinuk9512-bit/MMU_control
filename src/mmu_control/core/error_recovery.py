"""Retry and recovery helpers for transient operations."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar


T = TypeVar("T")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry settings for a transient operation."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.5
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1.")


class RecoveryError(RuntimeError):
    """Raised when all retry attempts have failed."""


def run_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy | None = None,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run an operation using the supplied retry policy."""
    active_policy = policy or RetryPolicy()
    delay = active_policy.initial_delay_seconds
    last_error: Exception | None = None

    for attempt in range(1, active_policy.max_attempts + 1):
        try:
            return operation()
        except retry_on as exc:
            last_error = exc
            LOGGER.warning(
                "Operation failed on attempt %s/%s: %s",
                attempt,
                active_policy.max_attempts,
                exc,
            )
            if attempt < active_policy.max_attempts:
                sleep(delay)
                delay *= active_policy.backoff_multiplier

    raise RecoveryError(
        f"Operation failed after {active_policy.max_attempts} attempts."
    ) from last_error
