@echo off
setlocal
echo =========================================
echo       InfoAgent - Daily Tech Summary       
echo =========================================
echo.

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

IF NOT EXIST "%PROJECT_ROOT%\venv\Scripts\Activate.ps1" (
    echo [ERROR] Virtual environment not found in %PROJECT_ROOT%\venv
    echo Please make sure you have run the setup commands.
    pause
    exit /b 1
)

echo Activating virtual environment and running InfoAgent...
echo.
"%PROJECT_ROOT%\venv\Scripts\python.exe" "%PROJECT_ROOT%\scripts\cli.py"


echo.
pause
endlocal
