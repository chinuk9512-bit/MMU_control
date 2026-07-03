"""Configuration loading and saving service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mmu_control.models.settings import AppSettings


class ConfigError(RuntimeError):
    """Raised when the configuration file cannot be loaded or saved."""


class ConfigManager:
    """Persist application settings as backward-compatible JSON."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    @property
    def config_path(self) -> Path:
        """Return the JSON configuration file path."""
        return self._config_path

    @classmethod
    def create_default(cls) -> ConfigManager:
        """Create a manager using the default per-user Windows config path."""
        return cls(default_config_path())

    def load(self) -> AppSettings:
        """Load settings from disk or return defaults when no file exists."""
        if not self._config_path.exists():
            return AppSettings()

        try:
            raw_data: Any = json.loads(self._config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"Unable to read config file: {self._config_path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid config JSON: {self._config_path}") from exc

        if not isinstance(raw_data, dict):
            raise ConfigError(f"Config root must be a JSON object: {self._config_path}")

        try:
            return AppSettings.from_dict(raw_data)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"Invalid config values: {self._config_path}") from exc

    def save(self, settings: AppSettings) -> None:
        """Save settings to disk, creating the parent directory when needed."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
            temp_path.write_text(
                json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_path.replace(self._config_path)
        except OSError as exc:
            raise ConfigError(f"Unable to write config file: {self._config_path}") from exc


def default_config_path() -> Path:
    """Return the default application configuration file path."""
    appdata = os.environ.get("APPDATA")
    base_path = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base_path / "MMUControl" / "settings.json"
