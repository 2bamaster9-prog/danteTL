# Slice 021: Local GGUF imports

- Import a single-file GGUF by reference; weights remain user-owned. Registration is bounded,
  versioned and atomic in writable state. Locate validates the same identity; removal keeps files.
- Inspect bounded metadata and hash on a worker; never infer compatibility from the filename.
- Test local loading and menu/dialogue outputs in an owned cancellable child with a timeout.
  Testing temporarily unloads the current translator, hides its English, and preserves selection.
  Capture/OCR continue. Add only after explicit review; importing never automatically selects it.
- Add a separate GGUF backend: embedded templates plus explicit Gemma 4, ChatML and Llama 3
  formats, reasoning off, bounded current source/history/output. Reject incomplete/non-answer text.
  Missing templates require a choice. Split files, embedding/projector models and TranslateGemma's
  specialized input are outside this slice. Runtime load/probe is the final architecture check.
- Preserve built-in Gemma/Sugoi paths, native dependency versions and runtime setup. Reuse the
  installed CPU/CUDA/Vulkan engine, with actual GPU offload required by the compatibility test.
- Identity includes content hash, template/profile, prompt/decoding, runtime/device and language
  pair; existing request-scoped context remains part of cache identity. Recheck content on load.
- Verify model-free failures, real Qwen/Gemma imports, native selection/cancel/removal, built-in
  Gemma return, live dialogue/pause behavior and the relocated standalone package.

OCR engines, other translation languages, URLs, conversion and additional downloads in the model
catalog are outside this slice. Import accepts local files only and performs no network requests.
