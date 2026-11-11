# Verification

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
3. Resume and switch to the demo. Check numbered boxes and mouse pass-through while interacting.
   Compare **Stabilize game boxes** on/off. IDs should survive OCR ordering changes; raw preview
   positions still follow each analyzed image. In game, inspect genuine movement and disappearing text.
4. Move, resize, minimize, and restore. Switch focus to another app; the overlay must hide.
5. Stop/start capture and close the target. Controls should recover and the overlay must disappear.
6. Repeat with a game in windowed or borderless mode. Record resolution, DPI, capture mode, and
   observed behavior. Do not infer publisher approval or broad anti-cheat compatibility.

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

See [current slice](plans/003-stable-tracks.md). Existing test commands remain unchanged.
