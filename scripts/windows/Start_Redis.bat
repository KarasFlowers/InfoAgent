@echo off
setlocal
echo =========================================
echo       InfoAgent - Start Local Redis        
echo =========================================
echo.
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"
powershell -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\setup_redis.ps1"
echo.
pause
endlocal
