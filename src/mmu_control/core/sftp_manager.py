"""SFTP workflow manager for board access through the Linux server."""

from __future__ import annotations

from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.models.settings import BoardSettings


class SFTPError(RuntimeError):
    """Raised when an SFTP workflow cannot be prepared or executed."""


class SFTPManager:
    """Build and run board SFTP commands inside an interactive SSH shell."""

    PASSWORD_PROMPT = "password:"

    def build_command(self, settings: BoardSettings) -> str:
        """Build the Linux-side SFTP command for the board settings."""
        self._validate_settings(settings)
        if settings.interface:
            return f"sftp {settings.username}@[{settings.ip_address}%{settings.interface}]"
        return f"sftp {settings.username}@{settings.ip_address}"

    def open_session(self, shell: InteractiveShell, settings: BoardSettings) -> str:
        """Start an SFTP session from the connected Linux server."""
        command = self.build_command(settings)
        shell.send_line(command)
        return command

    def handle_password_prompt(self, shell: InteractiveShell, output: str, settings: BoardSettings) -> bool:
        """Send the board password when the SFTP password prompt appears."""
        if not settings.password:
            return False
        return shell.respond_to_prompt(output, self.PASSWORD_PROMPT, settings.password)

    def _validate_settings(self, settings: BoardSettings) -> None:
        if not settings.ip_address.strip():
            raise SFTPError("Board IP address is required.")
        if not settings.username.strip():
            raise SFTPError("Board username is required.")
