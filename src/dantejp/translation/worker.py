"""Local translation scheduling, backend swapping, and stale-result rejection."""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dantejp.ocr.text_content import has_japanese
from dantejp.ocr.tracking import TextTrack
from dantejp.translation.backend import (
    BatchResult,
    ContextualBackend,
    DeferredBackend,
    RequestRejected,
    Source,
    TranslationBackend,
)
from dantejp.translation.cache import TranslationCache
from dantejp.translation.dialogue.context import DialogueMemory, DialogueTurn
from dantejp.translation.grouping import TextBlock
from dantejp.translation.schedule import Batch, Demand, TranslationSchedule
from dantejp.translation.values import TranslatedText as TranslatedText
from dantejp.translation.values import TranslationRejection as TranslationRejection
from dantejp.translation.values import TranslationRequest as TranslationRequest
from dantejp.translation.values import TranslationSnapshot as TranslationSnapshot
from dantejp.translation.values import TranslationState as TranslationState

logger = logging.getLogger(__name__)


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


class TranslationSession:
    """One local call or two independent cloud calls; at most 128 current requests.

    The UI replaces the desired set, never appends a job queue. Models and SQLite
    belong to this worker. A swap drains the active call, closes the old backend,
    then loads the latest requested backend before accepting results again.
    """

    def __init__(
        self,
        factory: Callable[[], TranslationBackend],
        cache_path: Path,
        *,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._factory, self._cache_path = factory, cache_path
        self._notify = on_change or (lambda: None)
        self._condition = threading.Condition()
        self._done = threading.Event()
        self._stop = False
        self._generation = 0
        self._backend_generation = 0
        self._desired: tuple[TranslationRequest, ...] = ()
        self._retained: tuple[TranslationRequest, ...] = ()
        self._demand_changed = False
        self._cancelled_obsolete = 0
        self._results: dict[TranslationRequest, TranslatedText] = {}
        self._state = TranslationState.LOADING
        self._message = ""
        self._duration = 0.0
        self._processing_since: float | None = None
        self._queued_at: dict[TranslationRequest, float] = {}
        self._queue_ms = 0.0
        self._cache_hits = 0
        self._translated_sources = 0
        self._load_ms = 0.0
        self._last_inference_ms = 0.0
        self._dialogue = DialogueMemory()
        self._blocks: dict[TranslationRequest, TextBlock] = {}
        self._contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]] = {}
        self._rejections: OrderedDict[tuple[TranslationRequest, tuple[DialogueTurn, ...]], str] = (
            OrderedDict()
        )
        self._thread = threading.Thread(target=self._run, name="translation-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def update(
        self,
        tracks: tuple[TextTrack | TextBlock, ...],
        *,
        retain: tuple[TextBlock, ...] = (),
        reset_context: bool = False,
        corrections: tuple[tuple[TextTrack, TextTrack], ...] = (),
    ) -> None:
        desired = tuple(
            TranslationRequest.from_block(t)
            if isinstance(t, TextBlock)
            else TranslationRequest.from_track(t)
            for t in tracks
            if has_japanese(t.text)
        )[:128]
        desired_set = set(desired)
        retained = tuple(
            key
            for block in retain[:128]
            if (key := TranslationRequest.from_block(block)) not in desired_set
        )[: 128 - len(desired)]
        with self._condition:
            now = time.monotonic()
            blocks = tuple(t for t in tracks[:128] if isinstance(t, TextBlock))
            allowed = desired_set.union(retained)
            self._blocks = {
                key: b
                for b in (*retain[:128], *blocks)
                if (key := TranslationRequest.from_block(b)) in allowed
            }
            if reset_context:
                self._dialogue.reset()
            self._dialogue.observe(retain[:128] or blocks, now, corrections=corrections)
            contexts = {
                key: () if reset_context else context
                for key, context in self._contexts.items()
                if key in allowed
            }
            for key in desired:
                if key not in contexts:
                    contexts[key] = (
                        self._dialogue.context_for(self._blocks[key]) if key in self._blocks else ()
                    )
            if (
                self._stop
                or self._state == TranslationState.FAILED
                or (
                    desired == self._desired
                    and retained == self._retained
                    and contexts == self._contexts
                )
            ):
                return
            self._desired, self._retained = desired, retained
            self._contexts = contexts
            self._demand_changed = True
            self._queued_at = {key: self._queued_at.get(key, now) for key in desired}
            self._results = {key: value for key, value in self._results.items() if key in allowed}
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._desired = ()
            self._retained = ()
            self._results.clear()
            self._rejections.clear()
            self._queued_at.clear()
            self._dialogue.reset()
            self._contexts.clear()
            self._blocks.clear()
            self._condition.notify()

    def switch_backend(self, factory: Callable[[], TranslationBackend]) -> None:
        with self._condition:
            if self._stop or self._state == TranslationState.FAILED:
                return
            self._factory = factory
            self._backend_generation += 1
            self._generation += 1
            self._results.clear()
            self._rejections.clear()
            self._state = TranslationState.LOADING
            self._message = ""
            self._queued_at = {key: time.monotonic() for key in self._desired}
            self._duration = self._queue_ms = self._load_ms = 0
            self._last_inference_ms = 0
            self._dialogue.reset()
            self._contexts.clear()
            self._cache_hits = self._translated_sources = 0
            self._cancelled_obsolete = 0
            self._condition.notify()

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._desired = ()
            self._retained = ()
            self._results.clear()
            self._rejections.clear()
            if self._state not in (TranslationState.FAILED, TranslationState.STOPPED):
                self._state = TranslationState.STOPPING
            self._condition.notify()

    @property
    def finished(self) -> bool:
        return self._done.is_set() and not self._thread.is_alive()

    def snapshot(self) -> TranslationSnapshot:
        with self._condition:
            rejected = tuple(
                TranslationRejection(key, message)
                for key in self._desired
                if (message := self._rejections.get((key, self._contexts.get(key, ()))))
            )
            return TranslationSnapshot(
                self._state,
                tuple(self._results.values()),
                sum(self._needs_translation(key) for key in self._desired),
                self._duration,
                " · ".join(
                    filter(
                        None,
                        (
                            self._message,
                            f"{len(rejected)} text block(s) rejected: {rejected[0].message}"
                            if rejected
                            else "",
                        ),
                    )
                ),
                processing_since=self._processing_since,
                queue_ms=self._queue_ms,
                cache_hits=self._cache_hits,
                translated_sources=self._translated_sources,
                load_ms=self._load_ms,
                last_inference_ms=self._last_inference_ms,
                backend_generation=self._backend_generation,
                rejected=rejected,
                cancelled_obsolete=self._cancelled_obsolete,
            )

    def _needs_translation(self, key: TranslationRequest) -> bool:
        return (
            key not in self._results and (key, self._contexts.get(key, ())) not in self._rejections
        )

    def _wake(self, _: object = None) -> None:
        with self._condition:
            self._condition.notify()

    def _run(self) -> None:
        engine: TranslationBackend | None = None
        cache: TranslationCache | None = None
        active_backend = -1
        schedule = TranslationSchedule()
        try:
            cache = TranslationCache(self._cache_path)
            while True:
                with self._condition:
                    stale = self._stop or schedule.stale(self._generation)
                if stale and isinstance(engine, DeferredBackend):
                    engine.cancel_pending()
                    schedule.reset()
                    with self._condition:
                        self._processing_since = None
                completed = schedule.completed()
                for batch, future in completed:
                    self._publish_batch(
                        batch,
                        future.result(),
                        cache,
                        inference=True,
                        remaining_since=schedule.processing_since,
                    )
                if completed:
                    continue
                with self._condition:
                    self._condition.wait_for(
                        lambda active=active_backend: (
                            self._stop
                            or active != self._backend_generation
                            or self._demand_changed
                            or schedule.has_completion()
                            or schedule.stale(self._generation)
                            or schedule.needs_plan(
                                self._generation,
                                (
                                    (key, self._contexts.get(key, ()))
                                    for key in self._desired
                                    if self._needs_translation(key)
                                ),
                            )
                        )
                    )
                    if self._stop:
                        return
                    if schedule.has_completion() or schedule.stale(self._generation):
                        continue
                    backend_generation, factory = self._backend_generation, self._factory
                    if self._demand_changed:
                        self._demand_changed = False
                        if schedule.processing_since is not None:
                            wanted = {
                                (key.source, self._contexts.get(key, ()))
                                for key in (*self._desired, *self._retained)
                            }
                            self._cancelled_obsolete += schedule.cancel_unused(wanted)
                            self._processing_since = schedule.processing_since
                    jobs = tuple(key for key in self._desired if self._needs_translation(key))
                    contexts: dict[TranslationRequest, tuple[DialogueTurn, ...]] = {
                        key: self._contexts.get(key) or () for key in jobs
                    }
                    demand = Demand(
                        self._generation,
                        jobs,
                        contexts,
                        frozenset(
                            key
                            for key in jobs
                            if key in self._blocks and self._blocks[key].dialogue
                        ),
                    )
                if active_backend != backend_generation:
                    if engine is not None:
                        engine.close()
                        engine = None
                    started = time.perf_counter()
                    engine = factory()
                    active_backend = backend_generation
                    schedule.reset()
                    with self._condition:
                        published = not self._stop and active_backend == self._backend_generation
                        if published:
                            self._state = TranslationState.READY
                            self._message = cache.warning
                            self._load_ms = (time.perf_counter() - started) * 1000
                    if published:
                        self._notify()
                    continue
                assert engine is not None
                batch = schedule.plan(demand, engine, cache)
                if batch is None:
                    continue
                with self._condition:
                    if self._stop or batch.generation != self._generation:
                        continue
                    if not batch.activate(
                        self._desired,
                        self._contexts,
                        self._queued_at,
                        now=time.monotonic(),
                        measured=time.perf_counter(),
                    ):
                        continue
                    if batch.missing:
                        since = schedule.processing_since
                        self._processing_since = (
                            min(batch.started, since) if since is not None else batch.started
                        )
                if batch.missing and isinstance(engine, DeferredBackend):
                    future = engine.submit_translation(batch.missing)
                    schedule.submitted(batch, future)
                    future.add_done_callback(self._wake)
                else:
                    outcome = translate_batch(engine, batch.missing) if batch.missing else ({}, {})
                    self._publish_batch(batch, outcome, cache, inference=bool(batch.missing))
        except Exception as error:
            logger.exception("Translation failed")
            with self._condition:
                self._state = TranslationState.FAILED
                self._results.clear()
                self._message = str(error)
            self._notify()
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception:
                    logger.exception("Translation backend cleanup failed")
            if cache is not None:
                try:
                    cache.close()
                except Exception:
                    logger.exception("Translation cache cleanup failed")
            with self._condition:
                self._processing_since = None
                if self._state != TranslationState.FAILED:
                    self._state = TranslationState.STOPPED
            self._done.set()
            self._notify()

    def _publish_batch(
        self,
        batch: Batch,
        outcome: BatchResult,
        cache: TranslationCache,
        *,
        inference: bool,
        remaining_since: float | None = None,
    ) -> None:
        translated, rejected_sources = outcome
        for source, english in translated.items():
            cache.put(batch.keys[source], english)
            batch.answers[source] = english
        duration = (time.perf_counter() - batch.measured) * 1000
        with self._condition:
            if inference:
                self._processing_since = remaining_since
            published = not self._stop and batch.generation == self._generation
            if published:
                for key in batch.jobs:
                    if key not in self._desired or batch.contexts[key] != self._contexts.get(
                        key, ()
                    ):
                        continue
                    source = batch.inputs[key]
                    if source in rejected_sources:
                        failure = (key, batch.contexts[key])
                        self._rejections[failure] = rejected_sources[source][:512]
                        self._rejections.move_to_end(failure)
                        while len(self._rejections) > 256:
                            self._rejections.popitem(last=False)
                    english = batch.answers.get(source)
                    if english is not None:
                        self._results[key] = TranslatedText(key, english)
                        if key in self._blocks:
                            self._dialogue.published(self._blocks[key], english, time.monotonic())
                self._duration, self._queue_ms = duration, batch.queue_ms
                self._cache_hits = len(batch.sources) - len(batch.missing)
                self._translated_sources = len(batch.missing) - len(rejected_sources)
                if inference:
                    self._last_inference_ms = duration
                self._message = cache.warning
        if published:
            self._notify()


def translate_batch(
    engine: TranslationBackend, sources: tuple[Source, ...]
) -> tuple[dict[Source, str], dict[Source, str]]:
    """Isolate known rejections. Split a rejected batch once; native failures stay fatal."""
    answers: dict[Source, str] = {}
    rejected = {
        source: "Source text exceeds the 512-character translation limit."
        for source in sources
        if len(source[0]) > 512
    }
    valid = tuple(source for source in sources if source not in rejected)

    def accept(source: Source, english: str) -> None:
        if not english.strip() or len(english) > 4096:
            rejected[source] = "Translation backend returned empty or oversized text."
        else:
            answers[source] = english

    if isinstance(engine, ContextualBackend):
        for source in valid:
            try:
                accept(source, engine.translate_with_context(*source))
            except RequestRejected as error:
                rejected[source] = str(error) or "Model rejected this request."
    elif valid:
        try:
            translated = engine.translate(tuple(source[0] for source in valid))
        except RequestRejected as error:
            if len(valid) == 1:
                rejected[valid[0]] = str(error) or "Model rejected this request."
            else:
                for source in valid:
                    good, bad = translate_batch(engine, (source,))
                    answers.update(good)
                    rejected.update(bad)
        else:
            for source, english in zip(valid, translated, strict=True):
                accept(source, english)
    return answers, rejected
