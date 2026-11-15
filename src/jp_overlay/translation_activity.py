"""The model owner's decision for one application tick; no publication policy."""

from dataclasses import dataclass
from enum import StrEnum

from jp_overlay.model_lifecycle import Worker
from jp_overlay.translation_values import TranslationSnapshot


class TranslationMode(StrEnum):
    PROBING = "probing"
    PREPARING = "preparing"
    STANDBY = "standby"
    INACTIVE = "inactive"
    ACTIVE = "active"
    SWITCHING = "switching"


@dataclass(frozen=True, slots=True)
class TranslationActivity:
    mode: TranslationMode
    worker: Worker | None = None
    snapshot: TranslationSnapshot | None = None
    probe_ready: bool = False
    message: str = ""
    model_name: str = "the translation model"

    @property
    def clears_english(self) -> bool:
        return self.mode in (TranslationMode.PROBING, TranslationMode.INACTIVE)
