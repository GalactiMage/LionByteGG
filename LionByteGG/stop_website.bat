@echo off
title LionByteGG Dashboard - Stop
color 0B
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBYTEGG DASHBOARD  -  STOP                 ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping Web Dashboard...
taskkill /F /FI "WINDOWTITLE eq LionByteGG Dashboard*" >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%web%%run.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   Web Dashboard stopped.                         ^|
echo   +-------------------------------------------------+
echo.
pause
