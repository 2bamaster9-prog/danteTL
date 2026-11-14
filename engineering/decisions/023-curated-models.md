# 023: Additional downloadable language models

Offer Gemma 4 E4B and Qwen3.5 4B through the existing explicit download/preparation flow.
E4B is the effective-parameter variant, not Gemma's 26B-A4B mixture model. Qwen3.5 is a different
architecture (`qwen35`) from previously tested Qwen3. No dependency upgrade is required.

`curated_models` pins single-file text GGUFs and their model cards by revision, size and SHA-256.
It constructs a checked model description on the translation worker and reuses `GgufBackend`,
without writing an import registration. Native loading validates the pinned full weights hash.
Gemma E2B's adapter, prompt, decoding and cache identity are unchanged. E4B uses the existing
Gemma 4 profile; Qwen uses its embedded template with thinking disabled. Both receive the existing
bounded dialogue history; menus stay independent. Image/audio projector files are unnecessary.

The catalog declares whether a model requires the language engine. Status/badges and first-run
setup share this fact. A backend has an explicit persistent selection ID independent of device;
E4B must never collapse into E2B through a `startswith("gemma")` match. Preparation, cache keys and
publication remain model/device scoped. Swaps drain/unload before loading the replacement.
Downloads live under writable state (`models/gemma-e4b`, `models/qwen35-4b`); standalone resources
and user-owned imports remain untouched. No model is downloaded or selected implicitly.

Descriptions explain resource/quality tradeoffs, not an unmeasured best-to-worst ranking. File
size is labelled separately from inference memory. Qwen's smaller download does not establish
lower latency or better translation; native smoke samples are not a representative benchmark.

Pinned sources:

- [Google E4B QAT](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf/tree/4b4a2c1d584be7264f87aac328a1bc739ce81b6c):
  Q4_0, 5,154,941,280-byte weights, Apache-2.0.
- [Unsloth Qwen3.5 4B conversion](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/e87f176479d0855a907a41277aca2f8ee7a09523):
  Q4_K_M, 2,740,937,888-byte weights, Apache-2.0.
- [Qwen's model card](https://huggingface.co/Qwen/Qwen3.5-4B): thinking is enabled by default;
  DanteJP explicitly uses the non-thinking template branch and rejects reasoning/incomplete output.
