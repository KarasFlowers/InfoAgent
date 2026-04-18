@echo off
echo =========================================
echo       InfoAgent - Daily Tech Summary       
echo =========================================
echo.

cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\Activate.ps1" (
    echo [ERROR] Virtual environment not found in %~dp0venv
    echo Please make sure you have run the setup commands.
    pause
    exit /b 1
)

echo Activating virtual environment and running InfoAgent...
echo.
"%~dp0venv\Scripts\python.exe" cli.py


echo.
pause
