# MMU Control PRD

## Goal

MMU Control is a Windows desktop GUI for engineers who need to operate board/MMU workflows through a Linux server and, where supported, directly from the local Windows PC.

The application should reduce repeated terminal setup by keeping SSH, board, power supply, command-set, SFTP, and automation workflows in one focused tool.

## Target Users

- Engineers validating or developing board/MMU software from a Windows PC.
- Users who access the board through a Linux server used as a gateway or work host.
- Users who repeatedly run shell commands, minicom serial sessions, SFTP transfers, power supply commands, and scripted validation scenarios.

## Primary Workflow

```text
Windows PC
  -> MMU Control GUI
  -> SSH to Linux Server
  -> Linux shell / minicom / Linux-side SFTP / power supply commands
  -> Board or MMU
```

Direct board SSH is also supported through a local `ssh` process when the Linux server connection is not active.

## Product Value

- Save and restore frequently used connection and device fields.
- Keep terminal, serial console, SFTP, command groups, and automation scenarios in one UI.
- Run blocking network and file operations without freezing the GUI.
- Organize reusable multi-line commands and replay them consistently.
- Transfer files between the Linux server and the board/MMU through an SFTP session, with drag-and-drop support for file-list transfers.
- Run condition-driven automation scenarios against the active terminal.

## Functional Requirements

### Linux Server SSH

- Accept host, port, username, and password.
- Connect and disconnect from the Linux server.
- Open an interactive shell after a successful connection.
- Show connection state in the status bar.
- Support remote command execution, shell channels, local PC file upload to the Linux server, and USB serial-port discovery.

### Terminal

- Show an interactive terminal pane for the Linux server shell.
- Before Linux SSH is connected, allow simple local terminal commands in the current Windows working directory.
- Send line commands with Enter.
- Support raw key input for interactive programs such as `minicom`, `htop`, `top`, `vi`, `vim`, `nano`, `less`, `more`, and `tail -f`.
- Strip ANSI/VT escape/control sequences from displayed output where needed.
- Keep a separate response pane for configured command responses.

### Board/MMU Serial Console

- Discover `/dev/ttyUSB*` and `/dev/ttyACM*` device paths on the Linux server.
- Let users select a detected USB serial port.
- Open `minicom -o -c off -D <port>` in the active Linux server shell.
- Close minicom by sending Ctrl-A, X, and Enter.
- Keep serial console state separate from board SSH and SFTP state.

### Board/MMU SSH Console

- Accept board/MMU IP or hostname, username, password, SSH port, optional SSH key path, and optional IPv6 interface/zone.
- Build board SSH destinations correctly for IPv4 and IPv6-with-zone usage.
- When Linux server SSH is connected, run board SSH from the Linux shell.
- When Linux server SSH is disconnected, start a local Windows `ssh` process to connect directly to the board.
- Show board SSH output in its own console area and support disconnect.

### SFTP

- Start a Linux-side `sftp` CLI session from the Linux server to the board/MMU.
- Use board/MMU IP, username, password, port, optional key path, and optional IPv6 interface.
- Handle first-connection authenticity prompts and password prompts.
- Keep the SFTP shell independent from the main terminal shell.
- Show Linux server and MMU current directories.
- Show file lists for both sides.
- Support directory navigation by double-click.
- Support symlink display and directory-link navigation where detectable.
- Upload from Linux server to MMU with `put`.
- Download from MMU to Linux server with `get`.
- Support drag-and-drop between the two file lists for upload/download.
- Support Delete/Backspace removal for selected files.
- For local PC file drops, upload the file to a temporary Linux server path before sending it to the MMU.

### Command Sets

- Let users create, edit, delete, and run named command groups.
- Store command groups as name, description, multi-line commands, and optional parent folder.
- Support folders and drag/drop movement of command groups into folders.
- Persist command groups as JSON under the user data directory.
- Load legacy flat command-set JSON and save back using the current hierarchical schema.

### Automation Scenarios

- Let users create, import, copy, edit, delete, run, and stop automation scenarios.
- Store scenarios as ordered steps.
- Each step has a command, timeout, optional start condition, and optional completion condition.
- Supported condition types are none, output contains, output regex, latest prompt regex, remote file contains, remote file regex, and delay.
- Start conditions can timeout/fail the step, or skip the step when `skip_on_start_condition_failure` is enabled.
- A run may start from any selected step.
- The runner retries only the current failing step once after a two-second delay.
- Show current state, selected start step, skipped steps, failure reason, and terminal target.
- Import scenarios from pasted text or a UTF-8 text file using the parser rules in `automation_import_parser.py`.

### Settings and Profiles

- Persist SSH, board/MMU, power supply, selected USB port, active profile name, and window state.
- Load missing settings fields with safe defaults.
- Save settings atomically through a temporary file and replace.
- Keep profile models and storage available for future full profile UI work.

### Power Supply

- Accept power supply IPv4 address, voltage, and current.
- Build configured ON, OFF, Status, All Status, and Set commands.
- Load power command templates from `resources/power_supply_commands.json`.
- Run power commands on the connected Linux server and show output or errors to the user.

### Logging and Error Recovery

- Write application logs under the user data directory.
- Use rotating file logging.
- Close logging handlers on application exit.
- Use retry/backoff helpers for operations that can reasonably be retried.
- Surface failures through terminal output and/or the status bar.

### Packaging

- Provide `mmu-control` as the development entry point.
- Build a Windows executable through `scripts/build_exe.ps1`.
- Include package resources required by runtime managers in the PyInstaller spec.

## Non-Functional Requirements

- Do not run blocking SSH, SFTP, file I/O, or long remote commands on the GUI thread.
- Keep UI orchestration separate from core business logic where practical.
- Keep JSON schemas backward compatible when fields are added.
- Validate and quote shell paths/arguments where user input can affect a command.
- Keep logic testable without real SSH, SFTP, minicom, power supply, or board hardware.
