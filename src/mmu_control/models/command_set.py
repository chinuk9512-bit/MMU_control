"""Command group and folder models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CommandSet:
    """Named collection of shell commands, optionally within a folder."""

    name: str
    description: str = ""
    commands: str = ""
    parent_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandSet":
        return cls(name=str(data.get("name", "")), description=str(data.get("description", "")), commands=str(data.get("commands", "")), parent_path=str(data.get("parent_path", data.get("parent_folder", ""))))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "commands": self.commands, "parent_path": self.parent_path}


@dataclass(slots=True)
class CommandFolder:
    """A folder used to organize command groups."""

    name: str
    parent_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandFolder":
        return cls(name=str(data.get("name", "")), parent_path=str(data.get("parent_path", "")))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parent_path": self.parent_path}


@dataclass(slots=True)
class CommandSetCollection:
    """Hierarchical collection of saved command groups and folders."""

    schema_version: int = 2
    command_sets: dict[str, CommandSet] | None = None
    folders: dict[str, CommandFolder] | None = None

    def __post_init__(self) -> None:
        self.command_sets = self.command_sets or {}
        self.folders = self.folders or {}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandSetCollection":
        raw_command_sets = data.get("command_sets", data.get("commands", {}))
        command_sets: dict[str, CommandSet] = {}
        if isinstance(raw_command_sets, dict):
            for name, command_data in raw_command_sets.items():
                if isinstance(command_data, dict):
                    command_set = CommandSet.from_dict({"name": name, **command_data})
                    if command_set.name:
                        command_sets[command_set.name] = command_set
        folders: dict[str, CommandFolder] = {}
        raw_folders = data.get("folders", {})
        if isinstance(raw_folders, dict):
            for path, folder_data in raw_folders.items():
                if isinstance(folder_data, dict):
                    folder = CommandFolder.from_dict(folder_data)
                    if folder.name:
                        folders[str(path)] = folder
        # Saving always upgrades legacy flat documents to the hierarchical schema.
        return cls(schema_version=2, command_sets=command_sets, folders=folders)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 2, "folders": {path: folder.to_dict() for path, folder in sorted(self.folders.items())}, "command_sets": {name: command_set.to_dict() for name, command_set in sorted(self.command_sets.items())}}
