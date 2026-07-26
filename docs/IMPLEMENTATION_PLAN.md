# Implementation Plan

This document tracks implemented work and likely next work. Keep it aligned with the current codebase, not with old intentions.

## Completed

### Phase 1. Project Skeleton

- Python package layout under `src/mmu_control`.
- `pyproject.toml` metadata and editable-install entry point.
- pytest configuration and test suite under `tests`.

### Phase 2. Main UI and Settings

- `MainWindow` with connection panel, terminal workspace, SFTP tab, command/scenario side tabs, board console tabs, status bar, and response pane.
- Persisted SSH, board/MMU, power supply, selected USB port, active profile name, and window state.
- Collapsible connection panel and response pane.
- `%APPDATA%/MMUControl/settings.json` loading/saving with default fallback behavior.

### Phase 3. SSH and Interactive Shell

- Paramiko-based `SSHManager`.
- Connect, disconnect, reconnect, shell open, remote command execution, local-to-server upload, and serial-port listing.
- `InteractiveShell` wrapper.
- QTimer shell polling.
- Background worker for blocking connect/upload/remote-command flows.

### Phase 4. Terminal UX

- `TerminalWidget` prompt/output/input behavior.
- Local command fallback before Linux SSH is connected.
- Immediate input mode for full-screen or raw-input programs.
- ANSI/VT stream filtering.

### Phase 5. USB and Minicom

- Linux server discovery for `/dev/ttyUSB*` and `/dev/ttyACM*`.
- USB combo box refresh.
- Minicom command validation/building.
- Minicom close sequence.
- Serial-console button state management.

### Phase 6. Command Sets

- Command group model and JSON store.
- Folder model and hierarchical schema version 2.
- Create, edit, delete, run, folder creation, and drag/drop movement.
- Legacy flat `commands` key compatibility.

### Phase 7. SFTP

- Linux-side SFTP command builder.
- IPv4/IPv6, interface, port, username, password, and key-path support.
- Separate SFTP shell from main terminal shell.
- Auth prompt and password prompt handling.
- Open/close/upload/download.
- Server/MMU file listing.
- Directory navigation.
- Symlink display and directory-link navigation support.
- File-list drag/drop transfers.
- Delete/Backspace selected-file removal.
- Local PC file drop through Linux server temporary upload path.
- Basic transfer progress dialog.

### Phase 8. Board/MMU SSH Console

- Board SSH command builder.
- Board SSH console output.
- Linux-shell board SSH when Linux server is connected.
- Local Windows `ssh` process fallback when Linux server is disconnected.
- Auth prompt handling and timeout state.

### Phase 9. Power Supply

- `PowerSupplySettings` model.
- `PowerSupplyManager`.
- JSON command templates in package resources.
- Set, ON, OFF, Status, and All Status buttons.
- PyInstaller package-data coverage.

### Phase 10. Automation Scenarios

- Scenario and step models.
- Scenario store.
- Editor dialog.
- Import dialog and parser.
- Copy/edit/delete/run/stop UI.
- Start step selection.
- Start conditions, completion conditions, delay, remote-file checks, skip-on-start-failure, retry-once behavior, and progress rendering.

### Phase 11. Logging and Error Recovery

- Rotating file logging.
- Logging shutdown on app exit.
- Retry/backoff helper.
- User-visible status and terminal error messages.

### Phase 12. Packaging

- PowerShell build script.
- PyInstaller spec.
- Tests for packaging inputs and package data.
- Executable output path documented as `dist/MMUControl.exe`.

## Remaining / Future Work

### Connection Profile UI

The profile model and store exist, but the full profile-management UI is still future work.

- Add profile list UI.
- Save current fields as a named profile.
- Load a selected profile into SSH and board/MMU fields.
- Delete and rename profiles.
- Synchronize `AppSettings.active_profile` and `ProfileCollection.active_profile`.

### UX and Hardening

- Improve long SFTP transfer progress and cancellation.
- Improve board SSH auth failure and timeout messages.
- Decide a safer policy for persisted passwords and SSH key usage.
- Add real-device power supply command presets if multiple devices are required.
- Add more cancellation paths for long remote commands.
- Add integration-style tests around scenario execution UI with fake terminals.

## Definition of Done

- Existing tests pass.
- New or changed behavior has focused tests where practical.
- Blocking work stays out of the GUI thread.
- JSON schema changes remain backward compatible.
- Shell/device paths are quoted or validated.
- PyInstaller resources are updated when runtime resources change.
- Docs are updated when behavior or workflow changes.
