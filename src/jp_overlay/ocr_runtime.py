"""Select and load local OCR execution providers without owning model algorithms."""

import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"
DML = "DmlExecutionProvider"
_dll_handles: list[Any] = []


def gpu_runtime_installed(name: str = "onnxruntime-gpu") -> bool:
    try:
        distribution(name)
        return True
    except PackageNotFoundError:
        return False


def prepare_cuda(ort: Any) -> None:
    """Expose pip-installed DLLs to cuDNN's lazy loader, only inside this process."""
    cache = Path(__file__).resolve().parents[2] / "data" / "cuda-cache"
    cache = Path(os.environ.get("CUDA_CACHE_PATH", str(cache)))
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CUDA_CACHE_PATH", str(cache))
    os.environ.setdefault("CUDA_CACHE_MAXSIZE", "536870912")
    # Blackwell's first PTX compilation can take a minute. Explicit setup warms
    # this bounded, writable cache so later launches reuse the compiled kernels.
    if os.name == "nt" and not _dll_handles:
        directories = set()
        for name in (
            "nvidia-cuda-runtime-cu12",
            "nvidia-cublas-cu12",
            "nvidia-cudnn-cu12",
            "nvidia-cuda-nvrtc-cu12",
            "nvidia-nvjitlink-cu12",
            "nvidia-cufft-cu12",
            "nvidia-curand-cu12",
        ):
            package = distribution(name)
            directories.update(
                str(package.locate_file(path).parent)
                for path in package.files or ()
                if str(path).endswith(".dll")
            )
        paths = sorted(directories)
        _dll_handles.extend(os.add_dll_directory(path) for path in paths)
        # cuDNN also loads sublibraries with LoadLibrary; add_dll_directory alone
        # did not resolve its tensor-IR engine on the tested Windows runtime.
        os.environ["PATH"] = os.pathsep.join((*paths, os.environ.get("PATH", "")))
    ort.preload_dlls(directory="")


def create_sessions(paths: tuple[Any, ...], threads: int, provider: str) -> list[Any]:
    import onnxruntime as ort

    ort.set_default_logger_severity(3)
    if provider == CUDA:
        if CUDA not in ort.get_available_providers():
            raise RuntimeError(
                "CUDA runtime is not installed. Run Setup GPU OCR.cmd or choose CPU."
            )
        prepare_cuda(ort)
    if provider == DML and DML not in ort.get_available_providers():
        raise RuntimeError("DirectML is unavailable. Run Setup AMD.cmd or choose CPU OCR.")
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    options.log_severity_level = 3
    if provider == DML:
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    providers: list[Any] = [CPU]
    if provider == CUDA:
        providers.insert(
            0,
            (
                CUDA,
                {
                    "device_id": 0,
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "gpu_mem_limit": 536_870_912,
                    "use_tf32": 0,
                },
            ),
        )
    elif provider == DML:
        providers.insert(0, (DML, {"device_id": 0}))
    sessions = []
    for path in paths:
        session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
        session.disable_fallback()  # The adapter owns visible whole-engine fallback.
        if provider not in session.get_providers():
            raise RuntimeError(f"Requested OCR provider {provider} did not initialize.")
        sessions.append(session)
    return sessions
