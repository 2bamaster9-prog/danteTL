# Slice eight — Responsive dialogue and optional GPU OCR

Status: implemented and verified on the development PC. Requested by the user after busy-screen
persistence improved but slowly appearing dialogue still translated too early and regrouped late.

## Delivered

- Reveal activity separated from committed display values. Pending continuation lines reserve a
  group early; final readiness uses observation time and avoids stacked confirmation/group delays.
- Published revision-valid English survives changes in readiness. Only ready requests initiate work.
- Optional NVIDIA CUDA OCR in an isolated environment, actual-provider reporting, one-time CPU
  fallback, and explicit CPU selection/launcher. Sugoi stays local CPU int8.
- Bounded project-local CUDA compilation cache, primed by explicit GPU setup. The regular launcher
  selects GPU only after successful verification. No global toolkit, service, or runtime download.
- Capture pacing selectable from 2–8 Hz, default 6 for GPU auto and 4 for CPU, with bounded existing
  worker mailboxes. Diagnostics distinguish capture rate from actual OCR throughput.
- Typewriter demo/replays and live checks, strict GPU model checks, and CPU-switching verification.

## Verification

159 tests pass in both CPU and GPU environments, with Ruff and Pyright. New tests cover growing
identity, early continuation grouping, no partial requests, quiet pauses, genuine pending edits,
retention without retranslation, CPU selection, GPU failure at load/run, and cache configuration.
Offline Meiki CPU/GPU and Sugoi checks pass with Python socket connections blocked.

On RTX 5080 / Ryzen 9800X3D, five warm dense 4K passes measured 237.7 ms GPU median versus 476.1 ms
CPU median. Both returned 64 detections from 80 drawn labels, with the same observed spelling
variants. A sparse GPU fixture measured 35.7 ms warm median. Profiling confirmed CUDA node execution.
The initial compilation took about 54 seconds; a subsequent process with the local cache measured
1.08 seconds first inference plus 0.89 seconds model loading. See the performance record for limits.

The live GPU typewriter check at DPI 168 started with an empty translation cache, issued no partial
dialogue translations, and displayed the complete English passage 0.75 seconds after the last
character appeared. It also checked speaker separation, grouping/profile toggles, automatic/manual
font controls, pause, resize, minimize/restore, restart on CPU, and shutdown. The CPU typewriter
check passed too. Slow CPU OCR with an added 900 ms delay retained English through 49 observations
over at least three seconds. Inspector/overlay artifacts were reviewed. No game FPS claim follows.

## Try it

This development PC already has the GPU environment installed and verified. Close the old app and
use `Run JP Overlay.cmd`; leave **Automatic · GPU with CPU fallback** and six samples/second selected.
Check the OCR status says **NVIDIA GPU**. Other machines can run `Setup GPU OCR.cmd` explicitly or
keep the default CPU setup. The CPU launcher always remains available.

Revisit a revealing dialogue and the crowded game scene. Inspect source grouping and total response
time. Long typing pauses or unusual layouts can still look complete; rates above model capacity
only replace waiting frames. Actual game frame-time impact, other GPUs, sustained RAM/VRAM usage,
vertical GPU accuracy, and midrange-PC performance remain unverified.
