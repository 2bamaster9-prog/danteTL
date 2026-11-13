@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\setup_models.py" --translation
if errorlevel 1 (
    pause
    exit /b 1
)
echo Translation setup complete. Open Run DanteJP.cmd.
pause
