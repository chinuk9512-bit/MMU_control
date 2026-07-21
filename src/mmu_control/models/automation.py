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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationStep":
        """Create a step from JSON-compatible data with safe defaults."""
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
        }


@dataclass(slots=True)
class AutomationScenario:
    """A sequential automation scenario for one SSH or minicom terminal."""

    name: str
    description: str = ""
    transport: str = "ssh"
    steps: list[AutomationStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationScenario":
        """Create a scenario from JSON-compatible data."""
        raw_steps = data.get("steps", [])
        steps = [AutomationStep.from_dict(step) for step in raw_steps if isinstance(step, dict)]
        transport = str(data.get("transport", "ssh"))
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            transport=transport if transport in {"ssh", "minicom"} else "ssh",
            steps=steps,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the scenario to JSON-compatible data."""
        return {
            "name": self.name,
            "description": self.description,
            "transport": self.transport,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(slots=True)
class AutomationScenarioCollection:
    """Collection of persisted automation scenarios."""

    schema_version: int = 1
    scenarios: dict[str, AutomationScenario] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationScenarioCollection":
        """Create a collection from JSON-compatible data."""
        scenarios: dict[str, AutomationScenario] = {}
        raw_scenarios = data.get("scenarios", {})
        if isinstance(raw_scenarios, dict):
            for name, raw_scenario in raw_scenarios.items():
                if isinstance(raw_scenario, dict):
                    scenario = AutomationScenario.from_dict({"name": name, **raw_scenario})
                    if scenario.name:
                        scenarios[scenario.name] = scenario
        return cls(schema_version=int(data.get("schema_version", 1)), scenarios=scenarios)

    def to_dict(self) -> dict[str, Any]:
        """Convert the collection to JSON-compatible data."""
        return {
            "schema_version": self.schema_version,
            "scenarios": {name: scenario.to_dict() for name, scenario in sorted(self.scenarios.items())},
        }
