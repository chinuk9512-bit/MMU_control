"""JSON storage for automation scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.models.automation import AutomationScenario, AutomationScenarioCollection


class AutomationStoreError(RuntimeError):
    """Raised when automation scenarios cannot be read or saved."""


class AutomationStore:
    """Persist user-configured automation scenarios in JSON."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def create_default(cls) -> "AutomationStore":
        """Create a store in the package's dedicated scenario directory."""
        package_directory = Path(__file__).resolve().parents[1]
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
        return AutomationScenarioCollection.from_dict(raw_data)

    def upsert(self, scenario: AutomationScenario) -> AutomationScenarioCollection:
        """Insert or replace one scenario."""
        name = scenario.name.strip()
        if not name:
            raise AutomationStoreError("Scenario name is required.")
        collection = self.load()
        collection.scenarios[name] = AutomationScenario(
            name=name,
            description=scenario.description,
            transport=scenario.transport,
            steps=scenario.steps,
        )
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
