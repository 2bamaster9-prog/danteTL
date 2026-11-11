# JP Overlay engineering instructions

Read `engineering/README.md` first. The agreed product plan is in
`engineering/plan.md`; current implementation scope is in
`engineering/plans/004-local-translation.md`.

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
  translation, bounded caching, and English layout are implemented. Other model adapters, grouping,
  glossaries, hotkeys, profiles, and packaging remain separate work.
