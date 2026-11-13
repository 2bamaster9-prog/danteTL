# Slice 017: Reduce runtime downloads without losing GPU OCR

Replace the dual CUDA 12/13 NVIDIA dependency set with shared CUDA 13. Keep OCR and Gemma on
the GPU, preserve model weights, explicit setup, AppData ownership and the CPU/AMD alternatives.
Do not modify an active user's runtime or introduce a lower-performance default to save downloads.

Acceptance:
- Resolve pinned Windows wheels in an isolated candidate; compare compressed dependency bytes.
- Compare real OCR text/bounds and warm timings to the existing CUDA 12 environment, including
  dense 4K and changed-region scans. New strict CUDA checks must fail if the provider falls back.
- Run Gemma offline, both engines together in each initialization order, and inspect loaded DLLs.
- Verify live dialogue/typewriter grouping, model swaps, original hold and overlay persistence.
- Check in-app preparation and runtime install/restart in a disposable standalone extraction.
- Rebuild the ZIP, verify its manifest and native launcher with Python absent from PATH.
- Preserve existing user models, installed runtimes and the default development CPU environment.

Numerical results, package measurements and platform limits belong in [verification](../verification.md).
