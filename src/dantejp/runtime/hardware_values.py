"""Hardware identity and pure advice; detection stays at the adapter boundary."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Adapter:
    name: str
    vendor: int
    dedicated_bytes: int = 0


@dataclass(frozen=True, slots=True)
class HardwareStatus:
    adapters: tuple[Adapter, ...] = ()
    cuda_ocr: bool = False
    llama_device: str | None = None
    error: str = ""


def recommended_profile(adapters: tuple[Adapter, ...]) -> str:
    # A discrete card normally has more dedicated memory than a CPU's integrated GPU.
    # This is a recommendation, not a driver/compute compatibility guarantee.
    supported = [a for a in adapters if a.vendor in (0x10DE, 0x1002)]
    if not supported:
        return "cpu"
    best = max(supported, key=lambda a: (a.dedicated_bytes, a.vendor == 0x10DE))
    return "nvidia" if best.vendor == 0x10DE else "amd"


class HardwareReader(Protocol):
    def snapshot(self) -> HardwareStatus | None: ...
