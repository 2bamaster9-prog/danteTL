# 021: User-owned GGUF translation models

Keep the tested built-in Gemma adapter unchanged. A separate `GgufBackend` implements the existing
translation contract and owns imported prompt formats, native loading and answer validation.
The runtime remains pinned; importing cannot install packages or change acceleration environments.

GGUF metadata describes architecture and chat format but does not prove executability or translation
quality. A bounded metadata reader rejects obvious wrong inputs, and the setup worker fingerprints
files. An owned child then loads the current engine and translates three original samples with
network connections blocked. The UI displays outputs/timings for review, distinguishing tested
execution from translation quality. Missing/unsupported formats never silently use a default.

Registration is explicit after testing, by absolute path and content/profile identity. This avoids
duplicating gigabytes of weights. Moving a file requires Locate; altered weights require a new
import. Missing models remain visible with recovery instructions. Remove never deletes weights.
Registry mutations use the setup worker and atomic publication; corrupt registries are preserved.

To prevent two language models competing for memory, a probe waits for the active translation
worker to drain. Capture/recognition continue; English is cleared during the test and the committed
model choice is retained. Cancellation and app shutdown kill/drain the owned test before cleanup.
Real selection uses the existing consent/unload/preparation path and stale-result protection.

Generic templates receive one user turn with translation instructions, bounded reference history
and CURRENT. This supports formats without a system role. Gemma 4 uses its native non-thinking
prompt. Qwen templates receive `enable_thinking=False`; only an empty thinking wrapper is stripped.
Nonempty reasoning and truncated output are rejected. TranslateGemma needs a dedicated profile
and is explicitly rejected for now. No language settings or arbitrary Python plugins are added.
