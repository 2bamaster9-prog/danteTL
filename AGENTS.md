# DanteJP engineering instructions

Read `engineering/README.md` first. The agreed product plan is in
`engineering/plan.md`; current implementation scope is in
`engineering/plans/018-cpu-llm-runtime.md`. NVIDIA OCR and Gemma share pinned CUDA 13 libraries.
Standalone releases bundle CPU ONNX and llama.cpp; models, preferences and optional GPU
environments live in per-user AppData. Runtime names describe hardware, not model brands.

The public app name is DanteJP. Preserve the legacy Python package/CLI IDs and `JP_OVERLAY_*`
variables for installed-runtime compatibility; the branding rename must not invalidate dependencies.

- Use Python with deep modules: small public interfaces that own meaningful complexity.
- Keep Windows, Qt, capture-library, and model details at their respective boundaries.
- Use explicit dependencies and typed values. Do not create generic frameworks for hypothetical needs.
- Runtime processing is local. Do not add network services, telemetry, or automatic model downloads.
- Keep frames and work queues bounded. The UI thread must not perform capture or inference.
- Preserve physical-pixel coordinate contracts, window identity, and session validity checks.
- Treat capture failures as visible recoverable states. Never silently capture another window or monitor.
- Add behavior tests for meaningful failure modes; avoid tests that only repeat implementation details.
- Run `uv run python tools/check.py` for code changes. Real capture verification is separate:
  `uv run python tools/verify_windows.py`. Read `engineering/verification.md` before running it.
- For OCR changes, run `uv run python tools/verify_ocr.py` with local models installed. Live OCR
  integration is `uv run python tools/verify_ocr_windows.py`. Keep frame/result pairs together;
  never draw old observations onto a newer preview frame. Preserve raw OCR output for inspection.
- Tracking is deterministic and bounded. Pass time explicitly, test replay sequences, preserve
  track identity through detector-order changes, and never turn approximate text matching into
  permanent suppression of real content edits. Only committed display changes request repaint.
- Processing time and skipped capture frames are not absence evidence. Keep committed tracks and
  English between completed OCR observations. Use bounded `presence` crop digests to retain text
  through unchanged-pixel misses; never retain frame history or use pixel changes alone as absence.
  Test slow workers, dense/reordered observations, repeated misses, genuine removal, and resets.
  Run `verify_ocr.py --dense` and the live translation/dialogue check with `--ocr-delay-ms 900`.
- Visual analysis owns a separate bounded worker. Keep its thumbnails, templates, and pending job
  bounded; never run image analysis on the UI thread or rewrite raw OCR/source frame pairs. Strong
  pattern loss on two captured frames may mask a box reversibly; retirement also needs completed
  negative OCR, current revision/geometry, and visual evidence at least as new as that OCR frame.
  New translation requests wait until visual checks have examined their OCR source. Test tiny
  continuation growth, background motion, brightness/polarity changes, stale generations, static
  WGC frames, and failure fallback. Run the live dialogue check with `--typewriter --transitions`.
- Reconcile new OCR only after source-matched visual evidence arrives. Unchanged accepted glyphs
  retain identity, geometry and English across noisy/missed OCR. Below 90% confidence allow three
  reviews with a strictly better score; never reset the budget on spelling alternation. Real local
  changes unlock ordinary tracking. `presentation` may bridge only explicit same-pixel correction
  lineage, never arbitrary stale revisions. Run `tools/verify_retention_windows.py` for this policy.
- Partial OCR has explicit coverage. Unscanned tracks are not misses; never merge old raw rows into
  a newer inspector frame. Coalesce pending areas as well as pixels, preserve per-line probe source
  sequences, and validate the acknowledgement/reset path. Test crop offsets, clipping fallback,
  whole-line closure, dialogue edits across partial scans, and independent discovery deadlines.
  Run dense real OCR and `verify_retention_windows.py --appearance` for regional latency/stability.
- Keep OCR providers at the runtime boundary. Never co-install CPU/GPU ONNX distributions. GPU
  verification must use `--device cuda` and fail on fallback; normal automatic mode reports fallback.
  Use `.venv-gpu/Scripts/python.exe` for GPU checks, and preserve the default CPU environment.
  Treat first-use compilation separately from warm inference; retain the bounded local CUDA cache.
- NVIDIA setup pins ONNX Runtime 1.30 and CUDA 13.0 libraries shared with Gemma. Preserve the
  legacy 1.26/CUDA 12 loader path for existing development environments. Never select libraries
  just because Gemma installed them; they must match the OCR provider build. Dependency changes
  require an isolated environment and `verify_shared_cuda.py` in both initialization orders,
  strict real OCR and live Gemma switching. Use an isolated candidate for upgrades before touching
  a working environment. No CPU/GPU provider mixing or removal of active native libraries.
- Translation readiness is separate from display retention. Pending growth can reserve a dialogue
  group but cannot become a translation source until committed. Keep revision-valid published
  English while readiness changes; never enqueue retained-only requests. Test typewriter growth,
  early continuation, short menus, and genuine edits. Run the live dialogue check with `--typewriter`.
- Confidence belongs to a live track/content family, not a permanent screen-position cache. Keep
  the winning score private to tracking; rejected variants must preserve text revision and geometry.
  Test alternating variants, real edits, static settling, and reset boundaries before changing policy.
- Preserve raw OCR in the inspector. `text_content` derives character-bounded tracking input and
  conservatively filters isolated weak edge glyphs; never globally discard low-confidence text.
- `grouping` builds bounded dialogue blocks from stable lines. Keep speakers, choices, and unrelated
  columns separate. Requests/rendering must validate every member's ID, source, and revision;
  group bounds use per-line font height. Run the live check with `--translation --dialogue`.
- Translation backends implement `TranslationBackend`; composition belongs in `app`. Keep model
  loading, inference, unloading, and SQLite on the translation worker. Bound desired work and batches;
  validate generation, track ID, exact source, and text revision before publishing/rendering English.
- Cache identity must include weights/tokenizers, runtime, language pair, decoding settings, and any
  future glossary/context. Moving a box must not trigger translation. Swaps unload before loading.
- Optional Gemma uses embedded llama.cpp, not CTranslate2 or a service. Keep runtime/model setup
  explicit, prompts bounded, reasoning off, and reject incomplete answers. Verify actual CUDA
  inference and swapping with `verify_ocr_windows.py --translation --dialogue --gemma --debug`.
  Diagnostics only observe worker snapshots; distinguish visual changes, proposed scans and actual
  OCR coverage. Do not change scheduling, retention or translation sources when toggling debug.
- Model downloads require an explicit UI/CLI action. Keep hashing/downloads on a bounded worker,
  verify pinned sizes/hashes, atomically publish files, and preserve valid files on cancel/failure.
  Gemma first-use consent must retain the committed selection until accepted; declined/failed
  preparation restores the previous choice. Reuse the prepared translation worker. Capture must
  work without models. Run `tools/verify_setup_windows.py` for native setup lifecycle changes.
  Test a missing-engine environment with downloaded Gemma: keep the model
  visible with setup instructions, never load it, and never equate downloaded weights with GPU
  availability. Use `verify_setup_windows.py --missing-runtime` for that regression. OCR device
  choices reflect runtime packages, not the presence of Meiki weights.
- AMD packaging isolates Vulkan/DirectML in `.venv-amd`; never mix ONNX or llama runtime wheels.
  CPU OCR is the AMD default. Strict `--device directml` must fail on provider/probe failure;
  `auto-directml` reports CPU fallback. DirectML initialized but miscomputed our pinned models:
  preserve the numerical compatibility probe, and do not call it validated Radeon acceleration.
- In-app runtime setup uses isolated `.runtimes` environments; never install into a loaded venv.
  Downloads require an explicit action. Keep detection, installation, probing and subprocess output
  off the GUI thread. Only validated, contained environments may be activated. Cancel/timeout must
  stop owned child processes before cleanup; preserve model files and the active runtime. Restart
  drains workers and waits for a new Qt startup acknowledgement (actual app PID, not Windows venv
  launcher PID). The normal launcher must honor the persisted selection and retain CPU fallback.
  AMD's in-app profile uses Vulkan Gemma + CPU OCR, without experimental DirectML. Run
  `tools/verify_runtime_windows.py` in a disposable extracted distribution for setup/launcher changes.
- Standalone app resources are read-only. Use `paths.state_root()` for writable files; source mode
  keeps project-local paths. Never bind AppData runtimes to the movable bundled interpreter or an
  editable source install. Use the bundled uv and an AppData-managed Python; launch current source
  through `module_command`. Test the real EXE after Unicode-path relocation with Python absent
  from PATH (`verify_standalone_windows.py`), plus packaged setup/restart. Do not bundle weights,
  caches, personal preferences or dev/GPU environments. Preserve dependency licenses and manifests.
- Dialogue history is two turns/512 characters, scoped to one unambiguous panel. Freeze context
  per request, include it in cache identity, reject outdated context, and never seed history from
  stale replies. Menus stay independent; layout/session/scene/age resets clear conversational state.
- For translation changes, run `uv run python tools/verify_translation.py` with local models installed
  and `uv run python tools/verify_ocr_windows.py --translation` for live integration. Fast tests must
  remain model-free. Preserve raw OCR inspection and full English text when overlay layout overflows.
- Update relevant engineering documents when architecture or behavior changes; record major choices
  in `engineering/decisions/`. Keep documentation concise and avoid duplicated instructions.
- Main/Settings/Advanced are separate views of the same live session. Hiding or pausing inspection
  must never invalidate OCR, visual evidence, tracks or translation. Keep accepted OCR outside the
  inspector; hidden inspection retains only the latest source/result pair, without image conversion
  or table rebuilds. Pause freezes both inspector languages only. Preserve exact source matching.
  Settings persist validated IDs/values asynchronously; never persist HWNDs, debug or pause state.
  Device/rate edits apply on the next capture, including when models arrive during capture. Settings
  may hide with setup running; app close always cancels/drains it. Run `verify_ui_windows.py`, the
  native setup regression, and live translation/pause checks for changes to these boundaries.
- Keep main controls top-left and width-bounded at large sizes; Advanced may expand independently.
  Test maximized on/off disclosure without unmaximizing. Hardware advice performs one worker-based
  read-only check, distinguishes detected adapters from verified inference, and must not flag AMD's
  intended CPU OCR as a failure. Model badges distinguish file presence from runtime availability.
  Model switches revoke painted and paused-inspector English. Scope presentation retention to the
  translation worker/backend generation; preserve model-keyed disk caches and reject late replies.
- Do not claim game, mixed-DPI, HDR, or anti-cheat compatibility based solely on a demo window.
- Global shortcuts use RegisterHotKey on the Qt thread, without keyboard hooks or idle key polling.
  While show-original is held, check only its chord at 16 ms for release; stop the timer afterward.
  Keep this transient mask out of saved toggles and processing state. Cancel on focus loss/stop/close.
  The capture hotkey can explicitly select the eligible foreground HWND/PID when starting; never
  follow focus during a session, fall back to another target, or capture our own windows/desktop.
  The ordinary Start button uses the selected window. Preserve
  working bindings if registration fails; reject stale messages after rebinding. Reuse the existing
  capture/overlay actions, honor stop/close/modal guards, and release shortcuts
  before runtime restart. Test native delivery with `tools/verify_hotkeys_windows.py`; synthetic
  inputs must target only our foreground fixture, never a game or unrelated application.
- Do not implement later milestones without a user request. Capture, OCR, tracking, local Sugoi
  translation, bounded caching, English layout, icon cleanup, and dialogue grouping are implemented.
  Gemma is an optional quality backend with bounded recent-dialogue context. Glossaries,
  profiles and an installer remain separate work; portable standalone and source sharing ZIPs exist.
