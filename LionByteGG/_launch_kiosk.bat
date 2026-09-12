@echo off
setlocal EnableExtensions
REM ============================================================================
REM  KIOSK BROWSER LAUNCHER  (Chrome --kiosk = a TRUE locked fullscreen)
REM  --------------------------------------------------------------------------
REM  This opens the kiosk page in Chrome's native kiosk mode: no address bar,
REM  no tabs, NO X / minimize / close buttons, and no way to exit fullscreen.
REM  That's the only way to make "they can't leave the kiosk" actually real --
REM  the in-page lockdown (beep + snap-back) is just a backup on top of this.
REM
REM  Called by the per-kiosk shortcuts (Launch Kiosk 1/2/Demo). Arg 1 = the
REM  kiosk path segment: 1, 2, or demo.
REM
REM  If the kiosk laptop is a DIFFERENT PC than the one running the web server,
REM  set KIOSK_SERVER before calling, e.g.  set KIOSK_SERVER=192.168.1.50:5000
REM ============================================================================

if "%KIOSK_SERVER%"=="" set "KIOSK_SERVER=127.0.0.1:5000"
set "KIOSK_PATH=%~1"
if "%KIOSK_PATH%"=="" set "KIOSK_PATH=1"
set "KIOSK_URL=http://%KIOSK_SERVER%/arena/kiosk/%KIOSK_PATH%"

REM ---- Locate Chrome (preferred); fall back to Edge (also Chromium, supports --kiosk) ----
set "BROWSER="
for %%P in (
  "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
  "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
  "%LocalAppData%\Google\Chrome\Application\chrome.exe"
) do if not defined BROWSER if exist %%~P set "BROWSER=%%~P"
if not defined BROWSER (
  for %%P in (
    "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
    "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
  ) do if not defined BROWSER if exist %%~P set "BROWSER=%%~P"
)
if not defined BROWSER (
  echo.
  echo   Could not find Google Chrome or Microsoft Edge.
  echo   Install Google Chrome, then run this again.
  echo.
  pause
  exit /b 1
)

REM ---- Isolated profile per kiosk so it never inherits stray tabs / settings ----
set "PROFILE=%~dp0.kiosk-profile-%KIOSK_PATH%"

echo Launching kiosk %KIOSK_PATH% at %KIOSK_URL%
echo Browser: %BROWSER%

start "" "%BROWSER%" ^
  --kiosk ^
  --start-fullscreen ^
  --user-data-dir="%PROFILE%" ^
  --no-first-run ^
  --no-default-browser-check ^
  --noerrdialogs ^
  --disable-infobars ^
  --disable-session-crashed-bubble ^
  --disable-features=TranslateUI,Translate,AutofillServerCommunication,DevToolsConsoleLogging ^
  --disable-pinch ^
  --overscroll-history-navigation=0 ^
  --disable-dev-tools ^
  --disable-extensions ^
  --disable-plugins-discovery ^
  --disable-background-networking ^
  --disable-component-update ^
  --disable-translate ^
  --disable-save-password-bubble ^
  --disable-notifications ^
  --disable-popup-blocking ^
  --no-context-menu ^
  --autoplay-policy=no-user-gesture-required ^
  --check-for-update-interval=31536000 ^
  --password-store=basic ^
  "%KIOSK_URL%"

endlocal
exit /b 0
