"""Tests for minicom command preparation."""

from __future__ import annotations

import unittest

from mmu_control.core.minicom_manager import MinicomError, MinicomManager


class FakeShell:
    def __init__(self) -> None:
        self.sent = ""

    def send(self, text: str) -> int:
        self.sent += text
        return len(text)


class MinicomManagerTest(unittest.TestCase):
    def test_builds_command_for_detected_port(self) -> None:
        self.assertEqual(
            MinicomManager().build_command("/dev/ttyUSB0"),
            "minicom -o -c off -D /dev/ttyUSB0",
        )

    def test_rejects_non_serial_device(self) -> None:
        with self.assertRaises(MinicomError):
            MinicomManager().build_command("/dev/sda")

    def test_closes_minicom_with_control_sequence(self) -> None:
        shell = FakeShell()

        MinicomManager().close_session(shell)

        self.assertEqual(shell.sent, "\x01x\n")


if __name__ == "__main__":
    unittest.main()
