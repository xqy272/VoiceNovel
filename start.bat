@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================
echo   VoiceNovel Launcher
echo ========================================

echo.
echo [1/3] Syncing Python dependencies...
uv sync --extra dev
if %errorlevel% neq 0 (
    echo ERROR: Python dependency sync failed
    pause
    exit /b 1
)
echo   Python deps ready

echo.
echo [2/3] Checking frontend dependencies...
if not exist "web_reader\node_modules" (
    echo   Installing frontend dependencies...
    cd web_reader
    call npm install
    if %errorlevel% neq 0 (
        echo ERROR: npm install failed
        cd ..
        pause
        exit /b 1
    )
    cd ..
)
echo   Frontend deps ready

echo.
echo [3/3] Starting services...
echo.

:: Start backend
start "VoiceNovel-Backend" cmd /c "cd /d %~dp0 && uv run python -m vn_server --host 127.0.0.1 --port 5000 && pause"

:: Start frontend
start "VoiceNovel-Frontend" cmd /c "cd /d %~dp0\web_reader && npm run dev && pause"

echo ========================================
echo   VoiceNovel Started!
echo   Frontend: http://localhost:3000
echo   Backend:  http://localhost:5000
echo   API docs: http://localhost:5000/docs
echo ========================================
echo.
echo   Close each window to stop its service.
echo   Press any key to close this window...
pause >nul
