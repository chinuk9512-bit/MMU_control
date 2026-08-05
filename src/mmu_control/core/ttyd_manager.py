"""ttyd process lifecycle helpers for the Streamlit web terminal."""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mmu_control.models.settings import SSHSettings


class TtydError(RuntimeError):
    """Raised when ttyd cannot be started or managed."""


@dataclass(frozen=True, slots=True)
class TtydSession:
    """A running ttyd web terminal endpoint."""

    url: str
    port: int


class TtydManager:
    """Start and stop a local ttyd process for browser-based terminals."""

    def __init__(
        self,
        executable: str | None = None,
        host: str = "127.0.0.1",
        process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self._configured_executable = executable
        self._host = host
        self._process_factory = process_factory
        self._process: subprocess.Popen[str] | None = None
        self._session: TtydSession | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the managed ttyd process is still running."""
        return self._process is not None and self._process.poll() is None

    @property
    def session(self) -> TtydSession | None:
        """Return the active ttyd session endpoint, if one is running."""
        return self._session if self.is_running else None

    def start_ssh_terminal(self, settings: SSHSettings) -> TtydSession:
        """Start ttyd with an SSH client connected to the configured Linux server."""
        self.stop()
        executable = self._resolve_executable()
        ssh_command = self._ssh_command(settings)
        port = self._free_port()
        command = [
            executable,
            "--interface",
            self._host,
            "--port",
            str(port),
            *ssh_command,
        ]
        try:
            self._process = self._process_factory(  # noqa: S603 - command is built from fixed argv items.
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError as exc:
            raise TtydError(f"Failed to start ttyd: {exc}") from exc
        self._session = TtydSession(url=f"http://{self._host}:{port}", port=port)
        return self._session

    def stop(self) -> None:
        """Stop the managed ttyd process, if one exists."""
        process = self._process
        self._process = None
        self._session = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def _resolve_executable(self) -> str:
        configured = self._configured_executable or os.environ.get("MMU_CONTROL_TTYD")
        if configured:
            return self._resolve_candidate(configured)

        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            for bundled in (Path(bundle_dir) / "ttyd.exe", Path(bundle_dir) / "ttyd"):
                if bundled.is_file():
                    return str(bundled)

        resolved = shutil.which("ttyd")
        if resolved:
            return resolved
        raise TtydError(
            "ttyd executable was not found. Install ttyd, add it to PATH, or set MMU_CONTROL_TTYD."
        )

    def _resolve_candidate(self, candidate: str) -> str:
        if Path(candidate).is_file():
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        raise TtydError(f"Configured ttyd executable was not found: {candidate}")

    def _ssh_command(self, settings: SSHSettings) -> list[str]:
        if not settings.host.strip():
            raise TtydError("SSH host is required before starting ttyd.")
        if not settings.username.strip():
            raise TtydError("SSH user is required before starting ttyd.")
        destination = f"{settings.username.strip()}@{settings.host.strip()}"
        return [
            "ssh",
            "-p",
            str(settings.port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            destination,
        ]

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((self._host, 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def describe_command(settings: SSHSettings) -> str:
        """Return a user-readable SSH command that ttyd will host."""
        destination = f"{settings.username.strip()}@{settings.host.strip()}"
        return " ".join(
            shlex.quote(part)
            for part in ["ssh", "-p", str(settings.port), "-o", "StrictHostKeyChecking=accept-new", destination]
        )
