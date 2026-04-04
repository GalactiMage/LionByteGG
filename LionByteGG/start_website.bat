@echo off
title LionByteGG Web Dashboard
color 0B

echo ============================================
echo        LionByteGG Web Dashboard
echo ============================================
echo.

cd /d "%~dp0"

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Check if virtual environment exists, if not create one
if not exist "web\venv" (
    echo Creating virtual environment...
    cd web
    python -m venv venv
    cd ..
)

:: Activate virtual environment and install dependencies
echo Checking dependencies...
cd web
call venv\Scripts\activate.bat 2>nul || (
    echo Installing dependencies globally...
    pip install -r requirements.txt -q
    goto :start_server
)

pip install -r requirements.txt -q

:start_server
echo.
echo Starting Web Dashboard...
echo.
echo Press CTRL+C to stop the server.
echo.

:: Run in development mode by default
python run.py

pause
