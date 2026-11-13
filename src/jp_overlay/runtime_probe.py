"""Fresh-process library check, without model downloads or first-use model preparation."""

import sys
from importlib.metadata import PackageNotFoundError, version


def verify(profile: str) -> None:
    if profile not in ("cpu", "nvidia", "amd"):
        raise ValueError("Unknown runtime profile.")
    installed = []
    for name in ("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"):
        try:
            version(name)
            installed.append(name)
        except PackageNotFoundError:
            pass
    expected = "onnxruntime-gpu" if profile == "nvidia" else "onnxruntime"
    if installed != [expected]:
        raise RuntimeError(f"Expected only {expected}; found {installed}.")
    # Verify the same native imports used at app startup, in this throwaway process.
    import ctranslate2  # noqa: F401
    import meikiocr  # noqa: F401
    import onnxruntime as ort
    import windows_capture  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401

    if profile == "nvidia":
        from jp_overlay.ocr_runtime import CUDA, prepare_cuda

        prepare_cuda(ort)
        if CUDA not in ort.get_available_providers():
            raise RuntimeError("The installed OCR runtime does not provide CUDA.")
    from jp_overlay.llama_runtime import installed_device, load_runtime

    device = {"nvidia": "cuda", "amd": "vulkan", "cpu": "cpu"}[profile]
    if installed_device() != device:
        raise RuntimeError(f"The installed language-model engine does not provide {device}.")
    runtime = load_runtime(device)
    runtime.llama_backend_init()
    try:
        if device != "cpu" and not runtime.llama_supports_gpu_offload():
            raise RuntimeError(
                "GPU offload is unavailable. Update your graphics driver or use CPU."
            )
    finally:
        runtime.llama_backend_free()
    print("Library checks passed. Model preparation happens after restart.", flush=True)


if __name__ == "__main__":
    verify(sys.argv[1])
