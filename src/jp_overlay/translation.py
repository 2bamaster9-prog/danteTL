"""Local translation scheduling, backend swapping, and stale-result rejection."""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jp_overlay.dialogue_context import DialogueMemory, DialogueTurn
from jp_overlay.grouping import TextBlock
from jp_overlay.text_content import has_japanese
from jp_overlay.tracking import TextTrack
from jp_overlay.translation_cache import TranslationCache, translation_key

logger = logging.getLogger(__name__)


class TranslationBackend(Protocol):
    cache_identity: str

    def translate(self, texts: tuple[str, ...], /) -> tuple[str, ...]: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BackendChoice:
    name: str
    create: Callable[[], TranslationBackend]
    key: str = ""
    preparation_id: str = ""
    unavailable_reason: str = ""
    performance_notice: str = ""


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    track_id: int
    text_revision: int
    source: str
    members: tuple[tuple[int, int, str], ...] = ()

    @classmethod
    def from_track(cls, track: TextTrack) -> "TranslationRequest":
        return cls(track.track_id, track.text_revision, track.text)

    @classmethod
    def from_block(cls, block: TextBlock) -> "TranslationRequest":
        first = block.lines[0]
        if len(block.lines) == 1:
            return cls.from_track(first)
        return cls(first.track_id, first.text_revision, block.text, block.key)

    @property
    def line_sources(self) -> tuple[tuple[int, int, str], ...]:
        return self.members or ((self.track_id, self.text_revision, self.source),)


@dataclass(frozen=True, slots=True)
class TranslatedText:
    request: TranslationRequest
    english: str


class TranslationState(StrEnum):
    LOADING = "loading"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TranslationSnapshot:
    state: TranslationState
    results: tuple[TranslatedText, ...] = ()
    pending: int = 0
    last_batch_ms: float = 0
    message: str = ""
    processing_since: float | None = None
    queue_ms: float = 0
    cache_hits: int = 0
    translated_sources: int = 0
    load_ms: float = 0
    last_inference_ms: float = 0
    backend_generation: int = 0


class TranslationSession:
    """One model, one in-flight batch, and at most 128 current requests.

    The UI replaces the desired set, never appends a job queue. Models and SQLite
    belong to this worker. A swap drains the active call, closes the old backend,
    then loads the latest requested backend before accepting results again.
    """

    def __init__(self, factory: Callable[[], TranslationBackend], cache_path: Path) -> None:
        self._factory, self._cache_path = factory, cache_path
        self._condition = threading.Condition()
        self._done = threading.Event()
        self._stop = False
        self._generation = 0
        self._backend_generation = 0
        self._desired: tuple[TranslationRequest, ...] = ()
        self._retained: tuple[TranslationRequest, ...] = ()
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
        self._thread = threading.Thread(target=self._run, name="translation-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def update(
        self,
        tracks: tuple[TextTrack | TextBlock, ...],
        *,
        retain: tuple[TextBlock, ...] = (),
        reset_context: bool = False,
    ) -> None:
        desired = tuple(
            TranslationRequest.from_block(t)
            if isinstance(t, TextBlock)
            else TranslationRequest.from_track(t)
            for t in tracks
            if has_japanese(t.text)
        )[:128]
        retained = tuple(
            key
            for block in retain[:128]
            if (key := TranslationRequest.from_block(block)) not in desired
        )[: 128 - len(desired)]
        with self._condition:
            now = time.monotonic()
            blocks = tuple(t for t in tracks[:128] if isinstance(t, TextBlock))
            allowed = set(desired) | set(retained)
            self._blocks = {
                key: b
                for b in (*retain[:128], *blocks)
                if (key := TranslationRequest.from_block(b)) in allowed
            }
            if reset_context:
                self._dialogue.reset()
                self._contexts = {key: () for key in desired if key not in self._results}
            self._dialogue.observe(retain[:128] or blocks, now)
            self._contexts = {
                key: self._contexts.get(key, self._dialogue.context_for(self._blocks[key]))
                if key in self._blocks
                else ()
                for key in desired
            }
            if (
                self._stop
                or self._state == TranslationState.FAILED
                or (desired == self._desired and retained == self._retained)
            ):
                return
            self._desired, self._retained = desired, retained
            self._queued_at = {key: self._queued_at.get(key, now) for key in desired}
            allowed = set(desired) | set(retained)
            self._results = {key: value for key, value in self._results.items() if key in allowed}
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._desired = ()
            self._retained = ()
            self._results.clear()
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
            self._state = TranslationState.LOADING
            self._message = ""
            self._queued_at = {key: time.monotonic() for key in self._desired}
            self._duration = self._queue_ms = self._load_ms = 0
            self._last_inference_ms = 0
            self._dialogue.reset()
            self._contexts.clear()
            self._cache_hits = self._translated_sources = 0
            self._condition.notify()

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._desired = ()
            self._retained = ()
            self._results.clear()
            if self._state not in (TranslationState.FAILED, TranslationState.STOPPED):
                self._state = TranslationState.STOPPING
            self._condition.notify()

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def snapshot(self) -> TranslationSnapshot:
        with self._condition:
            return TranslationSnapshot(
                self._state,
                tuple(self._results.values()),
                sum(key not in self._results for key in self._desired),
                self._duration,
                self._message,
                processing_since=self._processing_since,
                queue_ms=self._queue_ms,
                cache_hits=self._cache_hits,
                translated_sources=self._translated_sources,
                load_ms=self._load_ms,
                last_inference_ms=self._last_inference_ms,
                backend_generation=self._backend_generation,
            )

    def _run(self) -> None:
        engine: TranslationBackend | None = None
        cache: TranslationCache | None = None
        active_backend = -1
        try:
            cache = TranslationCache(self._cache_path)
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda active=active_backend: (
                            self._stop
                            or active != self._backend_generation
                            or any(key not in self._results for key in self._desired)
                        )
                    )
                    if self._stop:
                        return
                    backend_generation = self._backend_generation
                    factory = self._factory
                    generation = self._generation
                    jobs = tuple(key for key in self._desired if key not in self._results)
                    contexts = {key: self._contexts.get(key, ()) for key in jobs}
                if active_backend != backend_generation:
                    if engine is not None:
                        engine.close()
                        engine = None
                    started = time.perf_counter()
                    engine = factory()
                    active_backend = backend_generation
                    with self._condition:
                        if not self._stop and active_backend == self._backend_generation:
                            self._state = TranslationState.READY
                            self._message = cache.warning
                            self._load_ms = (time.perf_counter() - started) * 1000
                    continue
                assert engine is not None
                batch_size = max(1, min(4, int(getattr(engine, "batch_size", 4))))
                contextual = getattr(engine, "translate_with_context", None)
                inputs = {key: (key.source, contexts[key] if contextual else ()) for key in jobs}
                sources = tuple(dict.fromkeys(inputs.values()))[:batch_size]
                keys = {
                    source: translation_key(
                        engine.cache_identity + (":dialogue-context-v1" if source[1] else ""),
                        json.dumps(
                            [source[0], [(t.source, t.english) for t in source[1]]],
                            ensure_ascii=False,
                        )
                        if source[1]
                        else source[0],
                    )
                    for source in sources
                }
                answers = {source: cache.get(keys[source]) for source in sources}
                missing = tuple(source for source in sources if answers[source] is None)
                started = time.monotonic()
                measured = time.perf_counter()
                inference_ms = 0.0
                with self._condition:
                    self._processing_since = started if missing else None
                    queue_ms = max(
                        (started - self._queued_at.get(key, started)) * 1000
                        for key in jobs
                        if inputs[key] in sources
                    )
                if missing:
                    if any(len(source[0]) > 512 for source in missing):
                        raise ValueError("Source text exceeds the 512-character translation limit.")
                    translated = (
                        tuple(contextual(source, context) for source, context in missing)
                        if contextual
                        else engine.translate(tuple(source for source, _ in missing))
                    )
                    inference_ms = (time.perf_counter() - measured) * 1000
                    for source, english in zip(missing, translated, strict=True):
                        if not english.strip() or len(english) > 4096:
                            raise RuntimeError(
                                "Translation backend returned empty or oversized text."
                            )
                        cache.put(keys[source], english)
                        answers[source] = english
                duration = (time.perf_counter() - measured) * 1000
                with self._condition:
                    self._processing_since = None
                    if not self._stop and generation == self._generation:
                        for key in jobs:
                            english = answers.get(inputs[key])
                            if (
                                key in self._desired
                                and english is not None
                                and (not contextual or contexts[key] == self._contexts.get(key, ()))
                            ):
                                self._results[key] = TranslatedText(key, english)
                                if key in self._blocks:
                                    self._dialogue.published(
                                        self._blocks[key], english, time.monotonic()
                                    )
                        self._duration = duration
                        self._queue_ms = queue_ms
                        self._cache_hits = len(sources) - len(missing)
                        self._translated_sources = len(missing)
                        if missing:
                            self._last_inference_ms = inference_ms
                        self._message = cache.warning
        except Exception as error:
            logger.exception("Local translation failed")
            with self._condition:
                self._state = TranslationState.FAILED
                self._results.clear()
                self._message = str(error)
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
