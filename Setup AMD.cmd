@echo off
setlocal
cd /d "%~dp0"
echo Installing AMD-compatible Vulkan translation and DirectML OCR runtimes.
echo Models are downloaded separately from Models in the app. No CUDA toolkit is needed.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Amd
if errorlevel 1 (
  echo Setup failed. Review the error above.
  pause
  exit /b 1
)
echo Setup complete. Open Run DanteJP AMD.cmd, then Models to download a model.
echo Radeon hardware validation is still needed. CPU OCR and Sugoi remain available.
pause
