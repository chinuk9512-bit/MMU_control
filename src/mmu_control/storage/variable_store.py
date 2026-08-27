"""Per-user storage for shared-command variable values."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mmu_control.core.config_manager import default_user_data_directory


class VariableStoreError(RuntimeError):
    """Raised when local command variables cannot be loaded or saved."""


class VariableStore:
    _NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def create_default(cls) -> "VariableStore":
        return cls(default_user_data_directory() / "variables.json")

    def load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw_data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise VariableStoreError(f"Unable to read command variables: {self._path}") from exc
        except json.JSONDecodeError as exc:
            raise VariableStoreError(f"Invalid command variables JSON: {self._path}") from exc
        if not isinstance(raw_data, dict):
            raise VariableStoreError("Command variables JSON must contain an object.")
        raw_variables = raw_data.get("variables", raw_data)
        if not isinstance(raw_variables, dict):
            raise VariableStoreError("The variables field must contain an object.")
        variables = {str(name): str(value) for name, value in raw_variables.items()}
        self._validate_names(variables)
        return variables

    def save(self, variables: dict[str, str]) -> None:
        self._validate_names(variables)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
            payload = {"schema_version": 1, "variables": variables}
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._path)
        except OSError as exc:
            raise VariableStoreError(f"Unable to write command variables: {self._path}") from exc

    @classmethod
    def _validate_names(cls, variables: dict[str, str]) -> None:
        invalid = sorted(name for name in variables if not cls._NAME.fullmatch(name))
        if invalid:
            raise VariableStoreError(f"Invalid command variable names: {', '.join(invalid)}")
