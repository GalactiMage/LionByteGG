@echo off
title BoilerCraftGG Discord Bot
color 0C
cls
echo.
echo   :::::::::   ::::::::  ::::::::::: :::        :::::::::: :::::::::
echo   :+:    :+: :+:    :+:    :+:     :+:        :+:        :+:    :+:
echo   +:+    +:+ +:+    +:+    +:+     +:+        +:+        +:+    +:+
echo   +#++:++#+  +#+    +:+    +#+     +#+        +#++:++#   +#++:++#:
echo   +#+    +#+ +#+    +#+    +#+     +#+        +#+        +#+    +#+
echo   #+#    #+# #+#    #+#    #+#     #+#        #+#        #+#    #+#
echo    #######    ########  ########### ########## ########## ###    ###
echo.
echo   +-------------------------------------------------+
echo   ^|   BOILERCRAFTGG DISCORD BOT                     ^|
echo   ^|   Purdue Network Minecraft Server               ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"
echo   [*] Initializing BoilerCraftGG Bot...
echo.
python bot.py
echo.
echo   [!] Bot process has exited.
echo       Press any key to close this window.
pause >nul
