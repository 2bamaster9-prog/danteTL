# 018: CPU language models and optional acceleration

Gemma's inference engine supports CPU execution. The previous GPU-only readiness check and
distribution were a product limitation. Bundle the pinned llama-cpp-python 0.3.36 Windows CPU wheel
in standalone releases and include it in the explicit CPU runtime profile. Models still require
explicit downloads. The `llm-cpu` dependency group conflicts with CUDA/Vulkan llama groups; never
install competing wheels into one environment. Source users can select `--group llm-cpu` explicitly.

`llama_runtime` owns engine discovery and native loading separately from Gemma's prompt, weights
and decoding. Metadata discovery distinguishes absent, CPU, CUDA and Vulkan engines without
importing native code on the GUI thread. GPU builds still prefer their installed accelerator;
CPU fallback is explicit through the CPU runtime, not a silent change after GPU inference failure.

Runtime labels describe hardware: CPU, NVIDIA GPU — CUDA, GPU — Vulkan. Preserve persisted profile
IDs (`cpu`, `nvidia`, `amd`) and legacy dependency groups. These install engines usable by compatible
models; they do not promise that any arbitrary future model is supported. Vulkan retains CPU OCR
and the existing Radeon validation limitation. NVIDIA keeps shared CUDA 13 and GPU OCR.

CPU Gemma sets zero offloaded layers, disables flash attention, batches prompt evaluation at 128,
and uses at most four threads (half logical CPUs, minimum one). GPU's tested single-token prefill
and thread settings stay unchanged. Device/prefill remain in cache identity. CPU never creates a
CUDA cache or asks for NVIDIA libraries. Do not equate mapped model size with additional RAM usage.

Show CPU availability with a nonblocking performance notice; only missing engines block selection.
First-use consent verifies weights and runs a short translation on either device, preserving the
previous choice when declined or failed. Reuse the prepared worker. Runtime setup/restart, model
cache isolation and bounded dialogue context remain unchanged.

Verify real CPU-only inference, current GPU inference, native preparation and live dialogue swaps,
then verify the final portable EXE and in-app runtime switching in isolated AppData. CPU timings
on the developer's 9800X3D are fixture measurements, not promises for typical PCs or game frame rates.

Source: [official CPU wheel index](https://abetlen.github.io/llama-cpp-python/whl/cpu/llama-cpp-python/).
