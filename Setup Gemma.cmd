@echo off
setlocal
cd /d "%~dp0"
echo Installing the optional local Gemma runtime. Models are chosen in the app.
echo This uses an embedded NVIDIA CUDA runtime. Sugoi remains available.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Gemma
if errorlevel 1 goto failed
if exist ".venv-gpu\ocr-verified" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Gpu -Gemma
    if errorlevel 1 goto failed
)
echo Runtime ready. Open DanteJP, then Models to download Gemma if needed.
echo Select Gemma in Translation backend. The app asks before first-use GPU preparation.
pause
exit /b 0
:failed
echo Gemma setup failed. Review the error above. Sugoi remains available.
pause
exit /b 1
