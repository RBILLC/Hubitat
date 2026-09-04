@echo off
rem Starts the MoonHalo Bridge detached with the windowless launcher, then exits.
cd /d "%~dp0"
start "" /B pyw -m moonhalo_bridge serve %*
exit /b 0
