<#
Run the local quality gate for Vigil Document Analyst.

Checks:
- Ruff dead-code and undefined name checks
- Vulture dead-code scan
- Python compile check
- Frontend JavaScript syntax check
#>

param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$py = Join-Path $PSScriptRoot ".venv/.venv/Scripts/python.exe"
if (-not (Test-Path $py)) {
    $py = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
}
if (-not (Test-Path $py)) {
    $py = "python"
}

Write-Host "Using Python: $py" -ForegroundColor Cyan

if (-not $SkipInstall) {
    & $py -m pip install --quiet ruff vulture
}

& $py -m ruff check . --select F401,F821,F822,F841
& $py -m vulture . --exclude ".venv,uploads,__pycache__,.git" --min-confidence 80
& $py -m compileall -q .

if (Get-Command node -ErrorAction SilentlyContinue) {
    node --check static/app.js
} else {
    Write-Warning "Node not found; skipped frontend syntax check."
}

Write-Host "Quality gate passed." -ForegroundColor Green