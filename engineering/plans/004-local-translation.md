# Slice four — Local translation in the stabilized overlay

The user authorized Sugoi V4 through CTranslate2, a swappable backend boundary, and English rendering.

## Delivered

- Pinned Sugoi weights/tokenizers with explicit setup, integrity checks, and offline CPU int8 inference.
- A small translation backend protocol and composition-time registration. Fast CPU and Wider search
  profiles exercise the same safe unload/load mechanism that future model adapters will use.
- One bounded translation worker, source deduplication, and revision/generation validation. Capture,
  OCR, inspection, and shutdown remain responsive while model work finishes.
- Translation readiness on confirmed tracks. Existing English survives a pending OCR wobble or
  one missed observation; committed new text, removed tracks, and resets reject old replies.
- Bounded memory/SQLite caching with model/settings-aware keys and memory-only disk-error fallback.
- English in the click-through overlay, translucent backgrounds, Automatic text size checkbox,
  manual pixel sizing, wrapping, viewport limits, and visible overflow indication.
- Original frame/raw OCR inspection plus an English column and Copy English action.
- Translation status and recoverable failure instructions. English off unloads its model and
  restores the OCR comparison view.

## Verification

72 fast tests pass with Ruff and Pyright. Translation tests cover duplicate work, movement, changed
and removed text, invalidation, backend swaps, persistent cache reuse, bounded work, failures, and
shutdown. Rendering tests check font/viewport limits, explicit overflow, rejection of stale revisions,
and unchanged English avoiding repaint requests. SQLite tests use actual temporary databases.

The offline Sugoi check loads/translates with Python socket connections blocked and checks three
original phrases. The live Windows fixture at DPI 168 and 96 exercises the complete pipeline, switches
decoding profiles, checks font controls, and passes pause, resize, minimize/restore, restart, and
worker cleanup. Native geometry, capture exclusion, and input-transparent styles pass separately.
Demo-only inspector and English overlay artifacts were visually reviewed.

See [verification](../verification.md) and [measurements](../performance.md) for commands and evidence.

## Remaining review

Restart the app and evaluate real dialogue, typewriter text, menus, names, choices, and dense scenes.
Check that the English stays put, follows real movement, clears on transitions, and remains readable.
The current model translates independent OCR regions; grouping, context, glossaries, collision-aware
layout, and comparative model evaluation remain future slices. No broader game compatibility or
ordinary-PC performance claim follows from the demo checks.
