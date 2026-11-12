# Decision 013 — Explicit runtime installation inside the app

The user requested GPU setup without separate scripts, and a UI redesign proposal without
implementing that redesign. Only a Runtime setup dialog is added to the current Models flow;
selecting downloaded Gemma without dependencies opens the same dialog. No automatic installs.

`hardware` enumerates DXGI adapters on a worker, excluding software devices. It recommends the
supported vendor with most dedicated memory (NVIDIA wins a tie), avoiding this PC's integrated
Radeon in preference to its RTX 5080. This is not a driver/VRAM suitability guarantee; manual choice
and CPU remain available. See [DXGI adapter description](https://learn.microsoft.com/en-us/windows/win32/api/dxgi/ns-dxgi-dxgi_adapter_desc1).

`runtime_setup` owns three pinned profiles: CUDA OCR/CUDA Gemma, CPU OCR/Vulkan Gemma, and CPU
OCR/Sugoi. It uses [locked uv synchronization](https://docs.astral.sh/uv/concepts/projects/sync/)
with no default dependency groups, so competing ONNX/llama distributions never share an environment.
The AMD flow deliberately omits experimental DirectML. Legacy development scripts retain it.

Installations use unique final paths under `.runtimes`; never resync or rename a loaded venv.
The running app, model weights, and translation cache remain unchanged. An OS file lock serializes
installers for one project. Dependency downloads/builds and native imports run in hidden child
processes; a Windows job terminates owned descendants on cancel, timeout, or parent exit. Output is
bounded in memory and included in rotating app logs. The UI polls snapshots and reports real stages;
no invented percent/ETA. A library probe checks imports/provider support without loading models.
Gemma's existing explicit first-use preparation remains separate; OCR reports loading/fallback.

Only a completed probe publishes a readiness receipt. Receipts bind the profile environment to
pyproject/lock fingerprints. Receipt paths accept only generated, contained environments. Failed
fresh installs remove only their owned directory after child exit. Verified installs are reused;
repair probes first and creates a separate replacement only on failure. Replaced environments are
kept for recovery; automatic runtime garbage collection is out of scope.

`runtime_restart` starts the selected environment only after MainWindow drains capture/inference
and setup work. The new Qt event loop acknowledges startup with its actual PID (Windows venv
launchers can have a different PID). Only then is the next-launch selection committed and the old
window closed. Failure keeps the old UI available. `tools/launch.py` honors this selection, falls
back to the original environment on launch failure, and preserves legacy verified NVIDIA launch
behavior until a user chooses an in-app runtime. The source kit still bootstraps Python/Qt before
the first GUI; this slice does not turn it into a frozen installer or install GPU drivers.

The UI proposal lives separately in `engineering/plans/014-ui-proposal.md`. Moving controls,
renaming English overlay, adding switches, and preference persistence are not implemented here.
