# MMU Control

Windows Python GUI application for connecting to a Linux server over SSH and controlling board workflows such as shell, minicom, and SFTP.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

## Run

```powershell
mmu-control
```

## Board workflows

- SSH connection and board fields are restored when the application restarts.
- `Refresh USB` searches the connected Linux server for `/dev/ttyUSB*` and `/dev/ttyACM*` devices.
- Select a detected device and use `Open Minicom` / `Close Minicom` for the board serial console.
- Full-screen commands such as `htop` use immediate key input, so `q` and `Ctrl+C` are sent without pressing Enter.
- The SFTP tab uses its own SSH terminal and opens an SFTP session from the Linux server to the board. Closing it does not close the main Terminal tab.
- `Server path` is a path on that Linux server, not a path on the Windows PC. `Board path` is the corresponding path on the board.
- You can drag and drop a file into the `Server path` input to fill in a local PC path as an entry aid; use it only when that same path is accessible from the SSH Linux server, otherwise enter the Linux server path manually.
- Use `Upload to Board` for SFTP `put` and `Download to Server` for SFTP `get`.

## Automation scenarios

- Command sets and automation scenarios are saved in `%APPDATA%/MMUControl` (or
  `~/AppData/Roaming/MMUControl` when `APPDATA` is unavailable), so they remain
  available after restarting the executable.
- The Scenarios tab loads this file when the application starts and refreshes the scenario list after a scenario is saved.

## Test

```powershell
python -m pytest
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The executable is created at `dist\MMUControl.exe`.
