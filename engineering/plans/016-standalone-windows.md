# Slice 016: Standalone Windows distribution

Deliver `dist/DanteJP-windows-x64.zip`: extract the whole folder, run `DanteJP.exe`, then download
models and optional GPU libraries inside Settings. Windows x64 is the target. No system Python,
separate setup scripts or administrator rights. No model weights are included.

Use a private CPU interpreter/library tree and a native GUI launcher. Store writable state in
`%LOCALAPPDATA%/DanteJP`. Keep source checkout behavior and internal package IDs compatible.
Changing the app folder must preserve models, settings and installed runtime selection. Model
preparation still asks before running; NVIDIA/AMD profiles retain their existing verified limits.

Acceptance:
- Fresh native EXE launch from a Unicode path with Python/tools removed from PATH.
- Core native imports, model-free capture, Settings and clean shutdown work in the bundled CPU runtime.
- No startup downloads or files written into the app directory; AppData receives settings/logs.
- Explicit model setup still verifies checksums and populates the model selector.
- In-app runtime install/probe/restart uses AppData Python, current app code and owned child processes.
- Installed-runtime selection survives relocation, transfers hotkeys and falls back visibly on failure.
- GPU preparation and real inference still run after restart; Radeon claims require Radeon hardware.
- Release manifest excludes models, personal state, developer environments and tools.

Results and remaining platform limitations belong in [verification](../verification.md).
