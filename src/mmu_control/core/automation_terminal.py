"""Terminal contract used to execute automation scenarios."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class AutomationTerminalCapability(StrEnum):
    """Optional facilities an automation terminal may provide."""

    REMOTE_FILE_CHECKS = "remote_file_checks"


class AutomationTerminal(Protocol):
    """A currently usable console that can run an automation scenario."""

    @property
    def is_open(self) -> bool: ...

    @property
    def display_name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[AutomationTerminalCapability]: ...

    def send_line(self, command: str) -> None: ...

    def read_recent_output(self) -> str: ...
