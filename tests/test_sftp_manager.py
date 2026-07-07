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
        self.assertEqual(
            channel.sent,
            ["rm -f ~/.ssh/known_hosts\n", "sftp root@[fe80::1%eth0]\n", "secret\n"],
        )
        self.assertTrue(handled)

    def test_authenticity_prompt_is_accepted(self) -> None:
        """Manager accepts first-connection SFTP host authenticity prompts."""
        channel = FakeChannel()
        shell = InteractiveShell(channel)
        manager = SFTPManager()

        prompt = (
            "The authenticity of host 'board' can't be established. "
            "Are you sure you want to continue connecting (yes/no/[fingerprint])?"
        )

        handled = manager.handle_authenticity_prompt(shell, prompt)

        self.assertTrue(handled)
        self.assertEqual(channel.sent, ["yes\n"])

    def test_authenticity_confirmation_prompt_is_accepted(self) -> None:
        """Manager also accepts wrapped prompts that only include the confirmation text."""
        channel = FakeChannel()
        shell = InteractiveShell(channel)
        manager = SFTPManager()

        handled = manager.handle_authenticity_prompt(
            shell,
            "Are you sure you want to continue connecting (yes/no/[fingerprint])?",
        )

        self.assertTrue(handled)
        self.assertEqual(channel.sent, ["yes\n"])

    def test_required_fields_are_validated(self) -> None:
        """Board IP and username are required."""
        manager = SFTPManager()

        with self.assertRaises(SFTPError):
            manager.build_command(BoardSettings(username="root"))

    def test_transfer_commands_are_quoted_and_session_can_close(self) -> None:
        """Put/get preserve paths with spaces and bye leaves SFTP mode."""
        channel = FakeChannel()
        shell = InteractiveShell(channel)
        manager = SFTPManager()

        manager.upload(shell, "/tmp/update file.bin", "/opt/update.bin")
        manager.download(shell, "/opt/result.bin", "/tmp/result file.bin")
        manager.close_session(shell)

        self.assertEqual(
            channel.sent,
            [
                "put '/tmp/update file.bin' /opt/update.bin\n",
                "get /opt/result.bin '/tmp/result file.bin'\n",
                "bye\n",
            ],
        )


if __name__ == "__main__":
    unittest.main()
