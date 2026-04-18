@echo off
echo =========================================
echo    InfoAgent - Web Dashboard Launcher    
echo =========================================
echo.

cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\Activate.ps1" (
    echo [ERROR] Virtual environment not found.
    pause
    exit /b 1
)

echo Starting Backend Server...
start /b powershell.exe -ExecutionPolicy Bypass -Command "& '.\venv\Scripts\Activate.ps1'; uvicorn main:app"

echo Waiting for server to initialize...
timeout /t 5 /nobreak > nul

echo Opening Dashboard in your browser...
start http://127.0.0.1:8000

echo.
echo Dashboard is now running at http://127.0.0.1:8000
echo Close this window to stop the server.
echo.
pause
taskkill /f /im python.exe > nul 2>&1
