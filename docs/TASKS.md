# Agent Workflow

This file describes how Codex or another coding agent should work in this repository.

## Start Here

1. Read `docs/PROJECT_OVERVIEW_FOR_AGENTS.md` for the quickest orientation.
2. Read `docs/PRD.md` to understand product requirements.
3. Read `docs/ARCHITECTURE.md` to understand module boundaries and data flow.
4. Read `docs/IMPLEMENTATION_PLAN.md` to distinguish completed work from future work.
5. Read `docs/CODING_RULES.md` before editing code.
6. Inspect relevant source and tests before changing behavior.

## Working Principles

- Make one focused change at a time.
- Preserve existing user changes in the working tree.
- Keep UI orchestration and core logic separate where practical.
- Do not introduce GUI-thread blocking for SSH, SFTP, file I/O, or long commands.
- Keep saved JSON backward compatible.
- Prefer fake managers, fake shells, and fake runners in tests.
- Quote or validate shell inputs that become command arguments.

## Recommended Change Flow

1. Compare the requested behavior with current source and tests.
2. Identify the source, tests, and docs that are actually affected.
3. Add or update tests first when the behavior is easy to isolate.
4. Implement the smallest safe change.
5. Update docs only where the behavior or workflow changed.
6. Run focused tests first, then the full suite when feasible.
7. Report changed files, verification commands, and any residual risk.

## Useful Commands

```powershell
python -m pytest
python -m pytest tests/test_main_window.py
python -m compileall src tests
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

## Priority Backlog

- Build the full connection profile UI on top of existing profile models/stores.
- Improve SFTP long-transfer progress and cancellation.
- Review password persistence and SSH key handling.
- Expand fake-terminal tests for automation start/completion conditions.
- Improve direct board SSH authentication failure messages.

## Completion Report Checklist

Include:

- What changed.
- Key files changed.
- Tests or validation run.
- Anything not run or not completed.
