@echo off
cd /d "%~dp0"
py -m moonhalo_bridge serve %*
