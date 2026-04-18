@echo off
setlocal
echo =========================================
echo    InfoAgent - Web Dashboard Launcher    
echo =========================================
echo.

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

IF NOT EXIST "%PROJECT_ROOT%\venv\Scripts\Activate.ps1" (
    echo [ERROR] Virtual environment not found.
    pause
    exit /b 1
)

echo Starting Backend Server...
start "InfoAgent Backend" powershell.exe -NoExit -ExecutionPolicy Bypass -Command "& '%PROJECT_ROOT%\venv\Scripts\Activate.ps1'; Set-Location '%PROJECT_ROOT%'; uvicorn main:app --reload"

echo Waiting for server to initialize...
timeout /t 5 /nobreak > nul

echo Opening Dashboard in your browser...
start http://127.0.0.1:8000

echo.
echo Dashboard is now running at http://127.0.0.1:8000
echo Close the "InfoAgent Backend" window to stop the server.
echo.
pause
endlocal
