# Local dev: create venv, install deps, start the service (Windows / PowerShell 7+)
#
#   .\scripts\dev.ps1                 # Normal start (real PBX)
#   .\scripts\dev.ps1 -Mock           # Start with mock PBX, UI preview only
#   .\scripts\dev.ps1 -Port 8099      # Use a different port
#   .\scripts\dev.ps1 -Reload:$false  # Disable hot reload
#
param(
    [int]$Port = 8080,
    [switch]$Mock,
    [bool]$Reload = $true
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        Write-Host '==> Creating .venv' -ForegroundColor Cyan
        python -m venv (Join-Path $root '.venv')
        & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root 'requirements.txt')
    }

    if ($Mock) {
        Write-Host '==> Starting UI preview (mock PBX, http://127.0.0.1:8098)' -ForegroundColor Cyan
        & $python (Join-Path $root 'scripts\dev_preview.py')
        return
    }

    $args = @('-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', $Port)
    if ($Reload) { $args += '--reload' }
    Write-Host "==> http://127.0.0.1:$Port" -ForegroundColor Cyan
    & $python @args
}
finally {
    Pop-Location
}
