# Milestone one capture and overlay

Status: complete, 2026-11-13.

## Scope

Create a usable window picker, WGC capture by HWND, a clean client-area preview, and a nonactivating
click-through sample overlay. Follow movement and resize. Hide on minimize, closure, and loss of
foreground focus. Establish meaningful automated checks, a demo target, and local setup/launch.

## Acceptance

- Window selection identifies the exact HWND and process, including duplicate window titles.
- Capture produces owned BGRA client images with recorded physical geometry and bounded retention.
- Overlay follows the client bounds without covering the title bar or stealing input/focus.
- Source resize rejects incompatible frames until geometry agrees.
- Stop, close, and repeated start/stop release capture resources.
- Native failures are visible. Source selection does not fall back to another target.
- The capture preview excludes the sample overlay.
- Fast checks and a real Windows integration check pass.
- Manual UI inspection checks selection, start/stop, input through an overlay, and readable layout.

## Deferred

OCR, translation, automatic source-font estimation, caching, model downloads, display capture,
native hooks, HDR support, and portable executable distribution belong to later milestones.

## Evidence

Ruff formatting/lint, Pyright, and 20 behavior tests pass. Native verification passed at DPI 96
(100%), 144 (150%), and 168 (175%). At 175%, the check captured 1575 × 1015 client pixels,
resized to 1330 × 875, checked source colors and overlay bounds, verified exclusion/native input
styles, minimized, stopped, restarted, and destroyed the source. The final run at 100% repeated
these checks at 900 × 580 and 760 × 500. All capture workers finished cleanly.

The main UI and demo launch were inspected through Computer Use. The user selected a real game;
its preview was observed at 3840 × 2160 and DPI 168, and the user confirmed that the overlay was
aligned and mouse clicks passed through. The user's active session was left running.

The existing empty Git repository was used, with development on `codex/milestone-one`. Dependencies
and the pinned Python runtime were installed in project-local environments; uv.lock is committed
as the reproducible dependency record. The setup script succeeded using the local package cache.

Remaining validation limits: cross-monitor mixed-DPI transitions, HDR, exclusive fullscreen,
long-session memory behavior, low-end hardware performance, and Azur Promilia itself. These are
not claims of compatibility or blockers for the defined first milestone.
