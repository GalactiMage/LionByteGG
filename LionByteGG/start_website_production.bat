@echo off
title LionByteGG Web Dashboard - PRODUCTION
color 0A

echo ============================================
echo    LionByteGG Web Dashboard - PRODUCTION
echo ============================================
echo.

cd /d "%~dp0"

:: Set production environment
set FLASK_ENV=production
set FLASK_DEBUG=false

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Check for waitress (production server)
pip show waitress >nul 2>&1
if errorlevel 1 (
    echo Installing production server (waitress)...
    pip install waitress -q
)

:: Install other dependencies
cd web
pip install -r requirements.txt -q

echo.
echo Starting Production Server...
echo.
echo ============================================
echo PRODUCTION MODE - Using Waitress WSGI Server
echo This is more stable for daily use.
echo ============================================
echo.
echo Press CTRL+C to stop the server.
echo.

python run.py --production

pause
