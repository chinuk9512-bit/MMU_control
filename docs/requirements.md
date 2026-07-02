# Requirements

## Runtime Requirements

- Python `3.12` or newer
- `PySide6>=6.7`
- `paramiko>=3.4`

## Development Requirements

The following packages are needed for local development, testing, and packaging:

- `pyinstaller>=6.0`
- `pytest>=8.0`

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
