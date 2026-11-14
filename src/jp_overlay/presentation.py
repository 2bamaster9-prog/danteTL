"""Bounded, atomic publication of English; no inference or rendering dependencies."""

from dataclasses import dataclass

from jp_overlay.grouping import TextBlock
from jp_overlay.tracking import TextTrack
from jp_overlay.translation_values import TranslatedText, TranslationRequest


@dataclass(frozen=True, slots=True)
class Publication:
    accepted: TextBlock
    painted: TextBlock
    translation: TranslatedText


class EnglishPresentation:
    """Keep English during explicitly verified same-pixel OCR corrections only.

    Accepted identity advances independently of the painted source, so several
    corrections can finish while an older translation is still in flight. Real
    edits, membership changes, removals and session/backend resets revoke retention.
    """

    def __init__(self) -> None:
        self._published: dict[tuple[int, ...], Publication] = {}
        self._scope: object = None

    def reset(self) -> None:
        self._published.clear()
        self._scope = None

    def update(
        self,
        blocks: tuple[TextBlock, ...],
        translations: tuple[TranslatedText, ...],
        corrections: tuple[tuple[TextTrack, TextTrack], ...] = (),
        *,
        scope: object = None,
    ) -> tuple[Publication, ...]:
        # Identical Japanese/track IDs do not make different models interchangeable.
        if scope != self._scope:
            self.reset()
            self._scope = scope
        english = {t.request: t for t in translations}
        predecessors = dict(corrections)
        published = {}
        for block in blocks[:128]:
            ids = tuple(t.track_id for t in block.lines)
            result = english.get(TranslationRequest.from_block(block))
            old = self._published.get(ids)
            if result is not None:
                published[ids] = Publication(block, block, result)
            elif old is not None and all(
                current == previous or predecessors.get(current) == previous
                for current, previous in zip(block.lines, old.accepted.lines, strict=True)
            ):
                published[ids] = Publication(block, old.painted, old.translation)
        self._published = published
        return tuple(published.values())
