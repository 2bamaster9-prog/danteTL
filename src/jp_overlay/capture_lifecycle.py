"""Capture transitions and frozen device settings, independent of desktop presentation."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jp_overlay.domain import CaptureSnapshot, CaptureState, WindowGeometry, WindowTarget
from jp_overlay.live_session import CaptureWorker, LiveSession
from jp_overlay.preference_values import Preferences
from jp_overlay.recognition import OcrChoice


class WindowAccess(Protocol):
    def is_target(self, target: WindowTarget) -> bool: ...
    def geometry(self, target: WindowTarget) -> WindowGeometry: ...
    def is_foreground(self, target: WindowTarget) -> bool: ...
    def list_targets(self) -> Sequence[WindowTarget]: ...
    def foreground_target(self) -> WindowTarget: ...


class CapturePhase(StrEnum):
    IDLE = "idle"
    STOPPING = "stopping"
    DRAINING = "draining"
    MINIMIZED = "minimized"
    WAITING_FRAME = "waiting_frame"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class CaptureStep:
    phase: CapturePhase
    snapshot: CaptureSnapshot | None = None
    geometry: WindowGeometry | None = None
    foreground: bool = False


class CaptureLifecycle:
    """Own capture intent until every capture/OCR/visual worker has drained.

    LiveSession retains sole ownership of the workers and their source ordering. This
    owner freezes device/rate choices and validates the target before scene processing.
    """

    def __init__(
        self,
        live: LiveSession,
        windows: WindowAccess,
        choices: tuple[OcrChoice, ...],
        create: Callable[[WindowTarget, int, bool], CaptureWorker],
    ) -> None:
        self.live, self.windows = live, windows
        self._choices, self._create = choices, create
        self.ocr_choice: OcrChoice | None = None
        self.rate = 8
        self.started_at = 0.0
        self.stopping = False
        self.stop_message = "Capture stopped."

    @property
    def can_stop(self) -> bool:
        capture = self.live.capture
        return bool(
            capture and not self.stopping and capture.snapshot().state != CaptureState.STOPPING
        )

    def prepare(self, target: WindowTarget, now: float, values: Preferences) -> CaptureWorker:
        if not self.windows.is_target(target):
            raise RuntimeError("The selected window closed. Refresh the window list.")
        self.rate, self.started_at = values.capture_rate, now
        self.ocr_choice = next(
            (c for c in self._choices if c.key == values.ocr_device), self._choices[0]
        )
        capture = self._create(target, self.rate, values.show_border)
        self.stop_message = "Capture source closed."
        self.stopping = False
        return capture

    def recognize_when_ready(self, ready: bool, *, closing: bool) -> None:
        capture = self.live.capture
        if (
            ready
            and not closing
            and not self.stopping
            and capture
            and not capture.finished
            and self.live.ocr is None
            and self.ocr_choice
        ):
            self.live.add_recognition(self.ocr_choice.create)

    def stop(self, message: str) -> None:
        self.stopping = self.live.capture is not None
        self.stop_message = message
        self.live.stop()

    def poll(self) -> CaptureStep:
        capture = self.live.capture
        if capture is None:
            return CaptureStep(CapturePhase.IDLE)
        snapshot = capture.snapshot()
        if capture.finished:
            return CaptureStep(CapturePhase.DRAINING, snapshot)
        if self.stopping or snapshot.state in (CaptureState.STOPPING, CaptureState.FAILED):
            if self.live.ocr:
                self.live.ocr.request_stop()
            return CaptureStep(CapturePhase.STOPPING, snapshot)
        geometry = self.windows.geometry(capture.target)
        foreground = self.windows.is_foreground(capture.target)
        phase = (
            CapturePhase.MINIMIZED
            if geometry.minimized
            else CapturePhase.ACTIVE
            if snapshot.frame is not None
            and snapshot.frame.geometry.client.size == geometry.client.size
            else CapturePhase.WAITING_FRAME
        )
        return CaptureStep(phase, snapshot, geometry, foreground)

    def drain(self, *, translation_drained: bool, snapshot: CaptureSnapshot) -> str:
        if not translation_drained:
            return "Waiting for the current translation operation to finish…"
        if not self.live.drain():
            return "Waiting for OCR and visual workers to finish…"
        return snapshot.message if snapshot.state == CaptureState.FAILED else self.stop_message
