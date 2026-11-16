"""Typed translation capabilities and request-local rejection, independent of scheduling."""

from concurrent.futures import Future
from typing import Protocol, runtime_checkable

from dantejp.translation.dialogue.context import DialogueTurn


class RequestRejected(ValueError):
    """This input/answer is unusable; the loaded backend remains usable for other work."""


class TranslationBackend(Protocol):
    cache_identity: str
    batch_size: int

    def translate(self, texts: tuple[str, ...], /) -> tuple[str, ...]: ...
    def close(self) -> None: ...


@runtime_checkable
class ContextualBackend(TranslationBackend, Protocol):
    def translate_with_context(self, text: str, context: tuple[DialogueTurn, ...]) -> str: ...


Source = tuple[str, tuple[DialogueTurn, ...]]
BatchResult = tuple[dict[Source, str], dict[Source, str]]


@runtime_checkable
class DeferredBackend(ContextualBackend, Protocol):
    """Network I/O completes elsewhere; the session retains cache/publication ownership."""

    def submit_translation(self, sources: tuple[Source, ...]) -> Future[BatchResult]: ...
    def cancel_pending(self) -> None: ...


@runtime_checkable
class ConcurrentBackend(DeferredBackend, Protocol):
    """Independent completed answers, with a small explicit transport concurrency limit."""

    max_in_flight: int
