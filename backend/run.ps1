# Starts the Nkuzi backend at http://localhost:8000
# Usage (from the backend folder):  .\run.ps1

Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Host "No virtual environment yet. Run these first:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  pip install -r requirements.txt"
    exit 1
}

. .\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
