"""Application command and presentation values, free of resource owners."""

from dataclasses import dataclass
from enum import StrEnum

from jp_overlay.domain import CapturedFrame, CaptureSnapshot, Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.model_selection import ModelOption
from jp_overlay.ocr_values import OcrResult, OcrSnapshot
from jp_overlay.tracking import TextTrack
from jp_overlay.translation_activity import TranslationMode
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_values import TranslatedText, TranslationSnapshot
from jp_overlay.visual_values import VisualState


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
