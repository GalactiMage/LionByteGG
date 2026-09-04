@echo off
setlocal

REM ===== Single-instance guard: don't launch the suite twice =====
REM If the Web Dashboard (port 5000) is already listening, the services are up.
netstat -an | findstr /R /C:":5000 .*LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    mode con cols=74 lines=14 >nul 2>&1
    color 0E
    cls
    echo.
    echo   ==================================================================
    echo.
    echo      LionByte services are ALREADY RUNNING.
    echo.
    echo      This launcher will not start them a second time.
    echo      To restart, close the existing service windows
    echo      ^(or the Master Terminal^) first, then run this again.
    echo.
    echo   ==================================================================
    echo.
    timeout /t 6 >nul
    exit /b 1
)

if not "%~1"=="--max" (
    start "LionByte" /max cmd /c ""%~f0" --max"
    exit /b
)

mode con cols=110 lines=48 >nul 2>&1
color 0F
title  LionByte  --  Booting
cls

python "%~dp0intro_animation.py"

cls
color 0F
title  LionByte  --  Service Launcher

echo.
echo  +======================================================================+
echo  ^|                                                                      ^|
echo  ^|   LIONBYTE MASTER SUITE                             LionByteGG      ^|
echo  ^|   Service Launcher                                   v2026           ^|
echo  ^|                                                                      ^|
echo  +======================================================================+
echo.
echo   Each service starts minimized. Master Terminal opens last.
echo.
echo  +----------------------------------------------------------------------+
echo.

echo   [1/6]  LionByteGG Bot              (Main Discord Bot)
start "LionByteGG Bot"    /D "%~dp0"                        /min cmd /k "color 0A && python main.py"
timeout /t 2 /nobreak >nul
echo          [ STARTED ]  minimized
echo.

echo   [2/6]  LionShiftGG Bot             (Shift Management)
start "LionShiftGG Bot"   /D "%~dp0..\LionShiftGG"          /min cmd /k "color 0D && python main.py"
timeout /t 2 /nobreak >nul
echo          [ STARTED ]  minimized
echo.

echo   [3/6]  BoilerCraftGG Bot           (Minecraft Community)
start "BoilerCraftGG Bot" /D "%~dp0..\BoilerCraftGG"         /min cmd /k "color 04 && python bot.py"
timeout /t 2 /nobreak >nul
echo          [ STARTED ]  minimized
echo.

echo   [4/6]  Lavalink Server             (Audio Backend)
start "Lavalink"          /D "%~dp0..\LionBeatsGG\lavalink"  /min cmd /k "color 07 && java -jar Lavalink.jar"
echo          [ STARTED ]  initializing  --  waiting 7 seconds...
timeout /t 7 /nobreak >nul
echo          [ READY   ]  Lavalink is up
echo.

echo   [5/6]  LionBeatsGG Bot             (Music Bot)
start "LionBeatsGG Bot"   /D "%~dp0..\LionBeatsGG\bot"       /min cmd /k "color 0B && node src/index.js"
timeout /t 2 /nobreak >nul
echo          [ STARTED ]  minimized
echo.

echo   [6/6]  Web Dashboard               (Admin Panel)
start "Web Dashboard"     /D "%~dp0web"                       /min cmd /k "color 09 && python run.py --production"
timeout /t 2 /nobreak >nul
echo          [ STARTED ]  minimized
echo.

echo  +----------------------------------------------------------------------+
echo.
echo   All 6 services are running.
echo.
echo   Opening Master Terminal in 3 seconds...
echo.
echo  +======================================================================+
echo.
timeout /t 3 /nobreak >nul

start "" /d "%~dp0" pythonw master_terminal.py
timeout /t 2 /nobreak >nul
exit