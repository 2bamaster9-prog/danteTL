"""Runtime metadata; does not install, probe or select environments."""

from dataclasses import dataclass

from dantejp.i18n import mark


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    key: str
    name: str
    groups: tuple[str, ...]
    description: str


PROFILES = (
    RuntimeProfile(
        "nvidia",
        mark("NVIDIA GPU — CUDA"),
        ("gpu", "gemma"),
        mark(
            "GPU recognition and translation. Requires a CUDA 13-compatible NVIDIA driver. "
            "About 1.3 GB plus app dependencies."
        ),
    ),
    RuntimeProfile(
        "amd",
        mark("GPU — Vulkan"),
        ("cpu", "gemma-vulkan"),
        mark("GPU translation with a Vulkan-compatible driver. Recognition uses the CPU."),
    ),
    RuntimeProfile(
        "cpu",
        "CPU",
        ("cpu", "llm-cpu"),
        mark("Recognition and translation on the CPU. Included in the standalone app."),
    ),
)
