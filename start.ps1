# VoiceNovel one-click launcher
# Starts backend (FastAPI :5000) + frontend (Svelte :3000)
param(
    [switch]$SkipInstall,
    [switch]$SkipCheck
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VoiceNovel Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# --- check tools ---
if (-not $SkipCheck) {
    Write-Host ""
    Write-Host "[1/4] Checking environment..." -ForegroundColor Yellow

    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "ERROR: py launcher not found, install Python 3.12" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }

    $pyVer = & py -3.12 --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Python 3.12 not found" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Python: $pyVer" -ForegroundColor Green

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        Write-Host "ERROR: uv not found, install with: pip install uv" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  uv: $(uv --version)" -ForegroundColor Green

    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        Write-Host "ERROR: Node.js not found" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Node: $(node --version)" -ForegroundColor Green

    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        Write-Host "ERROR: npm not found" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  npm: $(npm --version)" -ForegroundColor Green
}

# --- install python deps ---
if (-not $SkipInstall) {
    Write-Host ""
    Write-Host "[2/4] Syncing Python dependencies..." -ForegroundColor Yellow
    & uv sync --extra dev
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Python dependency sync failed" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Python deps ready" -ForegroundColor Green
}

# --- install frontend deps ---
if (-not $SkipInstall) {
    Write-Host ""
    Write-Host "[3/4] Checking frontend dependencies..." -ForegroundColor Yellow
    Push-Location "$root\web_reader"
    $nmExists = Test-Path "node_modules"
    if (-not $nmExists) {
        & npm install
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: npm install failed" -ForegroundColor Red
            Pop-Location
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
    Pop-Location
    Write-Host "  Frontend deps ready" -ForegroundColor Green
}

# --- kill existing process on backend port ---
Write-Host ""
Write-Host "[4/5] Cleaning port 5000..." -ForegroundColor Yellow
$existing = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($existing) {
    $procId = $existing.OwningProcess
    Write-Host "  Found process $procId on port 5000, killing it..." -ForegroundColor DarkYellow
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    Write-Host "  Port 5000 freed" -ForegroundColor Green
}
else {
    Write-Host "  Port 5000 is free" -ForegroundColor Green
}

# --- start services ---
Write-Host ""
Write-Host "[5/5] Starting services..." -ForegroundColor Yellow

$backendJob = Start-Job -Name "VoiceNovel-Backend" -ScriptBlock {
    param($r)
    Set-Location $r
    & uv run python -m vn_server --host 127.0.0.1 --port 5000 2>&1 | ForEach-Object { Write-Host "[backend] $_" }
} -ArgumentList $root

$frontendJob = Start-Job -Name "VoiceNovel-Frontend" -ScriptBlock {
    param($r)
    Set-Location "$r\web_reader"
    & npm run dev 2>&1 | ForEach-Object { Write-Host "[frontend] $_" }
} -ArgumentList $root

Write-Host ""
Write-Host "  Backend starting...  (FastAPI :5000)" -ForegroundColor Green
Write-Host "  Frontend starting... (Svelte  :3000)" -ForegroundColor Green

# wait for backend
Write-Host ""
Write-Host "  Waiting for backend..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/projects" -Method GET -TimeoutSec 2 -ErrorAction SilentlyContinue
        $ready = $true
        break
    }
    catch {
        # not ready yet
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    Write-Host "  WARNING: Backend did not respond within 60s" -ForegroundColor DarkYellow
}
else {
    Write-Host "  Backend is ready" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VoiceNovel Ready!" -ForegroundColor Cyan
Write-Host "  Frontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "  Backend:  http://localhost:5000" -ForegroundColor Cyan
Write-Host "  API docs: http://localhost:5000/docs" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop all services" -ForegroundColor Gray

# keep alive until Ctrl+C
try {
    while ($true) {
        Receive-Job -Name VoiceNovel-Backend, VoiceNovel-Frontend 2>&1 | Out-Null
        Start-Sleep -Seconds 1
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping services..." -ForegroundColor Yellow
    Stop-Job -Name VoiceNovel-Backend, VoiceNovel-Frontend -ErrorAction SilentlyContinue
    Remove-Job -Name VoiceNovel-Backend, VoiceNovel-Frontend -ErrorAction SilentlyContinue
    Write-Host "All services stopped" -ForegroundColor Green
}
