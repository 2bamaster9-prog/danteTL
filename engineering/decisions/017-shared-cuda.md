# 017: Shared CUDA 13 runtime

The previous NVIDIA profile combined ONNX Runtime 1.26/CUDA 12 with llama.cpp/CUDA 13. This was
a choice of pinned binaries, not a model requirement. Upgrade OCR to ONNX Runtime 1.30.0 with
cuDNN 9.13.1.26 for CUDA 13. Keep Gemma's existing llama-cpp-python 0.3.36 CUDA 13 build and model.

The `cuda` dependency group owns the shared CUDA runtime 13.0.96 and cuBLAS 13.0.2.14 pins. Both
`gpu` and `gemma` include it. Pin OCR's NVRTC/nvJitLink 13.0.88, cuFFT 12.0.0.61 and cuRAND 10.4.0.35
instead of silently moving to newer toolkit minor versions. Those cuFFT/cuRAND version numbers
are library versions, not CUDA toolkit families. CPU, AMD/Vulkan and model weights remain unchanged.

The managed PyPI OCR builds from 1.27 onward use CUDA 13. `ocr_runtime` chooses the matching DLL
packages by OCR build version, preserving the old 1.26/CUDA 12 development environment even though
it also contains Gemma's CUDA 13 libraries. Missing libraries fail normally and automatic mode can
report CPU fallback; strict CUDA verification never accepts fallback. Custom alternate-feed CUDA
builds are outside these pinned runtime contracts. No source patch changes Meiki's inference logic.

Pinned Windows x64 NVIDIA/ONNX wheel downloads fall from 2,261,945,327 to 1,285,413,768 bytes:
976,531,559 bytes (43.2%) less. This includes shared cuBLAS and smaller updated cuDNN/ORT builds;
it excludes model weights, llama.cpp, common dependencies and managed Python. Do not describe it
as a 43% reduction in the entire first-run download or promise matching wall-clock time savings.

Use the existing explicit installer and dependency fingerprint. A new dependency set creates a
fresh isolated environment, preserves the active runtime/models, and requires acknowledged restart.
No installed user's DLLs are replaced in place, no model downloads repeat, and CPU fallback remains.
Cold kernel preparation can still take time independently of dependency downloads.

Validate numerical/text output and timing before promotion. Verify actual inference in both
initialization orders and inspect the current process's loaded CUDA/cuBLAS DLLs to catch shared
library collisions. Keep measurements scoped to the tested machine and fixtures.

References: [ONNX CUDA compatibility](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html),
[ONNX 1.30 Windows files](https://pypi.org/project/onnxruntime-gpu/1.30.0/), and
[pinned CUDA 13 Gemma runtime](https://github.com/abetlen/llama-cpp-python/releases/tag/v0.3.36-cu130).
