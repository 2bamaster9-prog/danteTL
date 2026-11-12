# JP Overlay

A local Windows game translation overlay, being built in small milestones.

**Current milestone:** capture a game window, recognize Japanese with MeikiOCR, translate stable
text locally with Sugoi V4 or optional Gemma 4 E2B, and draw English in an aligned click-through overlay.
The inspector keeps raw Japanese, bounding boxes, and English together for review.

## Run

On Windows 11, double-click **Run JP Overlay.cmd**, then open **Settings → Models & runtime → Models**. Download **MeikiOCR**
(46 MB) for recognition and a translation model: **Sugoi V4** (1.11 GB, CPU) or **Gemma 4 E2B**
(3.35 GB, GPU). Use the **Acceleration** tab beside Models to install GPU support inside the app.
The translation dropdown
lists downloaded models. Gemma stays visible as **runtime setup needed** if its GPU runtime is
missing; selecting that entry opens runtime setup. **No translation** is always available.
Capture works even with no models; English appears only after selecting a translator.
Downloads show byte progress, support cancellation, and check pinned SHA-256 hashes before files
become usable. Retry keeps verified files; an interrupted individual file restarts. Processing works
offline after setup. The older **Setup OCR.cmd** / **Setup Translation.cmd** shortcuts still work.
Setup requires Python 3.12 or later on PATH to bootstrap uv; uv installs the pinned Python 3.12
runtime locally if needed. Nothing is installed into your global Python environment.

**Downloaded model but no English / no Automatic OCR?** Model files and GPU runtimes are separate.
Open **Settings → Models & runtime → Acceleration**. The app detects graphics cards and recommends a runtime;
you can choose manually. **Install runtime** downloads pinned dependencies into a separate local
environment, shows stage progress, and checks native libraries. **Restart now** stops capture,
waits for current work, and opens the new runtime. **Use on next launch** keeps this session running.
The normal **Run JP Overlay.cmd** remembers the choice. No separate GPU setup scripts are needed.
The Models tab distinguishes downloaded files from runtime readiness and shows their folder.
It reuses your downloads; reinstalling or redownloading model weights is unnecessary. The CPU
launcher intentionally uses the CPU OCR environment; it does not inherit packages from the GPU one.

The **NVIDIA** option installs CUDA OCR and Gemma support (several GB including dependencies).
The **AMD** option installs Vulkan Gemma and **CPU OCR**. It does not install experimental DirectML:
that provider produced incorrect Meiki results on the development machine. Vulkan setup and inference
were checked on the RTX 5080; a discrete Radeon still needs testing. **CPU** provides MeikiOCR/Sugoi.
No system CUDA toolkit or server is needed. Graphics drivers must already support the chosen runtime;
setup never installs or updates drivers. Hardware detection is a recommendation, not a compatibility
guarantee. Multi-GPU users can override it.

Runtime installation uses an indeterminate bar with actual stage/package updates; it does not invent
a download percentage. Cancel/failure keeps the running environment and model files. A failed install
can be retried; **Verify / repair runtime** checks an existing install and creates a separate replacement
if needed. A failed restart leaves the old app available. CPU fallback remains accessible through
**Run JP Overlay CPU.cmd**. Replaced runtimes are retained in `.runtimes` for recovery, so repeated
repairs can consume extra disk space. All processing after setup stays local.

Library checks do not load models. The first OCR GPU load can take about a minute to compile kernels;
its loading status stays visible. Gemma has the preparation flow below. A bounded cache under
`data/cuda-cache` is reused; driver/kernel changes may require another warm-up. Legacy setup scripts
remain available for development but are not required by the in-app acceleration flow.

Selecting an unprepared Gemma model asks **Prepare now?** Choosing No restores the previous model
or No translation. Yes shows a responsive progress dialog while checking weights and warming the
GPU. It uses an indeterminate bar because the runtime cannot report a reliable percentage. The
prepared worker stays loaded for capture. Preparation receipts are local to the machine/runtime;
driver changes can still require warm-up, shown as loading. Nothing downloads during preparation.

Gemma keeps at most **two recent dialogue exchanges / 512 characters** within its existing
2,048-token allocation. Only one likely dialogue panel owns history; short menu labels remain
independent. History expires after 30 seconds, prolonged panel absence, panel relocation, broad
scene changes, or session reset. It is a conservative heuristic, not a speaker/name glossary.
Context is part of cache identity, so unrelated conversations cannot reuse contextual answers.
Its weights are Apache-2.0; Sugoi retains its separate licensing. See
[the current slice](engineering/plans/012-model-management-and-context.md) for measurements.

To share, run `python tools/package.py` and send `dist/jp-overlay-windows.zip`. This is a small
**source/setup package**, not a frozen executable: unzip into a writable folder and use the launchers.
It excludes weights, environments, caches, screenshots and logs. Python/uv bootstrapping is still
needed on the recipient's PC; optional runtimes and models are installed from inside the app.

Alternatively, with uv installed:

```powershell
uv sync --locked
uv run python tools/setup_models.py
uv run python tools/setup_models.py --translation
uv run jp-overlay
```

For Gemma with the CLI, add `--group gemma` to `uv sync` and `uv run`, and install its model with
`uv run --group gemma python tools/setup_models.py --gemma`. The `.cmd` launchers use the installed
environment directly. Keep CPU and GPU OCR dependency groups in their separate environments.

Choose a window and select **Start capture**, then switch to the game. OCR and translation load in
the background. **Translation overlay** is enabled by default; translated regions cover the original
text with a translucent background. Regions awaiting translation leave the original text visible.

The main window contains the game picker, Start/Stop, **Show game overlay**, **Translation overlay**,
and the model selector. **Settings…** opens a separate window; **Advanced** expands the inspector and
detailed diagnostics. Setup errors and model loading remain visible even with Advanced collapsed.

- **Settings → Appearance** contains stabilization (on by default), background opacity, and text size.
  **Automatic text size** estimates the source height and wraps English with limited shrinking.
  Turn it off to set a fixed size in physical pixels. Opacity changes apply immediately.
- **Settings → Recognition → OCR device** selects available NVIDIA/DirectML acceleration with CPU
  fallback, or CPU only. Device and capture-rate edits apply **next time capture starts**; current
  capture continues uninterrupted. Advanced reports the actual provider and any fallback reason.
  **Capture rate** ranges from two to twelve samples/second and defaults to eight. These captures
  feed cheap visual checks; they do not each trigger OCR. Increasing capture rate improves visual
  response but increases frame-copy/analysis cost and cannot make a busy OCR model faster.
- **Sugoi V4 · Fast CPU** is the default. **Wider search** uses the same weights with more decoding
  candidates; it can take longer and is not guaranteed to improve every sentence. Switching safely
  unloads the previous backend before loading the selected one.
- **Gemma 4 E2B · NVIDIA/Vulkan GPU** uses an instruction-tuned LLM. It can produce more natural
  UI labels and dialogue, but quality still needs review in the actual game. Each completed label
  publishes immediately; the source-specific cache remains separate from Sugoi.
- **Advanced → Debug overlay** adds amber cells for significant visual changes and cyan dashed outlines for
  the **last completed OCR scan**. The panel shows OCR/translation times, queue waits, active call
  age, cache/model counts, and dialogue settling/reveal holds. Cyan coverage can remain after the
  scene changes: read its result age. Debug does not change scheduling or save game text/images.
- Translations are reused from a bounded memory cache and local SQLite database. Moving a box
  does not retranslate its text. Brief OCR jitter keeps the last committed English until a real
  change is confirmed; changed/removed text rejects late results.
- For small OCR variations in nearly the same position, the tracker remembers the highest-confidence
  reading. Weaker/equal alternatives keep its text and box unchanged; a confirmed stronger reading
  becomes the new preference. Numbers, short labels, and typewriter growth use normal confirmation.
  A consistently changed alternative can still replace the old reading after about 1.25 seconds.
- Turn **Translation overlay** off to unload translation and leave the game unobscured. To inspect
  numbered game boxes, explicitly enable **Advanced → Show OCR boxes**. **Stabilize game boxes**
  in Settings can then be toggled for comparison. English always uses stable tracks.
- **Settings → Recognition → Group dialogue lines**, on by default, joins likely wrapped dialogue before translation
  and draws one English box. Disable it if unrelated lines group together. Short speaker names,
  marked choices, and separate columns remain separate under the conservative rules.
- Revealing dialogue waits for its text to settle before new translation work is scheduled. Likely
  continuation lines join while they are still appearing, avoiding a second grouping delay at the
  end. Existing, revision-valid English remains visible while readiness changes. A long pause in
  unfinished text can still look like completion; this is a timing heuristic.
- Visual checks watch known text and the space where dialogue can continue. Small stroke additions
  can hold an obsolete partial translation before OCR recognizes the new line. A revealed paragraph
  may contain multiple sentences; a period alone no longer splits a paragraph that was growing.
- Closing a menu can hide its English after two visual checks find its text pattern gone, even
  while OCR is busy. Identity/cache entries stay available until OCR confirms absence; strong fresh
  visual absence plus one negative OCR pass can free old display slots promptly. Brightness shifts
  and hover color inversions are tolerated. Ambiguous cases keep the slower OCR evidence rules.
- Tracking uses recognized-character bounds so a detector box expanding over an icon does not
  automatically resize English. Isolated weak edge glyphs beside strong Japanese text can be
  excluded. Raw OCR remains unchanged in the inspector for comparison.

Settings save automatically in `data/preferences.json`. A successful model choice is remembered
without loading it at startup; first-use preparation still requires consent. Info buttons explain
each setting on hover, keyboard focus or click. Closing Settings during setup offers background
continuation or cancellation; closing the app always cancels/drains setup before exiting.

The **Advanced** inspector displays the exact analyzed frame, numbered line boxes, raw OCR, and matching English:

- Select a text row to highlight its box and see physical coordinates/orientation.
- Use **Pause inspection** to freeze the frame and both languages while capture and translation continue. Resume picks up
  the newest frame. Minimize, resize, or stopping clears the review so stale imagery is not retained.
- Use **Character boxes** and **Fit / 100% / 200%** zoom to examine small text; scroll when zoomed.
- **Copy Japanese / Copy English** copies the selected row, or all rows when none is selected.
  Hover a row for full text. English that cannot fit the overlay ends with an ellipsis; the full
  translation stays available in the table.
- Group continuations display **↳ Group #ID**. Hover an English cell to see the cleaned/grouped
  Japanese source actually translated. Copy English from any member copies the whole translation;
  copying all rows includes each group once.
- Confidence is the mean recognized-character score, not a probability of sentence correctness.
- The overlay may briefly lag; use the frame-matched preview when checking OCR accuracy.
  Hiding or pausing the inspector leaves the live game overlay and tracking intact. Collapsed
  inspection skips image conversion and table updates, retaining only the latest matching pair.
- Small shifts retain the existing box; repeated text/size changes are confirmed before updating.
  Processing delays do not erase boxes. Unchanged crop pixels preserve text through OCR misses;
  otherwise removal requires repeated negative observations. Raw OCR stays visible in the inspector.
- IDs persist through OCR reordering and match between the inspector and game. They reset to new
  identities after resize, minimize, or capture restart. Unrecognized text has no ID.

**Advanced → Open demo window** provides Japanese text and an animated target without needing a game. CPU
inference uses two threads per engine; optional GPU acceleration applies to OCR and Gemma, while
Sugoi stays on CPU. OCR timing and
capture-to-start delay, current-pass time, and skipped waiting frames are shown separately from
capture frequency. Hover the OCR status for recent average inference time. Frames are replaced
rather than queued when busy; processing one frame never starts overlapping OCR jobs.
The visual worker also keeps only its newest waiting job. Changed/settled regions prompt cropped
OCR; a full discovery scan runs about every three seconds. Crops include padding and whole known
lines. Broad changes or cut-off detections use a full scan. Waiting scan areas merge on the newest
frame so busy workers cannot lose a changed region.
Accepted regions also gate later OCR results: unchanged glyph patterns retain the same Japanese
source, English and geometry, even when a later pass misses or misreads them. Readings below 90%
OCR confidence get three review attempts; only a score improvement greater than one percentage
point can win. The previous English stays visible until the corrected translation is ready.
Real local changes unlock normal updates. The inspector always keeps the raw model output.

Unscanned regions keep their accepted translations and do not count as missing text. Dialogue
grouping uses the whole tracked scene; a scan elsewhere cannot restart a line's confirmation wait.
The inspector shows only the current scan's real detections, not old rows carried onto a new frame.

Status identifies full/area scans, unchanged regions held, visual-check time, and captures skipped.
This is not a guarantee that
every animation can be ignored. Visual failure is reported and falls back to ordinary OCR.

Use windowed or borderless fullscreen. The overlay hides when the target loses focus, minimizes,
or closes. Stop capture before changing sources. Windows may show its capture border.
This app does not inject into games, request administrator access, or save screenshots automatically.

## Development

```powershell
uv sync --locked
uv run python tools/check.py
uv run python tools/verify_ocr.py --output artifacts/ocr
uv run python tools/verify_ocr.py --dense --output artifacts/dense-ocr
uv run python tools/verify_translation.py
uv run python tools/verify_windows.py
uv run python tools/verify_ocr_windows.py --translation --dialogue
uv run python tools/verify_ocr_windows.py --translation --dialogue --ocr-delay-ms 900
uv run python tools/verify_ocr_windows.py --translation --dialogue --typewriter
uv run python tools/verify_ocr_windows.py --translation --dialogue --typewriter --transitions --ocr-delay-ms 900
```

After GPU setup, use `.venv-gpu\Scripts\python.exe` directly for the same checks, adding
`--device cuda` to OCR checks. This strict verification mode fails rather than silently passing on
CPU. Plain `uv run` uses the default CPU environment; do not install both ONNX Runtime distributions
into one environment because they share package files.

The replay check renders an original Japanese fixture and blocks network connections during model
loading/inference. Only its synthetic output is saved. The two Windows checks open temporary test
windows on an unlocked desktop. See [verification](engineering/verification.md).

Read the [agreed plan](engineering/plan.md), [engineering guide](engineering/README.md), and
[milestone status](engineering/plans/010-regional-ocr.md). The application runs locally;
only explicit setup downloads require a network connection.

Models are kept in ignored `models/meiki` and `models/sugoi-v4`; set `JP_OVERLAY_MODEL_DIR` or
`JP_OVERLAY_SUGOI_DIR` to use other directories. English cache entries persist in ignored
`data/translations.sqlite3`; close the app before removing that cache if you want a fresh evaluation.
Use uv/the bundled setup: it resolves the two upstream OpenCV dependency names to a single `cv2`
installation. No model weights or captured game screenshots belong in Git.

The pinned Sugoi repository supplies [research-use, noncommercial model terms](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2/blob/71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b/LICENSE).
Setup preserves that license with the weights. Code and model distribution remain separate;
private use does not automatically resolve the model's use restrictions.

## Current limits

Japanese OCR quality still needs representative game evaluation, especially tiny 4K HUD text,
furigana, long lines, dense menus, and vertical text. Other visible languages may be detected but
are not the accuracy target. The inspector shows recognition errors as returned. Exclusive fullscreen,
protected windows, HDR color fidelity, and untested game/anti-cheat combinations are not guaranteed.
Mixed-DPI monitor behavior has automated coordinate coverage but requires real hardware verification.
Windows 10 is not the initial validation target. The launcher is a development launcher; a portable
executable package is a later milestone.

Tracking uses position/text heuristics, not semantic understanding or optical flow. Crossing labels,
major layout changes, and multiline splits/merges can create new identities. A disappeared region
may linger briefly; real-game stabilization thresholds still need feedback. OCR continues sampling
to discover changes even when the displayed overlay remains unchanged.
Absence confirmation is a heuristic, not certainty. Slow inference delays discovery and removal;
a stuck worker retains its last state until recovery, failure, or a session reset. Foreground-stroke
checks retain unchanged labels over dim animated backgrounds; ambiguous/weak templates still use
OCR confirmation and can behave less reliably.

Dialogue grouping uses alignment, spacing, size, and punctuation; it does not identify actual game
panel boundaries. Punctuation-free, centered, or unusual dialogue may stay separate, and similar
menu layouts can still be ambiguous. Context covers the current group, without speaker history or
a glossary. Icon filtering is conservative and cannot identify every high-confidence or overlapping
icon. Names and short labels can translate awkwardly. English boxes may expand over neighboring
dense UI; collision-aware layout remains future work. Vertical source text stays ungrouped and
renders as horizontal English. Toggle English off/on to retry a visible backend failure.

Visual checks add evidence, not semantic certainty. A flash, occlusion, low-contrast/tiny text, or
unusual background can still delay or temporarily mask a box. Periodic full OCR catches uncertain
changes; small changes use regional inference with full-scan fallback. An already-running model call cannot
be canceled, so very slow OCR still delays new English even when old boxes hide promptly.
