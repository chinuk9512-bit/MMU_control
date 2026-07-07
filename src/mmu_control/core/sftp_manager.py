"""SFTP workflow manager for board access through the Linux server."""

from __future__ import annotations

import re
import shlex

from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.models.settings import BoardSettings


class SFTPError(RuntimeError):
    """Raised when an SFTP workflow cannot be prepared or executed."""


class SFTPManager:
    """Build and run board SFTP commands inside an interactive SSH shell."""

    PASSWORD_PROMPT = "password:"
    AUTHENTICITY_PROMPT = "authenticity of host"
    AUTHENTICITY_RESPONSE_PROMPT = "yes/no"
    KNOWN_HOSTS_CLEANUP_COMMAND = "rm -f ~/.ssh/known_hosts"

    def build_command(self, settings: BoardSettings) -> str:
        """Build the Linux-side SFTP command for the board settings."""
        self._validate_settings(settings)
        if settings.interface:
            return f"sftp {settings.username}@[{settings.ip_address}%{settings.interface}]"
        return f"sftp {settings.username}@{settings.ip_address}"

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
        """Send the board password when the SFTP password prompt appears."""
        if not settings.password:
            return False
        return shell.respond_to_prompt(output, self.PASSWORD_PROMPT, settings.password)

    def upload(self, shell: InteractiveShell, server_path: str, board_path: str) -> str:
        """Upload a Linux-server file to the board in an open SFTP session."""
        command = self._build_transfer_command("put", server_path, board_path)
        shell.send_line(command)
        return command

    def download(self, shell: InteractiveShell, board_path: str, server_path: str) -> str:
        """Download a board file to the Linux server in an open SFTP session."""
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
            raise SFTPError("Both server and board paths are required.")
        return f"{operation} {shlex.quote(source)} {shlex.quote(destination)}"

    def _validate_settings(self, settings: BoardSettings) -> None:
        if not settings.ip_address.strip():
            raise SFTPError("Board IP address is required.")
        if not settings.username.strip():
            raise SFTPError("Board username is required.")
        if re.fullmatch(r"[A-Za-z0-9._-]+", settings.username) is None:
            raise SFTPError("Board username contains unsupported characters.")
        if re.fullmatch(r"[A-Fa-f0-9:.]+", settings.ip_address) is None:
            raise SFTPError("Board IP address contains unsupported characters.")
        if settings.interface and re.fullmatch(r"[A-Za-z0-9_.:-]+", settings.interface) is None:
            raise SFTPError("Board interface contains unsupported characters.")
