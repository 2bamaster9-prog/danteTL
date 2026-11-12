# Slice eleven — Optional Gemma and latency diagnostics

Requested scope: investigate and try Gemma 4 E2B for local Japanese-to-English quality, keep Sugoi
selectable, and show changed regions, actual OCR coverage and timings during Honkai testing.

Implemented: pinned optional model/runtime setup, embedded GPU backend, bounded prompts/output,
separate cache identity, immediate per-source publication, and observation-only debug overlay.
See [decision](../decisions/011-gemma-and-diagnostics.md) for runtime and memory tradeoffs.

Acceptance: fast behavior/type/lint checks; offline real-model comparison; full native dialogue,
model switching in both directions, debug toggling, pause/resize/minimize/restart/close; CPU Sugoi
regression and unchanged regional coverage. Record results in verification/performance documents.

Verified on the development RTX 5080: 31–203 ms model-only translation of nine original phrases after
warm-up, 3.64 s load on a new process with prepared CUDA cache. Native typewriter-to-complete-English
was 0.75 s, with grouped source and no partial dialogue requests. Both switch directions, debug,
CPU OCR restart, and shutdown passed. Full synthetic GPU OCR/overlay process working set was about
3.0 GiB (private memory about 4.95 GiB); translation-only GPU-wide memory delta was about 1.6 GiB.
These are snapshots and fixture timings, not an in-game budget or a quality benchmark.

Not included: previous-dialogue memory, glossary/proper-name profiles, tuning, speculative decoding,
automatic quality scoring, AMD/Intel GPU presets, or a claim of superior game-wide translation quality.
