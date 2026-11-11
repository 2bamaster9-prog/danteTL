# Slice six — Icon cleanup and dialogue context

The user requested a fix for icon-driven box movement, then grouping dialogue lines before Sugoi.

## Delivered

- Reproduced the supplied button at 4K: an icon read as `中`/`@` also expanded the detector box.
- Conservative isolated-edge filtering and recognized-character bounds for tracking. Raw OCR,
  character scores, and detector boxes stay unchanged in the inspector.
- Bounded dialogue groups over confirmed tracks, with combined-source translation and one English
  overlay. Font sizing uses the individual lines' height. All member revisions participate in
  stale-result checks; existing cache and backend switching remain local and bounded.
- Default-on **Group dialogue lines** control, grouped-source tooltips, continuation-row markers,
  and whole-group clipboard copying without duplicate paragraphs.
- The app's demo now opens with a speaker label and wrapped Japanese dialogue. The native regression
  fixture's original mode remains available separately.

## Verification

136 tests passed with Ruff and Pyright. Added actual numeric OCR observations from the button,
alternating box/character replay, protected punctuation/numbers, incomplete metadata, grouping order,
speaker/menu/column exclusions, bounds, font sizing, member invalidation, regrouping, and clipboard
tests. No game image is checked in. A worker integration test confirms one complete source request
and rejection of a late result after a non-anchor member changes.

Offline real OCR and Sugoi checks passed. Full live Windows integration at DPI 168 passed grouped
translation, a separate speaker, model switching, grouping off/on, font controls, pause, resize,
minimize/restore, restart, and shutdown. Native geometry, capture exclusion, and input-transparent
styles passed separately. The inspector and English overlay artifacts were visually reviewed.

The live passage translated as: “A new adventure will begin here, but before that, please prepare
for the journey.” This verifies context delivery and rendering, not broad comparative model quality.

## Remaining review

Restart and revisit the supplied button in the live game, then inspect wrapped dialogue. The 4K
reproduction used the supplied crop in a synthetic canvas, not a live Honkai session. High-confidence
or overlapping icons, centered/punctuation-free dialogue, and ambiguous menus remain limitations.
No new dependency, model download, or GPU toolkit is required.
