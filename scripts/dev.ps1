# Local development helper (Windows PowerShell).
#   .\scripts\dev.ps1           docker compose stack on http://localhost:8080
#   .\scripts\dev.ps1 local     run API + frontend on the host against a local PostgreSQL (no Docker)
#   .\scripts\dev.ps1 down      stop the docker compose stack
param(
    [ValidateSet('docker', 'local', 'down')]
    [string]$Mode = 'docker'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

switch ($Mode) {
    'docker' {
        Write-Host 'Starting the stack: http://localhost:8080 (API docs: http://localhost:8000/api/docs)'
        docker compose up --build
    }
    'down' {
        docker compose down
    }
    'local' {
        # Requires a local PostgreSQL with a 'monitoring' database and user (see docs/local-development.md).
        if (-not $env:ENVIRONMENT) { $env:ENVIRONMENT = 'development' }
        if (-not $env:AUTH_MODE) { $env:AUTH_MODE = 'dev' }
        if (-not $env:AZURE_PROVIDER) { $env:AZURE_PROVIDER = 'mock' }
        if (-not $env:TASK_BACKEND) { $env:TASK_BACKEND = 'inline' }
        if (-not $env:DATABASE_URL) {
            $env:DATABASE_URL = 'postgresql+asyncpg://monitoring:monitoring@localhost:5432/monitoring'
        }
        $py = Join-Path $Root 'backend\.venv\Scripts\python.exe'
        if (-not (Test-Path $py)) {
            throw 'Create the backend virtualenv first: cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt'
        }
        Push-Location backend
        & $py -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Migrations failed' }
        $api = Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000' -PassThru -NoNewWindow
        Pop-Location
        try {
            Push-Location frontend
            if (-not (Test-Path node_modules)) { npm install }
            npm run dev
        }
        finally {
            Pop-Location
            if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
        }
    }
}
