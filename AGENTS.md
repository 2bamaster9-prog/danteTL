# JP Overlay engineering instructions

Read `engineering/README.md` first. The agreed product plan is in
`engineering/plan.md`; current implementation scope is in
`engineering/plans/008-responsive-ocr.md`.

- Use Python with deep modules: small public interfaces that own meaningful complexity.
- Keep Windows, Qt, capture-library, and model details at their respective boundaries.
- Use explicit dependencies and typed values. Do not create generic frameworks for hypothetical needs.
- Runtime processing is local. Do not add network services, telemetry, or automatic model downloads.
- Keep frames and work queues bounded. The UI thread must not perform capture or inference.
- Preserve physical-pixel coordinate contracts, window identity, and session validity checks.
- Treat capture failures as visible recoverable states. Never silently capture another window or monitor.
- Add behavior tests for meaningful failure modes; avoid tests that only repeat implementation details.
- Run `uv run python tools/check.py` for code changes. Real capture verification is separate:
  `uv run python tools/verify_windows.py`. Read `engineering/verification.md` before running it.
- For OCR changes, run `uv run python tools/verify_ocr.py` with local models installed. Live OCR
  integration is `uv run python tools/verify_ocr_windows.py`. Keep frame/result pairs together;
  never draw old observations onto a newer preview frame. Preserve raw OCR output for inspection.
- Tracking is deterministic and bounded. Pass time explicitly, test replay sequences, preserve
  track identity through detector-order changes, and never turn approximate text matching into
  permanent suppression of real content edits. Only committed display changes request repaint.
- Processing time and skipped capture frames are not absence evidence. Keep committed tracks and
  English between completed OCR observations. Use bounded `presence` crop digests to retain text
  through unchanged-pixel misses; never retain frame history or use pixel changes alone as absence.
  Test slow workers, dense/reordered observations, repeated misses, genuine removal, and resets.
  Run `verify_ocr.py --dense` and the live translation/dialogue check with `--ocr-delay-ms 900`.
- Keep OCR providers at the runtime boundary. Never co-install CPU/GPU ONNX distributions. GPU
  verification must use `--device cuda` and fail on fallback; normal automatic mode reports fallback.
  Use `.venv-gpu/Scripts/python.exe` for GPU checks, and preserve the default CPU environment.
  Treat first-use compilation separately from warm inference; retain the bounded local CUDA cache.
- Translation readiness is separate from display retention. Pending growth can reserve a dialogue
  group but cannot become a translation source until committed. Keep revision-valid published
  English while readiness changes; never enqueue retained-only requests. Test typewriter growth,
  early continuation, short menus, and genuine edits. Run the live dialogue check with `--typewriter`.
- Confidence belongs to a live track/content family, not a permanent screen-position cache. Keep
  the winning score private to tracking; rejected variants must preserve text revision and geometry.
  Test alternating variants, real edits, static settling, and reset boundaries before changing policy.
- Preserve raw OCR in the inspector. `text_content` derives character-bounded tracking input and
  conservatively filters isolated weak edge glyphs; never globally discard low-confidence text.
- `grouping` builds bounded dialogue blocks from stable lines. Keep speakers, choices, and unrelated
  columns separate. Requests/rendering must validate every member's ID, source, and revision;
  group bounds use per-line font height. Run the live check with `--translation --dialogue`.
- Translation backends implement `TranslationBackend`; composition belongs in `app`. Keep model
  loading, inference, unloading, and SQLite on the translation worker. Bound desired work and batches;
  validate generation, track ID, exact source, and text revision before publishing/rendering English.
- Cache identity must include weights/tokenizers, runtime, language pair, decoding settings, and any
  future glossary/context. Moving a box must not trigger translation. Swaps unload before loading.
- For translation changes, run `uv run python tools/verify_translation.py` with local models installed
  and `uv run python tools/verify_ocr_windows.py --translation` for live integration. Fast tests must
  remain model-free. Preserve raw OCR inspection and full English text when overlay layout overflows.
- Update relevant engineering documents when architecture or behavior changes; record major choices
  in `engineering/decisions/`. Keep documentation concise and avoid duplicated instructions.
- Do not claim game, mixed-DPI, HDR, or anti-cheat compatibility based solely on a demo window.
- Do not implement later milestones without a user request. Capture, OCR, tracking, local Sugoi
  translation, bounded caching, English layout, icon cleanup, and dialogue grouping are implemented.
  Other model adapters, richer dialogue context, glossaries, hotkeys, profiles, and packaging
  remain separate work.
