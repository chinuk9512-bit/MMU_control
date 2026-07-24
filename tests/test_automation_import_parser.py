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


def test_parser_combines_command_lines_between_three_line_slash_dividers() -> None:
    steps = parse_automation_commands(
        "echo prepare\nexport MODE=test\n//\n///\n////\necho run\necho done\n//\n//\n//\necho cleanup\n",
        30,
    )

    assert [step.name for step in steps] == ["Command 1", "Command 2", "Command 3"]
    assert [step.command for step in steps] == ["echo prepare\nexport MODE=test", "echo run\necho done", "echo cleanup"]


def test_parser_does_not_treat_short_or_non_slash_runs_as_dividers() -> None:
    steps = parse_automation_commands("echo first\n/\n//\n//\necho second\n//\n//\necho third\n", 60)

    assert [step.command for step in steps] == [
        "echo first",
        "/",
        "//",
        "//",
        "echo second",
        "//",
        "//",
        "echo third",
    ]


def test_parser_skips_empty_and_comment_only_divider_blocks_and_applies_timeout() -> None:
    steps = parse_automation_commands(
        "\n# before\n//\n//\n//\n\n  # middle\n//\n//\n//\n  echo retained  \n# after\n",
        0,
    )

    assert [step.name for step in steps] == ["Command 1"]
    assert [step.command for step in steps] == ["echo retained"]
    assert [step.timeout_seconds for step in steps] == [1]
    assert [step.start_timeout_seconds for step in steps] == [1]
