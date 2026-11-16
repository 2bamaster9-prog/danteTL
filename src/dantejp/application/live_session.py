"""Live pipeline ownership and ordered reconciliation, independent of Qt and Win32.

Model preparation/selection belongs to the application lifecycle. An active translator
is supplied explicitly; this coordinator owns which sources it sees and what may paint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from dantejp.application.values import Scene as Scene
from dantejp.domain import CapturedFrame, CaptureSnapshot, CaptureState, Rect, WindowTarget
from dantejp.ocr.tracking import TextActivity, TextTrack, TextTracker
from dantejp.ocr.values import OcrResult, OcrSnapshot, OcrState
from dantejp.ocr.visual import VisualSession
from dantejp.ocr.visual_values import VisualState
from dantejp.ocr.worker import OcrSession, Recognizer, overlay_result_ready
from dantejp.translation.dialogue.classifier import ClassifierSession
from dantejp.translation.dialogue.history import DialogueHistory
from dantejp.translation.grouping import DialogueGrouper, TextBlock
from dantejp.translation.presentation import EnglishPresentation
from dantejp.translation.values import TranslatedText, TranslationSnapshot, TranslationWorker


class CaptureWorker(Protocol):
    target: WindowTarget

    @property
    def finished(self) -> bool: ...
    def start(self) -> None: ...
    def request_stop(self) -> None: ...
    def set_border(self, enabled: bool) -> None: ...
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
        evidence_bounds: tuple[Rect, ...] = (),
        matching_sources: tuple[TextTrack, ...] = (),
    ) -> None: ...


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
        self.history = DialogueHistory()
        self.history_enabled = False
        self._history_key: object = None
        self._history_factory: Callable[[], object] | None = None
        self._classifier: ClassifierSession | None = None
        self._classifier_retiring = False
        self._history_layout_only = False
        self._history_suspended = False

    def suspend_history(self, suspended: bool) -> bool:
        self._history_suspended = suspended
        if suspended and self._classifier:
            self._classifier.request_stop()
            self._classifier_retiring = True
        self._advance_history()
        return self._classifier is None

    def configure_history(
        self,
        enabled: bool,
        key: object = "",
        factory: Callable[[], object] | None = None,
        *,
        layout_only: bool = False,
    ) -> None:
        if (enabled, key, layout_only) == (
            self.history_enabled,
            self._history_key,
            self._history_layout_only,
        ):
            return
        self.history_enabled, self._history_key = enabled, key
        self._history_factory, self._history_layout_only = factory, layout_only
        self.history.reset_scene()
        if self._classifier:
            self._classifier.request_stop()
            self._classifier_retiring = True

    @property
    def history_status(self) -> str:
        if not self.history_enabled:
            return "Disabled · No history collection or classification."
        if self._classifier_retiring:
            return "Finishing the previous classifier…"
        if self._history_layout_only:
            return "Layout heuristics only · No classifier calls."
        if not self._history_factory:
            return (
                "Choose an available classifier model. For first use, select the local model "
                "once in a main-screen translation selector to prepare it."
            )
        if self._classifier:
            state = self._classifier.snapshot()
            return state.message + (f" · {state.pending} pending" if state.pending else "")
        return "Ready · Start capture with translation enabled."

    def _advance_history(self) -> None:
        if self._classifier_retiring and self._classifier and self._classifier.finished:
            self._classifier = None
            self._classifier_retiring = False
        if (
            self.history_enabled
            and self._history_factory
            and self.capture
            and not self._classifier
            and not self._history_suspended
        ):
            self._classifier = ClassifierSession(self._history_factory)

    def start(self, capture: CaptureWorker, recognizer: Callable[[], Recognizer] | None) -> None:
        if self.capture is not None:
            raise RuntimeError("The previous capture must finish before starting another.")
        self.reset()
        self.history.start()
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

    def stop(self, translation: TranslationWorker | None = None) -> None:
        self.reset(translation)
        for worker in (self.ocr, self.visual, self.capture, self._classifier):
            if worker:
                worker.request_stop()

    def drain(self) -> bool:
        """A stopped source cannot be replaced while its workers still own resources."""
        if self.capture and not self.capture.finished:
            return False
        for worker in (self.visual, self.ocr, self._classifier):
            if worker:
                worker.request_stop()
        if any(
            worker and not worker.finished for worker in (self.visual, self.ocr, self._classifier)
        ):
            return False
        self.capture = self.ocr = self.visual = None
        self._classifier = None
        self._classifier_retiring = False
        self.valid_size = None
        self.reset()
        return True

    def invalidate(self, translation: TranslationWorker | None = None) -> None:
        if self.valid_size is not None and self.ocr:
            self.ocr.invalidate()
        self.valid_size = None
        self.reset(translation)

    def accept_size(self, size: tuple[int, int], translation: TranslationWorker | None) -> bool:
        if self.valid_size == size:
            return False
        self.invalidate(translation)
        self.valid_size = size
        return True

    def reset(self, translation: TranslationWorker | None = None) -> None:
        self.accepted = None
        self.assignments = ()
        if self.visual:
            self.visual.invalidate()
        self.visual_state = VisualState()
        self._tracker.reset()
        self._grouper.reset()
        self._presentation.reset()
        self._context_reset_sequence = 0
        self.history.reset_scene()
        if self._classifier:
            self._classifier.invalidate()
        if translation:
            translation.invalidate()

    def change_grouping(self, translation: TranslationWorker | None) -> None:
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
            candidate = (
                snapshot.result
                if snapshot.result
                and (
                    self.accepted is None
                    or snapshot.result.frame.sequence > self.accepted.frame.sequence
                )
                else None
            )
            if candidate and (
                state.checked_sequence == candidate.frame.sequence
                and state.matching is not None
                and state.matching.matches(
                    candidate, self._tracker.matching_sources(candidate.frame)
                )
            ):
                self.assignments = self._tracker.observe(
                    candidate,
                    visually_absent=state.absent,
                    visual_sequence=state.frame.sequence if state.frame else 0,
                    unchanged=state.unchanged,
                    visual_checked=state.checked,
                    checked_sequence=state.checked_sequence,
                    pixel_evidence=state.pixel_evidence,
                    matching=state.matching,
                )
                self.accepted = candidate
                self.ocr.acknowledge(self.accepted.frame.sequence)
                candidate = None
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
                candidate,
                self._tracker.evidence_bounds(),
                self._tracker.matching_sources(snapshot.result.frame) if snapshot.result else (),
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
        history_blocks = tuple(
            block
            for block in grouped.blocks
            if not any(t in self.visual_state.hidden for t in block.lines)
        )
        # Exact current names may gain confidence from partial observations. Unscanned
        # names retain their evidence only while the identical live track remains.
        scores = {}
        if self.accepted:
            by_id = {t.track_id: t for block in history_blocks for t in block.lines}
            for key, region in zip(self.assignments, self.accepted.regions, strict=True):
                track = by_id.get(key) if key is not None else None
                if (
                    track
                    and region.text.strip() == track.text.strip()
                    and region.confidence is not None
                ):
                    scores[track] = region.confidence
        self._advance_history()
        if self.history_enabled and (self._history_layout_only or self._history_factory):
            self.history.observe(
                history_blocks,
                requests,
                (frame.width, frame.height) if frame else (0, 0),
                now,
                scores=scores,
                corrections=self._tracker.display_predecessors(),
                assisted=not self._history_layout_only,
            )
            if self._classifier and not self._classifier_retiring and not self._history_suspended:
                self._classifier.update(self.history.classification_requests())
                self.history.accept_classifications(self._classifier.snapshot().results)
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
        session: TranslationWorker,
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
        session.update(
            requests,
            retain=retained,
            reset_context=broad_change,
            corrections=self._tracker.display_predecessors(),
        )
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
        if self.history_enabled:
            self.history.published(tuple(p.translation for p in showing))
        return EnglishScene(
            snapshot, tuple(p.painted for p in showing), tuple(p.translation for p in showing)
        )
