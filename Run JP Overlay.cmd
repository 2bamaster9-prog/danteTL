@echo off
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
if exist ".venv-gpu\ocr-verified" if exist ".venv-gpu\Scripts\jp-overlay.exe" (
  start "" "%~dp0.venv-gpu\Scripts\pythonw.exe" -m jp_overlay
  exit /b 0
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -m jp_overlay
