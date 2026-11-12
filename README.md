# JP Overlay

A local Windows game translation overlay, being built in small milestones.

**Current milestone:** capture a game window, recognize Japanese with MeikiOCR, translate stable
text locally with Sugoi V4 through CTranslate2, and draw English in an aligned click-through overlay.
The inspector keeps raw Japanese, bounding boxes, and English together for review.

## Run

On Windows 11, run **Setup OCR.cmd**, then **Setup Translation.cmd** once. They set up the
project-local Python environment and download/verify pinned models: about 46 MB for OCR and 1.11 GB
for Sugoi, its tokenizers, and source/license metadata. Existing verified files are reused.
Then double-click **Run JP Overlay.cmd**. Normal use works offline; missing/corrupt models produce
a visible setup instruction rather than downloading automatically. Existing OCR users only need
the translation setup step.
Setup requires Python 3.12 or later on PATH to bootstrap uv; uv installs the pinned Python 3.12
runtime locally if needed. Nothing is installed into your global Python environment.

Alternatively, with uv installed:

```powershell
uv sync --locked
uv run python tools/setup_models.py
uv run python tools/setup_models.py --translation
uv run jp-overlay
```

Choose a window and select **Start capture**, then switch to the game. OCR and translation load in
the background. **English overlay** is enabled by default; translated regions cover the original
text with a translucent background. Regions awaiting translation leave the original text visible.

- **Automatic text size** estimates the source text size and wraps English with limited shrinking.
  Uncheck it to set a fixed size in physical pixels. Opacity controls the translated box background.
- **Sugoi V4 · Fast CPU** is the default. **Wider search** uses the same weights with more decoding
  candidates; it can take longer and is not guaranteed to improve every sentence. Switching safely
  unloads the previous backend before loading the selected one.
- Translations are reused from a bounded memory cache and local SQLite database. Moving a box
  does not retranslate its text. Brief OCR jitter keeps the last committed English until a real
  change is confirmed; changed/removed text rejects late results.
- For small OCR variations in nearly the same position, the tracker remembers the highest-confidence
  reading. Weaker/equal alternatives keep its text and box unchanged; a confirmed stronger reading
  becomes the new preference. Numbers, short labels, and typewriter growth use normal confirmation.
  A consistently changed alternative can still replace the old reading after about 1.25 seconds.
- Turn **English overlay** off to unload the translation model and inspect numbered OCR game boxes.
  **Stabilize game boxes** can then be toggled for comparison. English always uses stable tracks.
- **Group dialogue lines**, enabled by default, joins likely wrapped dialogue before translation
  and draws one English box. Disable it if unrelated lines group together. Short speaker names,
  marked choices, and separate columns remain separate under the conservative rules.
- Tracking uses recognized-character bounds so a detector box expanding over an icon does not
  automatically resize English. Isolated weak edge glyphs beside strong Japanese text can be
  excluded. Raw OCR remains unchanged in the inspector for comparison.

The inspector displays the exact analyzed frame, numbered line boxes, raw OCR, and matching English:

- Select a text row to highlight its box and see physical coordinates/orientation.
- Use **Pause inspection** to freeze the frame and text while capture continues. Resume picks up
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
  Pause freezes both languages in the inspector and hides the game overlay.
- Small shifts retain the existing box; repeated text/size changes are confirmed before updating.
  Processing delays do not erase boxes. Unchanged crop pixels preserve text through OCR misses;
  otherwise removal requires repeated negative observations. Raw OCR stays visible in the inspector.
- IDs persist through OCR reordering and match between the inspector and game. They reset to new
  identities after pause/resume, resize, minimize, or capture restart. Unrecognized text has no ID.

**Open demo window** provides Japanese text and an animated target without needing a game. Models
run on CPU with two inference threads per engine; a GPU toolkit is not needed. OCR timing and
capture-to-start delay, current-pass time, and skipped waiting frames are shown separately from
capture frequency. Hover the OCR status for recent average inference time. Frames are replaced
rather than queued when busy; capture remains at four samples/second.

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
```

The replay check renders an original Japanese fixture and blocks network connections during model
loading/inference. Only its synthetic output is saved. The two Windows checks open temporary test
windows on an unlocked desktop. See [verification](engineering/verification.md).

Read the [agreed plan](engineering/plan.md), [engineering guide](engineering/README.md), and
[milestone status](engineering/plans/007-evidence-based-persistence.md). The application runs locally;
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
a stuck worker retains its last state until recovery, failure, or a session reset. Unchanged text
over an animated background may still need repeated OCR evidence because its crop pixels differ.

Dialogue grouping uses alignment, spacing, size, and punctuation; it does not identify actual game
panel boundaries. Punctuation-free, centered, or unusual dialogue may stay separate, and similar
menu layouts can still be ambiguous. Context covers the current group, without speaker history or
a glossary. Icon filtering is conservative and cannot identify every high-confidence or overlapping
icon. Names and short labels can translate awkwardly. English boxes may expand over neighboring
dense UI; collision-aware layout remains future work. Vertical source text stays ungrouped and
renders as horizontal English. Toggle English off/on to retry a visible backend failure.
