@echo off
title LionShiftGG Discord Bot
color 0D
cls
echo.
echo   ::::::::: :::    ::: ::::::::::: ::::::::::::::::::::::
echo   :+:    :+::+:    :+:    :+:     :+:        :+:    :+:
echo   +:+    +:++:+    +:+    +:+     +:+        +:+    +:+
echo   +#++:++#+ +#++:++#++    +#+     :#::+::#   +#+    +:+
echo          +#+#+#    #+#    #+#     #+#        #+#    #+#
echo   #+#    #+##+#    #+#    #+#     #+#        #+#    #+#
echo    #######  ###    ### ########### ###        ########
echo.
echo   +-------------------------------------------------+
echo   ^|   LIONSHIFTGG DISCORD BOT                       ^|
echo   ^|   Shift Management System for PNW eSports       ^|
echo   +-------------------------------------------------+
echo.
cd /d "%~dp0"
echo   [*] Initializing LionShiftGG Bot...
echo.
python main.py
echo.
echo   [!] Bot process has exited.
echo       Press any key to close this window.
pause >nul
