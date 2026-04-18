@echo off
echo =========================================
echo       InfoAgent - Start Local Redis        
echo =========================================
echo.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File ".\setup_redis.ps1"
echo.
pause
