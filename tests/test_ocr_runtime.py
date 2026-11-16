from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

from dantejp.runtime import ocr as ocr_runtime


def test_cuda_setup_reuses_an_explicit_cache_without_overwriting_user_limits(
    monkeypatch, tmp_path
) -> None:
    cache = tmp_path / "compiled-kernels"
    monkeypatch.setenv("CUDA_CACHE_PATH", str(cache))
    monkeypatch.setenv("CUDA_CACHE_MAXSIZE", "268435456")
    monkeypatch.setattr(ocr_runtime, "distribution", lambda _: SimpleNamespace(files=()))
    monkeypatch.setattr(ocr_runtime, "_dll_handles", [])
    # PATH changes are process-local in production; restore this test's environment too.
    monkeypatch.setenv("PATH", ocr_runtime.os.environ.get("PATH", ""))
    calls = []
    runtime = SimpleNamespace(
        __version__="1.30.0", preload_dlls=lambda **kwargs: calls.append(kwargs)
    )
    ocr_runtime.prepare_cuda(runtime)
    ocr_runtime.prepare_cuda(runtime)
    assert cache.is_dir()
    assert ocr_runtime.os.environ["CUDA_CACHE_PATH"] == str(cache)
    assert ocr_runtime.os.environ["CUDA_CACHE_MAXSIZE"] == "268435456"
    assert calls == [{"directory": ""}, {"directory": ""}]


@pytest.mark.parametrize("version, suffix", [("1.26.0", "-cu12"), ("1.30.0", "")])
def test_cuda_libraries_follow_ocr_build_even_when_gemma_uses_cuda13(
    monkeypatch, tmp_path, version, suffix
):
    requested, exposed = [], []

    def distribution(name):
        requested.append(name)
        return SimpleNamespace(
            files=(Path("bin/library.dll"),),
            locate_file=lambda path: tmp_path / name / path,
        )

    monkeypatch.setenv("CUDA_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setenv("PATH", "original-path")
    monkeypatch.setattr(ocr_runtime, "distribution", distribution)
    monkeypatch.setattr(ocr_runtime, "_dll_handles", [])
    monkeypatch.setattr(ocr_runtime.os, "add_dll_directory", lambda path: exposed.append(path))
    preload = []
    runtime = SimpleNamespace(__version__=version, preload_dlls=lambda **k: preload.append(k))
    ocr_runtime.prepare_cuda(runtime)
    assert f"nvidia-cublas{suffix}" in requested
    assert f"nvidia-cuda-runtime{suffix}" in requested
    assert ("nvidia-cudnn-cu12" if suffix else "nvidia-cudnn-cu13") in requested
    assert len(exposed) == len(requested) == 7
    assert all(Path(path).parts[-2] in requested for path in exposed)
    assert all(path in ocr_runtime.os.environ["PATH"] for path in exposed)
    assert preload == [{"directory": ""}]
    before = list(requested)
    ocr_runtime.prepare_cuda(runtime)
    assert requested == before  # Repeated sessions retain handles without duplicate PATH entries.


def test_missing_cuda13_dependency_never_silently_loads_cuda12(monkeypatch, tmp_path):
    requested = []

    def missing(name):
        requested.append(name)
        raise PackageNotFoundError(name)

    monkeypatch.setenv("CUDA_CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setenv("PATH", "untouched")
    monkeypatch.setattr(ocr_runtime, "distribution", missing)
    monkeypatch.setattr(ocr_runtime, "_dll_handles", [])
    runtime = SimpleNamespace(__version__="1.30.0")
    with pytest.raises(PackageNotFoundError):
        ocr_runtime.prepare_cuda(runtime)
    assert requested == ["nvidia-cuda-runtime"]
    assert not ocr_runtime._dll_handles
    assert ocr_runtime.os.environ["PATH"] == "untouched"
