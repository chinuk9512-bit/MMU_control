# Requirements

## Runtime Requirements

- Python `3.12` or newer
- `PySide6>=6.7` for the Windows desktop GUI, Qt widgets, timers, signals, and thread pool integration
- `paramiko>=3.4` for SSH connections, interactive shell channels, remote command execution, and local PC to Linux Server upload support

## Development Requirements

The following packages are needed for local development, testing, and packaging:

- `pytest>=8.0` for unit and UI-logic tests
- `pyinstaller>=6.0` for building the Windows executable
- `setuptools>=69` as the build backend used by `pyproject.toml`

## Project Metadata and Packaging Inputs

- `pyproject.toml`
  - Canonical package metadata
  - Python version constraint
  - Runtime dependencies
  - Optional development dependencies
  - `mmu-control` console script entry point
  - package discovery and package-data settings
- `MMUControl.spec`
  - PyInstaller build specification
  - Includes package resources required at runtime, including `power_supply_commands.json`
- `scripts/build_exe.ps1`
  - PowerShell entry point for Windows executable packaging
  - Produces `dist\MMUControl.exe`
- `src/mmu_control/resources/power_supply_commands.json`
  - Default command templates used by `PowerSupplyManager`

## Runtime User Data

The application stores user data under `%APPDATA%\MMUControl` on Windows. If `APPDATA` is not defined, it falls back to `~/AppData/Roaming/MMUControl`.

Expected files include:

- `settings.json` - SSH, Board/MMU, Power Supply, active profile name, and window state
- `command_sets.json` - saved command sets from the Commands tab
- `mmu_control.log` - rotating application log file
- `profiles.json` - connection profile storage for profile-management expansion

## External Environment Requirements

To use the full application workflow, the user needs:

- A reachable Linux Server with SSH enabled
- Credentials for the Linux Server
- Linux Server tools used by selected workflows:
  - `sh`/shell
  - `find` or compatible commands for local server-side file listing
  - `sftp` client for Board/MMU file transfer
  - `minicom` for serial console workflows
- Board/MMU access information:
  - IP address or hostname
  - username/password, or SSH key path for SSH console workflows
  - optional IPv6 interface/zone value
  - SFTP/SSH port when not using the default port 22
- USB serial devices exposed on the Linux Server as `/dev/ttyUSB*` or `/dev/ttyACM*` for minicom workflows
- Optional Power Supply endpoint reachable from the Linux Server when using power commands

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

- The Windows local PC path, Linux Server path, and Board/MMU path are separate concepts.
- Dragging a Windows local file into the SFTP view uploads it to the Linux Server first, then sends it to Board/MMU through the active SFTP session.
- JSON files are intended to remain backward compatible as new fields are added.
