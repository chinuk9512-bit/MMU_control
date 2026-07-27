"""Models for user-configurable terminal automation scenarios."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CompletionType(StrEnum):
    """Ways an automation step can determine that it has completed."""

    NONE = "none"
    OUTPUT_CONTAINS = "output_contains"
    OUTPUT_REGEX = "output_regex"
    PROMPT_REGEX = "prompt_regex"
    REMOTE_FILE_CONTAINS = "remote_file_contains"
    REMOTE_FILE_REGEX = "remote_file_regex"
    DELAY = "delay"


@dataclass(slots=True)
class AutomationStep:
    """One command with optional start and completion conditions."""

    name: str = ""
    command: str = ""
    completion_type: CompletionType = CompletionType.NONE
    completion_value: str = ""
    file_path: str = ""
    timeout_seconds: int = 60
    start_type: CompletionType = CompletionType.NONE
    start_value: str = ""
    start_file_path: str = ""
    start_timeout_seconds: int = 60
    skip_on_start_condition_failure: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationStep":
        """Create a step from JSON-compatible data with safe defaults."""
        raw_skip_on_start_condition_failure = data.get("skip_on_start_condition_failure", False)
        try:
            completion_type = CompletionType(str(data.get("completion_type", CompletionType.NONE)))
        except ValueError:
            completion_type = CompletionType.NONE
        try:
            start_type = CompletionType(str(data.get("start_type", CompletionType.NONE)))
        except ValueError:
            start_type = CompletionType.NONE
        return cls(
            name=str(data.get("name", "")),
            command=str(data.get("command", "")),
            completion_type=completion_type,
            completion_value=str(data.get("completion_value", "")),
            file_path=str(data.get("file_path", "")),
            timeout_seconds=max(1, int(data.get("timeout_seconds", 60))),
            start_type=start_type,
            start_value=str(data.get("start_value", "")),
            start_file_path=str(data.get("start_file_path", "")),
            start_timeout_seconds=max(1, int(data.get("start_timeout_seconds", 60))),
            skip_on_start_condition_failure=(
                raw_skip_on_start_condition_failure
                if isinstance(raw_skip_on_start_condition_failure, bool)
                else str(raw_skip_on_start_condition_failure).lower() in {"1", "true", "yes", "on"}
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the step to JSON-compatible data."""
        try:
            completion_type = CompletionType(str(self.completion_type))
        except ValueError:
            completion_type = CompletionType.NONE
        try:
            start_type = CompletionType(str(self.start_type))
        except ValueError:
            start_type = CompletionType.NONE
        return {
            "name": self.name,
            "command": self.command,
            "completion_type": completion_type.value,
            "completion_value": self.completion_value,
            "file_path": self.file_path,
            "timeout_seconds": self.timeout_seconds,
            "start_type": start_type.value,
            "start_value": self.start_value,
            "start_file_path": self.start_file_path,
            "start_timeout_seconds": self.start_timeout_seconds,
            "skip_on_start_condition_failure": self.skip_on_start_condition_failure,
        }


@dataclass(slots=True)
class AutomationFolder:
    """A folder used to organize automation scenarios."""

    name: str
    parent_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationFolder":
        return cls(name=str(data.get("name", "")), parent_path=str(data.get("parent_path", "")))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parent_path": self.parent_path}


@dataclass(slots=True)
class AutomationScenario:
    """A sequential automation scenario independent of its execution terminal."""

    name: str
    description: str = ""
    steps: list[AutomationStep] = field(default_factory=list)
    parent_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationScenario":
        """Create a scenario from JSON-compatible data."""
        raw_steps = data.get("steps", [])
        steps = [AutomationStep.from_dict(step) for step in raw_steps if isinstance(step, dict)]
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            steps=steps,
            parent_path=str(data.get("parent_path", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the scenario to JSON-compatible data."""
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "parent_path": self.parent_path,
        }


@dataclass(slots=True)
class AutomationScenarioCollection:
    """Collection of persisted automation scenarios."""

    schema_version: int = 2
    folders: dict[str, AutomationFolder] = field(default_factory=dict)
    scenarios: dict[str, AutomationScenario] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationScenarioCollection":
        """Create a collection from JSON-compatible data."""
        scenarios: dict[str, AutomationScenario] = {}
        folders: dict[str, AutomationFolder] = {}
        version = int(data.get("schema_version", 1))
        raw_folders = data.get("folders", {})
        if version >= 2 and isinstance(raw_folders, dict):
            for path, raw_folder in raw_folders.items():
                if isinstance(raw_folder, dict):
                    folder = AutomationFolder.from_dict(raw_folder)
                    if folder.name:
                        folders[str(path).strip("/")] = folder
        raw_scenarios = data.get("scenarios", {})
        if isinstance(raw_scenarios, dict):
            for name, raw_scenario in raw_scenarios.items():
                if isinstance(raw_scenario, dict):
                    scenario = AutomationScenario.from_dict({"name": name, **raw_scenario})
                    if version < 2:
                        scenario.parent_path = ""
                    if scenario.name:
                        scenarios[scenario.name] = scenario
        return cls(schema_version=2, folders=folders, scenarios=scenarios)

    def to_dict(self) -> dict[str, Any]:
        """Convert the collection to JSON-compatible data."""
        return {
            "schema_version": self.schema_version,
            "folders": {path: folder.to_dict() for path, folder in sorted(self.folders.items())},
            "scenarios": {name: scenario.to_dict() for name, scenario in sorted(self.scenarios.items())},
        }
