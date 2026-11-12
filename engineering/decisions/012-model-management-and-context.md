# Decision 012 — Explicit model setup, AMD runtimes, and dialogue context

User request: share with AMD friends, download optional models inside the app, explain first-use
GPU preparation before translation, and give Gemma a little recent dialogue context.

## Models and preparation

`model_store` owns the pinned catalog, atomic downloader, bounded operation snapshots, cancellation,
and machine/runtime-specific preparation receipts. `model_manager` polls snapshots on Qt's thread;
files are hashed/downloaded on its worker. Availability uses cheap size checks, while actual loading
still checks integrity. Explicit download is the only network operation; no background updater.
An interrupted file restarts, while verified completed files are reused. Repair never replaces a
file until its replacement is verified. Models remain absent from the sharing archive.

Composition lists only downloaded translators with available runtimes. No translation is a real
selection; missing OCR allows capture/preview without inference. After an OCR download completes,
an active capture can initialize recognition. Runtime setup remains a launcher action, avoiding pip
changes underneath a running native process. Downloading Gemma alone does not install its runtime.

Preparation consent precedes model switching. A declined prompt preserves the committed backend
even during the modal dialog's nested event loop. Acceptance drains the previous translation owner,
creates one new owner, shows indeterminate progress, and records success only after actual warm-up.
The prepared owner is reused for capture, avoiding duplicate allocations/loading. Failure restores
the previous selection; close waits for native work to finish. Preparation cannot be interrupted
inside a native model call, but the GUI stays responsive. Receipts are distinct from cached driver
kernels; new driver compilation can still happen after a receipt exists.

## AMD boundary

The Windows AMD environment uses the official llama-cpp-python 0.3.36 Vulkan wheel and ONNX
DirectML 1.24.4. NVIDIA CUDA dependencies are absent from it. UV conflicts enforce mutually exclusive
ONNX distributions and llama wheels. One Gemma adapter is used, rather than splitting onto an iGPU.
CPU Sugoi remains selectable. CPU OCR is the default in this package.

Vulkan translation passed on the development RTX 5080. Discrete Radeon cards remain untested.
DirectML initialization succeeded but Meiki detection/recognition returned incorrect values on this
machine; 1.23.0 also failed. Disabling graph fusion/optimization, memory reuse/arena, or metacommands
did not resolve the detector failure. These observations do not establish an upstream root cause.
Therefore DirectML is experimental and compares deterministic model outputs with temporary CPU
references at initialization. Automatic mode reports fallback; strict mode raises. The probe is a
compatibility guard, not a proof of accuracy on all text. CPU references are released after checking.

References: [DirectML requirements](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html),
[official Vulkan wheel](https://github.com/abetlen/llama-cpp-python/releases/tag/v0.3.36-vulkan).

## Bounded context

Grouping marks likely dialogue; a single panel owns up to two published Japanese/English turns,
512 characters combined. Revisions of the same utterance replace rather than append history. A
short punctuated reply may continue a known dialogue panel, while menu labels get empty context.
Ambiguous panels, relocation, three seconds of absence, 30 seconds of age, broad visual change,
pause/resize/restart, grouping changes and model swaps discard history. Semantic panel detection
and permanent proper-name glossaries are outside this slice; layout heuristics can misclassify text.

`TranslationSession` freezes history when a request first becomes ready. A request does not change
its own context after publishing, preventing retranslations/feedback loops. Only current valid
publications seed history. Exact context is hashed into a separate cache-key namespace; menu and
Sugoi caches stay independent. Scene resets reject in-flight old-context responses before retry.
The optional `translate_with_context` backend capability leaves the existing protocol usable by
Sugoi. Gemma drops older context before exceeding the fixed 2,048-token allocation; it never truncates
the current source. Prompt-template hashing includes the history instruction. No extra model or
conversation database is introduced; the existing bounded cache stores English and hashed keys.

## Sharing

`tools/package.py` builds an explicit allowlist of source, setup scripts, tests and engineering docs.
The ZIP includes a SHA-256 manifest and excludes local models, environments, personal IDE files,
logs, caches and captured artifacts. It is a source distribution requiring Python bootstrap and
runtime downloads, not a signed or frozen executable. Upstream model licensing remains separate.
