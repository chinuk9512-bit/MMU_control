# Requirements

## Runtime Requirements

- Python `3.12` or newer.
- `PySide6>=6.7` for the Windows desktop GUI, Qt widgets, timers, signals, `QThreadPool`, and `QProcess`.
- `paramiko>=3.4` for Linux server SSH, interactive shell channels, remote command execution, and local PC to Linux server upload support.
- `streamlit>=1.37` for the local browser-based web UI.
- A local `ssh` executable on PATH when using direct board/MMU SSH without an active Linux server connection.

These are the direct dependencies declared by the project. Their transitive dependencies are resolved by `pip`; they should not be maintained as a separate manual list here.

## Development Requirements

- `pytest>=8.0` for unit, desktop UI, and web UI tests.
- `pyinstaller>=6.0` for building the Windows desktop and web executables.
- `setuptools>=69` as the build backend used by `pyproject.toml`.

The optional dependency groups in `pyproject.toml` provide the supported install sets:

- `.[test]` - packages required to run the test suite.
- `.[dev]` - test packages plus PyInstaller and all dependencies needed for local development and executable builds.

## Project Metadata and Packaging Inputs

- `pyproject.toml`
  - Canonical package metadata.
  - Python version constraint.
  - Runtime dependencies.
  - Optional development dependencies.
  - `mmu-control` console script entry point.
  - Package discovery and package-data settings.
- `MMUControl.spec`
  - Desktop GUI PyInstaller build specification.
  - Includes runtime package resources, including `power_supply_commands.json`.
- `MMUControlWeb.spec`
  - Streamlit web UI PyInstaller build specification.
  - Collects Streamlit modules, static data, package metadata, and the power-supply command resource.
- `scripts/build_exe.ps1`
  - PowerShell entry point for Windows desktop executable packaging.
  - Produces `dist\MMUControl.exe`.
- `scripts/build_web_exe.ps1`
  - PowerShell entry point for Windows web executable packaging.
  - Produces `dist\MMUControlWeb.exe`.
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

The application host also needs:

- Windows with PowerShell for the documented `.venv` and executable build workflow.
- Network access from the host to the configured Linux SSH server (normally TCP port 22, or the configured alternative).
- A writable per-user application-data directory for settings, scenarios, command sets, profiles, and logs.
- A web browser for `mmu-control-web`; the Streamlit server is started locally by the command.

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

## Run Web UI

```powershell
mmu-control-web
```

For development, the Streamlit module can be run directly:

```powershell
python -m streamlit run .\src\mmu_control\web_app.py
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

## Build Web EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_web_exe.ps1
```

The web executable is created at:

```text
dist\MMUControlWeb.exe
```

## Notes

- Windows local PC paths, Linux server paths, and board/MMU paths are separate concepts.
- Dragging a Windows local file into the SFTP workflow uploads it to the Linux server first, then sends it to the board/MMU through the active SFTP session.
- JSON files should remain backward compatible as new fields are added.
