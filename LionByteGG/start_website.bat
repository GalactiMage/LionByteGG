@echo off
title LionByteGG Web Dashboard
color 0B
cls
echo.
echo   :::       ::: :::::::::: :::::::::
echo   :+:       :+: :+:        :+:    :+:
echo   +:+       +:+ +:+        +:+    +:+
echo   +#+  +:+  +#+ +#++:++#   +#++:++#+
echo   +#+ +#+#+ +#+ +#+        +#+    +#+
echo    #+#+# #+#+#  #+#        #+#    #+#
echo     ###   ###   ########## #########
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBYTEGG WEB DASHBOARD                      ^|
echo   ^|   Flask Web Interface + API                     ^|
echo   +-------------------------------------------------+
echo.

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python is not installed or not in PATH!
    echo           Please install Python 3.10+
    pause
    exit /b 1
)

if not exist "web\venv" (
    echo   [*] Creating virtual environment...
    cd web
    python -m venv venv
    cd ..
)

echo   [*] Checking dependencies...
cd web
call venv\Scripts\activate.bat 2>nul || (
    pip install -r requirements.txt -q
    goto :start_server
)
pip install -r requirements.txt -q

:start_server
echo.
echo   [*] Starting Web Dashboard...
echo       Press CTRL+C to stop the server.
echo.
python run.py
echo.
echo   [!] Dashboard has stopped.
echo       Press any key to close this window.
pause >nul
