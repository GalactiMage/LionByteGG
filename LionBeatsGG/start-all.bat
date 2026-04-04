@echo off
title LionBeatsGG Launcher
echo ========================================
echo   LionBeatsGG Bot Launcher
echo ========================================
echo.

echo Starting Lavalink Server...
start "Lavalink Server" cmd /k "cd /d "%~dp0lavalink" && java -jar Lavalink.jar"

echo Waiting 5 seconds for Lavalink to start...
timeout /t 5 /nobreak >nul

echo Starting Discord Bot...
start "LionBeatsGG Bot" cmd /k "cd /d "%~dp0bot" && node src/index.js"

echo.
echo ========================================
echo   Both services started!
echo ========================================
echo.
echo You can close this window.
pause
