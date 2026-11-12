@echo off
setlocal
cd /d "%~dp0"
echo Installing optional local Gemma 4 E2B QAT. Model download: 3.35 GB.
echo This uses an embedded NVIDIA CUDA runtime. Sugoi remains available.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Gemma
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\setup_models.py --gemma
if errorlevel 1 goto failed
if exist ".venv-gpu\ocr-verified" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Gpu -Gemma
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" tools\verify_translation.py --backend gemma
if errorlevel 1 goto failed
echo Gemma verified. Restart JP Overlay and select Gemma in Translation backend.
pause
exit /b 0
:failed
echo Gemma setup failed. Review the error above. Sugoi remains available.
pause
exit /b 1
