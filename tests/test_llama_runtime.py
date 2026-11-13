from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jp_overlay import llama_runtime


@pytest.mark.parametrize(
    "files, expected",
    [
        ((), None),
        (("llama.dll",), None),
        (("llama.dll", "ggml-cpu.dll"), "cpu"),
        (("llama.dll", "ggml-cpu.dll", "ggml-cuda.dll"), "cuda"),
        (("llama.dll", "ggml-cpu.dll", "ggml-vulkan.dll"), "vulkan"),
    ],
)
def test_discovery_distinguishes_cpu_gpu_and_missing_engine_without_importing(
    monkeypatch, files, expected
):
    monkeypatch.setattr(llama_runtime, "distribution", lambda _: SimpleNamespace(files=files))
    imports = Mock(side_effect=AssertionError("Discovery must not load native libraries"))
    monkeypatch.setattr(llama_runtime.importlib, "import_module", imports)
    assert llama_runtime.installed_device() == expected
    imports.assert_not_called()


def test_missing_distribution_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        llama_runtime, "distribution", Mock(side_effect=PackageNotFoundError("llama-cpp-python"))
    )
    assert llama_runtime.installed_device() is None


def test_cpu_loading_never_requests_gpu_packages(monkeypatch, tmp_path):
    requested = []

    def package(name):
        requested.append(name)
        assert name == "llama-cpp-python"
        return SimpleNamespace(
            files=(Path("llama_cpp/lib/llama.dll"),),
            locate_file=lambda p: tmp_path / p,
        )

    monkeypatch.setattr(llama_runtime, "distribution", package)
    monkeypatch.setattr(llama_runtime, "_dll_handles", [])
    monkeypatch.setattr(llama_runtime.os, "add_dll_directory", lambda p: object())
    monkeypatch.setenv("PATH", "original")
    runtime = object()
    monkeypatch.setattr(llama_runtime.importlib, "import_module", lambda _: runtime)
    assert llama_runtime.load_runtime("cpu") is runtime
    assert llama_runtime.load_runtime("cpu") is runtime
    assert requested == ["llama-cpp-python"]
