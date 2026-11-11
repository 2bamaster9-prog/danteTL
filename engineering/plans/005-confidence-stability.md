# Slice five — Confidence-aware OCR stability

The user reported strong initial translation results and requested that near-identical OCR
variants at the same location prefer the strongest reading instead of repeatedly replacing English.

## Delivered

- Per-track memory of the strongest confidence for committed text; repeated weaker observations
  cannot lower it. Confidence does not enter public rendering values or translation/cache keys.
- Conservative similarity/position checks for likely OCR variants. Rejected weaker/equal variants
  preserve the exact text, revision, and box, including small icon-induced crop changes.
- Confirmed higher-confidence readings become the preference once; subsequent weaker variants hold.
- Normal confirmation for unrelated dialogue, numbers, short labels, typewriter growth/contraction,
  and substantial position changes. Sustained weaker similar readings have a 1.25-second escape
  so genuine edits are not permanently suppressed, including on a truly static source.
- Confidence/candidate state resets with content changes, expiry, and session lifecycle. Different
  regions remain independent; raw OCR text and scores in the inspector remain untouched.

## Verification

101 fast tests pass with Ruff and Pyright. Replays cover long alternating bursts, equal scores,
dakuten-like substitutions, leading icons/crops, stronger corrections, peak-score memory, real
dialogue/numeric/typewriter edits, static settling, misses, independent tracks, reset/expiry,
position changes, and missing/invalid scores. A tracker-to-translation test verifies that noisy
alternation leaves English continuously available and invokes the backend only once.

The offline Meiki smoke check passed. Full live capture → OCR → translation integration passed
at DPI 168, including model switching, font controls, stable IDs/bounds, pause, resize,
minimize/restore, restart, and worker shutdown. These checks use the project's own demo.

## Remaining review

Restart the app and revisit the original flickering scene. Check icons, tiny glyphs, alternating
readings, choices, and new dialogue in the same box. Raw inspector rows may still vary as intended;
the stabilized game overlay is the acceptance target. No new dependencies or model setup are needed.
Future product slices remain separate from this targeted correction.

Follow-up: [slice six](006-dialogue-grouping.md) addresses detector/icon geometry explicitly and
adds grouped dialogue translation, based on the user's supplied button example and next request.
