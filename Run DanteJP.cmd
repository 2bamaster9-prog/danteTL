@echo off
title DanteJP
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\jp-overlay.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
  if errorlevel 1 (
    echo Setup failed. Please review the message above.
    pause
    exit /b 1
  )
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0tools\launch.py" %*
