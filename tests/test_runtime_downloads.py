import hashlib
import io
import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest

from jp_overlay import runtime_downloads as downloads
from jp_overlay.model_store import Cancelled


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


@pytest.fixture
def download(monkeypatch):
    data = b"wheel bytes" * 100000
    wheel = downloads.RuntimeWheel(
        "example",
        "example-1.0-py3-none-any.whl",
        "https://example.test/example.whl",
        hashlib.sha256(data).hexdigest(),
        len(data),
    )

    class Response(io.BytesIO):
        headers = {}  # Unknown HTTP length; pinned size still gives progress.

    def response(*args, **kwargs):
        return Response(data)

    network = Mock(side_effect=response)
    monkeypatch.setattr(downloads, "urlopen", network)
    return wheel, data, network


def test_download_has_intermediate_bytes_verifies_and_reuses_cache(tmp_path, download):
    wheel, data, network = download
    progress = []
    path = downloads.download_wheel(wheel, tmp_path, progress.append, threading.Event())
    assert path.read_bytes() == data
    values = [v.download for v in progress if v.download]
    assert any(0 < v.received < v.total for v in values)
    assert values[-1].received == values[-1].total == len(data)
    assert downloads.download_wheel(wheel, tmp_path, progress.append, threading.Event()) == path
    assert network.call_count == 1
    assert not list(tmp_path.rglob("*.part"))


def test_unknown_http_length_is_not_fabricated(tmp_path, download):
    wheel, data, _ = download
    progress = []
    downloads.download_wheel(replace(wheel, size=0), tmp_path, progress.append, threading.Event())
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
        downloads.download_wheel(wheel, tmp_path, progress, cancel)
    assert kept.read_bytes() == b"kept"
    assert not list(tmp_path.rglob("*.part"))
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
