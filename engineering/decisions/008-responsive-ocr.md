# Decision 008 — Reveal readiness and optional CUDA OCR

The user found dialogue slow to regroup after typewriter animation and requested RTX 5080 OCR
acceleration while retaining a simple CPU path.

## Readiness

Previously, confirmed old fragments remained eligible during new pending edits. Grouping saw only
committed text and began its own 350 ms wait afterward. This could schedule short translations early
and delay the final combined request.

Tracking now exposes current reveal activity independently of displayed text. The grouper reserves
likely continuations using plausible candidate geometry/text, then builds its actual sources from
committed lines. New work requires confirmed members, no genuine pending edit, and a quiet period
measured from the observed change. Terminal punctuation uses 180 ms; growing/unfinished paragraphs
use 550 ms; other long single lines use 350 ms. Ordinary short menus need no extra delay. One-character
growth at the same origin can keep its identity. The existing confidence and absence policies remain.

The translation worker separately receives ready and retained-only requests, bounded to 128 total.
Retention preserves already-published English without generating work. Exact source, revision,
membership, and generation checks still reject obsolete replies. There is no new queue or text history.
A sufficiently long typing pause can look finished; detecting game-specific animation completion
without game state remains heuristic.

## Optional runtime

The default environment remains CPU. Explicit GPU setup installs ONNX Runtime GPU 1.26.0 (CUDA 12.8
build), pip NVIDIA CUDA 12 libraries, and cuDNN 9.10.2.21 into `.venv-gpu`. The lockfile records all
versions; cublas 12.9.2.10 has a Windows wheel. The groups conflict because both ONNX distributions
write the same Python namespace. The pinned Meiki dependency metadata removes its unconditional CPU
runtime dependency; model algorithms/weights are unchanged. Setup uses uv, not raw pip installation.

Auto mode validates all three CUDA sessions. Initialization/inference failure unloads the GPU engine
and retries on CPU with a visible diagnostic. Strict CUDA verification fails instead. CPU selection
never initializes CUDA. DLL paths are scoped to the process; no driver/toolkit or global PATH changes.
Sugoi remains CPU int8. Capture is selectable from 2–8 Hz, initially 6 for GPU auto and 4 for CPU.
One replaceable pending frame absorbs overload; higher capture rates cannot force extra inference.

GPU arena limit is 512 MiB per ONNX session, not a total VRAM guarantee. Blackwell first-use kernel
compilation took about 55 seconds in exploratory runs. A writable local CUDA cache reduced repeated
process startup inference to about 1.2 seconds. Setup primes `data/cuda-cache` and marks the GPU
environment ready only after successful real OCR. Cache budget defaults to 512 MiB; explicit user
CUDA cache settings are respected. Driver/new-kernel changes can require warm-up again.

DirectML was evaluated because of its smaller install, but returned zero detections on known-good
fixtures on this machine even though its provider initialized. It is not shipped. CUDA produced the
expected output and profiling recorded actual CUDA node execution. `HEURISTIC` convolution selection
was substantially faster than `DEFAULT` here. These are fixture results, not claims for all GPUs.

## References

- [ONNX Runtime CUDA provider and pip DLL loading](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- [CUDA compilation cache controls](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html)
- [uv dependency metadata and conflicting groups](https://docs.astral.sh/uv/concepts/projects/config/)
