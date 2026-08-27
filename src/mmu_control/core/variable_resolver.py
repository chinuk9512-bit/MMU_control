"""Resolve user-local variables in shared command templates."""

from __future__ import annotations

import re
from collections.abc import Mapping


class MissingVariablesError(ValueError):
    """Raised when a command template references variables without values."""

    def __init__(self, names: set[str]) -> None:
        self.names = frozenset(names)
        super().__init__(f"Missing command variables: {', '.join(sorted(names))}")


class VariableResolver:
    """Replace ``${NAME}`` placeholders without invoking a shell."""

    _PLACEHOLDER = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    _ESCAPED = re.compile(r"\$\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

    @classmethod
    def names(cls, template: str) -> set[str]:
        return set(cls._PLACEHOLDER.findall(template))

    @classmethod
    def resolve(cls, template: str, variables: Mapping[str, str]) -> str:
        missing = {name for name in cls.names(template) if name not in variables}
        if missing:
            raise MissingVariablesError(missing)
        resolved = cls._PLACEHOLDER.sub(lambda match: variables[match.group(1)], template)
        return cls._ESCAPED.sub(lambda match: f"${{{match.group(1)}}}", resolved)
