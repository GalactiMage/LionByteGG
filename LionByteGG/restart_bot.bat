@echo off
title LionByteGG Bot Restart
color 0C
echo ============================================
echo       LionByteGG Bot Restart
echo ============================================
echo.
cd /d "%~dp0"

echo Stopping existing bot processes...
taskkill /F /FI "WINDOWTITLE eq LionByteGG Bot*" >nul 2>&1

:: Also try to kill by PID if available
if exist "data\bot.pid" (
    set /p BOT_PID=<data\bot.pid
    taskkill /F /PID %BOT_PID% >nul 2>&1
    del "data\bot.pid" >nul 2>&1
)

:: Kill any python process running main.py (be careful with this)
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%main.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

echo.
echo Starting Discord Bot...
echo.
start "LionByteGG Bot" cmd /k "cd /d "%~dp0" && python main.py"

echo.
echo Bot has been restarted!
echo.
timeout /t 3
