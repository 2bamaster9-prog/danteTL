import threading
from unittest.mock import Mock

import pytest

from dantejp.runtime import first_run
from dantejp.runtime.model_store import ModelOperation
from dantejp.runtime.setup_values import Cancelled, DownloadProgress, ModelProgress
from dantejp.runtime.values import PROFILES


def test_setup_plan_has_no_side_effect_until_run_and_preserves_byte_progress(monkeypatch, tmp_path):
    order = []
    download = DownloadProgress("weights", 4, 10)
    models = (Mock(name="ocr"), Mock(name="translator"))
    plan = first_run.SetupPlan(models, PROFILES[0])
    monkeypatch.setattr(
        first_run,
        "install_model",
        lambda model, report, cancel: (
            order.append(model),
            report(ModelProgress(download=download)),
        ),
    )
    monkeypatch.setattr(
        first_run, "install_runtime", lambda root, runtime, report, cancel: order.append(runtime)
    )
    monkeypatch.setattr(first_run, "ready_runtime", lambda *args: tmp_path)
    assert not order
    updates = []
    assert first_run.run_setup(plan, tmp_path, updates.append, threading.Event()) == tmp_path
    assert order == [*models, PROFILES[0]]
    assert updates[0].download == download and updates[0].stage == 1 and updates[0].stages == 3


def test_cancel_between_models_never_installs_runtime(monkeypatch, tmp_path):
    cancel = threading.Event()
    runtime = Mock()
    monkeypatch.setattr(first_run, "install_model", lambda *args: cancel.set())
    monkeypatch.setattr(first_run, "install_runtime", runtime)
    with pytest.raises(Cancelled):
        first_run.run_setup(
            first_run.SetupPlan((Mock(), Mock()), PROFILES[0]), tmp_path, lambda p: None, cancel
        )
    runtime.assert_not_called()


def test_operation_keeps_download_snapshot_on_completion():
    value = ModelProgress("ready", download=DownloadProgress("file", 10, 10), stage=2, stages=2)
    operation = ModelOperation(lambda progress, cancel: progress(value))
    operation.start()
    operation._thread.join(2)
    result = operation.snapshot()
    assert result.done and result.download == value.download and result.stage == 2
