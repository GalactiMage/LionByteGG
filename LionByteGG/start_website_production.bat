@echo off
title LionByteGG Web Dashboard - PRODUCTION
color 0B
cls
echo.
echo  =============================================
echo  ^|                                           ^|
echo  ^|     LIONBYTEGG WEB DASHBOARD               ^|
echo  ^|     PRODUCTION MODE                        ^|
echo  ^|     Using Waitress WSGI Server             ^|
echo  ^|                                           ^|
echo  =============================================
echo.

cd /d "%~dp0"

set FLASK_ENV=production
set FLASK_DEBUG=false

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python is not installed or not in PATH!
    pause
    exit /b 1
)

pip show waitress >nul 2>&1
if errorlevel 1 (
    echo  Installing production server (waitress)...
    pip install waitress -q
)

cd web
pip install -r requirements.txt -q

echo.
echo  Starting Production Server...
echo  Press CTRL+C to stop the server.
echo.
python run.py --production
echo.
echo  Dashboard has stopped. Press any key to exit.
pause >nul
