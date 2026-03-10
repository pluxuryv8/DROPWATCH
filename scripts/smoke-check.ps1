param(
    [string]$PythonExe = ".\\.venv\\Scripts\\python.exe",
    [switch]$UseMockFetcher
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

if (-not $env:TELEGRAM_TOKEN) {
    $env:TELEGRAM_TOKEN = "123456:SMOKE"
}

if ($UseMockFetcher) {
    $env:FETCHER = "mock"
}

$env:PYTHONPATH = "src"

@'
import asyncio

from dropwatch.common.config import settings
from dropwatch.db.database import create_db, init_engine
from dropwatch.monitor.fetchers.factory import create_fetcher


async def main() -> None:
    init_engine(settings.database_url)
    await create_db()
    fetcher = create_fetcher()
    print(f"database_url={settings.database_url}")
    print(f"fetcher={fetcher.__class__.__name__}")
    print("smoke_check=ok")


asyncio.run(main())
'@ | & $PythonExe -
