@echo off
title LionBeatsGG Launcher
color 09
cls
echo.
echo   :::::::::  ::::::::::    :::    ::::::::::: ::::::::
echo   :+:    :+: :+:          :+:+:      :+:    :+:    :+:
echo   +:+    +:+ +:+         +:+ +:+     +:+    +:+
echo   +#++:++#+  +#++:++#   +#+   +#+    +#+    +#++:++#++
echo   +#+    +#+ +#+        +#+###### #   +#+           +#+
echo   #+#    #+# #+#        #+#     #+#   #+#    #+#    #+#
echo   #########  ########## ###     ###   ###     ########
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBEATSGG MUSIC BOT                         ^|
echo   ^|   Lavalink Server + Discord Bot                 ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"

echo   [1/2] Starting Lavalink Server...
start "Lavalink Server" cmd /k "cd /d "%~dp0lavalink" && color 07 && java -jar Lavalink.jar"
echo         Waiting 5s for Lavalink to initialize...
timeout /t 5 /nobreak >nul
echo         Done.
echo.

echo   [2/2] Starting LionBeatsGG Bot (auto-restart enabled)...
start "LionBeatsGG Bot" cmd /k "cd /d "%~dp0bot" && color 09 && call run-bot.bat"
echo         Done.

echo.
echo   +-------------------------------------------------+
echo   ^|   Both services launched!                       ^|
echo   ^|     - Lavalink Server  [White window]           ^|
echo   ^|     - Music Bot        [Blue window]            ^|
echo   +-------------------------------------------------+
echo.
echo   You can safely close this launcher window.
pause
