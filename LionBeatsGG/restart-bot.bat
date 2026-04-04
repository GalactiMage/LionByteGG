@echo off
title LionBeatsGG Bot Restart
echo ========================================
echo   LionBeatsGG Bot Restart
echo ========================================
echo.

echo Killing any existing bot processes...
taskkill /f /fi "WINDOWTITLE eq LionBeatsGG Bot" >nul 2>&1

echo Killing any node processes running index.js...
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%index.js%%' and name='node.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%i >nul 2>&1
)

echo Waiting 2 seconds...
timeout /t 2 /nobreak >nul

echo Starting Discord Bot...
start "LionBeatsGG Bot" cmd /k "cd /d S:\LionBeatsGG\bot && node src/index.js"

echo.
echo ========================================
echo   Bot restarted successfully!
echo ========================================
echo.
echo You can close this window.
timeout /t 3 >nul
