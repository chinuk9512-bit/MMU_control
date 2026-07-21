"""Tests for parsing line-oriented automation command imports."""

from mmu_control.core.automation_import_parser import parse_automation_commands


def test_parser_skips_blank_and_comment_lines_and_applies_timeout() -> None:
    steps = parse_automation_commands("\n  # setup\n echo ready \n\npwd # retain inline comment\n", 25)

    assert [step.name for step in steps] == ["Command 1", "Command 2"]
    assert [step.command for step in steps] == ["echo ready", "pwd # retain inline comment"]
    assert [step.timeout_seconds for step in steps] == [25, 25]
    assert [step.start_timeout_seconds for step in steps] == [25, 25]


def test_parser_returns_no_steps_for_empty_or_comment_only_text() -> None:
    assert parse_automation_commands("\n # comment\n\t# another\n", 60) == []
