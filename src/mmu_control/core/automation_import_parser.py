"""Parse line-oriented terminal commands for automation scenario imports."""

from __future__ import annotations

from mmu_control.models.automation import AutomationStep


def parse_automation_commands(text: str, default_timeout_seconds: int) -> list[AutomationStep]:
    """Create automation steps from commands separated by slash divider blocks.

    Lines whose first non-whitespace character is ``#`` are treated as comments.
    Inline comments are intentionally preserved because they may be part of a shell
    command. A divider is a run of at least three consecutive lines containing two
    or more ``/`` characters; divider lines are excluded from commands. When one
    or more dividers are present, each non-empty block between dividers becomes a
    step and its command lines are joined with their original newline character.
    Without a divider, imports retain the legacy behavior of creating one step per
    non-empty, non-comment line. The imported steps have no completion condition,
    so users can review and configure conditions in the automation editor before
    saving.
    """
    timeout_seconds = max(1, default_timeout_seconds)
    lines = text.splitlines()

    divider_line_indexes: set[int] = set()
    run_start: int | None = None
    for index, line in enumerate(lines):
        if line.count("/") >= 2:
            run_start = index if run_start is None else run_start
            continue
        if run_start is not None and index - run_start >= 3:
            divider_line_indexes.update(range(run_start, index))
        run_start = None
    if run_start is not None and len(lines) - run_start >= 3:
        divider_line_indexes.update(range(run_start, len(lines)))

    command_lines = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not divider_line_indexes:
        commands = command_lines
    else:
        commands = []
        block_lines: list[str] = []
        for index, line in enumerate(lines):
            if index in divider_line_indexes:
                if block_lines:
                    commands.append("\n".join(block_lines))
                    block_lines = []
            elif line.strip() and not line.lstrip().startswith("#"):
                block_lines.append(line.strip())
        if block_lines:
            commands.append("\n".join(block_lines))
    return [
        AutomationStep(
            name=f"Command {index}",
            command=command,
            timeout_seconds=timeout_seconds,
            start_timeout_seconds=timeout_seconds,
        )
        for index, command in enumerate(commands, start=1)
    ]
