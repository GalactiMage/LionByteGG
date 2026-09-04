@echo off
title LionByteGG Bot - Stop
color 0A
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBYTEGG BOT  -  STOP                       ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping LionByteGG Bot...
taskkill /F /FI "WINDOWTITLE eq LionByteGG Bot*" >nul 2>&1
if exist "data\bot.pid" (
    set /p BOT_PID=<data\bot.pid
    taskkill /F /PID %BOT_PID% >nul 2>&1
    del "data\bot.pid" >nul 2>&1
)
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%main.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   LionByteGG Bot stopped.                       ^|
echo   +-------------------------------------------------+
echo.
pause
