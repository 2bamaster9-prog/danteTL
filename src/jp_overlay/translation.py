"""Local translation scheduling, backend swapping, and stale-result rejection."""

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from jp_overlay.tracking import TextTrack
from jp_overlay.translation_cache import TranslationCache, translation_key

logger = logging.getLogger(__name__)
_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")


class TranslationBackend(Protocol):
    cache_identity: str

    def translate(self, texts: tuple[str, ...], /) -> tuple[str, ...]: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BackendChoice:
    name: str
    create: Callable[[], TranslationBackend]


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    track_id: int
    text_revision: int
    source: str

    @classmethod
    def from_track(cls, track: TextTrack) -> "TranslationRequest":
        return cls(track.track_id, track.text_revision, track.text)


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
        self._results: dict[TranslationRequest, TranslatedText] = {}
        self._state = TranslationState.LOADING
        self._message = ""
        self._duration = 0.0
        self._thread = threading.Thread(target=self._run, name="translation-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def update(self, tracks: tuple[TextTrack, ...]) -> None:
        desired = tuple(
            TranslationRequest.from_track(t) for t in tracks if _JAPANESE.search(t.text)
        )[:128]
        with self._condition:
            if self._stop or self._state == TranslationState.FAILED or desired == self._desired:
                return
            self._desired = desired
            self._results = {key: value for key, value in self._results.items() if key in desired}
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._desired = ()
            self._results.clear()
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
            self._condition.notify()

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._desired = ()
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
                len(self._desired) - len(self._results),
                self._duration,
                self._message,
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
                if active_backend != backend_generation:
                    if engine is not None:
                        engine.close()
                        engine = None
                    engine = factory()
                    active_backend = backend_generation
                    with self._condition:
                        if not self._stop and active_backend == self._backend_generation:
                            self._state = TranslationState.READY
                            self._message = cache.warning
                    continue
                assert engine is not None
                sources = tuple(dict.fromkeys(key.source for key in jobs))[:4]
                keys = {
                    source: translation_key(engine.cache_identity, source) for source in sources
                }
                answers = {source: cache.get(keys[source]) for source in sources}
                missing = tuple(source for source in sources if answers[source] is None)
                started = time.monotonic()
                if missing:
                    if any(len(source) > 512 for source in missing):
                        raise ValueError("Source text exceeds the 512-character translation limit.")
                    translated = engine.translate(missing)
                    for source, english in zip(missing, translated, strict=True):
                        if not english.strip() or len(english) > 4096:
                            raise RuntimeError(
                                "Translation backend returned empty or oversized text."
                            )
                        cache.put(keys[source], english)
                        answers[source] = english
                duration = (time.monotonic() - started) * 1000
                with self._condition:
                    if not self._stop and generation == self._generation:
                        for key in jobs:
                            english = answers.get(key.source)
                            if key in self._desired and english is not None:
                                self._results[key] = TranslatedText(key, english)
                        self._duration = duration
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
                if self._state != TranslationState.FAILED:
                    self._state = TranslationState.STOPPED
            self._done.set()
