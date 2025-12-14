# PowerShell script to restart the PO Helper backend

Write-Host "PO Helper Backend Restart Script" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green

# Kill any existing Python processes on port 8000
Write-Host "`nChecking for existing backend processes..." -ForegroundColor Yellow
$processes = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($processes) {
    Write-Host "Found process listening on port 8000, terminating..." -ForegroundColor Yellow
    foreach ($proc in $processes) {
        try {
            Stop-Process -Id $proc.OwningProcess -Force -ErrorAction Stop
            Write-Host "Terminated process ID: $($proc.OwningProcess)" -ForegroundColor Red
        } catch {
            Write-Host "Could not terminate process ID: $($proc.OwningProcess)" -ForegroundColor Red
        }
    }
    Start-Sleep -Seconds 2
} else {
    Write-Host "No existing backend process found on port 8000" -ForegroundColor Gray
}

# Navigate to backend directory
$backendPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $backendPath
Write-Host "`nWorking directory: $backendPath" -ForegroundColor Cyan

# Check if virtual environment exists
$venvPath = Join-Path $backendPath ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "`nVirtual environment not found! Please create it first:" -ForegroundColor Red
    Write-Host "python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# Activate virtual environment and start backend
Write-Host "`nStarting backend server..." -ForegroundColor Green
Write-Host "Command: .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload" -ForegroundColor Cyan

# Start the backend in a new PowerShell window
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = "powershell.exe"
$startInfo.Arguments = "-NoExit -Command `"Set-Location '$backendPath'; .\.venv\Scripts\Activate.ps1; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`""
$startInfo.UseShellExecute = $true

$process = [System.Diagnostics.Process]::Start($startInfo)

Write-Host "`nBackend starting in new window (Process ID: $($process.Id))..." -ForegroundColor Green
Start-Sleep -Seconds 3

# Test if backend is responding
Write-Host "`nTesting backend health..." -ForegroundColor Yellow
$maxAttempts = 10
$attempt = 0
$healthy = $false

while ($attempt -lt $maxAttempts -and -not $healthy) {
    $attempt++
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            Write-Host "✓ Backend is healthy and responding!" -ForegroundColor Green
        }
    } catch {
        Write-Host "Attempt $attempt/$maxAttempts - Backend not ready yet..." -ForegroundColor Gray
        if ($attempt -lt $maxAttempts) {
            Start-Sleep -Seconds 2
        }
    }
}

if (-not $healthy) {
    Write-Host "`n✗ Backend failed to start properly!" -ForegroundColor Red
    Write-Host "Check the backend window for error messages." -ForegroundColor Yellow
} else {
    Write-Host "`n" -NoNewline
    Write-Host "====================================" -ForegroundColor Green
    Write-Host "Backend successfully started!" -ForegroundColor Green
    Write-Host "====================================" -ForegroundColor Green
    Write-Host "`nBackend URL: http://127.0.0.1:8000" -ForegroundColor Cyan
    Write-Host "API Docs: http://127.0.0.1:8000/api/v1/docs" -ForegroundColor Cyan
    Write-Host "`nFrontend should be accessible at: http://localhost:3001" -ForegroundColor Cyan
}

Write-Host "`nPress any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")