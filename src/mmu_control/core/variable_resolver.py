"""Resolve command variables, including computed names, without invoking a shell."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


class VariableResolutionError(ValueError):
    """Raised when a variable expression cannot be resolved safely."""


class MissingVariablesError(VariableResolutionError):
    """Raised when a command template references variables without values."""

    def __init__(self, names: set[str]) -> None:
        self.names = frozenset(names)
        super().__init__(f"Missing command variables: {', '.join(sorted(names))}")


@dataclass(frozen=True)
class _Reference:
    parts: tuple[str | _Reference, ...]


class VariableResolver:
    """Resolve nested placeholder names; inserted values remain literal strings."""

    _NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    MAX_DEPTH = 32

    @classmethod
    def _parse(cls, template: str, start: int = 0, depth: int = 0) -> tuple[tuple[str | _Reference, ...], int]:
        if depth > cls.MAX_DEPTH:
            raise VariableResolutionError("Variable nesting exceeds 32 levels")
        parts: list[str | _Reference] = []
        position = start
        while position < len(template):
            if depth and template[position] == "}":
                return tuple(parts), position + 1
            escaped = template.startswith("$${", position)
            if escaped or template.startswith("${", position):
                offset = 3 if escaped else 2
                inner, end = cls._parse(template, position + offset, depth + 1)
                if end == 0:
                    parts.append(template[position:])
                    return tuple(parts), 0 if depth else len(template)
                raw = template[position:end]
                if escaped:
                    parts.append(raw[1:])
                elif all(isinstance(part, str) for part in inner) and not cls._NAME.fullmatch("".join(inner)):
                    parts.append(raw)
                else:
                    parts.append(_Reference(inner))
                position = end
            else:
                parts.append(template[position])
                position += 1
        return tuple(parts), 0 if depth else position

    @classmethod
    def _evaluate(cls, parts: tuple[str | _Reference, ...], variables: Mapping[str, str], names: set[str], missing: set[str]) -> str | None:
        output: list[str] = []
        known = True
        for part in parts:
            if isinstance(part, str):
                output.append(part)
                continue
            name = cls._evaluate(part.parts, variables, names, missing)
            if name is None:
                known = False
                continue
            if not cls._NAME.fullmatch(name):
                # Do not include substituted values, which may be passwords.
                raise VariableResolutionError("Invalid computed variable name: use letters, digits and underscores")
            names.add(name)
            if name not in variables:
                missing.add(name)
                known = False
            else:
                output.append(variables[name])
        return "".join(output) if known else None

    @classmethod
    def names(cls, template: str, variables: Mapping[str, str] | None = None) -> set[str]:
        """Discover names whose inner dependencies can currently be resolved."""
        names: set[str] = set()
        cls._evaluate(cls._parse(template)[0], variables or {}, names, set())
        return names

    @classmethod
    def resolve(cls, template: str, variables: Mapping[str, str]) -> str:
        missing: set[str] = set()
        result = cls._evaluate(cls._parse(template)[0], variables, set(), missing)
        if missing:
            raise MissingVariablesError(missing)
        return result if result is not None else ""
