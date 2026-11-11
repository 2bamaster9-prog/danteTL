# Slice three — Stable text tracks and overlay positions

The user reported excellent OCR but visibly jittering boxes, then authorized the next slice.
Implement tracking now, ahead of translation, to keep near-identical observations from replacing
displayed content and positions repeatedly.

## Delivered

- Deterministic one-to-one text/geometry association with persistent IDs and bounded state.
- Position deadband, repeated-evidence confirmation for modest shifts/crop changes, and immediate
  following for large coherent moves. Committed geometry stays exactly fixed within its tolerance.
- Confirmed text revisions, including short numeric/label changes. Single-frame OCR mistakes are held.
- One-miss grace, two-miss removal, advancing-source expiry, and static-frame retention.
- Static edits settle after 350 ms without a newer frame; long static gaps preserve matching IDs.
- Lifecycle reset on pause, minimize, resize, errors, stop, and source changes; no reuse of old IDs.
- Value-based overlay updates. Raw frame inspection is preserved, with IDs shared across views.
- Default-on stabilization toggle for direct comparison with raw game boxes.

## Verification

56 fast tests pass, including deterministic replay scenarios for jitter, slow drift, true movement,
bad crops, noisy text, numbers/short labels, typewriter growth, reordering, duplicate labels, missed
observations, static/stalled capture, static edits/gaps, stale results, resize/reset, vertical text,
and bounded tracks.
A renderer regression verifies equivalent display values do not request additional repaints.

Live Windows OCR verification preserved the stationary Japanese phrase's ID and exact display bounds
over repeated captures, exercised raw/stable and pause/resume toggles, and passed resize, minimize,
restore, restart, and close checks. Native overlay input styles, exclusion, geometry, and teardown
also passed. The updated inspector layout was visually reviewed using the demo-only artifact.

## Remaining review

Restart the app and compare both toggle states in the game that exhibited jitter. Check stable menus,
typewriter dialogue, scrolling choices, disappearing text, and transitions. Thresholds are starting
heuristics and may need adjustment for real scenes. Translation, caches, fonts, split/merge handling,
and optical flow remain outside this slice. No new dependency or model download is required.

Follow-up: [slice four](004-local-translation.md) now connects local translation, caching, and English
layout. The tracker also exposes confirmed content for translation while retaining raw inspection.
