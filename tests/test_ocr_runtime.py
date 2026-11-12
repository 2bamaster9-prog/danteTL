from types import SimpleNamespace

from jp_overlay import ocr_runtime


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
    runtime = SimpleNamespace(preload_dlls=lambda **kwargs: calls.append(kwargs))
    ocr_runtime.prepare_cuda(runtime)
    ocr_runtime.prepare_cuda(runtime)
    assert cache.is_dir()
    assert ocr_runtime.os.environ["CUDA_CACHE_PATH"] == str(cache)
    assert ocr_runtime.os.environ["CUDA_CACHE_MAXSIZE"] == "268435456"
    assert calls == [{"directory": ""}, {"directory": ""}]
