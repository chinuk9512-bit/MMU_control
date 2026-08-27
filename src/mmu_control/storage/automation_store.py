"""JSON storage for automation scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.models.automation import AutomationFolder, AutomationScenario, AutomationScenarioCollection


class AutomationStoreError(RuntimeError):
    """Raised when automation scenarios cannot be read or saved."""


class AutomationStore:
    """Persist user-configured automation scenarios in JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Return the file used to persist automation scenarios."""
        return self._path

    @classmethod
    def create_default(cls) -> "AutomationStore":
        """Create a store for the scenario data shared with the source tree."""
        package_directory = Path(__file__).resolve().parent.parent
        return cls(package_directory / "user_scenario" / "automation_scenarios.json")

    def load(self) -> AutomationScenarioCollection:
        """Load scenarios, returning an empty collection if the file is absent."""
        if not self._path.exists():
            return AutomationScenarioCollection()
        try:
            raw_data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AutomationStoreError(f"Unable to read automation scenarios: {self._path}") from exc
        except json.JSONDecodeError as exc:
            raise AutomationStoreError(f"Invalid automation scenarios JSON: {self._path}") from exc
        if not isinstance(raw_data, dict):
            raise AutomationStoreError("Automation scenarios JSON must contain an object.")
        collection = AutomationScenarioCollection.from_dict(raw_data)
        if int(raw_data.get("schema_version", 1)) < 2:
            self._save(collection)
        return collection

    def upsert(self, scenario: AutomationScenario) -> AutomationScenarioCollection:
        """Insert or replace one scenario."""
        name = scenario.name.strip()
        if not name:
            raise AutomationStoreError("Scenario name is required.")
        collection = self.load()
        collection.scenarios[name] = AutomationScenario(
            name=name,
            description=scenario.description,
            steps=scenario.steps,
            parent_path=self._validate_parent(collection, scenario.parent_path),
        )
        self._save(collection)
        return collection

    @staticmethod
    def _folder_path(name: str, parent_path: str = "") -> str:
        name, parent_path = name.strip().strip("/"), parent_path.strip("/")
        if not name or "/" in name:
            raise AutomationStoreError("Folder name is required and cannot contain '/'.")
        return f"{parent_path}/{name}" if parent_path else name

    @staticmethod
    def _validate_parent(collection: AutomationScenarioCollection, parent_path: str) -> str:
        parent_path = parent_path.strip("/")
        if parent_path and parent_path not in collection.folders:
            raise AutomationStoreError(f"Unknown parent folder: {parent_path}")
        return parent_path

    def create_folder(self, name: str, parent_path: str = "") -> AutomationScenarioCollection:
        collection = self.load()
        parent_path = self._validate_parent(collection, parent_path)
        path = self._folder_path(name, parent_path)
        if path in collection.folders:
            raise AutomationStoreError(f"Folder already exists: {path}")
        collection.folders[path] = AutomationFolder(name.strip(), parent_path)
        self._save(collection)
        return collection

    def rename_folder(self, path: str, name: str) -> AutomationScenarioCollection:
        collection = self.load()
        folder = collection.folders.get(path)
        if folder is None:
            raise AutomationStoreError(f"Unknown folder: {path}")
        new_path = self._folder_path(name, folder.parent_path)
        if new_path != path and new_path in collection.folders:
            raise AutomationStoreError(f"Folder already exists: {new_path}")
        replacements = {key: new_path + key[len(path):] for key in collection.folders if key == path or key.startswith(path + "/")}
        moved = {key: collection.folders.pop(key) for key in replacements}
        for key, child in moved.items():
            collection.folders[replacements[key]] = AutomationFolder(name.strip(), folder.parent_path) if key == path else AutomationFolder(child.name, replacements.get(child.parent_path, child.parent_path))
        for scenario in collection.scenarios.values():
            if scenario.parent_path == path or scenario.parent_path.startswith(path + "/"):
                scenario.parent_path = new_path + scenario.parent_path[len(path):]
        self._save(collection)
        return collection

    def move_scenario(self, name: str, parent_path: str = "") -> AutomationScenarioCollection:
        collection = self.load()
        scenario = collection.scenarios.get(name)
        if scenario is None:
            raise AutomationStoreError(f"Unknown scenario: {name}")
        scenario.parent_path = self._validate_parent(collection, parent_path)
        self._save(collection)
        return collection

    def children(self, parent_path: str = "") -> tuple[list[tuple[str, AutomationFolder]], list[AutomationScenario]]:
        collection = self.load()
        parent_path = parent_path.strip("/")
        folders = sorted(((path, folder) for path, folder in collection.folders.items() if folder.parent_path == parent_path), key=lambda item: item[1].name.lower())
        scenarios = sorted((scenario for scenario in collection.scenarios.values() if scenario.parent_path == parent_path), key=lambda item: item.name.lower())
        return folders, scenarios

    def list_children(self, parent_path: str = "") -> tuple[list[tuple[str, AutomationFolder]], list[AutomationScenario]]:
        return self.children(parent_path)

    def delete_folder(self, path: str, *, delete_contents: bool) -> AutomationScenarioCollection:
        collection = self.load()
        folder = collection.folders.get(path)
        if folder is None:
            raise AutomationStoreError(f"Unknown folder: {path}")
        descendants = [key for key in collection.folders if key == path or key.startswith(path + "/")]
        if delete_contents:
            for key in descendants:
                collection.folders.pop(key, None)
            for name, scenario in list(collection.scenarios.items()):
                if scenario.parent_path == path or scenario.parent_path.startswith(path + "/"):
                    del collection.scenarios[name]
        else:
            # Match the Commands tab: retained contents are promoted to top level.
            parent = ""
            children = sorted(key for key in collection.folders if key.startswith(path + "/"))
            replacements = {key: f"{parent}/{key[len(path)+1:]}".strip("/") for key in children}
            if any(target in collection.folders and target not in replacements for target in replacements.values()):
                raise AutomationStoreError("Cannot promote folder because a destination folder exists.")
            collection.folders.pop(path)
            moved = {key: collection.folders.pop(key) for key in children}
            for key, child in moved.items():
                collection.folders[replacements[key]] = AutomationFolder(child.name, replacements.get(child.parent_path, parent if child.parent_path == path else child.parent_path))
            for scenario in collection.scenarios.values():
                if scenario.parent_path == path:
                    scenario.parent_path = parent
                elif scenario.parent_path.startswith(path + "/"):
                    scenario.parent_path = replacements[scenario.parent_path]
        self._save(collection)
        return collection

    def delete(self, name: str) -> AutomationScenarioCollection:
        """Delete a scenario by name."""
        collection = self.load()
        collection.scenarios.pop(name, None)
        self._save(collection)
        return collection

    def _save(self, collection: AutomationScenarioCollection) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
            temporary.write_text(json.dumps(collection.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        except OSError as exc:
            raise AutomationStoreError(f"Unable to write automation scenarios: {self._path}") from exc
