# Requirements

## Runtime Requirements

- Python `3.12` or newer
- `PySide6>=6.7`
- `paramiko>=3.4`

## Development Requirements

The following packages are needed for local development, testing, and packaging:

- `pyinstaller>=6.0`
- `pytest>=8.0`

## Virtual Environment Installation Inputs

The items below are additional inputs needed to create or reproduce the Python virtual environment. Packages already listed in the runtime and development sections are intentionally omitted.

### Additional Required Packages

- `setuptools>=69` - build backend required by `pyproject.toml` for editable installs and package metadata generation.

### Installation and Build Files

- `pyproject.toml` - canonical project metadata, Python version constraint, dependency declarations, optional development extras, and package discovery settings.
- `src/mmu_control.egg-info/requires.txt` - generated dependency metadata that records the installed package requirements for the current editable install.
- `scripts/build_exe.ps1` - PowerShell entry point for packaging the application into a Windows executable after the virtual environment dependencies are installed.
- `MMUControl.spec` - PyInstaller specification used by the build script to define the executable packaging configuration.

## Recommended Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

## Notes

- `PySide6` is required for the GUI.
- `paramiko` is required for SSH and SFTP functionality.
- `pytest` is used for the test suite.
- `pyinstaller` is used to build the Windows executable.
- The project uses a local virtual environment in `.venv` to keep dependencies isolated from the system Python.
