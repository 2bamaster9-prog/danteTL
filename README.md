# JP Overlay

A local Windows game translation overlay, being built in small milestones.

**Milestone one:** select a window, preview its captured client area, and draw a translucent,
click-through sample overlay that follows the window. OCR and translation are not implemented yet.

## Run

On Windows 11, double-click **Run JP Overlay.cmd**. First run sets up a project-local Python
environment and downloads dependencies. Subsequent runs use the installed environment offline.
Setup requires Python 3.12 or later on PATH to bootstrap uv; uv installs the pinned Python 3.12
runtime locally if needed. Nothing is installed into your global Python environment.

Alternatively, with uv installed:

```powershell
uv sync --locked
uv run jp-overlay
```

Choose a window and select **Start capture**. Switch to that window to see the sample overlay.
The preview shows the original captured image. **Open demo window** provides an animated target
with a click counter for checking input and alignment without a running game.

Use windowed or borderless fullscreen. The overlay hides when the target loses focus, minimizes,
or closes. Stop capture before changing sources. Windows may show its capture border.
This app does not inject into games, request administrator access, or save screenshots automatically.

## Development

```powershell
uv sync --locked
uv run python tools/check.py
uv run python tools/verify_windows.py
```

The second check opens a temporary test window and exercises real Windows capture and overlay
geometry. Run it on an unlocked desktop. See [verification](engineering/verification.md).

Read the [agreed plan](engineering/plan.md), [engineering guide](engineering/README.md), and
[milestone status](engineering/plans/001-capture-overlay.md). The application runs locally;
only explicit setup downloads require a network connection.

## Current limits

This milestone displays sample text, not recognized or translated text. Exclusive fullscreen,
protected windows, HDR color fidelity, and untested game/anti-cheat combinations are not guaranteed.
Mixed-DPI monitor behavior has automated coordinate coverage but requires real hardware verification.
Windows 10 is not the initial validation target. The launcher is a development launcher; a portable
executable package is a later milestone.
