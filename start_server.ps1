# ============================================================
# SynaptiMesh - Smart Server Launcher
# Clears ports 8000 & 5000 before starting to avoid WinError 10048
# Usage: Right-click -> "Run with PowerShell"  OR  .\start_server.ps1
# ============================================================

function Kill-Port {
    param([int]$Port)
    $pids = (netstat -ano | Select-String ":$Port\s.*LISTENING") |
        ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique
    foreach ($p in $pids) {
        if ($p -match '^\d+$' -and $p -ne '0') {
            try {
                Stop-Process -Id $p -Force -ErrorAction Stop
                Write-Host "  [OK] Killed PID $p on port $Port" -ForegroundColor Green
            } catch {
                Write-Host "  [SKIP] PID $p already gone" -ForegroundColor DarkGray
            }
        }
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SynaptiMesh - Smart Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

Write-Host "`n[1/3] Clearing port 8000 (uvicorn)..." -ForegroundColor Yellow
Kill-Port 8000

Write-Host "[2/3] Clearing port 5000 (Flask/SocketIO)..." -ForegroundColor Yellow
Kill-Port 5000

Start-Sleep -Milliseconds 700

Write-Host "[3/3] Starting SynaptiMesh server...`n" -ForegroundColor Yellow

Set-Location $PSScriptRoot
python main.py
