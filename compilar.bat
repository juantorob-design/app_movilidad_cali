@echo off
title Compilador Automático
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "build_app.ps1"
pause