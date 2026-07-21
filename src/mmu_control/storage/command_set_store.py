"""JSON storage for hierarchical command groups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.models.command_set import CommandFolder, CommandSet, CommandSetCollection


class CommandSetStoreError(RuntimeError):
    """Raised when command sets cannot be loaded or saved."""


class CommandSetStore:
    """Persist command groups and their folders in JSON."""

    def __init__(self, command_sets_path: Path) -> None:
        self._command_sets_path = command_sets_path

    @property
    def command_sets_path(self) -> Path:
        return self._command_sets_path

    @classmethod
    def create_default(cls) -> "CommandSetStore":
        """Create a store in the package's dedicated command directory."""
        package_directory = Path(__file__).resolve().parents[1]
        return cls(package_directory / "user_command" / "command_sets.json")

    def load(self) -> CommandSetCollection:
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
        try:
            self._command_sets_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._command_sets_path.with_suffix(f"{self._command_sets_path.suffix}.tmp")
            temp_path.write_text(json.dumps(collection.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(self._command_sets_path)
        except OSError as exc:
            raise CommandSetStoreError(f"Unable to write command sets: {self._command_sets_path}") from exc

    @staticmethod
    def _path(name: str, parent_path: str = "") -> str:
        name, parent_path = name.strip().strip("/"), parent_path.strip("/")
        if not name or "/" in name:
            raise CommandSetStoreError("Folder name is required and cannot contain '/'.")
        return f"{parent_path}/{name}" if parent_path else name

    @staticmethod
    def _validate_parent(collection: CommandSetCollection, parent_path: str) -> str:
        parent_path = parent_path.strip("/")
        if parent_path and parent_path not in collection.folders:
            raise CommandSetStoreError(f"Unknown parent folder: {parent_path}")
        return parent_path

    def upsert(self, command_set: CommandSet) -> CommandSetCollection:
        name = command_set.name.strip()
        if not name:
            raise CommandSetStoreError("Command set name is required.")
        collection = self.load()
        parent_path = self._validate_parent(collection, command_set.parent_path)
        collection.command_sets[name] = CommandSet(name, command_set.description, command_set.commands, parent_path)
        self.save(collection)
        return collection

    def delete(self, name: str) -> CommandSetCollection:
        collection = self.load()
        collection.command_sets.pop(name, None)
        self.save(collection)
        return collection

    def create_folder(self, name: str, parent_path: str = "") -> CommandSetCollection:
        collection = self.load()
        parent_path = self._validate_parent(collection, parent_path)
        path = self._path(name, parent_path)
        if path in collection.folders:
            raise CommandSetStoreError(f"Folder already exists: {path}")
        collection.folders[path] = CommandFolder(name=name.strip(), parent_path=parent_path)
        self.save(collection)
        return collection

    def rename_folder(self, path: str, name: str) -> CommandSetCollection:
        collection = self.load()
        folder = collection.folders.get(path)
        if folder is None:
            raise CommandSetStoreError(f"Unknown folder: {path}")
        new_path = self._path(name, folder.parent_path)
        if new_path != path and new_path in collection.folders:
            raise CommandSetStoreError(f"Folder already exists: {new_path}")
        self._replace_path(collection, path, new_path, CommandFolder(name.strip(), folder.parent_path))
        self.save(collection)
        return collection

    def move_command_set(self, name: str, parent_path: str = "") -> CommandSetCollection:
        collection = self.load()
        command_set = collection.command_sets.get(name)
        if command_set is None:
            raise CommandSetStoreError(f"Unknown command set: {name}")
        command_set.parent_path = self._validate_parent(collection, parent_path)
        self.save(collection)
        return collection

    def children(self, parent_path: str = "") -> tuple[list[tuple[str, CommandFolder]], list[CommandSet]]:
        collection = self.load()
        parent_path = parent_path.strip("/")
        return (sorted(((path, folder) for path, folder in collection.folders.items() if folder.parent_path == parent_path), key=lambda item: item[1].name.lower()), sorted((group for group in collection.command_sets.values() if group.parent_path == parent_path), key=lambda group: group.name.lower()))

    def list_children(self, parent_path: str = "") -> tuple[list[tuple[str, CommandFolder]], list[CommandSet]]:
        """Alias for :meth:`children` with an explicit query-style name."""
        return self.children(parent_path)

    def delete_folder(self, path: str, *, delete_contents: bool) -> CommandSetCollection:
        """Delete a folder; explicitly delete descendants or promote direct contents."""
        collection = self.load()
        folder = collection.folders.get(path)
        if folder is None:
            raise CommandSetStoreError(f"Unknown folder: {path}")
        descendants = [key for key in collection.folders if key == path or key.startswith(f"{path}/")]
        if delete_contents:
            for key in descendants:
                collection.folders.pop(key, None)
            for name, group in list(collection.command_sets.items()):
                if group.parent_path == path or group.parent_path.startswith(f"{path}/"):
                    del collection.command_sets[name]
        else:
            # Promote the folder's entire subtree to the top level while retaining its shape.
            parent = ""
            descendants = sorted(key for key in collection.folders if key.startswith(f"{path}/"))
            replacements = {
                key: f"{parent}/{key[len(path) + 1:]}".strip("/")
                for key in descendants
            }
            if any(target in collection.folders and target not in replacements for target in replacements.values()):
                raise CommandSetStoreError("Cannot promote folder because a destination folder exists.")
            collection.folders.pop(path)
            moved = {key: collection.folders.pop(key) for key in descendants}
            for key, child in moved.items():
                target = replacements[key]
                new_parent = replacements.get(child.parent_path, parent if child.parent_path == path else child.parent_path)
                collection.folders[target] = CommandFolder(child.name, new_parent)
            for group in collection.command_sets.values():
                if group.parent_path == path:
                    group.parent_path = parent
                elif group.parent_path.startswith(f"{path}/"):
                    group.parent_path = replacements[group.parent_path]
        self.save(collection)
        return collection

    @staticmethod
    def _replace_path(collection: CommandSetCollection, old: str, new: str, renamed: CommandFolder) -> None:
        replacements = {key: (new + key[len(old):]) for key in collection.folders if key == old or key.startswith(f"{old}/")}
        for key in replacements:
            folder = collection.folders.pop(key)
            target = replacements[key]
            collection.folders[target] = renamed if key == old else CommandFolder(folder.name, replacements.get(folder.parent_path, folder.parent_path))
        for group in collection.command_sets.values():
            if group.parent_path == old or group.parent_path.startswith(f"{old}/"):
                group.parent_path = new + group.parent_path[len(old):]
