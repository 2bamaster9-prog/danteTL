# Milestone two — Local OCR inspection

Implementation complete. The user subsequently tested it and reported excellent OCR; no quantitative
accuracy score or broad game-compatibility claim follows from that feedback.

## Delivered

- MeikiOCR 0.3.5 on local ONNX Runtime CPU, two inference threads, bounded recognition batches.
- Explicit model setup, pinned revisions/checksums, visible missing/corrupt-model errors; no runtime
  downloads or external inference. The three models are installed on the development machine.
- Latest-frame OCR worker with one pending frame, generation invalidation, and asynchronous teardown.
- Exact analyzed-frame preview with numbered line boxes and selectable raw Japanese text.
- Character-box toggle, Fit/100%/200% zoom, per-line confidence, box coordinates/orientation,
  copy selected/all text, inference duration, source-frame number/age, and pause/resume inspection.
- Numbered, click-through game boxes with focus/geometry checks and stale-result expiry.
- Offline fixture replay, fast behavior checks, and real Windows capture/OCR lifecycle verification.

## Acceptance evidence

See [verification](../verification.md) for commands and recorded results. The synthetic 1080p
fixture recognized all three expected phrases after Unicode width normalization. Raw output
preserved an ASCII question mark in place of a full-width question mark. Live demo recognition
worked at 175% desktop scaling; pause, resize, minimize/restore, restart, and close passed.

## Next accuracy review

Use Japanese game dialogue, menus, tiny HUD text, vertical text, furigana, and animated backgrounds.
Pause representative frames, compare source/recognized text and box placement, and record latency.
Check long lines and dense screens for model limits. This implementation does not establish a
general character error rate, game frame-time impact, 4K small-text quality, or broad compatibility.
No game screenshots are saved automatically. Deliberate replay capture/export can be added if needed.

Translation, caching, stable text tracking, automatic translated-font sizing, and model comparison
are not part of this implementation request. The wider [agreed plan](../plan.md) remains in effect.

Follow-up: the user reported box jitter and requested the [stable-tracking slice](003-stable-tracks.md)
before translation. The raw OCR inspector from this milestone remains available.
