@echo off
title LionBeatsGG Bot (auto-restart)
cd /d "%~dp0"

:loop
echo.
echo [%date% %time%] Starting LionBeatsGG bot...
node src/index.js

echo.
echo [%date% %time%] Bot exited (code %errorlevel%). Restarting in 5 seconds...
echo Press Ctrl+C now to stop for good.
timeout /t 5 >nul
goto loop
