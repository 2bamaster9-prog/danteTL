"""Worker-local batch planning and in-flight bookkeeping; no threads or engine ownership."""

from __future__ import annotations

import json
from collections.abc import Iterable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.languages.target import ENGLISH, TargetLanguage
from dantejp.translation.backend import (
    BatchResult,
    ConcurrentBackend,
    ContextualBackend,
    Source,
    TranslationBackend,
)
from dantejp.translation.cache import TranslationCache, translation_key
from dantejp.translation.dialogue.context import DialogueTurn

if TYPE_CHECKING:
    from dantejp.translation.worker import TranslationRequest


@dataclass(frozen=True, slots=True)
class Demand:
    generation: int
    jobs: tuple[TranslationRequest, ...]
    contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]]
    dialogue: frozenset[TranslationRequest]
    target: TargetLanguage = ENGLISH


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
    target: TargetLanguage = ENGLISH
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

    def __init__(self, *, language: SourceLanguage = DEFAULT_SOURCE) -> None:
        self._language = language
        self._flights: list[tuple[Batch, Future[BatchResult]]] = []
        self._blocked: set[tuple[TranslationRequest, tuple[DialogueTurn, ...]]] | None = None
        self._waiting: dict[tuple[TranslationRequest, tuple[DialogueTurn, ...]], None] = {}
        self._scope: tuple[int, str, TargetLanguage] | None = None
        self._keys: dict[Source, str] = {}

    def reset(self) -> None:
        self._flights.clear()
        self._blocked = None
        self._waiting.clear()
        self._scope = None
        self._keys = {}

    def stale(self, generation: int) -> bool:
        return any(batch.generation != generation for batch, _ in self._flights)

    def has_completion(self) -> bool:
        return any(future.done() for _, future in self._flights)

    def needs_plan(
        self, generation: int, jobs: Iterable[tuple[TranslationRequest, tuple[DialogueTurn, ...]]]
    ) -> bool:
        # Withdrawals also end a lookup's lifetime, including the last request in a scene.
        return (
            self._blocked is None
            or self._scope is None
            or generation != self._scope[0]
            or self._blocked != set(jobs)
        )

    @property
    def processing_since(self) -> float | None:
        return min((batch.started for batch, _ in self._flights), default=None)

    def completed(self) -> tuple[tuple[Batch, Future[BatchResult]], ...]:
        done = tuple((batch, future) for batch, future in self._flights if future.done())
        if done:
            self._flights = [(b, f) for b, f in self._flights if (b, f) not in done]
            self._blocked = None
        return done

    def submitted(self, batch: Batch, future: Future[BatchResult]) -> None:
        self._flights.append((batch, future))
        self._blocked = None

    def cancel_unused(self, wanted: set[Source]) -> int:
        """Release a deferred slot only when every input has lost its last consumer."""
        cancelled = 0
        for batch, future in tuple(self._flights):
            if wanted.isdisjoint(batch.missing) and future.cancel():
                self._flights.remove((batch, future))
                self._blocked = None
                cancelled += 1
        return cancelled

    def plan(
        self, demand: Demand, engine: TranslationBackend, cache: TranslationCache
    ) -> Batch | None:
        # Demand order is screen order, not waiting age. Preserve surviving requests
        # ahead of new revisions so a changing early box cannot starve later text.
        scope = demand.generation, engine.cache_identity, demand.target
        reset = self._scope != scope
        if reset:
            self._waiting.clear()
            self._keys = {}
            self._scope = scope
        wanted = dict.fromkeys((key, demand.contexts[key]) for key in demand.jobs[:128])
        self._waiting = {key: None for key in self._waiting if key in wanted}
        self._waiting.update(wanted)
        contextual = isinstance(engine, ContextualBackend)
        inputs = {
            key: (key.source, demand.contexts[key] if contextual else ()) for key in demand.jobs
        }
        sources = tuple(dict.fromkeys(inputs[key] for key, _ in self._waiting))
        keys: dict[Source, str] = {}
        for source in sources:
            if source in self._keys:
                keys[source] = self._keys[source]
            else:
                text, context = source
                keys[source] = translation_key(
                    engine.cache_identity + (":dialogue-context-v1" if context else ""),
                    json.dumps([text, [(t.source, t.english) for t in context]], ensure_ascii=False)
                    if context
                    else text,
                    language=self._language,
                    target=demand.target,
                )
        self._keys = keys
        hits = cache.lookup_pending(keys.values(), reset=reset)
        answers = {source: hits[key] for source, key in keys.items()}
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
            self._blocked = set(wanted)
            return None
        self._blocked = None
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
            target=demand.target,
        )
