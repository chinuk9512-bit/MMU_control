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

## Test

```powershell
python -m pytest
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

The executable is created at `dist\MMUControl.exe`.
