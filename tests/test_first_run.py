import threading
from unittest.mock import Mock

import pytest

from dantejp.runtime import first_run
from dantejp.runtime.hardware import HardwareStatus
from dantejp.runtime.model_store import Cancelled, DownloadProgress, ModelOperation, ModelProgress
from dantejp.runtime.setup import PROFILES


def test_cpu_is_available_without_gpu_and_amd_does_not_require_gpu_ocr():
    assert not first_run.needs_runtime(PROFILES[2], HardwareStatus(llama_device="cpu"))
    assert not first_run.needs_runtime(PROFILES[1], HardwareStatus(llama_device="vulkan"))
    assert first_run.needs_runtime(PROFILES[0], HardwareStatus(llama_device="cuda"))
    assert not first_run.needs_runtime(
        PROFILES[0], HardwareStatus(cuda_ocr=True, llama_device="cuda")
    )
    assert first_run.needs_runtime(PROFILES[2], HardwareStatus(llama_device=None))


def test_plamo_wizard_includes_upgrade_when_existing_hardware_engine_is_too_old(monkeypatch):
    from dantejp.translation.models.curated import MODELS

    model = next(m.bundle() for m in MODELS if m.key == "plamo-0.8b")
    hardware = HardwareStatus(cuda_ocr=True, llama_device="cuda")
    monkeypatch.setattr(first_run, "supports_plamo", lambda: False)
    assert first_run.needs_runtime(PROFILES[0], hardware, model)
    assert not first_run.needs_runtime(PROFILES[0], hardware)
    monkeypatch.setattr(first_run, "supports_plamo", lambda: True)
    assert not first_run.needs_runtime(PROFILES[0], hardware, model)


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
