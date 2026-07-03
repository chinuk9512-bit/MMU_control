"""Minicom command preparation."""

from __future__ import annotations

import re
import shlex

from mmu_control.core.interactive_shell import InteractiveShell


class MinicomError(RuntimeError):
    """Raised when a minicom session cannot be prepared."""


class MinicomManager:
    """Build safe minicom commands for a selected remote serial port."""

    def build_command(self, usb_port: str) -> str:
        port = usb_port.strip()
        if re.fullmatch(r"/dev/tty(?:USB|ACM)\d+", port) is None:
            raise MinicomError("Select a detected USB serial port first.")
        return f"minicom -o -c off -D {shlex.quote(port)}"

    def close_session(self, shell: InteractiveShell) -> None:
        """Send minicom's Ctrl-A, X, Enter exit sequence."""
        shell.send("\x01x\n")
