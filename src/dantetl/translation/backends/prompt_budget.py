"""Fit a complete source and its most recent dialogue into a local model prompt."""

from collections.abc import Callable
from typing import Protocol

from dantetl.i18n import mark, tr
from dantetl.translation.backend import RequestRejected
from dantetl.translation.dialogue.context import DialogueTurn


class Tokenizer(Protocol):
    def tokenize(self, text: bytes, /, *, add_bos: bool, special: bool) -> list[int]: ...


def fit_prompt(
    tokenizer: Tokenizer,
    text: str,
    context: tuple[DialogueTurn, ...],
    render: Callable[[str, tuple[DialogueTurn, ...]], str],
    *,
    max_tokens: int,
    invalid_source: str = mark("Translation source must contain 1–512 characters."),
    overflow: str = mark("Source exceeds the allocated context; refusing truncation."),
) -> list[int]:
    if not text.strip() or len(text) > 512:
        raise RequestRejected(tr(invalid_source))
    context = context[-2:]
    while sum(len(turn.source) + len(turn.english) for turn in context) > 512:
        context = context[1:]
    while True:
        tokens = tokenizer.tokenize(render(text, context).encode(), add_bos=False, special=True)
        if len(tokens) <= max_tokens:
            return tokens
        if not context:
            raise RequestRejected(tr(overflow))
        context = context[1:]
