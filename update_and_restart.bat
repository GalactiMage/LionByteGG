@echo off
echo ============================================
echo   LionByteGG System - Update and Restart
echo   This ONLY updates code files.
echo   Student data, databases, and .env files
echo   will NOT be touched.
echo ============================================
echo.

cd /d "%~dp0"

echo Pulling latest code from GitHub...
git pull origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Git pull failed. Check your internet connection
    echo or resolve any merge conflicts before retrying.
    pause
    exit /b 1
)

echo.
echo Code updated. Restarting bots...
echo.

REM Kill existing bot processes gracefully
echo Stopping running bots...
taskkill /f /im python.exe 2>nul
taskkill /f /im node.exe 2>nul
taskkill /f /im java.exe 2>nul
timeout /t 3 /nobreak >nul

echo Starting LionByteGG...
start "" cmd /c "cd /d %~dp0LionByteGG && start_bot.bat"
timeout /t 2 /nobreak >nul

echo Starting LionByteGG Website...
start "" cmd /c "cd /d %~dp0LionByteGG && start_website.bat"
timeout /t 2 /nobreak >nul

echo Starting LionShiftGG...
start "" cmd /c "cd /d %~dp0LionShiftGG && start_bot.bat"
timeout /t 2 /nobreak >nul

echo Starting BoilerCraftGG...
start "" cmd /c "cd /d %~dp0BoilerCraftGG && start.bat"
timeout /t 2 /nobreak >nul

echo Starting LionBeatsGG...
start "" cmd /c "cd /d %~dp0LionBeatsGG && start-all.bat"

echo.
echo ============================================
echo   Update complete! All bots restarting.
echo   Data files were NOT modified.
echo ============================================
echo.
pause
