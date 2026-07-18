@echo off
setlocal

cd /d "%~dp0"
title Bolao - Iniciador

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_bolao.ps1"

if errorlevel 1 (
    echo.
    echo O iniciador terminou com erro.
    pause
)

endlocal
