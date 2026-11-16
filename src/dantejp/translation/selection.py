"""UI-facing assignment values. Executable backend recipes stay with their owner."""

from dataclasses import dataclass

from dantejp.translation.cloud.values import CloudProfile
from dantejp.translation.plan import TranslationPlan


@dataclass(frozen=True)
class OcrOption:
    name: str
    key: str
    capture_fps: int = 8


@dataclass(frozen=True)
class ModelOption:
    reference: str
    name: str
    key: str
    provider: str = ""
    prepared: bool = False
    unavailable_reason: str = ""
    performance_notice: str = ""
    classifies: bool = False

    @property
    def local(self) -> bool:
        return not self.provider

    @property
    def preference_key(self) -> str:
        return self.reference.removeprefix("local:").removeprefix("cloud:")


@dataclass(frozen=True)
class AssignmentChange:
    plan: TranslationPlan
    reference: str = ""


@dataclass(frozen=True)
class LocalIdentity:
    key: str
    preparation: str
    unavailable: str = ""


@dataclass(frozen=True)
class CloudIdentity:
    profile: CloudProfile
    game: str
    credential_revision: int


@dataclass(frozen=True)
class ClassifierIdentity:
    reference: str
    model: LocalIdentity | CloudProfile | None
    credential_revision: int = 0
    available: bool = False
