"""Application command and presentation values, free of resource owners."""

from dataclasses import dataclass
from enum import StrEnum

from dantejp.application.translation_activity import TranslationMode
from dantejp.domain import CapturedFrame, CaptureSnapshot, Rect
from dantejp.ocr.tracking import TextTrack
from dantejp.ocr.values import OcrResult, OcrSnapshot
from dantejp.ocr.visual_values import VisualState
from dantejp.translation.grouping import TextBlock
from dantejp.translation.plan import TranslationPlan
from dantejp.translation.selection import ModelOption
from dantejp.translation.values import TranslatedText, TranslationSnapshot


class ShutdownPhase(StrEnum):
    IDLE = "idle"
    DRAINING = "draining"
    RESTARTING = "restarting"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class ShutdownSnapshot:
    phase: ShutdownPhase = ShutdownPhase.IDLE
    message: str = ""


@dataclass(frozen=True, slots=True)
class Scene:
    tracks: tuple[TextTrack, ...] = ()
    blocks: tuple[TextBlock, ...] = ()
    requests: tuple[TextBlock, ...] = ()
    waiting_blocks: int = 0


@dataclass(frozen=True)
class ModelConsent:
    token: int
    option: ModelOption


@dataclass(frozen=True)
class ProcessingProgress:
    message: str = ""
    busy: bool = False
    tone: str = "info"


@dataclass(frozen=True)
class ApplicationView:
    status: str = "Select a window, then start capture."
    ocr_status: str = ""
    translation_status: str = ""
    translation_mode: TranslationMode = TranslationMode.INACTIVE
    progress: ProcessingProgress = ProcessingProgress()
    scene: Scene = Scene()
    blocks: tuple[TextBlock, ...] = ()
    english: tuple[TranslatedText, ...] = ()
    results: tuple[TranslatedText, ...] = ()
    frame: CapturedFrame | None = None
    observation: OcrResult | None = None
    assignments: tuple[int | None, ...] = ()
    ocr: OcrSnapshot | None = None
    translation: TranslationSnapshot | None = None
    overlay_bounds: Rect | None = None
    reset: int = 0
    english_reset: int = 0
    capture: CaptureSnapshot | None = None
    visual: VisualState = VisualState()


@dataclass(frozen=True)
class ApplicationControls:
    options: tuple[ModelOption, ...]
    assignment: TranslationPlan
    preparing: bool
    preparation_message: str
    capture_active: bool
    can_stop: bool
    started_at: float
    capture_rate: int
