DanteJP - Windows x64

1. Extract this entire ZIP to a folder. Do not run it inside the ZIP preview.
2. Double-click DanteJP.exe. Keep the _internal folder beside the EXE.
3. Open Settings > Models & runtime > Models. Download MeikiOCR and Sugoi V4
   (CPU) or Gemma 4 E2B (GPU). No models download until you ask.
4. For Gemma/GPU OCR, use the Acceleration tab to install the recommended
   NVIDIA or AMD runtime, then use Restart now. No Python installation,
   setup scripts, system CUDA toolkit or administrator rights are required.
   A compatible graphics driver must already be installed.

NVIDIA: CUDA OCR + Gemma. AMD: Vulkan Gemma + CPU OCR; Radeon testing is pending.
NVIDIA OCR and Gemma share CUDA 13 libraries: about 1.29 GB of NVIDIA/ONNX downloads,
plus other app dependencies. Model downloads are separate. If upgrading from the
older dual-CUDA package, install the new runtime in Acceleration and restart once;
your existing models are reused.
Capture works without models. Recognition/translation need their respective downloads.
Gemma asks before first-use preparation. Inference is local after setup.

Downloads and settings are kept per Windows user at:
  %LOCALAPPDATA%\DanteJP
  models\       OCR and translation weights
  data\         preferences, translation cache, preparation/runtime receipts
  .runtimes\    optional CPU/GPU environments
  .python\      private Python used by those optional environments
  .uv-cache\    dependency download cache
  logs\         diagnostic logs (no captured game images)

Updating: close DanteJP, extract a new version into a new folder, and run its EXE.
Your AppData is reused. If dependencies changed, the app may ask for runtime setup again.
Moving the extracted app folder does not move or delete your downloads.
Uninstall: close the app and delete its extracted folder. Optionally delete the
AppData\Local\DanteJP folder too if you want to remove all models and settings.

This is a portable folder, not an installer or a single self-contained EXE.
The executable is unsigned. Only run a package obtained from a source you trust.
Use a borderless/windowed game. Compatibility with a specific game/anti-cheat is not guaranteed.
See THIRD-PARTY.txt for bundled library notices. No model weights are bundled.
