"""SSH connection manager."""

from __future__ import annotations

from collections.abc import Callable

import paramiko

from mmu_control.core.error_recovery import RetryPolicy, run_with_retry
from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.models.settings import SSHSettings


class SSHConnectionError(RuntimeError):
    """Raised when an SSH operation cannot be completed."""


class SSHManager:
    """Manage SSH client connection lifecycle."""

    SERIAL_PORT_COMMAND = (
        "find /dev -maxdepth 1 -type c "
        "\\( -name 'ttyUSB*' -o -name 'ttyACM*' \\) -print 2>/dev/null | sort"
    )

    def __init__(
        self,
        client_factory: Callable[[], paramiko.SSHClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or paramiko.SSHClient
        self._client: paramiko.SSHClient | None = None
        self._last_settings: SSHSettings | None = None

    @property
    def is_connected(self) -> bool:
        """Return whether the SSH transport is currently active."""
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return bool(transport and transport.is_active())

    def connect(self, settings: SSHSettings, timeout_seconds: float = 10.0) -> None:
        """Connect to the configured SSH server."""
        self._validate_settings(settings)
        self.disconnect()

        client = self._client_factory()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            client.connect(
                hostname=settings.host,
                port=settings.port,
                username=settings.username,
                password=settings.password,
                timeout=timeout_seconds,
                look_for_keys=False,
                allow_agent=False,
            )
        except Exception as exc:
            client.close()
            raise SSHConnectionError(f"Failed to connect to {settings.host}:{settings.port}") from exc

        self._client = client
        self._last_settings = settings

    def disconnect(self) -> None:
        """Disconnect the current SSH client if one exists."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def reconnect(self, timeout_seconds: float = 10.0) -> None:
        """Reconnect using the last successful connection settings."""
        if self._last_settings is None:
            raise SSHConnectionError("No previous SSH settings are available.")
        self.connect(self._last_settings, timeout_seconds=timeout_seconds)

    def reconnect_with_retry(
        self,
        policy: RetryPolicy | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        """Reconnect using a retry policy for transient failures."""
        run_with_retry(
            lambda: self.reconnect(timeout_seconds=timeout_seconds),
            policy=policy,
            retry_on=(SSHConnectionError,),
        )

    def open_shell(self, term: str = "vt100", width: int = 120, height: int = 40) -> InteractiveShell:
        """Open an interactive shell over the active SSH connection."""
        client = self._require_client()
        try:
            channel = client.invoke_shell(term=term, width=width, height=height)
        except Exception as exc:
            raise SSHConnectionError("Failed to open interactive shell.") from exc
        return InteractiveShell(channel)

    def execute_command(self, command: str, timeout_seconds: float = 10.0) -> str:
        """Execute a non-interactive command on the connected server."""
        client = self._require_client()
        try:
            _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_seconds)
            output = stdout.read().decode("utf-8", errors="replace")
            error_output = stderr.read().decode("utf-8", errors="replace")
            exit_status = stdout.channel.recv_exit_status()
        except Exception as exc:
            raise SSHConnectionError("Failed to execute a remote command.") from exc
        if exit_status != 0:
            detail = error_output.strip() or f"exit status {exit_status}"
            raise SSHConnectionError(f"Remote command failed: {detail}")
        return output

    def list_serial_ports(self) -> list[str]:
        """Return USB serial device paths found on the connected Linux server."""
        output = self.execute_command(self.SERIAL_PORT_COMMAND)
        prefixes = ("/dev/ttyUSB", "/dev/ttyACM")
        return sorted({line.strip() for line in output.splitlines() if line.strip().startswith(prefixes)})

    def _require_client(self) -> paramiko.SSHClient:
        if self._client is None or not self.is_connected:
            raise SSHConnectionError("SSH client is not connected.")
        return self._client

    def _validate_settings(self, settings: SSHSettings) -> None:
        if not settings.host.strip():
            raise SSHConnectionError("SSH host is required.")
        if not settings.username.strip():
            raise SSHConnectionError("SSH username is required.")
        if not 1 <= settings.port <= 65535:
            raise SSHConnectionError("SSH port must be between 1 and 65535.")
