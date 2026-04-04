@echo off
title LionShiftGG Bot Restart
color 0D
echo ============================================
echo      LionShiftGG Bot Restart
echo ============================================
echo.
echo Stopping any running LionShiftGG instances...
taskkill /f /fi "WINDOWTITLE eq LionShiftGG*" >nul 2>&1
timeout /t 2 /nobreak >nul
echo.
echo Starting LionShiftGG Bot...
echo.
cd /d "%~dp0"
python main.py
pause
