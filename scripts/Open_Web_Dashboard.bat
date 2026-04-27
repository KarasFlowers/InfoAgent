@echo off
setlocal EnableExtensions
echo =========================================
echo    InfoAgent - Web Dashboard Launcher    
echo =========================================
echo.

REM Locate project root (one level up from scripts/)
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

REM --- 1) venv sanity check ---------------------------------------------
if not exist "%PROJECT_ROOT%\venv\Scripts\Activate.ps1" (
    echo [ERROR] Virtual environment not found at: %PROJECT_ROOT%\venv
    echo Please run:
    echo    python -m venv venv
    echo    venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM --- 2) port-in-use shortcut ------------------------------------------
netstat -ano | findstr /r /c:":8000 .*LISTENING" > nul 2>&1
if not errorlevel 1 (
    echo [INFO] Port 8000 is already in use. Opening the existing dashboard...
    start "" http://127.0.0.1:8000
    echo.
    pause
    exit /b 0
)

REM --- 3) Ensure Redis is running (idempotent) --------------------------
echo Ensuring local Redis is running...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\setup_redis.ps1" > nul 2>&1
if errorlevel 1 (
    echo [WARN] Redis setup script failed. The app will still run, but caching will be disabled.
)

REM --- 4) Start backend in a visible window -----------------------------
echo Starting InfoAgent backend...
start "InfoAgent Backend" powershell.exe -NoExit -ExecutionPolicy Bypass -Command ^
    "& '%PROJECT_ROOT%\venv\Scripts\Activate.ps1'; Set-Location '%PROJECT_ROOT%'; uvicorn main:app --reload"

REM --- 5) Poll /api/v1/ping until healthy (max ~30s) --------------------
echo Waiting for server to become healthy...
set /a _tries=0
:WAIT_LOOP
set /a _tries+=1
powershell.exe -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/v1/ping' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }" > nul 2>&1
if not errorlevel 1 goto :READY
if %_tries% GEQ 30 goto :TIMEOUT
timeout /t 1 /nobreak > nul
goto :WAIT_LOOP

:TIMEOUT
echo [WARN] Server did not respond within 30 seconds. Opening the URL anyway.
goto :LAUNCH

:READY
echo Server is ready.

:LAUNCH
echo Opening dashboard in your browser...
start "" http://127.0.0.1:8000

echo.
echo Dashboard: http://127.0.0.1:8000
echo Close the "InfoAgent Backend" window to stop the server.
echo.
pause
endlocal
