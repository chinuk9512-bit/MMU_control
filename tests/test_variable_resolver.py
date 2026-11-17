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


def test_nested_name_resolves_inside_out_without_changing_template():
    template = "configure ${CC_${MMU_A}}"
    variables = {"MMU_A": "1", "CC_1": "selected-command"}
    assert VariableResolver.resolve(template, variables) == "configure selected-command"
    assert VariableResolver.names(template, variables) == {"MMU_A", "CC_1"}
    assert template == "configure ${CC_${MMU_A}}"


def test_multiple_nested_name_parts_and_deeper_selectors():
    variables = {"SLOT": "A", "IDX_A": "01", "SIDE": "LEFT", "CC_01_LEFT": "result"}
    assert VariableResolver.resolve("${CC_${IDX_${SLOT}}_${SIDE}}", variables) == "result"


@pytest.mark.parametrize("variables,missing", [({}, {"MMU_A"}), ({"MMU_A": "1"}, {"CC_1"})])
def test_missing_nested_dependencies_are_reported(variables, missing):
    with pytest.raises(MissingVariablesError) as error:
        VariableResolver.resolve("${CC_${MMU_A}}", variables)
    assert error.value.names == missing


def test_nested_escape_and_inserted_values_stay_literal():
    assert VariableResolver.resolve("$${CC_${MMU_A}}", {}) == "${CC_${MMU_A}}"
    assert VariableResolver.resolve("${VALUE}", {"VALUE": "${OTHER}"}) == "${OTHER}"
    assert VariableResolver.resolve("${VALUE}", {"VALUE": "$${OTHER}"}) == "$${OTHER}"
    assert VariableResolver.resolve("${SELF}", {"SELF": "${SELF}"}) == "${SELF}"


def test_invalid_computed_names_and_excess_depth_fail_without_value_disclosure():
    from mmu_control.core.variable_resolver import VariableResolutionError
    with pytest.raises(VariableResolutionError) as error:
        VariableResolver.resolve("${CC_${INDEX}}", {"INDEX": "secret-value; echo"})
    assert "secret-value" not in str(error.value)
    with pytest.raises(VariableResolutionError, match="nesting"):
        VariableResolver.resolve("${" * 40 + "INDEX" + "}" * 40, {})
