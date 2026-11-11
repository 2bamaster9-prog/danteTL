# Verification

## Fast checks

Run `uv run python tools/check.py` from the repository root. It checks Ruff formatting and lint,
Pyright types, and pytest behavior tests. It does not open windows or download models. Dependencies
must already be installed with `uv sync --locked` or the bundled setup script.

Fast tests cover physical geometry across scale factors and negative desktop origins, decorated
and borderless crops, resize rejection, focus/closure policy, bounded frame replacement, and late
callbacks after shutdown. They do not establish native Windows compatibility.

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
2. Start capture. The preview should contain Japanese text and source imagery, without our English
   sample overlay. Switch to the demo; check its teal client border and dialogue overlay.
3. Click the demo's covered button. Its counter must increase without disabling the overlay.
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
