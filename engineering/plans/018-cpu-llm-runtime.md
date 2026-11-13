# Slice 018: CPU Gemma and model-independent runtimes

- Include a pinned CPU llama.cpp engine in the standalone app and explicit CPU setup profile.
- Recognize CPU readiness independently from downloaded weights and optional GPU acceleration.
- Keep runtime labels about hardware and show a nonblocking CPU performance notice.
- Preserve explicit downloads, first-use consent, previous selection, preparation worker reuse,
  model/device cache separation, native restart and CPU fallback.
- Verify CPU output, memory/timings, native setup, model switches and dialogue with real local models.
- Recheck actual CUDA inference after moving shared engine loading out of the Gemma adapter.
- Test final ZIP in a relocated Unicode path without Python on PATH, plus packaged CPU/GPU setup.

No new model architectures, generic plugin framework, auto-downloads or installer are included.
Results and limits belong in [verification](../verification.md).
