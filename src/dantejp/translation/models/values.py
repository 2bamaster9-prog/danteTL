"""Model import descriptions. Inspection and registration live in gguf_models."""

from dataclasses import dataclass

from dantejp.i18n import mark

PROFILES = {
    "auto": mark("Automatic (recommended)"),
    "embedded": mark("Embedded chat template"),
    "gemma4": "Gemma 4",
    "plamo3": "PLaMo 3 Translate",
    "chatml": "ChatML",
    "llama3": "Llama 3",
}


@dataclass(frozen=True, slots=True)
class GgufInfo:
    name: str
    architecture: str
    template: str
    size: int
    profile: str


@dataclass(frozen=True, slots=True)
class ImportedModel:
    key: str
    path: str
    name: str
    sha256: str
    size: int
    architecture: str
    profile: str
    template_hash: str


@dataclass(frozen=True, slots=True)
class ProbeResult:
    model: ImportedModel
    device: str
    samples: tuple[tuple[str, str, float], ...]
    load_ms: float
    offloaded_layers: int = 0
