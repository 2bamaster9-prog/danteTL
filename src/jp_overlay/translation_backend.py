"""Typed translation capabilities and request-local rejection, independent of scheduling."""

from typing import Protocol, runtime_checkable

from jp_overlay.dialogue_context import DialogueTurn


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
