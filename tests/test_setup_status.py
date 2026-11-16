import threading
from unittest.mock import Mock

import pytest

from dantejp.application.setup_status import acceleration_advice
from dantejp.runtime.hardware import Adapter, HardwareCheck, HardwareStatus

NVIDIA = Adapter("NVIDIA fixture", 0x10DE, 16 * 2**30)
AMD = Adapter("AMD fixture", 0x1002, 8 * 2**30)


@pytest.mark.parametrize(
    ("hardware", "device", "provider", "expected", "destination"),
    [
        (None, "cpu", "", "", "runtime"),
        (HardwareStatus(), "cpu", "", "", "runtime"),
        (HardwareStatus((NVIDIA, AMD)), "cpu", "", "NVIDIA GPU detected", "runtime"),
        (HardwareStatus((NVIDIA,), True, "cuda"), "cpu", "", "CPU is selected", "recognition"),
        (HardwareStatus((NVIDIA,), True, "cuda"), "auto", "CUDAExecutionProvider", "", "runtime"),
        (
            HardwareStatus((NVIDIA,), True, "cuda"),
            "auto",
            "CPUExecutionProvider",
            "fell back",
            "runtime",
        ),
        (HardwareStatus((AMD,)), "cpu", "", "AMD GPU detected", "runtime"),
        (HardwareStatus((AMD,), False, "vulkan"), "cpu", "CPUExecutionProvider", "", "runtime"),
        (HardwareStatus(error="DXGI unavailable"), "cpu", "", "could not be checked", "runtime"),
    ],
)
def test_acceleration_advice_does_not_treat_amd_cpu_ocr_or_unknown_hardware_as_failure(
    hardware, device, provider, expected, destination
):
    advice = acceleration_advice(
        hardware, device, actual_provider=provider, fallback="probe failed"
    )
    assert expected in advice.message if expected else not advice.message
    assert advice.destination == destination
    if "fell back" in expected:
        assert "probe failed" in advice.message


def test_hardware_check_is_once_off_thread_and_failure_is_reported(monkeypatch):
    threads = []
    entered, release = threading.Event(), threading.Event()

    def detect():
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        return (NVIDIA,)

    monkeypatch.setattr("dantejp.runtime.hardware.detect_adapters", detect)
    monkeypatch.setattr("dantejp.runtime.llama.installed_device", lambda: "cuda")
    monkeypatch.setattr("dantejp.runtime.ocr.gpu_runtime_installed", lambda: True)
    check = HardwareCheck()
    check.start()
    assert entered.wait(1) and check.snapshot() is None
    release.set()
    check._thread.join(2)
    assert check.snapshot() == HardwareStatus((NVIDIA,), True, "cuda")
    assert threads == [check._thread.ident] and threads[0] != threading.get_ident()
    monkeypatch.setattr(
        "dantejp.runtime.hardware.detect_adapters", Mock(side_effect=OSError("DXGI"))
    )
    failed = HardwareCheck()
    failed.start()
    failed._thread.join(2)
    status = failed.snapshot()
    assert failed.finished and status is not None and status.error == "DXGI"
