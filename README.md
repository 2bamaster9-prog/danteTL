# JP Overlay

A local Windows game translation overlay, being built in small milestones.

**Current milestone:** capture a game window, recognize Japanese locally with MeikiOCR, and inspect
the text with aligned bounding boxes. Game boxes now use persistent text tracks to suppress jitter.
Translation comes later.

## Run

On Windows 11, double-click **Setup OCR.cmd** once. It sets up the project-local Python environment
and downloads/verifies three pinned OCR models (about 46 MB). This also upgrades a milestone-one
checkout. Then double-click **Run JP Overlay.cmd**. Normal use works offline; missing/corrupt models
produce a visible setup instruction rather than downloading automatically.
Setup requires Python 3.12 or later on PATH to bootstrap uv; uv installs the pinned Python 3.12
runtime locally if needed. Nothing is installed into your global Python environment.

Alternatively, with uv installed:

```powershell
uv sync --locked
uv run python tools/setup_models.py
uv run jp-overlay
```

Choose a window and select **Start capture**. MeikiOCR loads on a background worker, then the
inspector displays its exact analyzed frame, numbered line boxes, and raw recognized text.

- Select a text row to highlight its box and see physical coordinates/orientation.
- Use **Pause inspection** to freeze the frame and text while capture continues. Resume picks up
  the newest frame. Minimize, resize, or stopping clears the review so stale imagery is not retained.
- Use **Character boxes** and **Fit / 100% / 200%** zoom to examine small text; scroll when zoomed.
- **Copy text** copies the selected row, or all rows when none is selected. Hover a row for full text.
- Confidence is the mean recognized-character score, not a probability of sentence correctness.
- Switch to the game to see the optional click-through numbered boxes. These may briefly lag;
  use the frame-matched preview when checking accuracy. Pause hides the game boxes.
- **Stabilize game boxes** is enabled by default. Small shifts retain the existing box; repeated
  text/size changes are confirmed before updating. A missed detection gets a short grace period.
  Disable this checkbox to compare raw boxes. The inspector always keeps raw OCR coordinates/text.
- IDs persist through OCR reordering and match between the inspector and game. They reset to new
  identities after pause/resume, resize, minimize, or capture restart. Unrecognized text has no ID.

**Open demo window** provides Japanese text and an animated target without needing a game. Models
run on CPU with two inference threads; a GPU toolkit is not needed. OCR timing and source-frame age
are shown separately from capture frequency. Frames are replaced rather than queued when busy.

Use windowed or borderless fullscreen. The overlay hides when the target loses focus, minimizes,
or closes. Stop capture before changing sources. Windows may show its capture border.
This app does not inject into games, request administrator access, or save screenshots automatically.

## Development

```powershell
uv sync --locked
uv run python tools/check.py
uv run python tools/verify_ocr.py --output artifacts/ocr
uv run python tools/verify_windows.py
uv run python tools/verify_ocr_windows.py
```

The replay check renders an original Japanese fixture and blocks network connections during model
loading/inference. Only its synthetic output is saved. The two Windows checks open temporary test
windows on an unlocked desktop. See [verification](engineering/verification.md).

Read the [agreed plan](engineering/plan.md), [engineering guide](engineering/README.md), and
[milestone status](engineering/plans/003-stable-tracks.md). The application runs locally;
only explicit setup downloads require a network connection.

Models are kept in ignored `models/meiki`; set `JP_OVERLAY_MODEL_DIR` to use another directory.
Use uv/the bundled setup: it resolves the two upstream OpenCV dependency names to a single `cv2`
installation. No model weights or captured game screenshots belong in Git.

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
