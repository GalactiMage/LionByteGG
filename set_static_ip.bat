@echo off
REM Set Ethernet to static IP 205.215.119.211
netsh interface ip set address "Ethernet" static 205.215.119.211 255.255.255.0 205.215.119.254
netsh interface ip set dns "Ethernet" static 205.215.126.28
netsh interface ip add dns "Ethernet" 205.215.126.30 index=2
echo Static IP set to 205.215.119.211
