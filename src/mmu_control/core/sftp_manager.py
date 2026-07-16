"""SFTP workflow manager for MMU access through the Linux server."""

from __future__ import annotations

import re
import shlex

from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.models.settings import BoardSettings


class SFTPError(RuntimeError):
    """Raised when an SFTP workflow cannot be prepared or executed."""


class SFTPManager:
    """Build and run MMU SFTP commands inside an interactive SSH shell."""

    PASSWORD_PROMPT = "password:"
    AUTHENTICITY_PROMPT = "authenticity of host"
    AUTHENTICITY_RESPONSE_PROMPT = "yes/no"
    KNOWN_HOSTS_CLEANUP_COMMAND = "rm -f ~/.ssh/known_hosts"
    CONNECTION_FAILURE_PATTERNS = (
        "connection refused",
        "connection timed out",
        "connection closed",
        "could not resolve hostname",
        "name or service not known",
        "no route to host",
        "network is unreachable",
        "permission denied",
        "host key verification failed",
        "lost connection",
    )

    def build_command(self, settings: BoardSettings) -> str:
        """Build the Linux-side SFTP command for the MMU settings."""
        self._validate_settings(settings)
        destination = self._format_destination(settings)
        command = ["sftp"]
        if settings.ssh_port != 22:
            command.extend(["-P", str(settings.ssh_port)])
        if settings.ssh_key_path.strip():
            command.extend(["-i", settings.ssh_key_path.strip()])
        command.append(f"{settings.username.strip()}@{destination}")
        return " ".join(shlex.quote(part) for part in command)

    def open_session(self, shell: InteractiveShell, settings: BoardSettings) -> str:
        """Start an SFTP session from the connected Linux server."""
        command = self.build_command(settings)
        shell.send_line(self.KNOWN_HOSTS_CLEANUP_COMMAND)
        shell.send_line(command)
        return command

    def handle_authenticity_prompt(self, shell: InteractiveShell, output: str) -> bool:
        """Accept first-connection host authenticity prompts."""
        output_lower = output.lower()
        if (
            self.AUTHENTICITY_PROMPT not in output_lower
            or self.AUTHENTICITY_RESPONSE_PROMPT not in output_lower
        ):
            return False
        shell.send_line("yes")
        return True

    def handle_password_prompt(
        self,
        shell: InteractiveShell,
        output: str,
        settings: BoardSettings,
    ) -> bool:
        """Send the MMU password when the SFTP password prompt appears."""
        if not settings.password:
            return False
        return shell.respond_to_prompt(output, self.PASSWORD_PROMPT, settings.password)

    def connection_failed(self, output: str) -> bool:
        """Return whether SFTP startup output contains a connection failure."""
        output_lower = output.lower()
        return any(pattern in output_lower for pattern in self.CONNECTION_FAILURE_PATTERNS)

    def upload(self, shell: InteractiveShell, server_path: str, board_path: str) -> str:
        """Upload a Linux-server file to the MMU in an open SFTP session."""
        command = self._build_transfer_command("put", server_path, board_path)
        shell.send_line(command)
        return command

    def download(self, shell: InteractiveShell, board_path: str, server_path: str) -> str:
        """Download a MMU file to the Linux server in an open SFTP session."""
        command = self._build_transfer_command("get", board_path, server_path)
        shell.send_line(command)
        return command

    def close_session(self, shell: InteractiveShell) -> None:
        """Leave the active SFTP session."""
        shell.send_line("bye")

    def _build_transfer_command(self, operation: str, source: str, destination: str) -> str:
        source = source.strip()
        destination = destination.strip()
        if not source or not destination:
            raise SFTPError("Both server and MMU paths are required.")
        return f"{operation} {shlex.quote(source)} {shlex.quote(destination)}"

    def _format_destination(self, settings: BoardSettings) -> str:
        host = settings.ip_address.strip()
        interface = settings.interface.strip()
        if interface:
            return f"[{host}%{interface}]"
        if ":" in host:
            return f"[{host}]"
        return host

    def _validate_settings(self, settings: BoardSettings) -> None:
        if not settings.ip_address.strip():
            raise SFTPError("MMU IP address is required.")
        if not settings.username.strip():
            raise SFTPError("MMU username is required.")
        if re.fullmatch(r"[A-Za-z0-9._-]+", settings.username) is None:
            raise SFTPError("MMU username contains unsupported characters.")
        if not 1 <= settings.ssh_port <= 65535:
            raise SFTPError("MMU SFTP port must be between 1 and 65535.")
        if re.fullmatch(r"[A-Za-z0-9_.:-]+", settings.ip_address.strip()) is None:
            raise SFTPError("MMU host contains unsupported characters.")
        if settings.interface and re.fullmatch(r"[A-Za-z0-9_.:-]+", settings.interface.strip()) is None:
            raise SFTPError("MMU interface contains unsupported characters.")
