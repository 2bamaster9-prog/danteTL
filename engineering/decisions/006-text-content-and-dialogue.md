# Decision 006 — Text bounds and dialogue units before translation

Status: accepted and implemented.

## Evidence and icon handling

The user supplied a Honkai: Star Rail button showing `ストーリーを振り返る` beside a film icon.
The tight crop recognized cleanly. Placing that same crop in a 3840 × 2160 canvas reproduced the
problem: the detector included the icon, and recognition emitted `中` or `@` at 0.28–0.46 confidence
beside text around 0.9. At 1080p the icon was excluded. The recognition model's character boxes
located the text consistently even as the detector box moved from about x=210 to x=131–134.

[Meiki's documentation](https://github.com/rtr46/meikiocr#adjusting-thresholds) exposes separate
detection and recognition thresholds. Inspection of pinned 0.3.5 confirms separate line detection
and character recognition. Raising recognition thresholds alone would still leave the detector's
expanded geometry and could remove real low-confidence glyphs elsewhere. No model retraining or
global threshold increase is introduced.

Instead, derive a text-only observation before tracking, preserving the raw result for inspection:

- Require complete, valid character geometry matching the recognized string before using its union.
- For horizontal, spatially ordered characters, consider at most two glyphs at either edge.
- Require at least four remaining characters including Japanese, median confidence ≥0.75, edge scores
  ≤0.55, and a confidence difference ≥0.25. Require a gap of at least 0.45 median glyph widths,
  three ordinary inter-character gaps, and three pixels.
- Preserve structural quotes/punctuation/signs, numeric characters, interior glyphs, vertical text,
  nonfinite scores, and uncertain/incomplete metadata. No word-specific or game-specific blacklist.

This resolves both spurious source characters and detector-only box expansion. Tracking's existing
geometry deadband absorbs the remaining small character-bound differences. The supplied observation
replay alternates clean/icon-inclusive detections while retaining the exact same public track object.
Only derived text and numeric OCR metadata are checked in; the supplied game image stays outside Git.

This is a conservative heuristic, not a universal icon classifier. A high-confidence icon, overlapping
symbol, unusually separated weak genuine glyph, or very tall detector crop can remain ambiguous.

## Dialogue grouping

Introduce a pure `DialogueGrouper` between stable lines and the translation worker. A `TextBlock`
contains original member tracks, their union, combined source, and original line height. Nearby
lines alone are insufficient: require comparable height, left alignment, a small vertical gap,
continuation/punctuation evidence, and exactly one plausible successor. Short/narrow names, marked
choices, completed sentences, separate columns, and vertical text remain independent. The first
line must have at least ten characters; unusual or punctuation-free wrapping may remain separate.

Bound groups to six lines and 512 source characters. Require all members confirmed and 350 ms of
unchanged group source/membership. Join Japanese without adding punctuation or artificial word gaps;
retain a space between Latin words across a wrap. Never queue unconfirmed fragments from a group.
The default-on checkbox supports comparison and recovery from an incorrect heuristic grouping.

The translation request includes all member IDs, revisions, and source strings. Its first member is
only an anchor. Any member change or regrouping invalidates the previous display request; movement
does not. Cache reuse is based on the exact combined source plus model settings, so an equivalent
paragraph rewrapped into different lines can reuse translation without accepting stale membership.

Render one English box per group, using median line height for automatic font size. Preserve raw
rows/boxes in the inspector, show continuation markers, expose the translated source in tooltips,
and deduplicate Copy English by group. Speaker history, glossary context, panel detection, and
collision-aware placement remain future work.
