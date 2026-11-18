"""Selected connection defaults shared by newly created Client workspaces."""

from __future__ import annotations

import json
from pathlib import Path

from mmu_control.core.config_manager import ConfigError, default_user_data_directory
from mmu_control.models.settings import AppSettings


class DefaultSettingsStore:
    """Persist only explicitly selected connection groups, never window state."""

    SECTIONS = frozenset({"ssh", "power_supply", "board"})

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_user_data_directory() / "default_settings.json"

    def load(self) -> tuple[AppSettings, frozenset[str]]:
        """Return defaults and the groups actually saved in the file."""
        if not self.path.exists():
            return AppSettings(), frozenset()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Expected an object")
            sections = self.SECTIONS.intersection(raw)
            if any(not isinstance(raw[key], dict) for key in sections):
                raise ValueError("Invalid connection group")
            settings = AppSettings.from_dict({key: raw[key] for key in sections})
            return settings, frozenset(sections)
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigError(f"Unable to load connection defaults: {self.path}") from exc

    def save(self, settings: AppSettings, sections: set[str]) -> None:
        """Replace defaults with the selected groups using an atomic file update."""
        if not sections or not sections <= self.SECTIONS:
            raise ConfigError("Select at least one valid connection group")
        data = settings.to_dict()
        payload = {"schema_version": 1, **{key: data[key] for key in sorted(sections)}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise ConfigError(f"Unable to save connection defaults: {self.path}") from exc
