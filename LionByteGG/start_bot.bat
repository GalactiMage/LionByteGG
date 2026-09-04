@echo off
title LionByteGG Discord Bot
color 0A
cls
echo.
echo   :::        :::::::::::  ::::::::  ::::    :::
echo   :+:            :+:     :+:    :+: :+:+:   :+:
echo   +:+            +:+     +:+    +:+ :+:+:+  +:+
echo   +#+            +#+     +#+    +:+ +#+ +:+ +#+
echo   +#+            +#+     +#+    +#+ +#+  +#+#+#
echo   #+#            #+#     #+#    #+# #+#   #+#+#
echo   ##########     ###      ########  ###    ####
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONBYTEGG DISCORD BOT                        ^|
echo   ^|   Main Bot for PNW eSports Club                 ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"
echo   [*] Initializing LionByteGG Bot...
echo.
python main.py
echo.
echo   [!] Bot process has exited.
echo       Press any key to close this window.
pause >nul
