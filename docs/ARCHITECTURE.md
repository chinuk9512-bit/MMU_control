# Architecture

## Overview

MMU Control is a Python 3.12 / PySide6 Windows desktop application. It connects to a Linux server over SSH, uses that server as the main work host, and supports board/MMU shell, serial, SFTP, power supply, saved-command, and automation workflows.

```text
Windows PC GUI
  -> PySide6 MainWindow
  -> Paramiko SSHManager
  -> Linux Server
  -> shell / minicom / sftp / power supply command
  -> Board or MMU
```

The board SSH console can also run through a local Windows `ssh` process when the Linux server connection is not active.

## Technology Stack

- Python 3.12+
- PySide6 for widgets, signals/slots, timers, `QThreadPool`, and `QProcess`
- Paramiko for Linux server SSH, shell channels, command execution, and local-to-server file upload
- JSON for app settings, command groups, profiles, automation scenarios, and power command templates
- PyInstaller for Windows executable packaging
- pytest for model, manager, storage, and UI-logic tests

## Source Layout

```text
src/mmu_control/
  app.py                         # QApplication startup and logging lifecycle
  core/                          # SSH, shell, SFTP, minicom, automation, logging, config, retry logic
  models/                        # JSON-serializable dataclass models
  storage/                       # JSON stores for command sets, automation scenarios, and profiles
  ui/                            # PySide6 main window, dialogs, terminal widget, background worker
  resources/                     # Packaged JSON resources
  user_scenario/                 # Seed/sample automation scenarios
```

## Main Modules

### Entry Point

- `mmu_control.app.main`
  - Configures logging.
  - Creates `QApplication`.
  - Creates and shows `MainWindow`.
  - Shuts down logging handlers when the app exits.

### UI Layer

- `MainWindow`
  - Owns the application workflow and visible state.
  - Builds the connection panel, terminal workspace, SFTP tab, command groups, automation scenarios, board serial console, board SSH console, and response pane.
  - Coordinates managers and stores.
  - Polls interactive shells with `QTimer`.
  - Starts blocking work through `ThreadPoolTaskRunner`.
  - Starts direct board SSH through `QProcess` when needed.
- `TerminalWidget`
  - Handles terminal text display, prompt rendering, line editing, paste, clear, and immediate input mode.
- `CommandEditorDialog`
  - Edits one named command group with description and multi-line command text.
- `AutomationEditorDialog`
  - Edits scenario metadata and ordered steps, including start/completion conditions.
- `AutomationImportDialog`
  - Creates an unsaved scenario draft from pasted text or a UTF-8 text file.
- `ThreadPoolTaskRunner`
  - Wraps Qt global thread-pool execution and reports success/failure through callbacks.

### Core Layer

- `SSHManager`
  - Manages the Paramiko SSH client lifecycle.
  - Connects, disconnects, reconnects, opens shell channels, executes non-interactive commands, uploads local files, and lists USB serial ports.
- `InteractiveShell`
  - Wraps a Paramiko shell channel.
  - Sends raw text or newline-terminated commands.
  - Reads currently available output without blocking.
  - Responds to prompts such as password prompts.
- `SFTPManager`
  - Builds Linux-side `sftp` commands for board/MMU access.
  - Handles authenticity and password prompts.
  - Sends upload/download/cd/rm/bye commands.
  - Quotes transfer paths.
- `MinicomManager`
  - Validates Linux serial device paths.
  - Builds `minicom -o -c off -D <port>`.
  - Sends the minicom close sequence.
- `PowerSupplyManager`
  - Loads command templates from `resources/power_supply_commands.json`.
  - Validates configured IP/voltage/current requirements.
  - Builds power supply action commands.
- `AutomationRunner`
  - Runs one `AutomationScenario` step by step.
  - Evaluates start and completion conditions.
  - Retains a bounded output history for condition checks.
  - Requests periodic remote-file checks through generated `grep` commands.
  - Retries the current failing step once.
- `TerminalStreamFilter`
  - Removes ANSI/VT/control sequences while preserving parser state across chunks.
- `ConfigManager`
  - Loads and saves `%APPDATA%/MMUControl/settings.json`.
  - Falls back to `~/AppData/Roaming/MMUControl` when `APPDATA` is unavailable.
- `run_with_retry`
  - Shared retry/backoff helper.

### Model and Storage Layer

- `AppSettings`, `SSHSettings`, `BoardSettings`, `PowerSupplySettings`, `WindowSettings`
  - Persist user-entered connection and window state.
- `CommandSet`, `CommandFolder`, `CommandSetCollection`
  - Represent hierarchical saved command groups.
- `AutomationScenario`, `AutomationStep`, `CompletionType`, `AutomationScenarioCollection`
  - Represent condition-driven terminal automation.
- `ConnectionProfile`, `ProfileCollection`
  - Represent future full profile workflows.
- `CommandSetStore`
  - Persists command folders and command sets in `command_sets.json`.
  - Upgrades legacy flat command documents to schema version 2.
- `AutomationStore`
  - Persists scenarios in `automation_scenarios.json`.
- `ProfileStore`
  - Persists named profile collections in `profiles.json`.

## Data Flows

### Linux Server Terminal

```text
Connect
  -> ThreadPoolTaskRunner
  -> SSHManager.connect()
  -> SSHManager.open_shell()
  -> InteractiveShell
  -> QTimer polling
  -> TerminalWidget.write_stream()
```

User commands entered in the Terminal tab are sent through `InteractiveShell.send_line()`. In immediate input mode, key presses are sent through `InteractiveShell.send()`.

### Board Serial Console

```text
Refresh USB
  -> SSHManager.list_serial_ports()
  -> device list in UI
Open Minicom
  -> MinicomManager.build_command()
  -> main Linux shell sends minicom command
  -> TerminalWidget immediate input mode
Close Minicom
  -> Ctrl-A, X, Enter
```

### Board SSH Console

```text
SSH Connect
  -> if Linux shell is connected: send ssh command through InteractiveShell
  -> else: start local Windows ssh through QProcess
  -> board console output
```

### SFTP

```text
Open SFTP
  -> open a second SSH shell
  -> SFTPManager.open_session()
  -> handle authenticity/password prompts
  -> refresh Linux server and MMU file lists
Drag server file to MMU
  -> sftp put
Drag MMU file to server
  -> sftp get
Drop local PC file
  -> SSHManager.upload_file(local, /tmp/mmu_control_uploads/...)
  -> sftp put uploaded_server_path
```

The SFTP shell is independent from the main terminal shell, so closing SFTP does not close the terminal connection.

### Automation

```text
Run Scenario
  -> choose active terminal adapter
  -> AutomationRunner.start()
  -> poll terminal output
  -> evaluate start/completion conditions
  -> optionally send file-check grep command
  -> update UI status/progress
```

Automation currently targets the active terminal abstraction and uses remote-file checks only when the selected terminal reports support for them.

## Persistent Files

Default user data location:

```text
%APPDATA%/MMUControl
```

Fallback when `APPDATA` is missing:

```text
~/AppData/Roaming/MMUControl
```

Files:

- `settings.json` - connection, power supply, board, active profile, and window state.
- `command_sets.json` - hierarchical command folders and command groups.
- `automation_scenarios.json` - automation scenarios.
- `profiles.json` - profile storage for future profile UI expansion.
- `mmu_control.log` - rotating application log.

## Packaging

- `pyproject.toml` defines package metadata, dependencies, package data, and the `mmu-control` entry point.
- `MMUControl.spec` defines the PyInstaller executable and bundled resources.
- `scripts/build_exe.ps1` builds `dist/MMUControl.exe`.
