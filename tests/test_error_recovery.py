"""Tests for retry and error recovery helpers."""

from __future__ import annotations

import unittest

from mmu_control.core.error_recovery import RecoveryError, RetryPolicy, run_with_retry


class ErrorRecoveryTest(unittest.TestCase):
    """Tests for transient operation retry behavior."""

    def test_operation_succeeds_after_retry(self) -> None:
        """A transient failure is retried until the operation succeeds."""
        attempts = 0
        delays: list[float] = []

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("temporary")
            return "ok"

        result = run_with_retry(
            operation,
            policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=0.1,
                backoff_multiplier=2,
            ),
            retry_on=(OSError,),
            sleep=delays.append,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(delays, [0.1, 0.2])

    def test_exhausted_retries_raise_recovery_error(self) -> None:
        """Permanent failures raise RecoveryError after all attempts."""
        with self.assertRaises(RecoveryError):
            run_with_retry(
                lambda: (_ for _ in ()).throw(OSError("failed")),
                policy=RetryPolicy(max_attempts=2, initial_delay_seconds=0),
                retry_on=(OSError,),
                sleep=lambda delay: None,
            )


if __name__ == "__main__":
    unittest.main()
