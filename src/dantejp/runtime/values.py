"""Runtime metadata; does not install, probe or select environments."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    key: str
    name: str
    groups: tuple[str, ...]
    description: str


PROFILES = (
    RuntimeProfile(
        "nvidia",
        "NVIDIA GPU — CUDA",
        ("gpu", "gemma"),
        "Accelerates supported recognition and translation engines with CUDA 13. "
        "Downloads about 1.3 GB "
        "of NVIDIA/ONNX libraries, plus app dependencies. Model downloads are separate. "
        "An up-to-date NVIDIA driver is required; system drivers are not changed.",
    ),
    RuntimeProfile(
        "amd",
        "GPU — Vulkan",
        ("cpu", "gemma-vulkan"),
        "Accelerates supported translation engines with Vulkan; recognition stays on CPU. "
        "Requires a Vulkan-capable graphics driver. Radeon inference still needs testing "
        "on your card; experimental DirectML OCR is not installed by this option.",
    ),
    RuntimeProfile(
        "cpu",
        "CPU",
        ("cpu", "llm-cpu"),
        "Runs local recognition and translation without GPU dependencies. "
        "Larger language models may translate more slowly. CPU support is included in the "
        "standalone app. Your downloaded models are kept when switching.",
    ),
)
