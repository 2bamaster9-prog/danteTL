"""Immutable OCR observations and worker status; physical pixel coordinates."""

from dataclasses import dataclass
from enum import StrEnum

from dantetl.domain import CapturedFrame, Rect


@dataclass(frozen=True, slots=True)
class TextCharacter:
    text: str
    bounds: Rect
    confidence: float


@dataclass(frozen=True, slots=True)
class TextRegion:
    """Client-relative physical pixels; confidence is mean retained-character confidence."""

    text: str
    bounds: Rect
    characters: tuple[TextCharacter, ...] = ()
    vertical: bool = False
    line_confidence: float | None = None

    @property
    def confidence(self) -> float | None:
        if not self.characters:
            return self.line_confidence
        return sum(char.confidence for char in self.characters) / len(self.characters)


@dataclass(frozen=True, slots=True)
class OcrResult:
    frame: CapturedFrame
    regions: tuple[TextRegion, ...]
    duration_ms: float
    completed_at: float
    scanned: tuple[Rect, ...] | None = None

    def covers(self, bounds: Rect) -> bool:
        return self.scanned is None or any(area.contains(bounds) for area in self.scanned)


class OcrState(StrEnum):
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class OcrSnapshot:
    state: OcrState
    result: OcrResult | None = None
    message: str = ""
    processed_frames: int = 0
    skipped_frames: int = 0
    queue_ms: float = 0
    mean_duration_ms: float = 0
    processing_since: float | None = None
    provider: str = ""
