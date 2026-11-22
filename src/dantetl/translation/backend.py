"""Typed translation capabilities and request-local rejection, independent of scheduling."""

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from dantetl.languages.source import SourceLanguage
from dantetl.languages.target import ENGLISH, TargetLanguage
from dantetl.translation.dialogue.context import DialogueTurn


class RequestRejected(ValueError):
    """This input/answer is unusable; the loaded backend remains usable for other work."""


class TranslationBackend(Protocol):
    cache_identity: str
    batch_size: int

    def translate(
        self, texts: tuple[str, ...], /, *, target: TargetLanguage = ENGLISH
    ) -> tuple[str, ...]: ...
    def close(self) -> None: ...


@runtime_checkable
class MultilingualBackend(TranslationBackend, Protocol):
    """Switch prompt and cache identity on the inference thread with the same weights."""

    def set_source(self, language: SourceLanguage) -> None: ...


@runtime_checkable
class ContextualBackend(TranslationBackend, Protocol):
    def translate_with_context(
        self, text: str, context: tuple[DialogueTurn, ...], *, target: TargetLanguage = ENGLISH
    ) -> str: ...


Source = tuple[str, tuple[DialogueTurn, ...]]
BatchResult = tuple[dict[Source, str], dict[Source, str]]


class LabelDecoder(Protocol):
    """An owner-driven set of independent sequences sharing the loaded weights."""

    width: int

    def submit(self, source: Source, target: TargetLanguage) -> Future[BatchResult] | None: ...
    def step(self) -> None: ...
    def reset(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class ParallelLabelBackend(TranslationBackend, Protocol):
    @property
    def label_width(self) -> int: ...
    def prepare_labels(self, target: TargetLanguage) -> LabelDecoder | None: ...


@runtime_checkable
class DeferredBackend(ContextualBackend, Protocol):
    """Network I/O completes elsewhere; the session retains cache/publication ownership."""

    def submit_translation(
        self, sources: tuple[Source, ...], *, target: TargetLanguage = ENGLISH
    ) -> Future[BatchResult]: ...
    def cancel_pending(self) -> None: ...


@runtime_checkable
class ConcurrentBackend(DeferredBackend, Protocol):
    """Independent completed answers, with a small explicit transport concurrency limit."""

    max_in_flight: int


@dataclass(frozen=True, slots=True)
class BackendChoice:
    name: str
    # Discovery may recreate a lazy recipe. Its identity is the pinned model/runtime
    # metadata below, never the identity of a newly allocated Python closure.
    create: Callable[[], TranslationBackend] = field(compare=False)
    key: str = ""
    preparation_id: str = ""
    unavailable_reason: str = ""
    performance_notice: str = ""
    selection_id: str = ""
    classifies: bool = False
    output_codes: frozenset[str] | None = None

    @property
    def preference_key(self) -> str:
        if self.selection_id:
            return self.selection_id
        # Retain legacy E2B preferences without conflating larger Gemma models.
        return (
            "gemma"
            if self.key in ("gemma", "gemma-cpu", "gemma-cuda", "gemma-vulkan", "gemma-unavailable")
            else self.key
        )
