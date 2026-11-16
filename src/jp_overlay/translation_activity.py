"""The model owner's decision for one application tick; no publication policy."""

from dataclasses import dataclass
from enum import StrEnum

from jp_overlay.translation_values import TranslationSnapshot, TranslationWorker


class TranslationMode(StrEnum):
    PROBING = "probing"
    PREPARING = "preparing"
    STANDBY = "standby"
    INACTIVE = "inactive"
    ACTIVE = "active"
    SWITCHING = "switching"


class InactiveReason(StrEnum):
    UNLOADING = "unloading"
    NEEDS_RUNTIME = "needs_runtime"
    OFF = "off"
    NO_MODEL = "no_model"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class TranslationActivity:
    mode: TranslationMode
    worker: TranslationWorker | None = None
    snapshot: TranslationSnapshot | None = None
    probe_ready: bool = False
    reason: InactiveReason = InactiveReason.STOPPED
    model_name: str = "the translation model"

    @property
    def clears_english(self) -> bool:
        return self.mode in (TranslationMode.PROBING, TranslationMode.INACTIVE)
