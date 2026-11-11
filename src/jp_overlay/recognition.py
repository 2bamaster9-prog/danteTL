"""One OCR worker, one pending frame, and generation-checked immutable results."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jp_overlay.domain import CapturedFrame, Rect

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TextCharacter:
    text: str
    bounds: Rect
    confidence: float


@dataclass(frozen=True, slots=True)
class TextRegion:
    """Client-relative physical pixels; confidence is mean retained-character confidence."""

    text: str
    bounds: Rect
    characters: tuple[TextCharacter, ...] = ()
    vertical: bool = False

    @property
    def confidence(self) -> float | None:
        if not self.characters:
            return None
        return sum(char.confidence for char in self.characters) / len(self.characters)


@dataclass(frozen=True, slots=True)
class OcrResult:
    frame: CapturedFrame
    regions: tuple[TextRegion, ...]
    duration_ms: float
    completed_at: float


class OcrState(StrEnum):
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class OcrSnapshot:
    state: OcrState
    result: OcrResult | None = None
    message: str = ""


class Recognizer(Protocol):
    def recognize(self, frame: CapturedFrame, /) -> tuple[TextRegion, ...]: ...


class OcrSession:
    """Own models on a worker thread. No Qt, Windows calls, or unbounded job queues.

    A new capture gets a new session. Invalidation discards in-flight results after
    resize/minimize/pause; shutdown waits asynchronously for native inference to return.
    """

    def __init__(self, factory: Callable[[], Recognizer]) -> None:
        self._factory = factory
        self._condition = threading.Condition()
        self._done = threading.Event()
        self._stop = False
        self._generation = 0
        self._last_sequence = 0
        self._pending: tuple[int, CapturedFrame] | None = None
        self._snapshot = OcrSnapshot(OcrState.LOADING)
        self._thread = threading.Thread(target=self._run, name="ocr-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, frame: CapturedFrame) -> None:
        with self._condition:
            if (
                self._stop
                or self._snapshot.state == OcrState.FAILED
                or frame.sequence <= self._last_sequence
            ):
                return
            self._last_sequence = frame.sequence
            self._pending = self._generation, frame
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._last_sequence = 0
            self._pending = None
            self._snapshot = OcrSnapshot(self._snapshot.state, message=self._snapshot.message)

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._pending = None
            self._snapshot = OcrSnapshot(
                self._snapshot.state
                if self._snapshot.state in (OcrState.FAILED, OcrState.STOPPED)
                else OcrState.STOPPING,
                message=self._snapshot.message,
            )
            self._condition.notify()

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def snapshot(self) -> OcrSnapshot:
        with self._condition:
            return self._snapshot

    def _run(self) -> None:
        try:
            with self._condition:
                if self._stop:
                    return
            engine = self._factory()
            with self._condition:
                if self._stop:
                    return
                self._snapshot = OcrSnapshot(OcrState.READY)
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stop or self._pending is not None)
                    if self._stop:
                        return
                    job = self._pending
                    self._pending = None
                assert job is not None
                generation, frame = job
                started = time.monotonic()
                regions = engine.recognize(frame)
                completed = time.monotonic()
                result = OcrResult(frame, regions, (completed - started) * 1000, completed)
                with self._condition:
                    if not self._stop and generation == self._generation:
                        self._snapshot = OcrSnapshot(OcrState.READY, result)
                # Do not keep old frame buffers alive through the next idle wait.
                del job, frame, result
        except Exception as error:
            logger.exception("Local OCR failed")
            with self._condition:
                self._snapshot = OcrSnapshot(OcrState.FAILED, message=str(error))
        finally:
            with self._condition:
                self._pending = None
                if self._snapshot.state != OcrState.FAILED:
                    self._snapshot = OcrSnapshot(OcrState.STOPPED)
            self._done.set()


def overlay_result_ready(result: OcrResult, latest: CapturedFrame, now: float) -> bool:
    """Allow static frames; expire lagging diagnostics on a changing source after 750 ms."""
    return result.frame.geometry.client.size == latest.geometry.client.size and (
        result.frame.sequence == latest.sequence or now - result.frame.captured_at <= 0.75
    )
