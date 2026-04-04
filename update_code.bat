@echo off
echo ============================================
echo   LionByteGG System - Code Update
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
echo ============================================
echo   Code updated successfully!
echo   Your data files, databases, and .env
echo   files were NOT modified.
echo ============================================
echo.
echo To apply changes, restart the bots using:
echo   - LionByteGG\start_bot.bat
echo   - LionByteGG\start_website.bat
echo   - LionShiftGG\start_bot.bat
echo   - BoilerCraftGG\start.bat
echo   - LionBeatsGG\start-all.bat
echo.
echo Or use update_and_restart.bat to do both.
echo.
pause
