# Slice thirteen — Runtime setup inside the app

Implemented: worker-based DXGI detection and manual override; explicit NVIDIA, AMD/Vulkan and CPU
profiles; pinned, isolated dependency installation with stage progress/cancel; library probing;
verified reuse/repair; graceful restart and remembered normal-launcher choice. The Models dialog
and unavailable Gemma entry both lead to runtime setup. Existing model preparation stays separate.

Failure paths preserve the running environment and model files. No drivers, system Python changes,
automatic downloads, inference services, or redesign of the main/settings layout were added.
The source package still requires initial Python/uv/Qt bootstrapping through the normal launcher.

Verification includes fake-process failure/cancel/repair/receipt tests, native child-process cleanup,
Qt close/restart lifecycle tests, and clean CPU distribution discovery. The extracted distribution
installs NVIDIA and AMD profiles from cached pinned packages, restarts into each, and closes cleanly.
Actual CUDA OCR and Gemma preparation/reuse run in the app-installed NVIDIA environment. Native
Radeon testing and a cold download on a friend's machine remain user validation.

See [decision 013](../decisions/013-in-app-runtime-setup.md) and
[verification](../verification.md) for boundaries and commands. The subsequently approved
[UI slice](014-ui-proposal.md) integrates these views into Settings.
