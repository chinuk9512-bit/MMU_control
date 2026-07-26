# Coding Rules

## General

- Target Python 3.12 or newer.
- Use type hints consistently.
- Public classes, functions, and methods should have docstrings.
- Keep changes focused on the requested behavior.
- Avoid import-time side effects.
- Prefer standard library or existing project helpers over new dependencies.

## UI

- Build PySide6 widgets and layouts in `MainWindow` or focused dialog/widget classes.
- Keep UI callbacks focused on validation, state updates, and service orchestration.
- Run blocking SSH, SFTP, file upload, and remote command work through `TaskRunner` or `ThreadPoolTaskRunner`.
- Apply UI updates on Qt signal/callback paths.
- Keep terminal output in the pane that matches the remote context.
- Keep main terminal shell and SFTP shell state independent.
- If a workflow uses `QProcess`, make lifecycle and cleanup explicit.

## Core

- Keep `core/` modules independent from PySide6 widgets where practical.
- Use `shlex.quote` for shell command arguments that come from user input.
- Validate narrow device/path formats with explicit rules when possible.
- Keep Paramiko client/channel close and disconnect paths clear.
- Raise specific, action-oriented error messages that the UI can show to users.

## Models and Storage

- JSON-backed models should provide `from_dict` and `to_dict`.
- When adding fields, make `from_dict` tolerate missing values with safe defaults.
- Keep schema changes backward compatible.
- Save persistent JSON through a temporary file and replace where practical.
- Use `%APPDATA%/MMUControl` as the default user data location, with the current fallback behavior from `default_user_data_directory()`.

## Terminal and Shell

- Send line commands with a trailing newline.
- Send raw key input immediately in interactive mode.
- Treat Ctrl+C, `q`, Backspace, and similar keys according to the current interactive context.
- Use the stateful terminal stream filter for ANSI/VT sequences that can cross chunk boundaries.

## SFTP

- Treat SFTP as a Linux-server-side CLI session.
- Keep SFTP shell lifecycle separate from the main terminal shell.
- Treat board/MMU paths as POSIX paths.
- Do not conflate Windows local paths, Linux server paths, and board/MMU paths.
- Local PC file drag-and-drop should upload to the Linux server first, then send through SFTP `put`.
- Quote transfer and remove paths.

## Automation

- Keep scenario execution logic in `AutomationRunner` rather than UI code.
- Keep terminal-specific capabilities behind the `AutomationTerminal` protocol.
- Preserve retry-once semantics unless the product requirement changes.
- Keep output history bounded.
- Validate regex patterns in the editor before accepting a scenario.

## Tests

- Test manager/model/storage logic with pytest unit tests.
- Test UI behavior with fake managers/runners rather than real network devices.
- Update packaging tests when PyInstaller resources or package data change.
- Add regression tests for bug fixes where practical.

## Documentation

- `PRD.md` describes user value and requirements.
- `ARCHITECTURE.md` describes actual code structure and data flow.
- `IMPLEMENTATION_PLAN.md` tracks completed work and future work.
- `requirements.md` describes runtime, development, packaging, and environment requirements.
- `TASKS.md` describes the agent workflow for making changes.
- `PROJECT_OVERVIEW_FOR_AGENTS.md` gives a fast onboarding map for AI coding agents.
