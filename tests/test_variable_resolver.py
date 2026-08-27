"""Tests for shared command-template variable resolution."""

from __future__ import annotations

import pytest

from mmu_control.core.variable_resolver import MissingVariablesError, VariableResolver
from mmu_control.models.automation import AutomationScenario, AutomationStep
from mmu_control.core.automation_runner import AutomationRunner


def test_resolve_replaces_braced_variables() -> None:
    template = "login ${MMU_USERNAME} ${MMU_PASSWORD} ${MMU_USERNAME}"
    assert VariableResolver.resolve(
        template, {"MMU_USERNAME": "alice", "MMU_PASSWORD": "secret"}
    ) == "login alice secret alice"


def test_resolve_reports_all_missing_variables_without_partial_result() -> None:
    with pytest.raises(MissingVariablesError) as error:
        VariableResolver.resolve("${MMU_USERNAME}:${MMU_PASSWORD}", {})
    assert error.value.names == {"MMU_USERNAME", "MMU_PASSWORD"}
    assert "secret" not in str(error.value)


def test_resolve_preserves_escaped_placeholder() -> None:
    assert VariableResolver.resolve("echo $${REMOTE_NAME}", {}) == "echo ${REMOTE_NAME}"


def test_names_ignores_shell_variables_without_braces_and_invalid_names() -> None:
    assert VariableResolver.names("$HOME ${VALID_1} ${1_INVALID}") == {"VALID_1"}


def test_automation_runner_resolves_command_only_when_sending() -> None:
    sent: list[str] = []
    runner = AutomationRunner(
        sent.append,
        lambda command: VariableResolver.resolve(command, {"MMU_USERNAME": "alice"}),
    )
    scenario = AutomationScenario("login", steps=[AutomationStep(command="login ${MMU_USERNAME}")])

    runner.start(scenario)

    assert sent == ["login alice"]
    assert scenario.steps[0].command == "login ${MMU_USERNAME}"
