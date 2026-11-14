"""Bounded visual evidence snapshot, independent of the analysis worker."""

from dataclasses import dataclass

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.tracking import TextTrack


@dataclass(frozen=True, slots=True)
class VisualState:
    frame: CapturedFrame | None = None
    request_ocr: bool = False
    hidden: frozenset[TextTrack] = frozenset()
    blocked: frozenset[int] = frozenset()
    stable_regions: tuple[int, ...] = ()
    ocr_sequence: int = 0
    duration_ms: float = 0
    avoided: int = 0
    message: str = ""
    absent: frozenset[TextTrack] = frozenset()
    checked_sequence: int = 0
    unchanged: frozenset[TextTrack] = frozenset()
    checked: frozenset[TextTrack] = frozenset()
    scan_areas: tuple[Rect, ...] | None = None
    stable_tracks: tuple[tuple[int, int, str], ...] = ()
    changed_areas: tuple[Rect, ...] = ()
