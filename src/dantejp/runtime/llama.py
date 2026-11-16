"""Embedded llama.cpp discovery and native loading, independent of model prompts/weights."""

import importlib
import os
import threading
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

_dll_handles: list[Any] = []
_load_lock = threading.Lock()
_runtime: Any = None


def _modern(runtime_version: str) -> bool:
    try:
        return Version(runtime_version) >= Version("0.4.7")
    except InvalidVersion:
        return False


def supports_plamo() -> bool:
    """Read metadata only; never load a native engine during UI discovery."""
    try:
        # Upstream 0.3.37 adds the tokenizer; the older fork used a separate 0.4.x API.
        return Version(distribution("llama-cpp-python").version) >= Version("0.3.37")
    except (PackageNotFoundError, InvalidVersion):
        return False


def flash_attention_options(runtime: Any, device: str) -> dict[str, Any]:
    """Keep the existing on/off policy across the old boolean and new enum API."""
    if _modern(getattr(runtime, "__version__", "0")):
        return {"flash_attn_type": 1 if device == "cuda" else 0}
    return {"flash_attn": device == "cuda"}


def installed_device() -> str | None:
    """Inspect the installed wheel without loading a native runtime on the GUI thread."""
    try:
        names = {Path(str(p)).name for p in distribution("llama-cpp-python").files or ()}
    except PackageNotFoundError:
        return None
    if "ggml-vulkan.dll" in names:
        return "vulkan"
    if "ggml-cuda.dll" in names:
        return "cuda"
    cpu = "ggml-cpu.dll" in names or any(n.startswith("ggml-cpu-") for n in names)
    return "cpu" if {"llama.dll", "libllama.dll"} & names and cpu else None


def load_runtime(device: str) -> Any:
    """Load native libraries on a worker or in the isolated setup probe only."""
    global _runtime
    with _load_lock:
        if _runtime is not None:
            return _runtime
        _prepare_libraries(device)
        runtime = importlib.import_module("llama_cpp")
        # Legacy 0.4.x wheels need explicit plugin discovery before GPU queries.
        # Publish only after complete initialization; a failed load can be retried.
        if _modern(getattr(runtime, "__version__", "0")):
            ggml = importlib.import_module("llama_cpp._ggml")
            if runtime.__file__ is None:
                raise RuntimeError("Language-model runtime has no library location.")
            directory = Path(runtime.__file__).parent / "lib"
            ggml.ggml_backend_load_all_from_path(str(directory).encode("utf-8"))
        _runtime = runtime
        return runtime


def _prepare_libraries(device: str) -> None:
    if os.name == "nt" and not _dll_handles:
        paths = set()
        packages = ("llama-cpp-python",)
        if device == "cuda":
            packages += ("nvidia-cuda-runtime", "nvidia-cublas")
        for name in packages:
            package = distribution(name)
            paths.update(
                str(package.locate_file(path).parent)
                for path in package.files or ()
                if str(path).endswith(".dll")
            )
        _dll_handles.extend(os.add_dll_directory(path) for path in sorted(paths))
        os.environ["PATH"] = os.pathsep.join((*sorted(paths), os.environ.get("PATH", "")))
