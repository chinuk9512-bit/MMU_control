"""Tests for the SFTP workflow manager."""

from __future__ import annotations

import unittest

from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.core.sftp_manager import SFTPError, SFTPManager
from mmu_control.models.settings import BoardSettings


class FakeChannel:
    """Interactive channel fake used by SFTP tests."""

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str] = []

    def recv_ready(self) -> bool:
        """Return whether output is ready."""
        return False

    def recv(self, nbytes: int) -> bytes:
        """Return no output."""
        del nbytes
        return b""

    def send(self, data: str) -> int:
        """Record sent text."""
        self.sent.append(data)
        return len(data)

    def close(self) -> None:
        """Close the fake channel."""
        self.closed = True


class SFTPManagerTest(unittest.TestCase):
    """Tests for SFTP command preparation and prompt handling."""

    def test_open_ipv6_session_and_handle_password(self) -> None:
        """Manager opens an interface-scoped session and sends its password."""
        channel = FakeChannel()
        shell = InteractiveShell(channel)
        manager = SFTPManager()
        settings = BoardSettings(
            ip_address="fe80::1",
            username="root",
            password="secret",
            interface="eth0",
        )

        command = manager.open_session(shell, settings)
        handled = manager.handle_password_prompt(shell, "root password:", settings)

        self.assertEqual(command, "sftp root@[fe80::1%eth0]")
        self.assertEqual(channel.sent, ["sftp root@[fe80::1%eth0]\n", "secret\n"])
        self.assertTrue(handled)

    def test_required_fields_are_validated(self) -> None:
        """Board IP and username are required."""
        manager = SFTPManager()

        with self.assertRaises(SFTPError):
            manager.build_command(BoardSettings(username="root"))


if __name__ == "__main__":
    unittest.main()
