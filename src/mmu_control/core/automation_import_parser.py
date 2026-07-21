"""Parse line-oriented terminal commands for automation scenario imports."""

from __future__ import annotations

from mmu_control.models.automation import AutomationStep


def parse_automation_commands(text: str, default_timeout_seconds: int) -> list[AutomationStep]:
    """Create one automation step for each non-empty, non-comment input line.

    Lines whose first non-whitespace character is ``#`` are treated as comments.
    Inline comments are intentionally preserved because they may be part of a shell
    command.  The imported steps have no completion condition, so users can review
    and configure conditions in the automation editor before saving.
    """
    timeout_seconds = max(1, default_timeout_seconds)
    commands = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [
        AutomationStep(
            name=f"Command {index}",
            command=command,
            timeout_seconds=timeout_seconds,
            start_timeout_seconds=timeout_seconds,
        )
        for index, command in enumerate(commands, start=1)
    ]
