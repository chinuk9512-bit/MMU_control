$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $projectRoot "MMUControl.spec"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Create .venv and install the project first."
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --clean -y $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
