DanteJP - Windows x64

1. Extract this entire ZIP to a folder. Do not run it inside the ZIP preview.
2. Double-click DanteJP.exe. Keep the _internal folder beside the EXE.
3. MeikiOCR is included; Japanese text recognition works immediately on CPU.
   Follow the first-run Setup assistant to choose Sugoi V4
   (CPU) or Gemma 4 E2B (CPU or GPU), and review optional GPU support.
   Nothing downloads until you confirm. You can skip it and reopen
   Settings > Setup assistant, or use the Models and Acceleration tabs directly.
4. CPU support is included: Gemma works without installing a GPU runtime.
   For faster processing, optionally use the Acceleration tab to install
   NVIDIA GPU - CUDA or GPU - Vulkan, then use Restart now. No Python installation,
   setup scripts, system CUDA toolkit or administrator rights are required.
   A compatible graphics driver must already be installed.

Runtime setup shows the current stage plus a second bar for the current download,
with real received bytes and a percentage when the total is known. Private Python
preparation uses an activity indicator. Cancel/retry keeps verified files.

CPU: recognition and translation; larger language models may be slower.
NVIDIA GPU - CUDA: accelerates supported recognition and translation engines.
GPU - Vulkan: accelerates supported translation engines; OCR stays on CPU.
Vulkan inference on Radeon still needs testing. Models are selected separately.
NVIDIA OCR and Gemma share CUDA 13 libraries: about 1.29 GB of NVIDIA/ONNX downloads,
plus other app dependencies. Model downloads are separate. If upgrading from the
older dual-CUDA package, install the new runtime in Acceleration and restart once;
your existing models are reused.
Capture and recognition work without model downloads. Translation needs a chosen translator.
Settings > Models shows MeikiOCR as Included with app. Verify / repair restores
damaged or missing OCR files into AppData, reusing bundled files where possible.
Gemma asks before first-use preparation. Inference is local after setup.

Downloads and settings are kept per Windows user at:
  %LOCALAPPDATA%\DanteJP
  models\       translation weights and any repaired/downloaded OCR files
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
See THIRD-PARTY.txt and third-party/meiki for library/model notices and source references.
MeikiOCR's three pinned models are bundled; translation weights are not bundled.
