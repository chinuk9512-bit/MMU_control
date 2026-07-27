@echo off
setlocal

rem Always run from the directory containing this script, including paths with spaces.
cd /d "%~dp0"
if errorlevel 1 (
    set "EXIT_CODE=%errorlevel%"
    echo [ERROR] Could not change to the project root: "%~dp0"
    echo Move the checkout to an accessible directory and run "install.bat" again.
    exit /b %EXIT_CODE%
)

set "PYTHON_CMD=py -3.12"
%PYTHON_CMD% --version >nul 2>&1
if errorlevel 1 (
    set "PYTHON_CMD=python"
    python --version >nul 2>&1
    if errorlevel 1 goto :python_not_found
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 goto :python_too_old

if exist ".venv\Scripts\python.exe" (
    echo [INFO] Reusing the existing virtual environment at ".venv".
) else (
    echo [INFO] Creating the virtual environment at ".venv"...
    %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto :venv_failed
)

echo [INFO] Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :pip_upgrade_failed

echo [INFO] Installing MMU Control and development dependencies...
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto :dependency_install_failed

echo [INFO] Building "dist\MMUControl.exe"...
".venv\Scripts\python.exe" -m PyInstaller --clean -y "MMUControl.spec"
if errorlevel 1 goto :executable_build_failed

echo.
echo [SUCCESS] MMU Control is ready and "dist\MMUControl.exe" was created.
echo Activate the virtual environment with:
echo   .venv\Scripts\activate
echo Run the packaged desktop application with:
echo   dist\MMUControl.exe
echo Run the desktop application with:
echo   mmu-control
echo Run the web application with:
echo   mmu-control-web
exit /b 0

:python_not_found
set "EXIT_CODE=%errorlevel%"
echo [ERROR] Python was not found. Python 3.12 or newer must be installed.
echo Install Python from https://www.python.org/downloads/ and enable the Python launcher or add Python to PATH, then run "install.bat" again.
exit /b %EXIT_CODE%

:python_too_old
set "EXIT_CODE=%errorlevel%"
echo [ERROR] The available Python version is older than 3.12.
echo Install Python 3.12 or newer and ensure "py -3.12" or "python" can find it, then run "install.bat" again.
exit /b %EXIT_CODE%

:venv_failed
set "EXIT_CODE=%errorlevel%"
echo [ERROR] Virtual environment creation failed with exit code %EXIT_CODE%.
echo Remove the incomplete ".venv" directory, verify that the Python venv module is installed, and run "install.bat" again.
exit /b %EXIT_CODE%

:pip_upgrade_failed
set "EXIT_CODE=%errorlevel%"
echo [ERROR] pip upgrade failed with exit code %EXIT_CODE%.
echo Check the network and proxy settings, then run "install.bat" again.
exit /b %EXIT_CODE%

:dependency_install_failed
set "EXIT_CODE=%errorlevel%"
echo [ERROR] Project dependency installation failed with exit code %EXIT_CODE%.
echo Review the pip error above, check the network and build tools, then run "install.bat" again.
exit /b %EXIT_CODE%

:executable_build_failed
set "EXIT_CODE=%errorlevel%"
echo [ERROR] Building "dist\MMUControl.exe" failed with exit code %EXIT_CODE%.
echo Review the PyInstaller error above, remove the "build" directory if it contains stale files, and run "install.bat" again.
exit /b %EXIT_CODE%
