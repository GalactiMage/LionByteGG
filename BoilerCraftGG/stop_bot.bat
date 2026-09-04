@echo off
title BoilerCraftGG Bot - Stop
color 0C
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   BOILERCRAFTGG BOT  -  STOP                    ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping BoilerCraftGG Bot...
taskkill /f /fi "WINDOWTITLE eq BoilerCraftGG*" >nul 2>&1
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%BoilerCraftGG%%bot.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   BoilerCraftGG Bot stopped.                     ^|
echo   +-------------------------------------------------+
echo.
pause
