# Requirements

## Runtime Requirements

- Python `3.12` or newer.
- `PySide6>=6.7` for the Windows desktop GUI, Qt widgets, timers, signals, `QThreadPool`, and `QProcess`.
- `paramiko>=3.4` for Linux server SSH, interactive shell channels, remote command execution, and local PC to Linux server upload support.
- A local `ssh` executable on PATH when using direct board/MMU SSH without an active Linux server connection.

## Development Requirements

- `pytest>=8.0` for unit and UI-logic tests.
- `pyinstaller>=6.0` for building the Windows executable.
- `setuptools>=69` as the build backend used by `pyproject.toml`.

## Project Metadata and Packaging Inputs

- `pyproject.toml`
  - Canonical package metadata.
  - Python version constraint.
  - Runtime dependencies.
  - Optional development dependencies.
  - `mmu-control` console script entry point.
  - Package discovery and package-data settings.
- `MMUControl.spec`
  - PyInstaller build specification.
  - Includes runtime package resources, including `power_supply_commands.json`.
- `scripts/build_exe.ps1`
  - PowerShell entry point for Windows executable packaging.
  - Produces `dist\MMUControl.exe`.
- `src/mmu_control/resources/power_supply_commands.json`
  - Default command templates used by `PowerSupplyManager`.
- `src/mmu_control/user_scenario/automation_scenarios.json`
  - Seed/sample automation scenarios shipped in the source tree.

## Runtime User Data

The application stores user data under `%APPDATA%\MMUControl` on Windows. If `APPDATA` is not defined, it falls back to `~/AppData/Roaming/MMUControl`.

Expected files include:

- `settings.json` - SSH, board/MMU, power supply, active profile name, and window state.
- `command_sets.json` - saved command folders and command groups.
- `automation_scenarios.json` - saved automation scenarios.
- `profiles.json` - connection profile storage for future profile-management UI.
- `mmu_control.log` - rotating application log file.

## External Environment Requirements

To use the full Linux-server workflow, the user needs:

- A reachable Linux server with SSH enabled.
- Credentials for the Linux server.
- Linux server tools used by selected workflows:
  - A normal shell.
  - `find` or compatible behavior for local server-side file listing.
  - `sftp` client for board/MMU file transfer.
  - `minicom` for serial console workflows.
  - `grep` for automation remote-file conditions.
- Board/MMU access information:
  - IP address or hostname.
  - Username/password, and optionally an SSH key path.
  - Optional IPv6 interface/zone value.
  - SSH/SFTP port when not using the default port 22.
- USB serial devices exposed on the Linux server as `/dev/ttyUSB*` or `/dev/ttyACM*` for minicom workflows.
- Optional power supply endpoint reachable from the Linux server when using power commands.

## Recommended Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

## Run

```powershell
mmu-control
```

## Test

```powershell
python -m pytest
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The executable is created at:

```text
dist\MMUControl.exe
```

## Notes

- Windows local PC paths, Linux server paths, and board/MMU paths are separate concepts.
- Dragging a Windows local file into the SFTP workflow uploads it to the Linux server first, then sends it to the board/MMU through the active SFTP session.
- JSON files should remain backward compatible as new fields are added.
