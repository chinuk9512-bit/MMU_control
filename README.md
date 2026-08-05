# MMU Control

Windows Python GUI application for connecting to a Linux server over SSH and controlling board workflows such as shell, minicom, and SFTP.

## Recommended Setup

From Command Prompt or PowerShell, run the installer. It selects Python 3.12 or
newer, creates (or reuses) `.venv`, and installs the runtime and development
dependencies. It also builds the desktop executable at `dist\MMUControl.exe`:

```powershell
.\install.bat
```

If the installer fails, use these manual commands for troubleshooting:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m PyInstaller --clean -y "MMUControl.spec"
```

## Run

```powershell
mmu-control
```

## Run Web UI

```powershell
mmu-control-web
```

During development you can also run the Streamlit entry point directly:

```powershell
python -m streamlit run .\src\mmu_control\web_app.py
```

The web UI runs locally and reuses the same settings, command sets, and
automation scenarios stored in `%APPDATA%/MMUControl`. Its Terminal tab embeds
a browser terminal served by `ttyd`, so install `ttyd` and make it available on
`PATH`, or set `MMU_CONTROL_TTYD` to the full `ttyd` executable path before
starting `mmu-control-web`. The embedded terminal runs a normal local `ssh`
client, so the browser terminal may prompt for SSH credentials separately from
the app-managed Paramiko connection used by automation and buttons.

## Board workflows

- SSH connection and board fields are restored when the application restarts.
- `Refresh USB` searches the connected Linux server for `/dev/ttyUSB*` and `/dev/ttyACM*` devices.
- Select a detected device and use `Open Minicom` / `Close Minicom` for the board serial console.
- When the Linux server is disconnected, `SSH Connect` opens a direct SSH session from the local Windows PC to the board. Serial console controls remain unavailable because Windows COM-port support is not implemented yet.
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

## Build Web EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_web_exe.ps1
```

The web executable is created at `dist\MMUControlWeb.exe` and starts the local
Streamlit browser UI.
