# Gemma 4 E2B and local diagnostics

The user wants better translation quality while retaining Sugoi, plus visible evidence of where
latency comes from. Gemma 4 E2B is an optional quality experiment, not a proven universal winner.

## Runtime and model

CTranslate2's current support table explicitly excludes Gemma 4 E2B/E4B. Keep Sugoi on CTranslate2
and implement the existing backend interface with embedded llama.cpp for Gemma. No HTTP server,
Ollama installation, inference API, or runtime downloads are introduced. A pinned Windows CUDA
wheel and pip-local CUDA 13 libraries are optional dependencies; CPU-only Sugoi remains the default.
CUDA 13 libraries live alongside OCR's separate CUDA 12 DLLs, without a system toolkit installation.

Use Google's official instruction-tuned QAT Q4_0 GGUF (3,349,516,256 bytes), pinned by repository
revision and SHA-256. Text-only use does not need the approximately 987 MB multimodal projector.
The GGUF contains the tokenizer. Google labels this model Apache-2.0; this does not change Sugoi's
separate terms or make a combined Sugoi bundle unrestricted. Preserve license notices when distributing.

Allocate 2,048 context tokens and cap output at 384. Use the Gemma 4 native system/user/model turn
format, no thinking token, greedy decoding, no cross-request conversation history. Current grouped
dialogue is the available context; a large advertised context window does not supply earlier dialogue
automatically. Escape turn-marker syntax in OCR input. Reject truncated/empty/non-answer output;
do not silently cache a partial sentence. Existing 512-character source limits remain.

The pinned CUDA wheel needed costly first-use kernel compilation on the RTX 5080 and stalled again
on changing prompt shapes. Use single-token prefill with prefix reuse for these short sources, plus
a warm-up under the loading state and the same bounded writable driver cache as OCR. A fresh-process
recheck removed the repeated stalls. Include prefill shape in cache identity; generation can differ
slightly with floating-point batch shape. Long prompts need their own latency review.

The translation worker owns model load/inference/close. Gemma requests a batch size of one so each
completed label is published immediately and obsolete remaining labels can be skipped. Sugoi retains
four-source batching. Cache identity includes weight/tokenizer hash, runtime, device, language pair,
prompt hash, context and decoding settings. Generation/revision/member checks apply to both backends.

## Diagnostics

The checkbox is an observation-only view. Amber cells show significant frame-to-frame differences
from the existing 32×18 visual grid. Cyan outlines show **last completed** OCR coverage, including
full-frame fallback, rather than proposed crops or fabricated retained detections. Display result age,
OCR capture-to-start wait, OCR runtime, visual runtime, settling/reveal holds, translation pending count,
current call age, last batch time, model/cache source counts, and model load time. Translation wait is
ready-request-to-batch-start; it does not include earlier dialogue settling.
The last actual model inference time remains visible across later cache-only batches. Use the
high-resolution performance clock for durations and monotonic timestamps for cross-worker ages.

Rendering stays click-through, excluded from capture, and physical-pixel aligned. No images, source
text, or history are saved by debug mode. Bounds, snapshots and timers are bounded; disabling it
returns to ordinary equality-based repaint behavior. Reset/hide rules remain identical to English.

## Primary references (checked 2026-11-13)

- [Google model and memory overview](https://ai.google.dev/gemma/docs/core)
- [Official quantized model, Apache-2.0 metadata](https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf)
- [CTranslate2 support table](https://opennmt.net/CTranslate2/guides/transformers)
- [Google llama.cpp integration](https://ai.google.dev/gemma/docs/integrations/llamacpp)
- [Pinned Python CUDA runtime release](https://github.com/abetlen/llama-cpp-python/releases/tag/v0.3.36-cu130)
- [Gemma 4 prompt template](https://huggingface.co/google/gemma-4-E2B-it/blob/main/chat_template.jinja)

Google's small/mobile memory estimates describe particular quantizations and runtimes; they are not
a total application RAM/VRAM guarantee. Record measured process memory, GPU totals, initialization,
warm inference and quality examples separately. Live game frame-time impact remains a manual check.
