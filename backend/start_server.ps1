# PowerShell script to safely start the uvicorn server
# Kills any existing process on port 8000 before starting

$port = 8000
$host = "127.0.0.1"
$env:BACKEND_BIND_HOST = $host

Write-Host "Checking for processes on port $port..." -ForegroundColor Yellow

# Find process using the port
$netstatOutput = netstat -ano | findstr ":$port"
if ($netstatOutput) {
    $lines = $netstatOutput -split "`n"
    foreach ($line in $lines) {
        if ($line -match "LISTENING\s+(\d+)") {
            $pid = $matches[1]
            Write-Host "Found process $pid using port $port" -ForegroundColor Red

            # Get process details
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "Process Name: $($process.ProcessName)" -ForegroundColor Cyan
                Write-Host "Killing process $pid..." -ForegroundColor Yellow
                Stop-Process -Id $pid -Force
                Start-Sleep -Seconds 1
                Write-Host "Process killed successfully" -ForegroundColor Green
            }
        }
    }
}

Write-Host "`nStarting uvicorn server on ${host}:${port}..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the server`n" -ForegroundColor Yellow

# Start the server
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host $host --port $port --reload
