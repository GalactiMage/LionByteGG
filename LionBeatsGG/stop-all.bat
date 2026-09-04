@echo off
title LionBeatsGG - Stop
color 09
cls
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBEATSGG  -  STOP                          ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo  Stopping LionBeatsGG Bot...
taskkill /f /fi "WINDOWTITLE eq LionBeatsGG Bot*" >nul 2>&1
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%index.js%%' and name='node.exe'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /f /pid %%i >nul 2>&1
)
echo.

echo  Stopping Lavalink Server...
taskkill /f /fi "WINDOWTITLE eq Lavalink*" >nul 2>&1
taskkill /f /im java.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo   +-------------------------------------------------+
echo   ^|   LionBeatsGG stopped.                           ^|
echo   ^|     - Lavalink Server stopped                    ^|
echo   ^|     - Music Bot stopped                          ^|
echo   +-------------------------------------------------+
echo.
pause
