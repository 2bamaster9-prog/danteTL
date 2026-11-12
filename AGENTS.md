# JP Overlay engineering instructions

Read `engineering/README.md` first. The agreed product plan is in
`engineering/plan.md`; current implementation scope is in
`engineering/plans/011-gemma-and-diagnostics.md`.

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
- Visual analysis owns a separate bounded worker. Keep its thumbnails, templates, and pending job
  bounded; never run image analysis on the UI thread or rewrite raw OCR/source frame pairs. Strong
  pattern loss on two captured frames may mask a box reversibly; retirement also needs completed
  negative OCR, current revision/geometry, and visual evidence at least as new as that OCR frame.
  New translation requests wait until visual checks have examined their OCR source. Test tiny
  continuation growth, background motion, brightness/polarity changes, stale generations, static
  WGC frames, and failure fallback. Run the live dialogue check with `--typewriter --transitions`.
- Reconcile new OCR only after source-matched visual evidence arrives. Unchanged accepted glyphs
  retain identity, geometry and English across noisy/missed OCR. Below 90% confidence allow three
  reviews with a strictly better score; never reset the budget on spelling alternation. Real local
  changes unlock ordinary tracking. `presentation` may bridge only explicit same-pixel correction
  lineage, never arbitrary stale revisions. Run `tools/verify_retention_windows.py` for this policy.
- Partial OCR has explicit coverage. Unscanned tracks are not misses; never merge old raw rows into
  a newer inspector frame. Coalesce pending areas as well as pixels, preserve per-line probe source
  sequences, and validate the acknowledgement/reset path. Test crop offsets, clipping fallback,
  whole-line closure, dialogue edits across partial scans, and independent discovery deadlines.
  Run dense real OCR and `verify_retention_windows.py --appearance` for regional latency/stability.
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
- Optional Gemma uses embedded llama.cpp, not CTranslate2 or a service. Keep runtime/model setup
  explicit, prompts bounded, reasoning off, and reject incomplete answers. Verify actual CUDA
  inference and swapping with `verify_ocr_windows.py --translation --dialogue --gemma --debug`.
  Diagnostics only observe worker snapshots; distinguish visual changes, proposed scans and actual
  OCR coverage. Do not change scheduling, retention or translation sources when toggling debug.
- For translation changes, run `uv run python tools/verify_translation.py` with local models installed
  and `uv run python tools/verify_ocr_windows.py --translation` for live integration. Fast tests must
  remain model-free. Preserve raw OCR inspection and full English text when overlay layout overflows.
- Update relevant engineering documents when architecture or behavior changes; record major choices
  in `engineering/decisions/`. Keep documentation concise and avoid duplicated instructions.
- Do not claim game, mixed-DPI, HDR, or anti-cheat compatibility based solely on a demo window.
- Do not implement later milestones without a user request. Capture, OCR, tracking, local Sugoi
  translation, bounded caching, English layout, icon cleanup, and dialogue grouping are implemented.
  Gemma is an optional quality backend. Richer dialogue context, glossaries, hotkeys, profiles, and packaging
  remain separate work.
