# Slice 023: Downloadable Gemma E4B and Qwen3.5 4B

- Add pinned GGUF/model-card downloads to Models and the first-run guide, with concise tradeoffs.
- Reuse the existing local adapter, preparation consent, runtime choices and bounded dialogue context.
- Preserve E2B behavior and separate persistent selections/cache identities for every model.
- Keep CPU usable, GPU optional, missing-engine recovery visible and downloads explicit.
- Verify hash rejection, preferences across runtime changes, post-restart consent and model badges.
- Run real CPU/CUDA/Vulkan samples, native setup/missing-runtime and live dialogue/switching checks.
- Rebuild and verify the standalone app with AppData model paths and no bundled translation weights.

No Linux port, new OCR languages, inference services or runtime dependency upgrades are in scope.
