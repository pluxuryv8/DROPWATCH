param(
    [string]$PythonExe = ".\\.venv\\Scripts\\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

if (-not (Test-Path ".env")) {
    Write-Warning ".env not found. Copy .env.example to .env and fill TELEGRAM_TOKEN."
}

$env:PYTHONPATH = "src"
& $PythonExe -m dropwatch.bot
