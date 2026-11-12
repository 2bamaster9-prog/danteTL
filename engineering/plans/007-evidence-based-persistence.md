# Slice seven — Persistent state on busy screens

The user requested diagnosis and implementation improvements for flicker and slow response when
many labels are visible.

## Delivered

- Reproduced age-based disappearance: 80 labels, 1.1-second OCR, zero visible tracks with old policy.
- Removed wall-clock expiry and slow-gap candidate resets. Committed state survives processing;
  removal uses completed negative evidence and bounded exact-pixel presence checks.
- Existing tracks have priority when detector order crosses the 128-display-slot boundary.
- Added OCR processing/queue/skipped-frame diagnostics without changing sampling or model settings.
- Added dense 4K benchmarking and live slow-worker verification to the engineering harness.

## Verification

151 fast tests passed with Ruff and Pyright. Replays cover 80 slow labels, duplicate polling,
two-pass dropouts, stable English and grouped dialogue, admission limits, true removal, exact-pixel
retention through repeated misses, background changes, static settling, reference revision changes,
bounded pixel work, and unavailable evidence. Offline real Meiki and Sugoi checks passed.

The 4K synthetic fixture draws 80 labels at 38 pixels. Meiki returned 64 detections and several
spelling variants: this is a workload measurement, not an 80/80 accuracy claim. Warm OCR median
was 468 ms (maximum 485 ms over five warm passes); tracking plus pixel evidence measured 8.53 ms
median and 9.19 ms maximum for those 64 observations. Other OCR runs measured 453–469 ms medians.
This supports keeping capture at 4 Hz while the worker skips obsolete waiting frames.

The live translation/dialogue check passed at DPI 168 with an added 900 ms delay on each OCR call
(about one second total per pass). English persisted across 49 continuity checks spanning at least
three seconds. Profile/grouping toggles, font controls, pause, resize, minimize/restore, restart,
and shutdown passed; the run completed in 15.44 seconds. Its inspector artifact was reviewed.

## Manual review and limits

Restart and revisit the busy game screen. Confirm stationary English persists, then leave the menu
or advance dialogue to check removal and new content. Use OCR status/tooltip to distinguish model
latency from capture frequency. This does not guarantee zero flicker across every OCR failure or
layout. See [decision 007](../decisions/007-evidence-based-persistence.md) for the precise evidence
rules and conservative retention tradeoffs. No new setup, model, or dependency is required.
