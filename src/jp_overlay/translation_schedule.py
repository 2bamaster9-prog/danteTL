"""Worker-local batch planning and in-flight bookkeeping; no threads or engine ownership."""

from __future__ import annotations

import json
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jp_overlay.dialogue_context import DialogueTurn
from jp_overlay.translation_backend import (
    BatchResult,
    ConcurrentBackend,
    ContextualBackend,
    Source,
    TranslationBackend,
)
from jp_overlay.translation_cache import TranslationCache, translation_key

if TYPE_CHECKING:
    from jp_overlay.translation import TranslationRequest


@dataclass(frozen=True, slots=True)
class Demand:
    generation: int
    jobs: tuple[TranslationRequest, ...]
    contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]]
    dialogue: frozenset[TranslationRequest]


@dataclass(slots=True)
class Batch:
    generation: int
    jobs: tuple[TranslationRequest, ...]
    contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]]
    inputs: dict[TranslationRequest, Source]
    sources: tuple[Source, ...]
    keys: dict[Source, str]
    answers: dict[Source, str | None]
    missing: tuple[Source, ...]
    serial: bool
    measured: float = 0.0
    queue_ms: float = 0.0
    started: float = 0.0

    def activate(
        self,
        current: tuple[TranslationRequest, ...],
        contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]],
        queued_at: dict[TranslationRequest, float],
        *,
        now: float,
        measured: float,
    ) -> bool:
        """Revalidate after cache I/O, under the session lock, before dispatching work."""
        self.jobs = tuple(
            key
            for key in self.jobs
            if key in current and self.contexts[key] == contexts.get(key, ())
        )
        wanted = {self.inputs[key] for key in self.jobs}
        self.sources = tuple(s for s in self.sources if s in wanted)
        self.missing = tuple(s for s in self.missing if s in wanted)
        if not self.sources:
            return False
        self.started, self.measured = now, measured
        self.queue_ms = max(
            (now - queued_at.get(key, now)) * 1000
            for key in self.jobs
            if self.inputs[key] in self.sources
        )
        return True


class TranslationSchedule:
    """Cache-first, exact-source deduplication and serial dialogue within bounded capacity.

    Used only by the translation owner, including while it holds its condition lock.
    Futures wake that owner but never mutate this schedule from their callback thread.
    """

    def __init__(self) -> None:
        self._flights: list[tuple[Batch, Future[BatchResult]]] = []
        self._checked: set[tuple[TranslationRequest, tuple[DialogueTurn, ...]]] = set()
        self._waiting: dict[tuple[TranslationRequest, tuple[DialogueTurn, ...]], None] = {}
        self._generation: int | None = None

    def reset(self) -> None:
        self._flights.clear()
        self._checked.clear()
        self._waiting.clear()
        self._generation = None

    def stale(self, generation: int) -> bool:
        return any(batch.generation != generation for batch, _ in self._flights)

    def has_completion(self) -> bool:
        return any(future.done() for _, future in self._flights)

    def unchecked(self, key: TranslationRequest, context: tuple[DialogueTurn, ...]) -> bool:
        return (key, context) not in self._checked

    @property
    def processing_since(self) -> float | None:
        return min((batch.started for batch, _ in self._flights), default=None)

    def completed(self) -> tuple[tuple[Batch, Future[BatchResult]], ...]:
        done = tuple((batch, future) for batch, future in self._flights if future.done())
        if done:
            self._flights = [(b, f) for b, f in self._flights if (b, f) not in done]
            self._checked.clear()
        return done

    def submitted(self, batch: Batch, future: Future[BatchResult]) -> None:
        self._flights.append((batch, future))
        self._checked.clear()

    def plan(
        self, demand: Demand, engine: TranslationBackend, cache: TranslationCache
    ) -> Batch | None:
        # Demand order is screen order, not waiting age. Preserve surviving requests
        # ahead of new revisions so a changing early box cannot starve later text.
        if self._generation != demand.generation:
            self._waiting.clear()
            self._generation = demand.generation
        wanted = dict.fromkeys((key, demand.contexts[key]) for key in demand.jobs[:128])
        self._waiting = {key: None for key in self._waiting if key in wanted}
        self._waiting.update(wanted)
        contextual = isinstance(engine, ContextualBackend)
        inputs = {
            key: (key.source, demand.contexts[key] if contextual else ()) for key in demand.jobs
        }
        sources = tuple(dict.fromkeys(inputs[key] for key, _ in self._waiting))
        keys = {
            source: translation_key(
                engine.cache_identity + (":dialogue-context-v1" if source[1] else ""),
                json.dumps(
                    [source[0], [(t.source, t.english) for t in source[1]]], ensure_ascii=False
                )
                if source[1]
                else source[0],
            )
            for source in sources
        }
        answers = {source: cache.get(keys[source]) for source in sources}
        cached = tuple(source for source in sources if answers[source] is not None)
        active = {source for batch, _ in self._flights for source in batch.missing}
        serial = {
            inputs[key] for key in demand.jobs if demand.contexts[key] or key in demand.dialogue
        }
        capacity = (
            max(1, min(2, engine.max_in_flight)) if isinstance(engine, ConcurrentBackend) else 1
        )
        eligible = (
            tuple(
                source
                for source in sources
                if source not in active
                and not (source in serial and any(b.serial for b, _ in self._flights))
            )
            if len(self._flights) < capacity
            else ()
        )
        if not cached and not eligible:
            self._checked = {(key, demand.contexts[key]) for key in demand.jobs}
            return None
        chosen = cached or eligible[: max(1, min(4, engine.batch_size))]
        missing = tuple(source for source in chosen if answers[source] is None)
        return Batch(
            demand.generation,
            demand.jobs,
            demand.contexts,
            inputs,
            chosen,
            keys,
            answers,
            missing,
            any(source in serial for source in missing),
        )
