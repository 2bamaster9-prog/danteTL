# Verification

## Session lifecycle and review fixes (2026-11-14)

402 model-free tests, Ruff and Pyright pass through `uv run python tools/check.py`. New regressions
cover same-profile repair with postponed/failed activation and rollback, delayed job assignment,
assignment/resume failure, descendant termination, blocked OCR cleanup, request-local rejection,
mixed batches, context/backend resets and bounded failure history. Pure `LiveSession` replays cover
source-matched visual review before acknowledgement, partial coverage, unchanged misses, dialogue
publication, mask/restore, backend scope, resize and worker draining without constructing a window.

Windows CI now runs the locked CPU/development environment and the same fast check on pushes and
pull requests. The local entry point passed; the hosted workflow awaits its first GitHub run.

Real dense CPU/CUDA OCR, Sugoi and CPU/CUDA Gemma passed. Native UI, model preparation/missing-runtime,
first-run guide, CUDA dialogue/typewriter/transitions, delayed CPU OCR (900 ms), stationary retention
and regional appearance passed. The retention fixture recorded zero publication changes over 358
unchanged polls; a newly appearing regional label reached English in 0.516 s on this run. These are
synthetic-fixture observations, not game latency guarantees. Qwen compatibility and native import,
cancellation, selection, Gemma return and removal also passed with the new process owner.

Native hotkeys passed after activating our owned demo through computer use. Two earlier attempts
could not acquire foreground focus and sent no input; the successful run allowed 90 s for fixture
activation, keeping all checks intact. Start/stop, rebind/conflict, held-original, focus loss and
shutdown passed. UI snapshots were inspected; evidence is under `artifacts/review`.

The rebuilt standalone passed Unicode-path relocation with Python absent from PATH, fresh offline
bundled OCR and all 6,950 manifest entries, without writes to the app folder or implicit downloads.
Its bundled CPU interpreter and AppData NVIDIA runtime passed native imports, cancellation, model
switching and return to Gemma. A malformed probe exited without a startup modal. Packaged CPU runtime
reuse/restart passed with actual GUI acknowledgement, hotkey handover and clean child exit. These
checks used disposable extracted files and test AppData; active user runtimes were not changed.

## Imported GGUF models (2026-11-14)

387 model-free tests, Ruff and Pyright pass. New coverage includes bounded/truncated metadata,
unsupported formats, cancelled hashing/probing, same-size weight changes, registry corruption,
relocation/removal, cache/profile/device identity, bounded context, incomplete/reasoning answers,
missing engines/files, waiting for the previous worker to unload and revoking an active removal.

`verify_import_models.py <local.gguf> --device cpu|cuda|vulkan --output <report.json>` runs the
same explicit offline child probe as the UI without registering a model. Official Qwen3 4B Q4_K_M
and Gemma 4 E4B QAT Q4_0 passed CPU, CUDA and Vulkan tests. GPU logs confirm 37 and 43 offloaded
layers respectively. Short fixture phrases took roughly 0.1–1.0 s on CPU and below 0.4 s on GPU,
after loading/warm-up. These are a few original samples on the 9800X3D/RTX 5080, not quality rankings
or game latency guarantees. Vulkan used the NVIDIA card; Radeon is not validated by these runs.

`verify_import_windows.py <local.gguf> --output <fresh-directory>` checks real native import review,
in-flight test cancellation, unchanged selection, unloading before probing, registration, Qwen
overlay translation, return to built-in Gemma, and registration-only removal. CPU and CUDA checks
passed; reviewed screenshots show samples/timings and the local-file badge/path. Reports and test
registrations are under `artifacts/model-import`; actual user AppData is not modified.

Built-in Sugoi and CPU/CUDA Gemma smoke checks, Settings layout and missing-engine recovery pass.
Live CUDA OCR/Gemma dialogue, typewriter/transitions, model swaps, paused inspection, original hold
and teardown pass. Built-in adapters and native dependency versions are unchanged. The setup
fixture now updates its stored catalog as well as its picker when simulating newly arrived files.

The final standalone ZIP passed Unicode-path relocation with Python absent from PATH, fresh
offline bundled OCR, and all 6,947 manifest entries. Its bundled CPU interpreter and AppData NVIDIA
runtime passed the native import/cancel/select/return checks against the packaged source. An invalid
model returned its error without an unattended startup dialog. Packaged CPU runtime reuse/restart
also passed, including hotkey handover and clean shutdown. Evidence is under
`artifacts/model-import/standalone-final` and `artifacts/model-import/packaged-*`.

For imports, add a wrong-format or missing file to check visible recovery, and cancel while the
probe loads. A passing test confirms executable text generation only; review translation quality.
Models stay by reference, and no model registration or file is added to the release package.

## Bundled MeikiOCR (2026-11-14)

365 model-free tests, Ruff and Pyright pass. Coverage includes fresh bundled availability without
copy/network activity, explicit overrides, complete AppData precedence, partial AppData fallback,
read-only package protection, checksum failures, local repair reuse and cancellation. Included OCR
has a ready badge and is excluded from the first-run download plan. The native guide fixture passed
translation-only setup, cancel/retry, saved completion and reopening Settings.

The standalone ZIP is about 266.6 MB (previously 225.0 MB). It includes exactly the three pinned
Meiki ONNX assets (45,970,040 uncompressed bytes), model cards/license/source notices, and the same
31 CPU distributions. Translation weights and GPU environments remain excluded. All 6,943 manifest
entries passed after Unicode-path relocation.

`verify_standalone_windows.py` now runs actual bundled CPU OCR with sockets blocked, Python absent
from PATH and fresh AppData. All three expected Japanese phrases were recognized; no AppData models
were created, no app-folder files changed and the EXE showed its welcome/drained cleanly. The real
Japanese fixture uses Qt's Windows font renderer; the offscreen renderer produced no recognizable
text and is not used for this native check. Evidence is under `artifacts/bundled-ocr/standalone-recheck`.

Packaged native UI checks passed and screenshots show Included with app plus the read/repair
locations. CPU model preparation/decline/reuse, missing-engine recovery, live Sugoi translation and
dialogue/pause/lifecycle checks, and verified CPU runtime reuse/restart passed using test AppData.
Original Meiki weights and all native dependency versions are unchanged. This verifies bundling and
path/lifecycle behavior, not new game, Radeon, DPI/HDR or anti-cheat compatibility.

## First-run setup and file progress (2026-11-14)

358 model-free tests, Ruff and Pyright pass. New cases cover explicit setup, CPU overrides during
delayed detection, skip persistence, cancel/drain, post-restart model consent, wheel compatibility,
pinned hashes/sizes, unknown totals, partial-file cleanup, cache reuse and byte snapshots.

`verify_first_run_windows.py` uses synthetic bytes through the real model installer and an owned
native window. Welcome/model/review/progress/completion screenshots were inspected under
`artifacts/first-run/welcome`. It checks two bars, cancel/retry, chosen-model-only downloads, saved
completion, reopening Settings and immediate downloaded badges. No real models are downloaded by
this fixture. Native layout, preparation/decline/worker reuse and absent-engine recovery also pass.

The extracted standalone app downloaded real pinned NVIDIA and CPU wheels into the test cache,
verified them, installed fresh isolated environments and acknowledged Qt restart. Native snapshots
record intermediate current-file bytes, including CUDA/cuDNN/ONNX and llama.cpp wheels. These runs
took 44.6 s (NVIDIA) and 5.1 s (CPU, shared files already cached) on this connection; they are not
download-speed guarantees. Managed Python was already present in test AppData; its cold bootstrap
still uses uv's activity/status reporting without invented byte percentages. Previous runtimes and
test model files remained intact. Restart transferred and released all fixture hotkeys.

Actual CUDA OCR and Gemma passed in both initialization orders in the new runtime, including DLL
family inspection. Live translation/grouping/typewriter, model swaps, inspection pause, transitions
and teardown passed; complete dialogue reached English in 0.625 s on the synthetic fixture.
These are integration checks on the RTX 5080, not Honkai latency or Radeon compatibility claims.

The standalone manifest contains 31 CPU distributions and no weights/GPU environments. The fresh
EXE showed the welcome after Unicode-path relocation with Python absent from PATH, used isolated
AppData, performed no implicit downloads and closed cleanly. Closing the modal welcome precedes
closing the parent window in the native harness. No actual user AppData was modified.

## Fast checks

Run `uv run python tools/check.py` from the repository root. It checks Ruff formatting and lint,
Pyright types, and pytest behavior tests. It does not open windows or download models. Dependencies
must already be installed with `uv sync --locked` or the bundled setup script.

Fast tests cover physical geometry across scale factors and negative desktop origins, decorated
and borderless crops, resize rejection, focus/closure policy, bounded frame replacement, and late
callbacks after shutdown. OCR tests cover latest-frame replacement, generation invalidation,
stop during loading/inference, model integrity, offline missing-model failure, frame-space boxes,
preview letterboxing, and empty results replacing prior detections. They do not establish native
Windows compatibility.

Translation tests use fake backends and real temporary SQLite databases. They cover deduplication,
movement without inference, stale revisions/generations, removed tracks, bounded work, cache identity,
disk fallback, model swaps/unloading, and nonblocking shutdown. Qt checks cover English layout,
overflow, revision-safe rendering, and repaint suppression. No model files are needed for fast tests.

## Local OCR checks

Install models explicitly with `uv run python tools/setup_models.py` or `Setup OCR.cmd`.
Run `uv run python tools/verify_ocr.py --output artifacts/ocr` for the offline real-model check.
It creates an original 1080p Japanese fixture, blocks socket connections while loading/inferencing,
compares recognized phrases after Unicode width normalization, and records raw text/boxes and
timings. `--output` is optional and saves only synthetic test artifacts, never game screenshots.

Run `uv run python tools/verify_ocr_windows.py` for capture-to-inspector integration. It uses only
our demo, checks Japanese recognition, freezes inspection while capture continues, resizes,
minimizes/restores, restarts, and closes both workers. Optional `--output artifacts/ocr/live.png`
saves the test app's own widget rendering. This runs on an unlocked desktop like the native check.

## Local translation checks

CPU Gemma: `uv sync --locked --group llm-cpu`; the standalone release includes this engine.
Verify with `tools/verify_translation.py --backend gemma --device cpu`. Device assertions reject
an unexpected engine; CPU, CUDA and Vulkan llama distributions must remain isolated.
Optional CUDA Gemma: `Setup Gemma.cmd`, or `uv sync --locked --group gemma` followed by
`uv run --group gemma python tools/setup_models.py --gemma`. Use the isolated GPU environment with
`--no-default-groups --group gpu --group dev --group gemma` when retaining CUDA OCR.
Run `tools/verify_translation.py --backend gemma --output artifacts/gemma/translation-final.json`
with either Gemma-enabled interpreter. It blocks Python sockets and reports per-source inference,
load/warm-up, memory snapshots and original Japanese/English pairs. Compare with `--backend sugoi`.
The first GPU run can compile kernels; repeat in a new process to validate the persistent CUDA cache.

Add `--gemma --debug` to the native translation/dialogue check to exercise Gemma → Sugoi → Gemma,
grouped output, debug coverage/toggle retention and ordinary lifecycle controls. This uses only the
test fixture, never game capture. Cold/uncached and cached results are labeled separately.

Install Sugoi explicitly with `uv run python tools/setup_models.py --translation` or
`Setup Translation.cmd`. Run `uv run python tools/verify_translation.py` to load/translate original
sample phrases with Python socket connections blocked. It prints the backend/cache identity,
load/batch timings, and a Windows process memory snapshot. It is a smoke check, not a quality benchmark.

Run `uv run python tools/verify_ocr_windows.py --translation --output artifacts/translation/live.png`
to test the full pipeline with both model sets installed. It waits for English, switches Sugoi
decoding profiles, verifies font controls, and runs pause, resize, minimize/restore, restart, and
shutdown checks. The optional output saves only the fixture app and its English overlay rendering.
Add `--dialogue` to verify two-line source grouping, a separate speaker label, grouping off/on,
and one combined English overlay. The app's Open demo window uses this dialogue fixture; the
standalone demo accepts `--dialogue` too. The native regression remains
`uv run python tools/verify_windows.py`.

Add `--ocr-delay-ms 900` to the translation/dialogue live check to keep capture advancing while
each OCR pass takes about one second. It checks track continuity between passes and holds the
translated passage under observation for at least three seconds after it first reaches the overlay.
The first publication waits for the UI poll; subsequent missing translations fail the check.

Add `--typewriter` to verify gradual character reveal, no partial dialogue requests during the
fixture's animation, and completion-to-English timing. Each typewriter check uses a fresh synthetic
translation cache under `artifacts`, so its final passage requires actual inference. The standalone
demo also accepts `--typewriter`. This is one reveal cadence, not every game's animation behavior.
Add `--transitions` to close and reopen the panel after English appears. It measures hide/restore
latency and, with `--ocr-delay-ms 900`, requires hiding before a new OCR result. It also checks that
the visual worker finishes on restart/close. Failure output includes bounded synthetic state and
uses escaped text so Japanese assertions cannot break shutdown on a legacy Windows console.

After `Setup GPU OCR.cmd`, use `.venv-gpu\Scripts\python.exe tools/verify_ocr.py --device cuda`
and repeat with `--dense`. Then run that interpreter with
`tools/verify_ocr_windows.py --translation --dialogue --typewriter --device cuda`. Strict CUDA
asserts the provider and fails on errors; normal auto mode may fall back. The GPU live check also
stops and restarts on CPU, verifying the selected provider. Run `tools/check.py` with both environment
interpreters. Keep raw OCR accuracy evidence; a provider merely being installed is insufficient.

`uv run python tools/verify_ocr.py --dense --output artifacts/dense-ocr` measures an original 4K
fixture with 80 small labels and reports actual detection count, OCR latency, and reconciliation
time. The detector need not recover every label; raw errors/misses stay visible in its artifact.
The same command also benchmarks the visual stage on sixteen unchanged captures and on eight
shifted frames that stress every crop. Report static and moving costs separately; skipped OCR
requests do not mean every skipped capture would previously have completed an inference.
The exact-source review benchmark separately includes comparisons for a newly completed OCR frame.
Dense verification also reads one padded region and alternates it with full scans. It checks the
recognized phrase and coordinate containment, recording first/warm/after-full timings. This catches
GPU batch-shape stalls that a repeated single-crop benchmark alone would conceal.

Run `uv run python tools/verify_retention_windows.py` (or the GPU interpreter with `--device cuda`)
for stationary-label retention. It creates six Japanese labels over dim moving stars, loads real
Meiki/Sugoi, then injects unrelated low-confidence readings, wider boxes and total Japanese misses.
It requires unchanged published blocks and English on every poll for at least twelve seconds and
six hostile OCR passes. It closes all workers and saves only synthetic diagnostic state under
`artifacts/visual`. Neither this fixture nor the model-free replays use the user's game video.
Add `--appearance` to introduce a new menu label after the stability interval, with a fresh synthetic
translation cache. It requires regional discovery, measures appearance-to-English, and checks the
existing English and box geometry on every poll during that update. Live dialogue checks accept
partial raw observations while requiring the unscanned speaker to remain in the tracked scene.

## Gemma and diagnostic evidence (2026-11-13)

- 224 model-free tests plus Ruff formatting/lint and Pyright pass in both environments. Coverage
  includes model setup failure, output/context limits, reasoning-marker rejection, warm-up cleanup,
  cache identity, serial early publication, cache/inference diagnostics and debug repaint behavior.
- Offline real Gemma and Sugoi comparisons passed with Python sockets blocked. See performance for
  timing/memory limits. Native GPU logs identified RTX 5080 and all 36 layers offloaded; the PLE
  embedding weights remain host-mapped. No native HTTP client or model downloader is invoked.
- GPU OCR + Gemma, DPI 144, fresh translation cache: complete grouped English **0.75 s** after the
  final revealed character; no partial dialogue translation. Gemma → Sugoi → Gemma, grouping off/on,
  debug toggles, font controls, pause, resize, minimize/restore, CPU OCR restart and teardown passed.
  Panel hide/restore measured 0.313/0.500 s. Full process snapshot: 3,063 MiB working set and
  5,066 MiB private memory. This is a synthetic fixture, not a sustained game measurement.
- Slow CPU OCR (900 ms added per call) + Sugoi + debug passed: complete English 2.375 s after reveal,
  50 persistence polls, hide/restore 0.313/0.312 s. Hiding occurred before a new OCR completion.
- Dense 4K CPU/GPU real OCR retained 64 detections from 80 labels. Regional coverage/coordinates
  passed. GPU full/region medians 231/27 ms; CPU 453/37 ms. CPU run overlapped an experimental
  translation profile and is only regression evidence, not an isolated speed comparison.
- The unchanged-label GPU/Sugoi regression retained all six publications across 248 render polls
  and seven injected noisy OCR passes over twelve seconds. New-label discovery used 3.66% regional
  coverage and reached English in 0.469 s while preserving existing English; all workers stopped.
- Reviewed native app/overlay PNGs under `artifacts/gemma`. The overlay diagnostics remain readable
  and partial scan bounds use source coordinates. The raw inspector contains no debug graphics.

Remaining manual review: Honkai translation quality/proper names, crowded-menu latency and game frame
times; mixed-DPI/HDR/anti-cheat behavior; other GPUs. No broad quality score or memory guarantee.

## Regional OCR evidence (2026-11-13)

- 209 fast tests cover crop coverage/offsets, artificial-edge fallback, unchanged dialogue members,
  independent full discovery, merged pending areas, result acknowledgement, per-line confirmation
  across unrelated scans, and CUDA padding/output trimming for both orientations.
- Real dense CPU/GPU OCR passed offline with socket connections blocked. Full scans still produced
  64 detections from 80 drawn labels, including documented spelling variants. The regional sample
  recognized its Japanese label correctly inside its declared coverage; no fabricated old rows were
  added to new raw output. Benchmarks are in [performance](performance.md).
- GPU stationary/new-label run at DPI 168: six existing English blocks remained stable across 342
  polls and six injected noisy OCR calls over 16.03 seconds. A new label used 3.22% coverage, took
  16 ms OCR and reached English in 0.468 seconds with an initially empty translation cache.
- CPU stationary/new-label run at DPI 144: six English blocks stayed unchanged through 256 polls,
  six injected noisy calls and 12.0 seconds. Regional discovery used 3.66% coverage, took 31 ms OCR
  and reached English in 0.469 seconds. Assertions also verified the existing English and geometry
  throughout the appearance update. Shutdown completed all workers.
- Slow CPU dialogue run with 900 ms added per recognizer call: no premature partial translation,
  correct combined passage and separate speaker, 50 English continuity polls, and full lifecycle
  checks passed. Final dialogue appeared after 2.25 seconds. Panel hiding took 0.313 seconds before
  OCR completed; restoration took 0.312 seconds. This delay simulation is not a CPU-load benchmark.
- Final GPU dialogue/transitions run at DPI 144 passed grouping/profile changes, font controls,
  pause, resize, minimize/restore, CPU restart and teardown. Full dialogue reached English in 0.750
  seconds; panel hide/restore measured 0.375/0.250 seconds. An earlier DPI 168 run measured 0.625
  seconds for dialogue. These are separate scale-factor runs, not cross-monitor movement tests.
  The harness permits a new identity after a genuinely removed panel is reopened; stationary
  continuity checks apply while the panel remains present, not across confirmed disappearance.
- The application's real game behavior, game FPS impact, and every dialogue reveal cadence remain
  unverified; these are controlled fixture checks. No dependency installation or model download is
  needed to use this slice.

## Visual scheduling and stationary retention evidence (2026-11-13)

- 194 model-free checks pass with Ruff/Pyright. Replays cover unchanged noisy OCR, repeated misses,
  geometry jitter, three-review budgets, high-confidence locking, changed digits, large and tiny
  reveal additions, dim moving stars, stale evidence, correction lineage, reset and real removal.
- Native stationary fixture, CUDA/DPI 168: six English blocks remained identical for 12.0 seconds,
  256 render-state polls and eight injected noisy OCR passes. Worker teardown passed. This test
  initially exposed a false growth signal from dim stars; the final foreground-specific guard passed.
- Full GPU typewriter/transitions run, DPI 168: no partial dialogue publication; complete English
  0.625 seconds after reveal; close-to-hide 0.438 seconds, reopen-to-restore 0.250 seconds. Profile and
  grouping switches, font controls, pause, resize, minimize/restore, CPU restart and shutdown passed.
- Full CPU run with 900 ms artificial OCR delay: no partial dialogue; final English after 1.938
  seconds; close-to-hide 0.375 seconds, before new OCR completed; restore 0.250 seconds. Existing
  English survived 50 continuity polls. The same lifecycle checks passed in 23.69 seconds.
- Offline real GPU OCR at 4K still detected 64 of 80 drawn labels, with raw spelling variants retained.
  Visual and source-review costs are recorded in [performance](performance.md). Local Sugoi's offline
  check also passed with connections blocked (94 ms sample batch). Saved live JSON accompanies the
  synthetic screenshots for reproducibility.
- The user's monitor recording was visually inspected; it includes camera motion and English boxes,
  so it was not treated as clean source capture. Exact live Honkai behavior and game FPS remain
  unverified. No model/download/setup changes are needed to try the updated launcher.

## Live Windows check

Run `uv run python tools/verify_windows.py` on an unlocked Windows 11 desktop. This creates and
captures only the project's own animated fixture, shows a nonactivating sample overlay, moves and
resizes the fixture, minimizes it, stops/restarts capture, and closes the source. It prints JSON
evidence and exits nonzero on failure. A hard deadline bounds the verification process.

The check verifies client-corner colors, overlay bounds, input-transparent/nonactivating styles,
capture exclusion, source resize, minimize policy, session restart, and native teardown. This does
not synthesize mouse clicks: actual click-through must additionally be checked interactively.

Restricted desktop sandboxes may reject GraphicsCaptureItem creation even for our fixture. Run
the live test in a normal desktop process; that environment limitation is separate from application
compatibility. Fast checks remain sandbox-compatible.

## Interactive acceptance

1. Launch the app and open its demo window. Select the demo in the window list.
2. Start capture. The preview should contain Japanese text, numbered boxes, and matching text rows.
   Pause, select a row, enable character boxes, zoom, and copy text. Verify image/boxes stay together.
3. Resume and switch to the demo. Check English placement and mouse pass-through while interacting.
   Toggle **Automatic text size**, adjust manual size/opacity, and switch decoding profiles. English
   should remain readable; hovering/copying a table cell should expose full overflow text.
4. Turn **English overlay** off, then compare **Stabilize game boxes** on/off. IDs should survive OCR
   ordering changes; raw preview positions still follow each analyzed image. Turn English back on
   and confirm the model reloads. In game, inspect genuine movement and disappearing text.
5. Move, resize, minimize, and restore. Switch focus to another app; the overlay must hide.
6. Stop/start capture and close the target. Controls should recover and the overlay must disappear.
7. Repeat with a game in windowed or borderless mode. Record resolution, DPI, capture mode, and
   observed behavior. Do not infer publisher approval or broad anti-cheat compatibility.
8. Revisit a scene where OCR alternates between close spellings or includes a nearby icon. Weaker
   variants should retain English and box geometry even though the raw inspector changes. Verify
   new dialogue, numbers, and typewriter growth still update; a sustained similar edit may take
   about 1.25 seconds to override an older, stronger reading.

## Recorded evidence on 2026-11-13

- Fast checks: 20 tests passed; Ruff and Pyright passed.
- Live fixture: client 1350 × 870 at DPI 144 (150%), resized to 1140 × 750. Client corner markers,
  physical overlay bounds, native styles, clean source capture, minimize policy, and teardown passed.
- Final lifecycle run: client 1575 × 1015 at DPI 168 (175%), resized to 1330 × 875. The same checks
  passed, plus capture restart and teardown after source destruction. It completed in about two seconds.
- After the final lifecycle guards changed, the check passed again at DPI 96 (100%), with client
  900 × 580 resized to 760 × 500. These are separate scale-factor tests, not a mixed-DPI move test.
- Main UI: window selection, demo launch, start capture, and live preview inspected through Computer Use.
- User-selected game session: preview observed at 3840 × 2160, DPI 168 (175%), approximately 3.5–3.8
  samples/s during observation. The user explicitly confirmed alignment and mouse click-through.
- Exclusive fullscreen, HDR color accuracy, prolonged memory stability, low-end hardware, and actual
  cross-monitor mixed-DPI transitions remain unverified. Azur Promilia has not been tested.

Read the [milestone record](plans/001-capture-overlay.md) for the completed scope.

## OCR milestone evidence on 2026-11-13

- Fast checks: 32 tests passed; Ruff and Pyright passed. Qt test objects are explicitly destroyed
  before Python finalization to avoid an intermittent native shutdown abort with the combined suite.
- Offline real-model fixture: all three phrases matched after NFKC width normalization. The raw
  question mark was `?` instead of `？`; raw recognition remains unchanged in the inspector.
- Replay inspection image and live inspector layout visually reviewed. The live fixture recognized
  `新しい冒険が、ここから始まる。`; English fixture text had errors, which remain visible.
- Live OCR integration at DPI 168 (175%): Japanese recognition, pause while capture continues,
  resize alignment, minimize clearing, restore, restart, and close all passed in about 3.4 seconds.
- Final integration also passed at DPI 96 (100%) after the rendering/shutdown adjustments.
- Native capture/overlay regression passed again at DPI 168, including capture exclusion and styles.
- No new real-game OCR accuracy claim is made. The previous user confirmation of click-through
  and alignment applied to milestone one. Follow the interactive review above for game OCR.

See [OCR milestone status](plans/002-ocr-inspection.md) and [measurements](performance.md).

## Tracking slice evidence

- User reported excellent OCR in their own test, and requested correction of repeated box jitter.
- 56 fast tests passed with Ruff/Pyright. `tests/test_tracking.py` replays deterministic observations
  with explicit times; no model or game is needed. `tests/test_inspection.py` verifies repaint suppression.
- Live OCR at DPI 96: repeated observations kept the Japanese dialogue ID and exact bounds; raw/stable
  toggles, pause, resize, minimize/restore, restart, and worker teardown passed in about four seconds.
- Final live integration also passed at DPI 168 after adding static-frame settling.
- Native capture/overlay regression passed at DPI 96, including exclusion and input-transparent styles.
- The jitter heuristics have not yet been confirmed by the user in the original problem scene.

See [tracking slice](plans/003-stable-tracks.md).

## Translation slice evidence (2026-11-13)

- 72 fast tests passed with Ruff and Pyright; no model downloads or live desktop required.
- Offline Sugoi load and three-phrase inference passed with socket connections blocked. Fast CPU
  translated `新しい冒険が、ここから始まる。` as `A new adventure begins here.`; the live Wider search
  profile returned `It was time for a new adventure.`. Different decoding is not guaranteed better.
- Full Windows integration passed at DPI 168: Japanese recognition, unchanged track ID/bounds,
  English after backend swap, automatic/manual sizing, pause while capture continued, resize,
  minimize/restore, restart, and cleanup. The observed run completed in about 7.4 seconds.
- The final integration also passed at DPI 96 in about 6.6 seconds, including assertions that
  capture, OCR, and translation all finish on stop/close. These are separate scale-factor runs,
  not a cross-monitor mixed-DPI transition test. The offline real-Meiki regression also passed.
- The native fixture passed alignment, source exclusion, input-transparent/nonactivating styles,
  minimize/focus policy, restart, source closure, and teardown in about two seconds at DPI 168.
- English overlay and raw/English inspector widget artifacts were visually reviewed. Only the
  translated Japanese region was covered in English mode; English fixture labels stayed untouched.
- Real-game English quality, collision handling in dense UI, sustained memory, mixed-DPI movement,
  and frame-time impact remain unverified. No new interactive mouse click-through claim is made.

See [translation slice](plans/004-local-translation.md) and [performance observations](performance.md).

## Confidence stability slice evidence

- The user reported good real-game translation results but repeated flicker from small OCR edits.
- 101 fast tests passed with Ruff and Pyright. Replays verify preferred-reading memory, stable
  geometry/revisions through weaker/equal alternatives, stronger promotion, and genuine-change
  escape paths. Missing/invalid confidence, distinct tracks, lifecycle resets, and misses are covered.
- A tracker-to-translation integration replay kept the existing English available through ten
  cycles of noisy readings and invoked the backend only once.
- Offline Meiki verification passed with connections blocked and all three expected phrases matched.
- Full live integration passed at DPI 168 in about 7.8 seconds, including English after backend
  switching, font controls, stable IDs/bounds, pause, resize, minimize/restore, restart, and shutdown.
- The original game's flickering scene still needs user confirmation with this policy. No new
  compatibility or game frame-time claims follow from the synthetic checks.

See [confidence slice](plans/005-confidence-stability.md).

## Icon and dialogue slice evidence

- 136 fast tests passed with Ruff and Pyright. The supplied button was recognized cleanly as a crop
  and at 1080p, but emitted a low-confidence `中`/`@` and a wider detector box when placed in a 4K
  canvas. Numeric OCR observations are checked in; game pixels are not. Alternating these observations
  now preserves the exact public track object and clean source text.
- Tests cover punctuation/numeric protection, interior/strong glyphs, incomplete metadata, group
  ordering/limits, menus/choices/speakers/columns, readiness, all-member invalidation, whole-group
  copying, and font height. A worker test verifies one combined request and rejects a stale reply
  when only the second line changes.
- Offline real OCR and Sugoi checks passed. Live `--translation --dialogue` at DPI 168 passed with
  two source lines translated together and the speaker separate. Model/profile switching, grouping
  off/on, pause, font controls, resize, minimize/restore, restart, and shutdown passed in about seven
  seconds. Inspector/overlay artifacts were visually reviewed. Native exclusion, physical geometry,
  input-transparent styles, focus/minimize policy, restart, and teardown passed separately.
- The live harness now reports assertion types/tracebacks and exits nonzero even for exceptions with
  an empty message. It waits for a regrouped passage to settle and freezes the actual displayed frame
  after event processing, avoiding false failures from other blocks finishing first or newer OCR.
- The original live-game button and broader dialogue layouts still require user evaluation. The 4K
  reconstruction is evidence for this case, not general icon detection or game compatibility.

Manual review: revisit the supplied button, compare raw character boxes with the English tooltip's
source, then inspect wrapped dialogue and toggle grouping. Confirm a speaker/choice stays separate,
full paragraphs copy once, and new dialogue clears old English. See
[current slice](plans/006-dialogue-grouping.md).

## Busy-screen persistence evidence

- 151 fast tests passed with Ruff/Pyright. The old 800 ms timeout was reproduced by an 80-label,
  1.1-second OCR replay. New replays retain IDs, geometry, group membership, and English through
  slow passes and two-pass dropouts. Duplicate polling/skipped captures never add absence votes.
- Pixel tests retain text through repeated misses with unchanged crops, ignore animation outside
  the box, remove confirmed changed/absent content, and prevent a new revision reusing old evidence.
  Work budgets, invalid frames, orientation outliers, dense reordering, and truncated input are covered.
- Offline Meiki and Sugoi passed with socket connections blocked. Dense Meiki returned 64 regions
  from 80 labels with some spelling variants; final warm median/max 468/485 ms. Tracking with pixel
  hashes measured 8.53/9.19 ms. These observations do not claim dense-game OCR accuracy.
- Live translation/dialogue at DPI 168 passed with 900 ms injected latency per OCR call, including
  49 English continuity checks over at least three seconds, model/grouping toggles, pause, resize,
  minimize/restore, restart, and teardown. Total 15.44 seconds; inspector artifact reviewed. This
  simulates slow inference without claiming equivalent game CPU contention or actual scene coverage.

Manual review: repeat the crowded scene, then change menus/dialogue. Confirm persistence and genuine
removal; record OCR duration and current-pass time if a delay remains. See
[current slice](plans/007-evidence-based-persistence.md).

## Responsive OCR evidence (2026-11-13)

159 tests passed in both isolated environments; Ruff and Pyright passed. CPU/GPU offline OCR and
CPU Sugoi inference passed with Python sockets blocked. CUDA profiling recorded 4,422 GPU and
222 CPU detector node executions, plus 4,752 GPU and 288 CPU horizontal-recognizer executions
across six sparse passes. The vertical model was loaded but not exercised by this fixture.

The live typewriter GPU check used a fresh translation cache and showed the final combined English
0.75 seconds after the last character, with no partial requests during reveal. GPU-to-CPU selection,
profile/grouping toggles, font controls, pause, resize, minimize/restore, restart, and shutdown passed
at DPI 168. The CPU typewriter check passed as well (its earlier run reused the synthetic cache).
The 900 ms slow-CPU regression preserved English across 49 continuity checks for at least three
seconds. Screenshots of our fixture/inspector were reviewed. Game-frame-time and other-GPU claims
remain unverified. See [slice eight](plans/008-responsive-ocr.md).
## Model management / AMD / context checks (2026-11-13)

Run `tools/verify_setup_windows.py` in a Gemma-capable environment with local models installed.
It uses only the app/demo, simulates Yes/No clicks, and does not write real preparation receipts.
It verifies capture without models, installed choices, decline restoring No translation, a responsive
preparation dialog, one model load reused for capture, No translation unloading, and shutdown.

Current evidence: 248 behavior tests plus Ruff/Pyright passed in CPU, CUDA and isolated AMD
environments. Download tests cover explicit invocation, hash/size mismatch, atomic publication,
cancel cleanup, verified-file reuse and failure reporting. A real pinned 29,260-byte model metadata
download also passed. GUI tests include a nested consent event loop and close during download.

CUDA and Vulkan actual inference ran with Python socket connections blocked. Context changed a
synthetic name from Lina to the previously established Rina. Full native dialogue/typewriter,
backend switches, debug, pause/resize/minimize/restart and cleanup passed in both runtime packages.
The Vulkan native run used checked CPU OCR fallback; it is not evidence of DirectML GPU accuracy.
DirectML 1.24.4 and 1.23.0 produced wrong Meiki outputs; the compatibility guard reports this and
automatic mode uses CPU. Strict DirectML intentionally fails on this machine.

Slow CPU OCR (900 ms injected) and unchanged-label regional appearance regressions passed.
Setup/dialog/overlay fixture screenshots were visually reviewed. No game, discrete Radeon,
mixed-DPI transition, or general name-consistency guarantee follows from these synthetic checks.
Artifacts live in ignored `artifacts/setup`, `artifacts/context` and `artifacts/amd`.

For friends: open Settings → Models & runtime → Acceleration, select AMD, install, then restart.
Download models in the Models tab, select Gemma and accept preparation. The in-app AMD profile uses CPU OCR. If using the
legacy experimental DirectML package, record the actual
provider/fallback reason and use `--device directml` for strict verification, never `auto-directml`
as evidence of GPU execution. Report GPU/driver, model load time and warm inference timings.

### Clean distribution runtime discovery regression

The user's fresh copy contained complete Meiki/Gemma files, CPU ONNX Runtime, no llama runtime,
and no CUDA OCR runtime. File detection succeeded; composition silently removed Gemma because its
runtime was absent. The resulting disabled controls and generic “downloaded” status concealed the
real requirement. This was reproduced from that copy before the user deleted it.

Downloaded Gemma now stays visible with a setup reason. Selecting it explains the missing runtime
without changing the active backend or invoking a factory. Download completion and the Models
dialog distinguish verified files from runtime readiness; OCR help explains that Automatic requires
GPU packages rather than Meiki files alone. Model folders are shown for checking multiple copies.

255 tests passed with Ruff/Pyright, including discovery before/after file arrival, missing/present
CUDA/Vulkan runtimes, Sugoi independence, unavailable selection, and post-download status. A new ZIP
was extracted into an isolated project and installed with only the default CPU dependencies. Existing
verified Meiki/Gemma files were linked as test inputs (not downloaded again). Native
`verify_setup_windows.py --missing-runtime` passed there. Installing the pinned NVIDIA runtime in
that same extracted project made Gemma and Automatic OCR discoverable without changing model files.
The native preparation/capture/translation/unload check then passed; first-use preparation kept the
event loop responsive for 719 timer polls (roughly 36 seconds). Runtime dialogs were visually reviewed.
Strict CUDA OCR also passed in the extracted project with socket connections blocked: first-use
inference/preparation took 51.4 seconds, followed by a 25.3 ms warm median. The GPU-launcher receipt
was written only after this check succeeded, matching the setup script's gating behavior.

Run the missing-runtime check with a genuinely CPU-only environment and downloaded Gemma. Testing
only in the development environment, where every optional runtime is installed, misses this failure.

## In-app runtime setup checks (2026-11-13)

`tools/verify_runtime_windows.py --profile nvidia` must run from an extracted distribution under
`artifacts`, never a user's installed copy. Repeat with `--profile amd` and `--profile cpu`.
`--offline --cache-root <development-root>` restricts uv to already cached dependencies and Python;
this tests packaging/installation, not a cold internet download. It opens Settings → Models & runtime → Acceleration,
checks detection without automatic installation, presses Install, observes GUI timer progress,
restarts through MainWindow into the chosen environment, and closes only the verified child window.
The normal launcher uses the same acknowledged-startup path. Windows venv launchers and app windows
can have distinct PIDs; tests use the acknowledged app PID for native window cleanup.

NVIDIA, AMD and CPU installs/restarts passed in the extracted CPU-only distribution. The environments
used the existing Meiki/Gemma files. Actual strict CUDA OCR passed in the app-installed NVIDIA runtime
with sockets blocked (29.1 ms warm median; already warmed kernel cache). The downloaded-Gemma/no-runtime
native regression passed; Gemma consent/preparation/worker reuse/unload/shutdown passed in the new
runtime with 63 responsive preparation polls. Actual Vulkan translation and bounded context also
passed in the new AMD runtime with sockets blocked, using the RTX 5080. These are synthetic checks,
not game or Radeon results.

Fast tests cover vendor selection on mixed integrated/discrete PCs, exclusive profile groups,
explicit activation, stale/corrupt/escaping receipts, cancel/probe failure retaining the old runtime,
repair without mutating existing libraries, child output/error/cancellation, no implicit install,
closing during setup, worker-draining restart and launch failure recovery. Model preparation remains
a separate consent step; package/library probing alone is not full model validation.
Final checks: 273 tests passed; Ruff formatting/lint and Pyright passed. Runtime setup screenshots
were reviewed. Cancel testing includes an installer that spawns a sleeping child, and verifies both
are stopped. At that stage the proposed UI was separate from product code; it is implemented below.

## Compact UI, Settings and independent inspection (2026-11-13)

`tools/verify_ui_windows.py --output artifacts/ui-redesign` checks native switch keyboard handling,
compact/expanded geometry, nonmodal Settings reuse, all tabs, small-window scrolling, accessible
information controls, saved opacity/font values and shutdown. It captures only its own widgets.
The Settings and main layouts were visually reviewed at DPI 168. This is not mixed-monitor testing.

287 model-free tests, Ruff formatting/lint and Pyright passed. New behaviors cover validated/default
preferences, preservation of malformed/newer files, atomic write failures/retry, coalescing off-thread
writes, no implicit model preparation on restore, stable Gemma IDs across runtimes, staged device/rate
changes, background setup/cancellation and app shutdown. Hidden inspection performs no frame-image
conversion/table build; pause freezes both inspector languages while live reconciliation/acknowledgement
continues. Translation off shows no numbered boxes unless explicitly requested.

The CUDA/Gemma live demo with dialogue/typewriter/transitions/debug passed model swaps, grouping,
pause, resize/minimize/restart and worker shutdown. Complete dialogue appeared 0.813 s after the last
character in this synthetic run. The pause-render assertion controls foreground eligibility because
the fixture deliberately does not steal focus; real foreground/minimize policy is checked separately.
The native capture regression passed input-transparent styles, capture exclusion and geometry checks.

`verify_retention_windows.py --device cuda --appearance` now collapses and reopens Advanced during
injected OCR noise. Six English blocks stayed unchanged across 348 polls/16.31 s, including six noisy
passes; a new regional label appeared in English after 0.469 s without disturbing existing blocks.
These are fixture measurements, not a promise of Honkai latency.

Native model preparation/decline/worker reuse/unload passed. A freshly packaged source tree was
extracted into the disposable CPU-only distribution; downloaded Gemma remained selectable with a
clear acceleration action and no unavailable model load. NVIDIA and AMD profile reuse/verification
and acknowledged restart through Settings both passed using cached installed environments. This
rerun does not claim cold dependency downloads, Radeon execution, or game/anti-cheat validation.

### UI feedback: large windows, model status and switching

`verify_ui_windows.py` now checks maximized compact/Advanced layouts, a bounded top-left control
column, retained maximize state, readable model descriptions, and downloaded badges. Run with
`--missing-models` for first-run warnings. Native captures were reviewed in the CUDA environment,
the CPU environment with missing model paths, and the extracted CPU-only distribution with Gemma
downloaded but no runtime. The latter shows both a green download badge and an acceleration warning.

301 fast tests pass with Ruff/Pyright. New cases cover one background hardware/package check and
shutdown draining, NVIDIA CPU selection/fallback, AMD Vulkan with intended CPU OCR, missing download
versus missing selection, and badge updates after download. A real worker + temporary SQLite GUI
test publishes Sugoi, holds a second reply in flight, switches to Gemma while inspection is paused,
and proves immediate display revocation, late-result rejection and Gemma-only output. Switching
back reuses only Sugoi's cache. A separate publication test rejects retention across worker/model
generations. No Sugoi/Gemma persistent cache-key collision was reproduced.

The native CUDA/Gemma dialogue/typewriter/debug/model-switch check passed (0.75 s after final
character in this fixture), as did offline socket-blocked Gemma translation and native preparation
consent/worker reuse. Retention held six blocks unchanged across 344 polls/16.12 s and six noisy
passes, including Advanced collapse/reopen; a new regional label appeared in English after 0.562 s.
The extracted downloaded-Gemma/no-runtime regression and NVIDIA runtime reuse/restart passed with
the new startup hardware check. These measurements use our synthetic windows, not Honkai or Radeon.

## Global hotkeys (2026-11-13)

`tools/verify_hotkeys_windows.py --output artifacts/hotkeys` runs real RegisterHotKey/WM_HOTKEY
delivery with DanteJP minimized and a separate owned demo process in the foreground. It verifies
capture frames arrive, hiding/showing preserves capture and focus, repeated key-downs toggle once,
another process's conflicting shortcut preserves the old binding, rebinding releases the old key,
stop drains, restart uses the same selected source, and shutdown releases all registrations.
Only its own foreground HWND/PID may receive synthetic input; it aborts rather than typing into
another app. The fixture requires no models, records only its own widgets, and closes its child.
Settings → Hotkeys was visually reviewed at DPI 168. This is not mixed-DPI or game-input testing.

316 model-free tests, Ruff formatting/lint and Pyright passed. Coverage includes old-preference
defaults, disabled/rebound persistence, drafts not being saved, native and duplicate conflicts,
stale messages, both Qt Windows routes, rollback on failed release, modal/stop/close guards, no
substitution of a closed selected window, and failed-runtime-restart reacquisition.

Native UI and model setup/preparation regressions passed. The CUDA/Gemma dialogue/typewriter/debug
regression passed with grouped English, model switching, pause retention, resize/minimize/restart
and drained shutdown (0.687 s after final character in this fixture; not a speed claim for hotkeys).
In the disposable extracted CPU distribution, the NVIDIA runtime reuse/restart check now also
registers saved shortcuts in the parent, proves they are released before launching the child,
proves the child owns those exact shortcuts, and verifies release after its clean exit.

No Honkai, exclusive-fullscreen, elevated-game or anti-cheat compatibility is inferred from these
fixtures. A game's input handling may reserve a chosen chord; users can select a different one.

### Focused capture and hold-to-show-original follow-up

325 model-free tests, Ruff and Pyright pass. New cases cover foreground selection from an empty
picker, no retargeting while capturing, explicit selected-window mode, rejected shell/own/tool and
closed windows, focus/PID races, persisted settings, hold repeat suppression, delayed key-downs,
key/modifier release, rebind/disable/stop/close cleanup, focus loss and idle release-timer shutdown.

The native hotkey fixture starts with an empty disabled picker, selects its separate foreground
demo by keypress, captures through a held show-original chord, then observes release by modifier
and main-key up. The modifier release was observed at 63 ms with the fixture's 50 ms observation
timer; this is not an inference-latency measurement. Focus loss cancels the held state. The Settings
layout with all three shortcuts was visually checked at DPI 168 (`artifacts/focused-original`).

The CUDA/Gemma live dialogue/typewriter/debug check now verifies actual English stays accepted
through the original hold, the overlay is immediately visible on release, all capture/OCR/visual/
translation worker objects remain identical, and an explicitly hidden overlay stays hidden.
Native alignment/click-through, compact/Advanced UI, model preparation and extracted NVIDIA runtime
restart also pass. Runtime handoff checks all three saved registrations and their final release.
These fixtures do not establish Honkai or anti-cheat compatibility.

## DanteJP branding (2026-11-14)

325 tests, Ruff formatting/lint and Pyright passed after the rename. The native UI check passed;
the renamed main/Settings/demo presentation was reviewed using our fixture (`artifacts/dantejp/ui`).
The new `dantejp-windows.zip` contains a `DanteJP/` root and all three Run DanteJP launchers; its
136-file manifest hashes were checked, with models, caches and personal data excluded. An update
of source files in the existing disposable distribution reused the exact installed NVIDIA runtime
offline, restarted the renamed app, transferred all three hotkeys and exited cleanly. Project
metadata, dependency lock, model/settings paths and runtime fingerprints remain unchanged.

## Standalone Windows package (2026-11-14)

`tools/build_standalone.py --offline` builds a native GUI launcher, private CPython and locked CPU
dependencies. `tools/verify_standalone_windows.py --output artifacts/<new-directory>` extracts the
release, verifies all 6,784 manifest entries and the Windows GUI subsystem, removes Python/tools from
PATH, launches the actual EXE from a path containing spaces/Japanese, observes Qt startup and closes
only the owned app. `--bundle artifacts/<extracted>/DanteJP` rechecks an existing extraction using a
new isolated AppData profile. Native library imports, AppData receipt/logs, no implicit downloads,
no writes inside the app folder and clean shutdown passed (`artifacts/standalone-launch`). Untouched
defaults need not create a preferences file; the native UI check separately verifies saved edits.

329 tests, Ruff formatting/lint and Pyright passed. New cases cover source compatibility, AppData
model paths, absolute state overrides, packaged installer/managed Python selection, current source
after relocation and dependency invalidation. A preparation test now polls the GUI while waiting for
the previous worker to drain, avoiding an assumption that one tick is sufficient under build load.
Some host Windows Temp runs stalled in background file/SQLite operations. The final complete check
used `PYTEST_ADDOPTS=--basetemp=artifacts/standalone-check-final` and passed all 329 tests in 3.55 s;
the isolated translation suite also passed with workspace temp files. No app timeouts were relaxed.

The extracted private CPU interpreter passed native UI/Settings/persistence and capture/alignment/
click-through checks, plus downloaded-Gemma-without-runtime handling. A real Models download-button
test downloaded all 45,970,040 Meiki bytes, verified them and displayed the downloaded badge in test
AppData (`artifacts/standalone-download`); other inference weights were read-only links to existing
test models, never part of the ZIP. Screenshots contain only our own fixtures.

In-app NVIDIA and AMD installation/probe/restart passed from the packaged CPU interpreter. These
tests reused cached wheels and seeded managed Python for offline verification; the resulting venv
base is in test AppData, not the bundle or a system Python. Restart transferred all three hotkeys
and clean exit released them. The AMD profile checked Vulkan on the RTX 5080, not a discrete Radeon.
Gemma consent/preparation/worker reuse and live CUDA OCR + Gemma/Sugoi switching passed in the new
AppData NVIDIA environment. The live fixture reported CUDAExecutionProvider and full dialogue
English 0.75 seconds after the last character; this is not a Honkai latency guarantee.

After moving the extracted folder, the real EXE selected the saved AppData GPU runtime with Python
absent from PATH. Temporarily invalidating only the fixture's ready receipt selected bundled CPU
instead and preserved the saved selection (`artifacts/standalone-moved`). Bootstrap exposes the
active runtime's app-local VC libraries before native imports, including fresh child probes.

This is host-side isolated verification, not a clean Windows VM, Radeon, game or anti-cheat test.
The release is unsigned. Cold dependency internet downloads were not repeated; the model download
used the actual pinned network URLs. No personal models/preferences, screenshots or GPU caches ship.

## Shared CUDA 13 (2026-11-14)

An isolated candidate under `artifacts/cuda13/candidate` installed ONNX Runtime 1.30.0,
cuDNN-cu13 9.13.1.26 and the pinned CUDA 13.0 library set while retaining the same Gemma build.
The six newly needed wheels were downloaded from their pinned sources; common dependencies were
cached. Existing `.venv-gpu`, the CPU native packages and actual user AppData were not modified.
The 1.26 compatibility path remains available for the older development environment.

The before/after Windows wheel inventory in `artifacts/cuda13/download-sizes.json` reports
2,261,945,327 → 1,285,413,768 bytes for NVIDIA/ONNX packages: 976,531,559 bytes (43.2%) less.
Model weights, llama.cpp, common dependencies and Python are excluded from those totals.

Strict CUDA dense OCR returned identical text/bounds for all 64 detected regions on the synthetic
80-label 4K fixture. Warm full-frame medians were 166.2 ms before and 149.8 ms after; cropped-region
medians were 18.3 ms and 17.4 ms. These are single fixture runs on the RTX 5080, not general speed or
game-accuracy claims. The missing 16 drawn labels were already missing in the baseline.

`verify_translation.py --backend gemma` passed with Python sockets blocked. Fresh-cache Gemma
preparation took 44.3 s; warm short translations took 31–157 ms. `verify_shared_cuda.py` passed both
`--order ocr-first` and `--order gemma-first`: actual OCR and translation succeeded in one process,
without CUDA 12 packages or CUDA 12 runtime/cuBLAS DLLs. It records the loaded paths for CUDA 13,
cuDNN, ORT's provider and ggml-cuda in `artifacts/cuda13/*-first.json`.

The live CUDA/Gemma dialogue/typewriter/transitions/debug regression passed grouping, backend swaps,
pause retention, original hold without worker restart, minimize/restore and shutdown. Complete
English appeared 0.688 s after the final character in that fixture. Runtime changes did not change
tracking, grouping, scheduling or translation settings.

The disposable standalone copy installed a fresh shared-CUDA runtime from cached wheels, preserved
the previous runtime directory, acknowledged Qt restart and transferred/released all three hotkeys.
Packaged preparation consent/worker reuse and real same-process inference/DLL checks also passed.
These checks used existing test model links and isolated AppData, not the user's active installation.

332 model-free tests, Ruff formatting/lint and Pyright passed. New coverage checks correct DLL
families with Gemma alongside legacy OCR, repeated initialization, and failure on missing CUDA 13
dependencies without silently loading the older family. Workspace test temp files were used to
avoid the host's intermittent Windows Temp file-I/O stalls. No Radeon or additional GPU was tested.

The rebuilt standalone ZIP contains 27 CPU distributions and no model weights or GPU environments.
Its 6,784 manifest entries passed verification after fresh extraction to a Unicode path. The real
EXE launched with Python absent from PATH, wrote only to isolated AppData, made no implicit
downloads and drained cleanly (`artifacts/cuda13/final-launch`). The ZIP and SHA-256 sidecar were
refreshed; the download reduction applies to optional runtime setup, not the CPU release ZIP.

## CPU language-model runtime (2026-11-14)

The isolated CPU environment and bundled interpreter use the official llama-cpp-python 0.3.36
CPU wheel, with no CUDA/Vulkan engine or NVIDIA packages. The wheel adds about 7.8 MB; the complete
release grew from 217,046,511 to 225,030,685 bytes with its supporting Python libraries.

Offline CPU Gemma passed the original nine phrases and bounded dialogue-context checks, with
Python socket connections blocked. On the 9800X3D, load plus warm-up took 3.3 s, sample inference
took 109–734 ms, and a process snapshot showed 2,611 MiB working set / 2,076 MiB private memory.
The packaged run took 3.5 s to load and 93–750 ms per sample. These are short fixture measurements,
not lower-end PC or game frame-time guarantees. No other CPU or discrete Radeon was tested.

CPU setup passed capture without models, downloaded/usable CPU badges, the performance notice,
declined preparation without loading, responsive accepted preparation, worker reuse and unloading.
Live CPU OCR/Gemma passed typewriter readiness, grouping, Sugoi swaps, debug/inspection pause,
original hold, panel transitions, resize/minimize, restart and shutdown. Complete grouped English
appeared 1.125 s after the final character. Native layout checks and simulated absent-engine recovery
also passed. Screenshots and timings are under `artifacts/cpu-llm`.

CUDA OCR/Gemma still passed actual inference in both startup orders, shared CUDA 13 DLL inspection,
and live model swapping/dialogue/pause checks. GPU code paths retain their tested decoding/prefill
settings; these runs validate functionality, not a new performance comparison.

The final ZIP contains 31 CPU distributions and no model weights or GPU engines. All 6,928 manifest
entries passed after Unicode-path relocation. The real EXE ran with Python absent from PATH,
wrote only isolated AppData, made no implicit downloads and drained on close. Packaged CPU
preparation/inference and CPU → NVIDIA → CPU setup/restart passed with cached dependencies;
returning to CPU reused its verified environment, preserved both runtimes and transferred/released
hotkeys. Actual user AppData, model files and development GPU environments were not changed.

342 model-free tests, Ruff and Pyright passed. Coverage includes CPU engine discovery without
native imports, missing/incomplete engines, CPU loading without NVIDIA packages, bounded CPU
threads/no offload, CPU selection without forced setup, and CPU/GPU-specific model/cache readiness.

## Separate Settings tabs (2026-11-14)

Models and Acceleration are peer tabs beside Appearance, Recognition and Hotkeys. Native UI checks
passed direct setup/hotkey navigation, lazy runtime creation/reuse, compact scrolling and maximized
Advanced disclosure. Reviewed screenshots under `artifacts/settings-tabs/ui` show one tab bar.
342 model-free tests, Ruff and Pyright passed. Native model preparation and live CPU translation,
dialogue swaps, inspection pause and shutdown also passed. The rebuilt ZIP's 6,928 manifest files
passed Unicode-path relocation with Python absent from PATH. Packaged runtime verification/restart
through Acceleration reused the existing isolated CPU runtime and transferred/released hotkeys.
Only fixture AppData was used; no game compatibility claim or dependency changes accompany this UI edit.
