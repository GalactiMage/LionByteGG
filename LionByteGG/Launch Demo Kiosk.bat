@echo off
REM One-click launcher for the Demo/Admin Kiosk in locked fullscreen kiosk mode.
REM If this laptop is not the web-server PC, uncomment + edit the line below:
REM set KIOSK_SERVER=192.168.1.50:5000
call "%~dp0_launch_kiosk.bat" demo
