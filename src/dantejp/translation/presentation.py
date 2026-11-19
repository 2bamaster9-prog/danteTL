"""Bounded, atomic publication of English for live OCR tracks."""

from dataclasses import dataclass, replace

from dantejp.ocr.tracking import TextTrack
from dantejp.translation.grouping import TextBlock
from dantejp.translation.values import TranslatedText, TranslationRequest


@dataclass(frozen=True, slots=True)
class Publication:
    painted: TextBlock
    translation: TranslatedText

    def at_live_bounds(self, live: dict[int, TextTrack]) -> "Publication":
        lines = self.painted.lines
        if all(t.bounds == live[t.track_id].bounds for t in lines):
            return self
        placed = tuple(replace(t, bounds=live[t.track_id].bounds) for t in lines)
        return Publication(replace(self.painted, lines=placed), self.translation)


class EnglishPresentation:
    """Own the painted scene independently of pending OCR revisions and translation work."""

    def __init__(self) -> None:
        self._published: tuple[Publication, ...] = ()
        self._visible: tuple[Publication, ...] = ()
        self._concealed: dict[TranslationRequest, tuple[str, ...]] = {}
        self._ready: dict[TranslationRequest, TranslatedText] = {}
        self._scope: object = None
        self._inputs: (
            tuple[tuple[TextBlock, ...], tuple[TranslatedText, ...], frozenset[TextTrack]] | None
        ) = None

    def reset(self) -> None:
        self._published = ()
        self._visible = ()
        self._concealed.clear()
        self._ready.clear()
        self._inputs = None
        self._scope = None

    def update(
        self,
        blocks: tuple[TextBlock, ...],
        translations: tuple[TranslatedText, ...],
        *,
        scope: object = None,
        cleared: frozenset[TextTrack] = frozenset(),
    ) -> tuple[Publication, ...]:
        if scope != self._scope:
            self.reset()
            self._scope = scope
        inputs = (blocks[:128], translations[:128], cleared)
        if inputs == self._inputs:
            return self._visible
        self._inputs = inputs
        blocks = tuple(b for b in inputs[0] if b.language.contains_text(b.text))
        results = {t.request: t for t in inputs[1]}
        requests = tuple(TranslationRequest.from_block(b) for b in blocks)
        self._ready = {
            key: value
            for key in requests
            if (value := results.get(key) or self._ready.get(key)) is not None
        }

        live = {t.track_id: t for b in blocks for t in b.lines}
        owner = {t.track_id: i for i, b in enumerate(blocks) for t in b.lines}
        prior = []
        for p in self._published:
            lines = p.painted.lines
            if not all(t.track_id in live for t in lines):
                continue
            # Once removed from the screen, old English cannot fill the wait for a
            # different source that happens to reuse the same track IDs.
            hidden_source = self._concealed.get(p.translation.request)
            if hidden_source is None or hidden_source == tuple(
                live[t.track_id].text for t in lines
            ):
                prior.append(p)

        # A split can need several replies; a merge can replace several painted
        # labels. Switch the connected old/new blocks together. A slow reply in
        # one paragraph cannot hold an independent label elsewhere on screen.
        successors = [{owner[t.track_id] for t in p.painted.lines} for p in prior]
        overlaps: list[list[int]] = [[] for _ in blocks]
        for old, indices in enumerate(successors):
            for index in indices:
                overlaps[index].append(old)
        waiting = {i for i, key in enumerate(requests) if key not in self._ready}
        pending = list(waiting)
        held: set[int] = set()
        while pending:
            for old in overlaps[pending.pop()]:
                if old in held:
                    continue
                held.add(old)
                pending.extend(successors[old] - waiting)
                waiting.update(successors[old])

        painted = [prior[i].at_live_bounds(live) for i in sorted(held)]
        painted.extend(
            Publication(block, self._ready[key])
            for i, (block, key) in enumerate(zip(blocks, requests, strict=True))
            if i not in waiting
        )
        self._published = tuple(sorted(painted, key=lambda p: p.painted.lines[0].track_id))
        self._concealed = {
            p.translation.request: tuple(live[t.track_id].text for t in p.painted.lines)
            for p in self._published
            if cleared and all(live[t.track_id] in cleared for t in p.painted.lines)
        }
        self._visible = tuple(
            p for p in self._published if p.translation.request not in self._concealed
        )
        return self._visible
