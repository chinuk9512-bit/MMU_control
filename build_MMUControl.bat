@echo off
setlocal

rem Run the existing PyInstaller build from the project root.
cd /d "%~dp0"
if errorlevel 1 goto :project_root_failed

call powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_exe.ps1"
if errorlevel 1 goto :build_failed

rem Publish the executable beside this batch file as requested.
copy /Y ".\dist\MMUControl.exe" ".\MMUControl.exe" >nul
if errorlevel 1 goto :copy_failed

echo [SUCCESS] "%~dp0MMUControl.exe" was created.
exit /b 0

:project_root_failed
echo [ERROR] Could not change to the project root: "%~dp0"
exit /b 1

:build_failed
echo [ERROR] MMUControl.exe build failed. Review the PowerShell output above.
exit /b 1

:copy_failed
echo [ERROR] Could not copy "dist\MMUControl.exe" to the project root.
exit /b 1
