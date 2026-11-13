@echo off
setlocal
cd /d "%~dp0"
echo Installing optional NVIDIA OCR libraries into .venv-gpu.
echo This requires roughly 1.8 GB of downloads. CPU setup remains available.
if exist ".venv-gpu\ocr-verified" del ".venv-gpu\ocr-verified"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup.ps1" -Gpu
if errorlevel 1 (
  echo GPU setup failed. The CPU launcher remains available.
  pause
  exit /b 1
)
echo Verifying real OCR and preparing the local CUDA cache. First use can take about a minute.
".venv-gpu\Scripts\python.exe" tools\verify_ocr.py --device cuda
if errorlevel 1 (
  echo GPU verification failed. Use Run DanteJP CPU.cmd or choose CPU OCR.
  pause
  exit /b 1
)
echo verified> ".venv-gpu\ocr-verified"
echo GPU OCR verified. Use Run DanteJP.cmd.
pause
