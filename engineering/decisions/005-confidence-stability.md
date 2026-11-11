# Decision 005 — Prefer stronger OCR readings within a live text track

Status: accepted and implemented.

## Problem

The user reported good translation results but flicker when OCR alternated between very similar
spellings, sometimes because of a tiny glyph element or a nearby icon. Two consecutive weaker
observations could revise the text, clear its English, and start an unnecessary translation.

## Policy

Retain the best finite character-mean confidence for the committed reading in each live track.
Equivalent normalized observations can improve that score without changing public `TextTrack`
values. No confidence field is added to the renderer/translation request. Memory stays bounded;
there is no global map of positions or unbounded spelling history.

A different reading is treated as potentially the same content only when:

- Bounds overlap by at least 70%, with edge displacement no greater than the shorter glyph-scale
  dimension (minimum tolerance 12 physical pixels).
- Both normalized strings have at least four characters, similarity is at least 0.75, and the edit
  count is at most one per five characters (minimum one, maximum two).
- Numeric characters have not changed, including Unicode numeric forms. Ordinary prefix growth or
  contraction is excluded so typewriter text updates promptly; trailing punctuation/symbol noise
  can still be treated as a variant. A small leading icon can qualify as an insertion.

When both scores are available, a lower/equal-scoring variant retains the exact winning text,
revision, and geometry. Equal scores include a 1e-6 rounding tolerance for character means.
A stronger variant still needs normal confirmation (two observations, or an unchanged frame for
350 ms) before promotion. Its best observed score becomes the new baseline. We use OCR's existing
score as evidence, not a calibrated probability that the whole sentence is correct.

## Genuine changes and lifecycle

A high score must not freeze an old sentence forever. A weaker similar alternative that remains
consistent for 1.25 seconds may commit; at four samples/s this normally means six observations
including its first appearance. If the source stops producing new frames, that unchanged latest
frame can satisfy the same interval. Repeated UI polls cannot add observation evidence, and an
unprocessed advancing frame cannot invoke static settling.

Returning to the winner, switching candidates, a missed detection, or a long observation gap clears
the pending run. Completely different dialogue, short labels, numeric changes, typewriter growth,
and substantial position changes use ordinary confirmation. Missing/nonfinite/out-of-range scores
also use ordinary confirmation rather than manufacturing a score. A new committed reading resets
its baseline; track removal or lifecycle reset drops confidence memory entirely.

## Tradeoffs

The time escape cannot perfectly distinguish a persistent OCR mistake from a genuine near-identical
edit. Such edits may update more slowly; prolonged stable misrecognition can still win. Conversely,
short ambiguous labels intentionally receive less suppression. These thresholds need feedback from
the original game scene, not only synthetic tests. Raw OCR remains visible for diagnosis even while
the game overlay holds its preferred reading. No visual scene fingerprint or semantic model is added.
