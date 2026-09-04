@echo off
title LionShiftGG Bot - Stop
color 0D
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONSHIFTGG BOT  -  STOP                      ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping LionShiftGG Bot...
taskkill /f /fi "WINDOWTITLE eq LionShiftGG*" >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%LionShiftGG%%main.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   LionShiftGG Bot stopped.                       ^|
echo   +-------------------------------------------------+
echo.
pause
