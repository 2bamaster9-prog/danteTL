import hashlib
import io
import threading
from unittest.mock import Mock

import pytest

from jp_overlay import model_store as store
from jp_overlay.models import ModelAsset


def bundle(tmp_path):
    asset = ModelAsset("fixture", "revision", "weights", hashlib.sha256(b"good").hexdigest(), 4)
    return store.ModelBundle("fixture", "Test", tmp_path, (asset,), "")


def test_download_is_explicit_atomic_verified_and_reuses_valid_files(tmp_path, monkeypatch):
    model = bundle(tmp_path)
    download = Mock(side_effect=lambda *a, **k: io.BytesIO(b"good"))
    monkeypatch.setattr(store, "urlopen", download)
    assert not model.present()
    download.assert_not_called()
    progress = []
    store.install_model(model, progress.append, threading.Event())
    assert model.present() and (tmp_path / "weights").read_bytes() == b"good"
    assert progress[-1].received == progress[-1].total == 4
    store.install_model(model, progress.append, threading.Event())
    download.assert_called_once()
    assert not tuple(tmp_path.glob("*.part"))


@pytest.mark.parametrize("payload", [b"bad", b"evil", b"too large"])
def test_bad_download_does_not_replace_existing_file(tmp_path, monkeypatch, payload):
    model = bundle(tmp_path)
    (tmp_path / "weights").write_bytes(b"old")
    monkeypatch.setattr(store, "urlopen", lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(RuntimeError):
        store.install_model(model, lambda p: None, threading.Event())
    assert (tmp_path / "weights").read_bytes() == b"old"
    assert not tuple(tmp_path.glob("*.part"))


def test_cancelled_download_removes_partial_without_publishing(tmp_path, monkeypatch):
    cancel = threading.Event()
    monkeypatch.setattr(store, "urlopen", lambda *a, **k: io.BytesIO(b"good"))

    def progress(value):
        if value.received:
            cancel.set()

    with pytest.raises(store.Cancelled):
        store.install_model(bundle(tmp_path), progress, cancel)
    assert not tuple(tmp_path.iterdir())


def test_worker_reports_failure_and_cancellation():
    def fail(progress, cancel):
        raise OSError("Disk full")

    operation = store.ModelOperation(fail)
    operation.start()
    operation._thread.join(2)
    assert operation.snapshot().done and operation.snapshot().error == "Disk full"


def test_receipt_is_runtime_and_machine_specific_and_only_written_after_success(
    tmp_path, monkeypatch
):
    model = bundle(tmp_path)
    monkeypatch.setattr(store, "preparation_file", lambda key: tmp_path / f"{key}.json")
    cuda = store.preparation_id(model, "cuda")
    vulkan = store.preparation_id(model, "vulkan")
    assert cuda != vulkan and not store.is_prepared(cuda)
    store.mark_prepared(cuda)
    assert store.is_prepared(cuda) and not store.is_prepared(vulkan)
    monkeypatch.setattr(store, "version", lambda _: "different-runtime")
    assert store.preparation_id(model, "cuda") != cuda
