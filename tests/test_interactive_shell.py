"""Tests for interactive shell channel wrapper."""

from __future__ import annotations

import unittest

from mmu_control.core.interactive_shell import InteractiveShell


class FakeChannel:
    """Small shell channel fake for unit tests."""

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str] = []
        self.output: list[bytes] = []

    def recv_ready(self) -> bool:
        """Return whether output remains."""
        return bool(self.output)

    def recv(self, nbytes: int) -> bytes:
        """Return the next output chunk."""
        del nbytes
        return self.output.pop(0)

    def send(self, data: str) -> int:
        """Record sent data."""
        self.sent.append(data)
        return len(data)

    def close(self) -> None:
        """Close the fake channel."""
        self.closed = True


class InteractiveShellTest(unittest.TestCase):
    """Tests for shell send and receive helpers."""

    def test_send_line_and_read_available(self) -> None:
        """Shell sends commands and reads pending output."""
        channel = FakeChannel()
        channel.output.extend([b"hello", b" world"])
        shell = InteractiveShell(channel)

        shell.send_line("pwd")
        output = shell.read_available()

        self.assertEqual(channel.sent, ["pwd\n"])
        self.assertEqual(output, "hello world")

    def test_closed_shell_rejects_send(self) -> None:
        """Closed shells do not accept new input."""
        channel = FakeChannel()
        shell = InteractiveShell(channel)

        shell.close()

        with self.assertRaises(RuntimeError):
            shell.send("ls")


if __name__ == "__main__":
    unittest.main()
