"""Immutable setup progress and review data, independent of operations/installers."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jp_overlay.hardware_values import Adapter


class Cancelled(Exception):
    """The owning setup operation was cancelled before publication."""


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    name: str
    received: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class ModelProgress:
    message: str = "Starting…"
    received: int = 0
    total: int = 0
    done: bool = False
    cancelled: bool = False
    error: str = ""
    download: DownloadProgress | None = None
    stage: int = 0
    stages: int = 0


Progress = Callable[[ModelProgress], None]


class SetupLane(StrEnum):
    MODELS = "models"
    RUNTIME = "runtime"
    GUIDE = "guide"


@dataclass(frozen=True)
class SetupJob:
    token: int = 0
    action: str = ""
    key: str = ""
    busy: bool = False
    cancelling: bool = False
    progress: ModelProgress = ModelProgress()


@dataclass(frozen=True)
class RuntimeStatus:
    adapters: tuple[Adapter, ...] = ()
    targets: tuple[tuple[str, Path | None], ...] = ()
    current: Path | None = None
    recommendation: str = "cpu"

    def target(self, key: str) -> Path | None:
        return next((path for name, path in self.targets if name == key), None)


@dataclass(frozen=True)
class SetupReview:
    token: int
    model: str
    runtime: str
    download_bytes: int
    install_runtime: bool
    model_keys: tuple[str, ...]
