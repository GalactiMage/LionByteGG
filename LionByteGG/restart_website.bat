@echo off
title LionByteGG Website Restart
color 0D
echo ============================================
echo      LionByteGG Website Restart
echo ============================================
echo.
cd /d "%~dp0"

echo Stopping existing website processes...
taskkill /F /FI "WINDOWTITLE eq LionByteGG Dashboard*" >nul 2>&1

:: Kill any python process running run.py in web folder
for /f "tokens=2" %%a in ('wmic process where "commandline like '%%web%%run.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: Also try common Flask ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

echo.
echo Starting Web Dashboard...
echo.
start "LionByteGG Dashboard" cmd /k "cd /d "%~dp0web" && python run.py"

echo.
echo Website has been restarted!
echo.
timeout /t 3
