# Project Overview for AI Coding Agents

## What This Project Is

MMU Control is a Windows Python desktop app for controlling board/MMU workflows. The normal path is:

```text
Windows PC GUI -> SSH Linux Server -> board/MMU shell, minicom, SFTP, power commands
```

The app is not a web service. It is a PySide6 GUI with Paramiko SSH under the hood.

## Fast Mental Model

- `MainWindow` is the orchestrator.
- `core/` contains testable service logic.
- `models/` contains JSON-serializable dataclasses.
- `storage/` persists JSON collections under the user data directory.
- `ui/` contains PySide6 widgets, dialogs, and background-worker plumbing.
- Tests use fakes heavily so most behavior can be changed without real hardware.

## Important Entry Points

- Runtime entry point: `mmu_control.app:main`
- Main UI: `src/mmu_control/ui/main_window.py`
- Terminal widget: `src/mmu_control/ui/terminal_widget.py`
- Background worker: `src/mmu_control/ui/background_worker.py`
- SSH manager: `src/mmu_control/core/ssh_manager.py`
- SFTP manager: `src/mmu_control/core/sftp_manager.py`
- Automation runner: `src/mmu_control/core/automation_runner.py`
- Settings manager: `src/mmu_control/core/config_manager.py`

## User-Facing Areas

### Connection Panel

The top connection panel collects:

- Linux server SSH host, port, user, password.
- Power supply IPv4, voltage, current.
- Board/MMU IP, user, password, interface, SSH port, selected USB port.

The panel can be hidden, and the app persists relevant values.

### Terminal Tab

The main terminal shows either:

- A local command prompt before Linux SSH is connected.
- The Linux server interactive shell after SSH connection.

The right side of the terminal tab contains:

- Commands: saved command groups with folders.
- Scenarios: automation scenario management and run controls.

### SFTP Tab

SFTP opens a separate shell to the Linux server, then starts Linux-side `sftp` to the board/MMU. It maintains independent file lists for Linux server and MMU directories.

Drag server files to the MMU list to upload. Drag MMU files to the server list to download. Local PC file drops first upload the file to `/tmp/mmu_control_uploads` on the Linux server.

### Board Console

The board area supports:

- Serial console through Linux server `minicom`.
- Board SSH through the Linux shell when connected, or through a local Windows `ssh` process when disconnected.

## Persistence

User data lives under `%APPDATA%/MMUControl`, with a fallback to `~/AppData/Roaming/MMUControl`.

Key files:

- `settings.json`
- `command_sets.json`
- `automation_scenarios.json`
- `profiles.json`
- `mmu_control.log`

Packaged resources live in `src/mmu_control/resources`.

## Schemas to Know

- `CommandSetCollection` currently saves schema version 2 with `folders` and `command_sets`.
- Legacy command JSON using a top-level `commands` key is still accepted.
- `AutomationScenarioCollection` saves scenarios by name.
- `AutomationStep` has both start-condition fields and completion-condition fields.
- `AppSettings` stores `active_profile`, but full profile UI is not implemented yet.

## Threading and Blocking Work

Do not block the GUI thread with network or file work.

Use existing patterns:

- `ThreadPoolTaskRunner` for Paramiko connect, upload, and remote command work.
- `QTimer` polling for interactive shell output.
- `QProcess` for local direct board SSH.

## Testing Strategy

Tests are in `tests/`.

Useful focused areas:

- `test_main_window.py` for UI orchestration with fakes.
- `test_sftp_manager.py` for SFTP command building and quoting.
- `test_ssh_manager.py` for SSH manager behavior.
- `test_automation*.py` for scenarios, parser, runner, and start conditions.
- `test_command_set_store.py` for command-folder persistence.
- `test_pyinstaller_spec.py` for packaging inputs.

Run:

```powershell
python -m pytest
```

## Common Pitfalls

- Do not confuse Windows local paths, Linux server paths, and MMU POSIX paths.
- SFTP is a CLI session running on the Linux server, not Paramiko SFTP directly to the board.
- The main terminal shell and SFTP shell are separate.
- Minicom runs in the main Linux shell and needs raw key mode.
- Board SSH has two modes: Linux-shell mode and local `ssh` process mode.
- Saved JSON must tolerate missing fields from older versions.
- User-visible automation import strings are ASCII English to avoid encoding-dependent display artifacts in Windows consoles.

## Before Editing

1. Read the relevant docs in `docs/`.
2. Inspect the source and matching tests.
3. Preserve unrelated working-tree changes.
4. Keep changes small and covered by focused tests.
