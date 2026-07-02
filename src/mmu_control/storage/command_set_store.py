"""JSON storage for command sets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.core.config_manager import default_config_path
from mmu_control.models.command_set import CommandSet, CommandSetCollection


class CommandSetStoreError(RuntimeError):
    """Raised when command sets cannot be loaded or saved."""


class CommandSetStore:
    """Persist named command sets in JSON."""

    def __init__(self, command_sets_path: Path) -> None:
        self._command_sets_path = command_sets_path

    @property
    def command_sets_path(self) -> Path:
        """Return the JSON command sets file path."""
        return self._command_sets_path

    @classmethod
    def create_default(cls) -> CommandSetStore:
        """Create a store using the default per-user Windows config path."""
        return cls(default_config_path().with_name("command_sets.json"))

    def load(self) -> CommandSetCollection:
        """Load command sets from disk, returning an empty collection when missing."""
        if not self._command_sets_path.exists():
            return CommandSetCollection()

        try:
            raw_data: Any = json.loads(self._command_sets_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise CommandSetStoreError(f"Unable to read command sets: {self._command_sets_path}") from exc
        except json.JSONDecodeError as exc:
            raise CommandSetStoreError(f"Invalid command sets JSON: {self._command_sets_path}") from exc

        if not isinstance(raw_data, dict):
            raise CommandSetStoreError("Command sets JSON must contain an object.")
        return CommandSetCollection.from_dict(raw_data)

    def save(self, collection: CommandSetCollection) -> None:
        """Save command sets to disk."""
        try:
            self._command_sets_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._command_sets_path.with_suffix(f"{self._command_sets_path.suffix}.tmp")
            temp_path.write_text(
                json.dumps(collection.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_path.replace(self._command_sets_path)
        except OSError as exc:
            raise CommandSetStoreError(f"Unable to write command sets: {self._command_sets_path}") from exc

    def upsert(self, command_set: CommandSet) -> CommandSetCollection:
        """Insert or replace a command set."""
        name = command_set.name.strip()
        if not name:
            raise CommandSetStoreError("Command set name is required.")
        collection = self.load()
        assert collection.command_sets is not None
        collection.command_sets[name] = CommandSet(
            name=name,
            description=command_set.description,
            commands=command_set.commands,
        )
        self.save(collection)
        return collection

    def delete(self, name: str) -> CommandSetCollection:
        """Delete a command set by name."""
        collection = self.load()
        assert collection.command_sets is not None
        collection.command_sets.pop(name, None)
        self.save(collection)
        return collection
