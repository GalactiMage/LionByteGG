@echo off
title LionByteGG Suite Launcher
color 0E
echo ============================================
echo      LionByteGG Full Suite Launcher
echo ============================================
echo.
echo  This will start:
echo    1. Master Terminal (System Monitor)
echo    2. LionByteGG Discord Bot
echo    3. LionShiftGG Discord Bot
echo    4. LionBeatsGG Music Bot (Lavalink + Bot)
echo    5. BoilerCraftGG Minecraft Bot
echo    6. Web Dashboard
echo.
echo ============================================
echo.
cd /d "%~dp0"

:: Start the Master Terminal FIRST (fullscreen, always on top)
echo [1/6] Starting Master Terminal...
start "LIONBYTE Master Terminal" cmd /k "cd /d "%~dp0" && python master_terminal.py"

:: Wait a moment for terminal to initialize
timeout /t 2 /nobreak >nul

:: Start LionByteGG bot in a new window
echo [2/6] Starting LionByteGG Bot...
start "LionByteGG Bot" cmd /k "cd /d "%~dp0" && color 0A && echo LionByteGG Bot Starting... && python "%~dp0main.py""

:: Wait a moment
timeout /t 2 /nobreak >nul

:: Start LionShiftGG bot in a new window
echo [3/6] Starting LionShiftGG Bot...
start "LionShiftGG Bot" cmd /k "cd /d "%~dp0..\LionShiftGG" && set LIONSHIFT_BOT=1 && color 0D && echo LionShiftGG Bot Starting... && python "%~dp0..\LionShiftGG\main.py""

:: Wait a moment for bots to initialize
timeout /t 2 /nobreak >nul

:: Start LionBeatsGG bot (Lavalink + Bot)
echo [4/6] Starting LionBeatsGG Music Bot...
start "LionBeatsGG Launcher" cmd /k "cd /d "%~dp0..\LionBeatsGG" && call start-all.bat"

:: Wait a moment for music bot to initialize
timeout /t 2 /nobreak >nul

:: Start BoilerCraftGG bot in a new window
echo [5/6] Starting BoilerCraftGG Bot...
start "BoilerCraftGG Bot" cmd /k "cd /d "%~dp0..\BoilerCraftGG" && color 0C && echo BoilerCraftGG Bot Starting... && python "%~dp0..\BoilerCraftGG\bot.py""

:: Wait a moment for bot to initialize
timeout /t 2 /nobreak >nul

:: Start the website in a new window
echo [6/6] Starting Web Dashboard...
start "LionByteGG Dashboard" cmd /k "cd /d "%~dp0web" && color 0B && echo Web Dashboard Starting... && python "%~dp0web\run.py""

echo.
echo ============================================
echo  All services are starting in separate windows!
echo ============================================
echo.
echo  - Master Terminal (System Monitor - Fullscreen)
echo  - LionByteGG Bot (Green window)
echo  - LionShiftGG Bot (Purple window)
echo  - LionBeatsGG Bot (Lavalink + Music Bot)
echo  - BoilerCraftGG Bot (Red window)
echo  - Web Dashboard (Cyan window)
echo.
echo You can close this launcher window.
echo.
timeout /t 5
