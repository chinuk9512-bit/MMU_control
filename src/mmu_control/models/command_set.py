"""Command set models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CommandSet:
    """Named collection of shell commands."""

    name: str
    description: str = ""
    commands: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandSet:
        """Create a command set from JSON-compatible data."""
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            commands=str(data.get("commands", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert this command set to JSON-compatible data."""
        return {
            "name": self.name,
            "description": self.description,
            "commands": self.commands,
        }


@dataclass(slots=True)
class CommandSetCollection:
    """Collection of saved command sets."""

    schema_version: int = 1
    command_sets: dict[str, CommandSet] | None = None

    def __post_init__(self) -> None:
        if self.command_sets is None:
            self.command_sets = {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandSetCollection:
        """Create a command set collection from JSON-compatible data."""
        raw_command_sets = data.get("command_sets", data.get("commands", {}))
        command_sets: dict[str, CommandSet] = {}
        if isinstance(raw_command_sets, dict):
            for name, command_data in raw_command_sets.items():
                if isinstance(command_data, dict):
                    command_set = CommandSet.from_dict({"name": name, **command_data})
                    if command_set.name:
                        command_sets[command_set.name] = command_set
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            command_sets=command_sets,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert this collection to JSON-compatible data."""
        assert self.command_sets is not None
        return {
            "schema_version": self.schema_version,
            "command_sets": {
                name: command_set.to_dict()
                for name, command_set in sorted(self.command_sets.items())
            },
        }
