param(
    [string]$PythonExe = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

$root = (Resolve-Path ".").Path
$python = (Resolve-Path $PythonExe).Path

$botCommand = "Set-Location '$root'; `$env:PYTHONPATH='src'; & '$python' -m dropwatch.bot"
$monitorCommand = "Set-Location '$root'; `$env:PYTHONPATH='src'; & '$python' -m dropwatch.monitor"

Start-Process powershell -ArgumentList "-NoExit", "-Command", $botCommand | Out-Null
Start-Process powershell -ArgumentList "-NoExit", "-Command", $monitorCommand | Out-Null

Write-Host "Bot and monitor started in separate windows."
