"""Embedded llama.cpp discovery and native loading, independent of model prompts/weights."""

import importlib
import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any

_dll_handles: list[Any] = []


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
    return "cpu" if {"llama.dll", "ggml-cpu.dll"} <= names else None


def load_runtime(device: str) -> Any:
    """Load native libraries on a worker or in the isolated setup probe only."""
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
    return importlib.import_module("llama_cpp")
