@echo off
title Master Terminal - Stop
color 0E
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   MASTER TERMINAL  -  STOP                      ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping Master Terminal...
taskkill /F /FI "WINDOWTITLE eq LIONBYTE Master Terminal*" >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%master_terminal.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   Master Terminal stopped.                       ^|
echo   +-------------------------------------------------+
echo.
pause
