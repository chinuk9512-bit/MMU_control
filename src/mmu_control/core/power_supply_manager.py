"""Power supply control abstraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.models.settings import PowerSupplySettings


class PowerSupplyCommandError(RuntimeError):
    """Raised when a power supply command cannot be built."""


class PowerSupplyManager:
    """Build configured power supply commands for SSH execution."""

    DEFAULT_COMMANDS_PATH = (
        Path(__file__).resolve().parents[1] / "resources" / "power_supply_commands.json"
    )

    def __init__(
        self,
        settings: PowerSupplySettings | None = None,
        commands_path: Path | None = None,
    ) -> None:
        self.settings = settings or PowerSupplySettings()
        self._commands_path = commands_path or self.DEFAULT_COMMANDS_PATH
        self._commands = self._load_commands()

    @property
    def commands_path(self) -> Path:
        """Return the JSON file used to configure power supply commands."""
        return self._commands_path

    def update_settings(self, settings: PowerSupplySettings) -> None:
        """Store the settings that command builders will use."""
        self.settings = settings

    def is_configured(self) -> bool:
        """Return whether a target power supply host has been configured."""
        return bool(self.settings.ip_address.strip())

    def build_command(self, action: str) -> str:
        """Build the configured shell command for a power supply action."""
        template = self._commands.get(action)
        if not isinstance(template, str) or not template.strip():
            raise PowerSupplyCommandError(f"Power supply command is not configured: {action}")
        ip_address = self.settings.ip_address.strip()
        if "{ip}" in template and not ip_address:
            raise PowerSupplyCommandError("Power supply IP address is required.")
        return template.format(ip=ip_address)

    def _load_commands(self) -> dict[str, str]:
        try:
            raw_data: Any = json.loads(self._commands_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PowerSupplyCommandError(
                f"Unable to read power supply commands: {self._commands_path}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise PowerSupplyCommandError(
                f"Invalid power supply commands JSON: {self._commands_path}"
            ) from exc
        if not isinstance(raw_data, dict):
            raise PowerSupplyCommandError("Power supply commands JSON must contain an object.")
        commands = raw_data.get("commands", raw_data)
        if not isinstance(commands, dict):
            raise PowerSupplyCommandError("Power supply commands must contain an object.")
        return {str(action): str(command) for action, command in commands.items()}
