@echo off
title DanteJP - CPU
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\jp-overlay.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -m jp_overlay
