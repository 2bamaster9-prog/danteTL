"""One OCR worker, one pending frame, and generation-checked immutable results."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.regions import scan_regions

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
    scanned: tuple[Rect, ...] | None = None

    def covers(self, bounds: Rect) -> bool:
        return self.scanned is None or any(area.contains(bounds) for area in self.scanned)


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
    processed_frames: int = 0
    skipped_frames: int = 0
    queue_ms: float = 0
    mean_duration_ms: float = 0
    processing_since: float | None = None
    provider: str = ""


class Recognizer(Protocol):
    def recognize(self, frame: CapturedFrame, /) -> tuple[TextRegion, ...]: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OcrChoice:
    name: str
    create: Callable[[], Recognizer]
    capture_fps: int = 8
    key: str = ""


class OcrSession:
    """Own models on a worker thread. No Qt, Windows calls, or unbounded job queues.

    A new capture gets a new session. Invalidation discards in-flight results after
    resize/minimize; inspection pause is independent. Shutdown drains inference and cleanup.
    """

    def __init__(self, factory: Callable[[], Recognizer], *, require_ack: bool = False) -> None:
        self._factory = factory
        self._condition = threading.Condition()
        self._done = threading.Event()
        self._stop = False
        self._generation = 0
        self._last_sequence = 0
        self._pending: tuple[int, CapturedFrame, tuple[Rect, ...] | None] | None = None
        self._require_ack = require_ack
        self._acknowledged = 0
        self._snapshot = OcrSnapshot(OcrState.LOADING)
        self._processed = 0
        self._skipped = 0
        self._queue_ms = 0.0
        self._durations: deque[float] = deque(maxlen=8)
        self._processing_since: float | None = None
        self._thread = threading.Thread(target=self._run, name="ocr-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, frame: CapturedFrame, areas: tuple[Rect, ...] | None = None) -> None:
        if areas == ():
            return
        with self._condition:
            if (
                self._stop
                or self._snapshot.state == OcrState.FAILED
                or frame.sequence <= self._last_sequence
            ):
                return
            self._last_sequence = frame.sequence
            if self._pending is not None:
                self._skipped += 1
                prior = self._pending[2]
                areas = None if areas is None or prior is None else (*prior, *areas)
            areas = scan_regions(areas, frame.geometry.client.size)
            if areas == ():
                return
            self._pending = self._generation, frame, areas
            self._condition.notify()

    def acknowledge(self, sequence: int) -> None:
        """Release the next job only after the current result reached tracking."""
        with self._condition:
            self._acknowledged = max(self._acknowledged, sequence)
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._last_sequence = 0
            self._acknowledged = 0
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
        return self._done.is_set() and not self._thread.is_alive()

    def snapshot(self) -> OcrSnapshot:
        with self._condition:
            return replace(
                self._snapshot,
                processed_frames=self._processed,
                skipped_frames=self._skipped,
                queue_ms=self._queue_ms,
                mean_duration_ms=sum(self._durations) / len(self._durations)
                if self._durations
                else 0,
                processing_since=self._processing_since,
            )

    def _ready(self, engine: Recognizer, result: OcrResult | None = None) -> OcrSnapshot:
        return OcrSnapshot(
            OcrState.READY,
            result,
            str(getattr(engine, "message", "")),
            provider=str(getattr(engine, "provider", "")),
        )

    def _run(self) -> None:
        engine: Recognizer | None = None
        try:
            with self._condition:
                if self._stop:
                    return
            engine = self._factory()
            with self._condition:
                if self._stop:
                    return
                self._snapshot = self._ready(engine)
            while True:
                with self._condition:
                    self._condition.wait_for(
                        lambda: (
                            self._stop
                            or (
                                self._pending is not None
                                and (
                                    not self._require_ack
                                    or self._snapshot.result is None
                                    or self._snapshot.result.frame.sequence <= self._acknowledged
                                )
                            )
                        )
                    )
                    if self._stop:
                        return
                    job = self._pending
                    self._pending = None
                    self._processing_since = time.monotonic()
                assert job is not None
                generation, frame, areas = job
                started = time.monotonic()
                regions, scanned = recognize_regions(engine, frame, areas)
                completed = time.monotonic()
                result = OcrResult(frame, regions, (completed - started) * 1000, completed, scanned)
                with self._condition:
                    self._processing_since = None
                    if not self._stop and generation == self._generation:
                        self._processed += 1
                        self._queue_ms = max(0, (started - frame.captured_at) * 1000)
                        self._durations.append(result.duration_ms)
                        self._snapshot = self._ready(engine, result)
                # Do not keep old frame buffers alive through the next idle wait.
                del job, frame, result
        except Exception as error:
            logger.exception("Local OCR failed")
            with self._condition:
                self._snapshot = OcrSnapshot(OcrState.FAILED, message=str(error))
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception as error:
                    logger.exception("OCR cleanup failed")
                    with self._condition:
                        self._snapshot = OcrSnapshot(OcrState.FAILED, message=str(error))
                finally:
                    engine = None
            with self._condition:
                self._pending = None
                self._processing_since = None
                if self._snapshot.state != OcrState.FAILED:
                    self._snapshot = OcrSnapshot(OcrState.STOPPED)
            self._done.set()


def recognize_regions(
    engine: Recognizer, frame: CapturedFrame, areas: tuple[Rect, ...] | None
) -> tuple[tuple[TextRegion, ...], tuple[Rect, ...] | None]:
    """Crop on the model worker; map every line/character back to the exact source.

    A detector box at an artificial crop edge may be an incomplete word. Discard
    that provisional crop output and perform one full scan instead of publishing it.
    """
    areas = scan_regions(areas, frame.geometry.client.size)
    if areas is None:
        return engine.recognize(frame), None
    if len(frame.bgra) != frame.width * frame.height * 4:
        raise ValueError("Invalid source pixels for regional OCR")
    pixels = memoryview(frame.bgra)
    regions = []
    for area in areas:
        rows = (
            pixels[(y * frame.width + area.x) * 4 : (y * frame.width + area.x + area.width) * 4]
            for y in range(area.y, area.y + area.height)
        )
        bounds = Rect(0, 0, area.width, area.height)
        crop = CapturedFrame(
            frame.sequence,
            frame.captured_at,
            WindowGeometry(bounds, bounds, bounds, frame.geometry.dpi),
            b"".join(rows),
        )
        for region in engine.recognize(crop):
            b = region.bounds
            if (
                (area.x > 0 and b.x <= 3)
                or (area.y > 0 and b.y <= 3)
                or (area.x + area.width < frame.width and b.x + b.width >= area.width - 3)
                or (area.y + area.height < frame.height and b.y + b.height >= area.height - 3)
            ):
                return engine.recognize(frame), None

            def shifted(b: Rect, origin: Rect = area) -> Rect:
                return replace(b, x=b.x + origin.x, y=b.y + origin.y)

            regions.append(
                replace(
                    region,
                    bounds=shifted(b),
                    characters=tuple(
                        replace(c, bounds=shifted(c.bounds)) for c in region.characters
                    ),
                )
            )
    return tuple(regions), areas


def overlay_result_ready(result: OcrResult, latest: CapturedFrame, now: float) -> bool:
    """Allow static frames; expire lagging diagnostics on a changing source after 750 ms."""
    return result.frame.geometry.client.size == latest.geometry.client.size and (
        result.frame.sequence == latest.sequence or now - result.frame.captured_at <= 0.75
    )
