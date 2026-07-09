"""Tests for SSH manager lifecycle."""

from __future__ import annotations

import unittest

from mmu_control.core.ssh_manager import SSHConnectionError, SSHManager
from mmu_control.models.settings import SSHSettings


class FakeTransport:
    """Small transport fake for active-state checks."""

    def __init__(self, active: bool = True) -> None:
        self.active = active

    def is_active(self) -> bool:
        """Return whether the fake transport is active."""
        return self.active


class FakeClient:
    """Paramiko-like SSH client fake."""

    def __init__(self) -> None:
        self.closed = False
        self.connect_kwargs: dict[str, object] = {}
        self.transport = FakeTransport(False)
        self.shell_channel = FakeShellChannel()
        self.command_output = b""
        self.sftp = FakeSFTP()

    def set_missing_host_key_policy(self, policy: object) -> None:
        """Accept a host key policy."""
        self.policy = policy

    def connect(self, **kwargs: object) -> None:
        """Record connection parameters and mark transport active."""
        self.connect_kwargs = kwargs
        self.transport.active = True

    def get_transport(self) -> FakeTransport:
        """Return the fake transport."""
        return self.transport

    def invoke_shell(self, term: str, width: int, height: int) -> FakeShellChannel:
        """Return a fake shell channel."""
        self.shell_args = (term, width, height)
        return self.shell_channel

    def exec_command(self, command: str, timeout: float) -> tuple[object, FakeStream, FakeStream]:
        """Return configured command output."""
        self.executed_command = (command, timeout)
        return object(), FakeStream(self.command_output), FakeStream(b"")

    def open_sftp(self) -> "FakeSFTP":
        """Return a fake SFTP client."""
        return self.sftp

    def close(self) -> None:
        """Close the fake client."""
        self.closed = True
        self.transport.active = False


class FakeShellChannel:
    """Paramiko-like shell channel fake."""

    closed = False

    def recv_ready(self) -> bool:
        """Return whether output is pending."""
        return False

    def recv(self, nbytes: int) -> bytes:
        """Return no output."""
        del nbytes
        return b""

    def send(self, data: str) -> int:
        """Accept shell input."""
        return len(data)

    def close(self) -> None:
        """Close the shell channel."""
        self.closed = True


class FakeExitChannel:
    def recv_exit_status(self) -> int:
        return 0


class FakeStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.channel = FakeExitChannel()

    def read(self) -> bytes:
        return self._data


class FakeSFTP:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.closed = False

    def put(self, local_path: str, remote_path: str) -> None:
        self.put_calls.append((local_path, remote_path))

    def close(self) -> None:
        self.closed = True


class SSHManagerTest(unittest.TestCase):
    """Tests for SSH connection management."""

    def test_connect_disconnect_and_open_shell(self) -> None:
        """Manager connects, opens a shell, and disconnects."""
        fake_client = FakeClient()
        manager = SSHManager(client_factory=lambda: fake_client)

        manager.connect(SSHSettings(host="server", port=2222, username="user", password="pw"))
        shell = manager.open_shell()
        manager.disconnect()

        self.assertEqual(fake_client.connect_kwargs["hostname"], "server")
        self.assertEqual(fake_client.connect_kwargs["port"], 2222)
        self.assertTrue(shell.is_open)
        self.assertFalse(manager.is_connected)
        self.assertTrue(fake_client.closed)

    def test_reconnect_requires_previous_settings(self) -> None:
        """Reconnect fails before an initial connection."""
        manager = SSHManager(client_factory=FakeClient)

        with self.assertRaises(SSHConnectionError):
            manager.reconnect()

    def test_connect_requires_host_and_username(self) -> None:
        """Required SSH fields are validated before connecting."""
        manager = SSHManager(client_factory=FakeClient)

        with self.assertRaises(SSHConnectionError):
            manager.connect(SSHSettings(host="", username="user"))
        with self.assertRaises(SSHConnectionError):
            manager.connect(SSHSettings(host="server", username=""))

    def test_lists_remote_usb_serial_ports(self) -> None:
        """Only supported remote serial device paths are returned."""
        fake_client = FakeClient()
        fake_client.command_output = b"/dev/ttyUSB1\n/dev/sda\n/dev/ttyACM0\n"
        manager = SSHManager(client_factory=lambda: fake_client)
        manager.connect(SSHSettings(host="server", username="user"))

        ports = manager.list_serial_ports()

        self.assertEqual(ports, ["/dev/ttyACM0", "/dev/ttyUSB1"])

    def test_upload_file_uses_sftp_client(self) -> None:
        """Local files can be copied to the connected Linux server."""
        fake_client = FakeClient()
        manager = SSHManager(client_factory=lambda: fake_client)
        manager.connect(SSHSettings(host="server", username="user"))

        manager.upload_file("C:\\tmp\\firmware.bin", "/tmp/firmware.bin")

        self.assertEqual(
            fake_client.sftp.put_calls,
            [("C:\\tmp\\firmware.bin", "/tmp/firmware.bin")],
        )
        self.assertTrue(fake_client.sftp.closed)


if __name__ == "__main__":
    unittest.main()
