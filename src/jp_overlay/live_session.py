"""Live pipeline ownership and ordered reconciliation, independent of Qt and Win32.

Model preparation/selection belongs to the application lifecycle. An active translator
is supplied explicitly; this coordinator owns which sources it sees and what may paint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jp_overlay.domain import CapturedFrame, CaptureSnapshot, CaptureState, Rect, WindowTarget
from jp_overlay.grouping import DialogueGrouper, TextBlock
from jp_overlay.presentation import EnglishPresentation
from jp_overlay.recognition import (
    OcrResult,
    OcrSession,
    OcrSnapshot,
    OcrState,
    Recognizer,
    overlay_result_ready,
)
from jp_overlay.tracking import TextActivity, TextTrack, TextTracker
from jp_overlay.translation import TranslatedText, TranslationSession, TranslationSnapshot
from jp_overlay.visual import VisualSession, VisualState


class CaptureWorker(Protocol):
    target: WindowTarget

    @property
    def finished(self) -> bool: ...
    def start(self) -> None: ...
    def request_stop(self) -> None: ...
    def snapshot(self) -> CaptureSnapshot: ...


class OcrWorker(Protocol):
    @property
    def finished(self) -> bool: ...
    def start(self) -> None: ...
    def request_stop(self) -> None: ...
    def invalidate(self) -> None: ...
    def snapshot(self) -> OcrSnapshot: ...
    def acknowledge(self, sequence: int) -> None: ...
    def submit(self, frame: CapturedFrame, areas: tuple[Rect, ...] | None = None) -> None: ...


class VisualWorker(Protocol):
    @property
    def finished(self) -> bool: ...
    def start(self) -> None: ...
    def request_stop(self) -> None: ...
    def invalidate(self) -> None: ...
    def poll(self) -> VisualState: ...
    def submit(
        self,
        frame: CapturedFrame,
        result: OcrResult | None,
        tracks: tuple[TextTrack, ...],
        assignments: tuple[int | None, ...],
        activity: tuple[TextActivity, ...],
        candidate: OcrResult | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class Scene:
    tracks: tuple[TextTrack, ...] = ()
    blocks: tuple[TextBlock, ...] = ()
    requests: tuple[TextBlock, ...] = ()
    waiting_blocks: int = 0


@dataclass(frozen=True, slots=True)
class EnglishScene:
    snapshot: TranslationSnapshot
    blocks: tuple[TextBlock, ...]
    translations: tuple[TranslatedText, ...]


class LiveSession:
    """One bounded live scene, with commands hiding reset/reconcile/ack ordering."""

    def __init__(
        self,
        *,
        ocr_factory: Callable[[Callable[[], Recognizer]], OcrWorker] | None = None,
        visual_factory: Callable[[], VisualWorker] = VisualSession,
    ) -> None:
        self._ocr_factory = ocr_factory or (lambda factory: OcrSession(factory, require_ack=True))
        self._visual_factory = visual_factory
        self.capture: CaptureWorker | None = None
        self.ocr: OcrWorker | None = None
        self.visual: VisualWorker | None = None
        self.visual_state = VisualState()
        self.accepted: OcrResult | None = None
        self.assignments: tuple[int | None, ...] = ()
        self.valid_size: tuple[int, int] | None = None
        self._tracker = TextTracker()
        self._grouper = DialogueGrouper()
        self._presentation = EnglishPresentation()
        self._context_reset_sequence = 0

    def start(self, capture: CaptureWorker, recognizer: Callable[[], Recognizer] | None) -> None:
        if self.capture is not None:
            raise RuntimeError("The previous capture must finish before starting another.")
        self.reset()
        self.valid_size = None
        self.capture = capture
        capture.start()
        if recognizer:
            self.add_recognition(recognizer)

    def add_recognition(self, factory: Callable[[], Recognizer]) -> None:
        if (
            self.ocr
            or not self.capture
            or self.capture.finished
            or self.capture.snapshot().state
            in (CaptureState.STOPPING, CaptureState.STOPPED, CaptureState.FAILED)
        ):
            return
        self.ocr, self.visual = self._ocr_factory(factory), self._visual_factory()
        self.ocr.start()
        self.visual.start()

    def stop(self, translation: TranslationSession | None = None) -> None:
        self.reset(translation)
        for worker in (self.ocr, self.visual, self.capture):
            if worker:
                worker.request_stop()

    def drain(self) -> bool:
        """A stopped source cannot be replaced while its workers still own resources."""
        if self.capture and not self.capture.finished:
            return False
        for worker in (self.visual, self.ocr):
            if worker:
                worker.request_stop()
        if any(worker and not worker.finished for worker in (self.visual, self.ocr)):
            return False
        self.capture = self.ocr = self.visual = None
        self.valid_size = None
        self.reset()
        return True

    def invalidate(self, translation: TranslationSession | None = None) -> None:
        if self.valid_size is not None and self.ocr:
            self.ocr.invalidate()
        self.valid_size = None
        self.reset(translation)

    def accept_size(self, size: tuple[int, int], translation: TranslationSession | None) -> bool:
        if self.valid_size == size:
            return False
        self.invalidate(translation)
        self.valid_size = size
        return True

    def reset(self, translation: TranslationSession | None = None) -> None:
        self.accepted = None
        self.assignments = ()
        if self.visual:
            self.visual.invalidate()
        self.visual_state = VisualState()
        self._tracker.reset()
        self._grouper.reset()
        self._presentation.reset()
        self._context_reset_sequence = 0
        if translation:
            translation.invalidate()

    def change_grouping(self, translation: TranslationSession | None) -> None:
        self._grouper.reset()
        self.clear_english()
        if translation:
            translation.invalidate()

    def clear_english(self) -> None:
        self._presentation.reset()

    def reconcile(self, frame: CapturedFrame, now: float) -> OcrSnapshot | None:
        if not self.ocr:
            return None
        snapshot = self.ocr.snapshot()
        if snapshot.state == OcrState.FAILED:
            self.reset()
            return snapshot
        if self.visual:
            state = self.visual.poll()
            if snapshot.result and (
                state.message or state.checked_sequence == snapshot.result.frame.sequence
            ):
                self.assignments = self._tracker.observe(
                    snapshot.result,
                    visually_absent=state.absent,
                    visual_sequence=state.frame.sequence if state.frame else 0,
                    unchanged=state.unchanged,
                    visual_checked=state.checked,
                    checked_sequence=state.checked_sequence,
                )
                self.accepted = snapshot.result
                self.ocr.acknowledge(self.accepted.frame.sequence)
            if state.frame is not None:
                self.visual_state = state
                if state.request_ocr:
                    self.ocr.submit(state.frame, state.scan_areas)
                self._tracker.confirm_observations(state.stable_tracks, state.frame.captured_at)
            self.visual.submit(
                frame,
                self.accepted,
                self._tracker.visible(frame, now),
                self.assignments,
                self._tracker.translation_activity(),
                snapshot.result,
            )
        return snapshot

    def scene(
        self, frame: CapturedFrame | None, now: float, *, grouping: bool, stabilize: bool = True
    ) -> Scene:
        tracks = self._tracker.visible(frame, now) if frame else ()
        ready = self._tracker.translation_tracks(frame, now) if frame else ()
        grouped = self._grouper.update(
            tracks, ready, now, enabled=grouping, activity=self._tracker.translation_activity()
        )
        requests = tuple(
            block
            for block in grouped.ready
            if not any(t.track_id in self.visual_state.blocked for t in block.lines)
            and (
                self.visual_state.message
                or (
                    self.accepted and self.visual_state.ocr_sequence == self.accepted.frame.sequence
                )
            )
        )
        tracks = tuple(t for t in tracks if t not in self.visual_state.hidden)
        if not stabilize:
            tracks = (
                tuple(
                    TextTrack(key, region.text, region.bounds, region.vertical)
                    for key, region in zip(self.assignments, self.accepted.regions, strict=True)
                    if key is not None
                )
                if self.accepted and frame and overlay_result_ready(self.accepted, frame, now)
                else ()
            )
        return Scene(tracks, grouped.blocks, requests, len(grouped.blocks) - len(grouped.ready))

    def publish(
        self,
        session: TranslationSession,
        requests: tuple[TextBlock, ...],
        retained: tuple[TextBlock, ...],
    ) -> EnglishScene:
        state = self.visual_state
        broad_change = bool(
            state.frame
            and state.frame.sequence != self._context_reset_sequence
            and sum(b.width * b.height for b in state.changed_areas)
            > state.frame.width * state.frame.height * 0.65
        )
        if broad_change and state.frame:
            self._context_reset_sequence = state.frame.sequence
        session.update(requests, retain=retained, reset_context=broad_change)
        snapshot = session.snapshot()
        published = self._presentation.update(
            retained,
            snapshot.results,
            self._tracker.display_predecessors(),
            scope=(session, snapshot.backend_generation),
        )
        hidden = {t.track_id for t in state.hidden}
        showing = tuple(
            p for p in published if not any(t.track_id in hidden for t in p.accepted.lines)
        )
        return EnglishScene(
            snapshot, tuple(p.painted for p in showing), tuple(p.translation for p in showing)
        )
