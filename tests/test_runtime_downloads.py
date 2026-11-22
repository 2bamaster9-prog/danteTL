import hashlib
import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest
from download_fixtures import download_bytes

from dantetl.runtime import downloads as downloads
from dantetl.runtime.setup_values import Cancelled


def export(tmp_path, wheels, *, marker="", digest=None):
    digest = digest if digest is not None else "a" * 64
    path = tmp_path / "pylock.toml"
    path.write_text(
        'lock-version = "1.0"\n[[packages]]\nname = "example"\n'
        + (f'marker = "{marker}"\n' if marker else "")
        + "wheels = [\n"
        + ",\n".join(
            f'{{ url = "https://example.test/{w}", hashes = {{sha256="{digest}"}} }}'
            for w in wheels
        )
        + "\n]\n"
    )
    return path


def test_locked_selection_prefers_windows_cpython_and_accepts_universal(tmp_path):
    names = [
        "example-1.0-py3-none-any.whl",
        "example-1.0-cp312-cp312-win_amd64.whl",
        "example-1.0-cp313-cp313-win_amd64.whl",
        "example-1.0-cp312-cp312-manylinux1_x86_64.whl",
    ]
    assert downloads.locked_wheels(export(tmp_path, names))[0].filename == names[1]
    assert downloads.locked_wheels(export(tmp_path, names[:1]))[0].filename == names[0]
    assert downloads.locked_wheels(export(tmp_path, names, marker="sys_platform == 'linux'")) == ()


def test_no_binary_or_unpinned_download_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="No pinned"):
        downloads.locked_wheels(export(tmp_path, ["example-1.0-cp313-cp313-win_amd64.whl"]))
    with pytest.raises(ValueError, match="SHA-256"):
        downloads.locked_wheels(export(tmp_path, ["example-1.0-py3-none-any.whl"], digest=""))


def test_cpu_source_uses_complete_local_wheel_without_network_or_building(tmp_path, monkeypatch):
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\n[[packages]]\nname = "llama-cpp-python"\nversion = "0.3.37"\n'
        'sdist = {url = "https://example.test/source.tar.gz", hashes = {sha256 = "'
        + "a" * 64
        + '"}}\n'
    )
    wheel = tmp_path / "llama_cpp_python-0.3.37-py3-none-win_amd64.whl"
    data = b"complete upstream wheel"
    wheel.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    wheel.with_suffix(".whl.sha256").write_text(f"{digest}  {wheel.name}")
    monkeypatch.setattr(downloads, "download_file", lambda *a, **kw: pytest.fail("No network"))
    with pytest.raises(ValueError, match="CPU wheel is missing"):
        downloads.locked_wheels(lock)
    requirements = downloads.prepare_wheels(
        lock, tmp_path / "cache", lambda p: None, threading.Event(), cpu_wheel=wheel
    )
    assert requirements.read_text().strip() == f"{wheel.as_uri()} --hash=sha256:{digest}"
    assert wheel.read_bytes() == data
    lock.write_text(lock.read_text().replace('version = "0.3.37"', 'version = "0.3.38"'))
    with pytest.raises(ValueError, match="does not match"):
        downloads.locked_wheels(lock, cpu_wheel=wheel)
    lock.write_text(lock.read_text().replace('version = "0.3.38"', 'version = "0.3.37"'))
    wheel.write_bytes(b"damaged wheel")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        downloads.prepare_wheels(
            lock, tmp_path / "cache", lambda p: None, threading.Event(), cpu_wheel=wheel
        )


def test_direct_gpu_wheel_keeps_locked_url_hash_and_never_substitutes_cpu(tmp_path):
    lock = tmp_path / "pylock.toml"
    url = "https://example.test/vulkan/llama_cpp_python-0.3.37-py3-none-win_amd64.whl"
    lock.write_text(
        'lock-version = "1.0"\n[[packages]]\nname = "llama-cpp-python"\n'
        f'archive = {{url = "{url}", hashes = {{sha256 = "' + "a" * 64 + '"}}\n'
    )
    (result,) = downloads.locked_wheels(lock, cpu_wheel=tmp_path / "unrelated.whl")
    assert result.url == url and result.sha256 == "a" * 64 and result.local_path is None


@pytest.fixture
def download(monkeypatch):
    data = b"wheel bytes" * 100000
    wheel = downloads.RuntimeArtifact(
        "example",
        "example-1.0-py3-none-any.whl",
        "https://example.test/example.whl",
        hashlib.sha256(data).hexdigest(),
        len(data),
    )

    network = Mock(side_effect=download_bytes(data))
    monkeypatch.setattr(downloads, "download_file", network)
    return wheel, data, network


def test_download_has_intermediate_bytes_verifies_and_reuses_cache(tmp_path, download):
    wheel, data, network = download
    progress = []
    path = downloads.download_artifact(wheel, tmp_path, progress.append, threading.Event())
    assert path.read_bytes() == data
    values = [v.download for v in progress if v.download]
    assert any(0 < v.received < v.total for v in values)
    assert values[-1].received == values[-1].total == len(data)
    assert downloads.download_artifact(wheel, tmp_path, progress.append, threading.Event()) == path
    assert network.call_count == 1
    assert not list(tmp_path.rglob("*.part"))


def test_unknown_http_length_is_not_fabricated(tmp_path, download):
    wheel, data, _ = download
    progress = []
    downloads.download_artifact(
        replace(wheel, size=0), tmp_path, progress.append, threading.Event()
    )
    assert progress[-1].download.received == len(data)
    assert progress[-1].download.total == 0


@pytest.mark.parametrize("failure", ["cancel", "checksum", "oversized"])
def test_failure_never_publishes_partial_wheel_or_removes_other_cached_files(
    tmp_path, download, failure
):
    wheel, _, _ = download
    kept = tmp_path / "previous.whl"
    kept.write_bytes(b"kept")
    cancel = threading.Event()
    if failure == "checksum":
        wheel = replace(wheel, sha256="b" * 64)
    elif failure == "oversized":
        wheel = replace(wheel, size=10)

    def progress(value):
        if failure == "cancel" and value.download and value.download.received:
            cancel.set()

    with pytest.raises(Cancelled if failure == "cancel" else RuntimeError):
        downloads.download_artifact(wheel, tmp_path, progress, cancel)
    assert kept.read_bytes() == b"kept"
    parts = list(tmp_path.rglob("*.part"))
    if failure == "cancel":
        assert len(parts) == 1 and 0 < parts[0].stat().st_size < wheel.size
    else:
        assert not parts
    assert not (tmp_path / wheel.sha256 / wheel.filename).exists()


def test_verified_requirements_retain_hash_and_unicode_paths(tmp_path, download):
    wheel, _, _ = download
    path = export(tmp_path, [wheel.filename], digest=wheel.sha256)
    requirements = downloads.prepare_wheels(
        path, tmp_path / "日本語 cache", lambda p: None, threading.Event()
    )
    text = requirements.read_text("utf-8")
    assert "--hash=sha256:" + wheel.sha256 in text
    assert "file:///" in text and "%20" in text
