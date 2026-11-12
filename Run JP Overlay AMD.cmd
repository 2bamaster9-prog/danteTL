@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv-amd\Scripts\jp-overlay.exe" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Amd
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" "%~dp0.venv-amd\Scripts\pythonw.exe" -m jp_overlay
