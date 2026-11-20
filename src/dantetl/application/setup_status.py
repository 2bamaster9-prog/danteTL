"""Actionable hardware advice, separate from model downloads and inference readiness."""

from dataclasses import dataclass

from dantetl.i18n import mark, tr
from dantetl.runtime.hardware_values import HardwareStatus


@dataclass(frozen=True, slots=True)
class SetupAdvice:
    message: str = ""
    destination: str = "runtime"
    action: str = mark("Set up acceleration")


def acceleration_advice(
    hardware: HardwareStatus | None,
    ocr_device: str,
    *,
    actual_provider: str = "",
    fallback: str = "",
) -> SetupAdvice:
    if hardware is None:
        return SetupAdvice()
    if hardware.error:
        return SetupAdvice(
            tr(
                "Graphics hardware could not be checked. CPU remains available; "
                "you can choose acceleration manually."
            )
        )
    nvidia = any(a.vendor == 0x10DE for a in hardware.adapters)
    amd = any(a.vendor == 0x1002 for a in hardware.adapters)
    if nvidia and not hardware.cuda_ocr:
        return SetupAdvice(
            tr(
                "NVIDIA GPU detected · GPU OCR is not enabled in this runtime. "
                "Open Acceleration to install or activate NVIDIA support."
            )
        )
    if nvidia and ocr_device == "cpu":
        return SetupAdvice(
            tr(
                "NVIDIA acceleration is installed, but CPU is selected. "
                "Choose Automatic in Recognition; the change applies next time capture starts."
            ),
            "recognition",
            tr("OCR settings"),
        )
    if ocr_device in ("auto", "auto-directml") and actual_provider == "CPUExecutionProvider":
        return SetupAdvice(
            tr("GPU OCR fell back to CPU. ") + (fallback or tr("Check the acceleration setup.")),
        )
    if amd and not nvidia and hardware.llama_device != "vulkan":
        return SetupAdvice(
            tr(
                "AMD GPU detected · GPU translation is not enabled in this runtime. "
                "Vulkan acceleration is optional; translation and OCR can run on CPU."
            )
        )
    return SetupAdvice()
