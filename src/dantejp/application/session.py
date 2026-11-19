"""Headless application commands and ordered processing; desktop views only present results."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from dantejp.application.capture_lifecycle import CaptureLifecycle, CapturePhase, WindowAccess
from dantejp.application.cloud_services import CloudServices
from dantejp.application.live_session import CaptureWorker, LiveSession
from dantejp.application.model_inventory import ModelInventory
from dantejp.application.notice import NoticeInput, Notices, project_notices
from dantejp.application.preference_values import Preferences
from dantejp.application.preferences import PreferenceStore
from dantejp.application.presentation import (
    ocr_status,
    processing_progress,
    reset_scene,
    translation_status,
)
from dantejp.application.setup_coordinator import SetupCoordinator
from dantejp.application.shutdown import ShutdownCoordinator
from dantejp.application.translation_activity import TranslationMode
from dantejp.application.translation_coordinator import TranslationCoordinator
from dantejp.application.values import (
    ApplicationControls,
    ShutdownPhase,
    ShutdownSnapshot,
)
from dantejp.application.values import ApplicationView as ApplicationView
from dantejp.application.values import ModelConsent as ModelConsent
from dantejp.domain import (
    CapturedFrame,
    WindowTarget,
    overlay_ready,
)
from dantejp.languages.target import TARGET_LANGUAGES
from dantejp.ocr.values import OcrState
from dantejp.ocr.worker import OcrChoice
from dantejp.runtime.hardware_values import HardwareStatus
from dantejp.translation.cloud.values import CloudProfile
from dantejp.translation.dialogue.values import HistoryTurn
from dantejp.translation.selection import AssignmentChange, OcrOption
from dantejp.translation.values import TranslationState


class ApplicationSession:
    def __init__(
        self,
        *,
        windows: WindowAccess,
        live: LiveSession,
        translation: TranslationCoordinator,
        inventory: ModelInventory,
        cloud: CloudServices,
        setup: SetupCoordinator,
        preferences: PreferenceStore,
        shutdown: ShutdownCoordinator,
        ocr_choices: tuple[OcrChoice, ...],
        capture: Callable[[WindowTarget, int, bool], CaptureWorker],
        notify: Callable[[], None] = lambda: None,
        hardware: Callable[[], HardwareStatus | None] = lambda: None,
    ) -> None:
        self.windows, self.live, self.translation = windows, live, translation
        self.inventory, self.cloud, self.setup = inventory, cloud, setup
        self.preferences, self.shutdown = preferences, shutdown
        self._notify = notify
        self.capture = CaptureLifecycle(live, windows, ocr_choices, capture)
        self.ocr_options = tuple(OcrOption(c.name, c.key, c.capture_fps) for c in ocr_choices)
        self._hardware = hardware
        self.values = preferences.initial
        self.cloud.test_target = TARGET_LANGUAGES[self.values.output_language]
        self.view = ApplicationView()
        self.original = False
        self.raw_boxes = False
        self.debug = False
        self.destination = ""
        self.error = ""
        self.error_revision = 0
        self._consent: ModelConsent | None = None
        self._consent_serial = 0
        self._inventory_revision = -1
        self._cloud_revision: tuple[tuple[CloudProfile, ...], frozenset[str], int] | None = None
        self._advancing = self._again = False
        self._first_run_requested = False
        self.refresh_routes()

    def configure(self, values: Preferences) -> None:
        # Assignment/preparation and setup intent have authoritative owners. A view
        # submits appearance/device preferences, not a stale copy of those decisions.
        if values.output_language not in TARGET_LANGUAGES:
            raise ValueError(f"Unknown output language: {values.output_language}")
        prior = self.values
        self.values = replace(
            values,
            model=prior.model,
            setup_seen=prior.setup_seen,
            setup_model=prior.setup_model,
            short_model=self.translation.plan.short
            if self.translation.restored
            else prior.short_model,
            long_model=self.translation.plan.long
            if self.translation.restored
            else prior.long_model,
            translate_short=self.translation.plan.short_enabled
            if self.translation.restored
            else prior.translate_short,
            translate_long=self.translation.plan.long_enabled
            if self.translation.restored
            else prior.translate_long,
        )
        if prior.output_language != values.output_language:
            self.cloud.test_target = TARGET_LANGUAGES[values.output_language]
            if worker := self.translation.lifecycle.publication:
                worker.invalidate()
            self.clear_english(force=True)
        if prior.group_dialogue != values.group_dialogue:
            self.live.change_grouping(self.translation.lifecycle.publication)
            self.clear_english()
        if prior.show_border != values.show_border and self.live.capture:
            self.live.capture.set_border(values.show_border)
        if (prior.game_hint, prior.game_from_window) != (values.game_hint, values.game_from_window):
            self.translation.set_game(
                automatic=values.game_from_window,
                manual=values.game_hint,
                title=self.translation.window_title,
            )
            self.refresh_routes()
        self.translation.configure_history(
            self.live, enabled=values.history_enabled, reference=values.history_model
        )
        self.persist()

    def persist(self) -> None:
        if not self.translation.restored:
            # A gesture before background discovery completes must not erase saved IDs.
            self.preferences.save(self.values)
            return
        plan = self.translation.plan
        self.values = replace(
            self.values,
            short_model=plan.short,
            long_model=plan.long,
            translate_short=plan.short_enabled,
            translate_long=plan.long_enabled,
        )
        self.preferences.save(self.values)

    def remember_model(self) -> None:
        choice = self.translation.lifecycle.snapshot().selected
        key = choice.preference_key if choice else "none"
        if key != self.values.model:
            self.values = replace(self.values, model=key)
            self.persist()

    def set_window_title(self, title: str) -> None:
        self.translation.set_game(
            automatic=self.values.game_from_window, manual=self.values.game_hint, title=title
        )
        self.refresh_routes()

    def refresh_routes(self, *, preserve_prepared: bool = False) -> None:
        if self.translation.refresh_route(preserve_prepared=preserve_prepared):
            self.clear_english()
        self.translation.configure_history(
            self.live, enabled=self.values.history_enabled, reference=self.values.history_model
        )

    def assign(self, change: AssignmentChange) -> ModelConsent | None:
        if (
            self.shutdown.active
            or not self.translation.restored
            or self.translation.lifecycle.snapshot().preparing
            or self.setup.probing
            or self._consent
        ):
            return None
        option = next(
            (c for c in self.translation.options() if c.reference == change.reference), None
        )
        if change.plan == self.translation.plan and (option is None or option.prepared):
            return None
        if option and option.unavailable_reason:
            self.destination = "models" if option.key.startswith("imported-") else "runtime"
            return None
        if not self.translation.assign(change):
            assert option is not None
            self._consent_serial += 1
            self._consent = ModelConsent(self._consent_serial, option)
            return self._consent
        self.refresh_routes()
        if not change.plan.short and not change.plan.long:
            self.remember_model()
        self.persist()
        return None

    def consent(self, token: int, accepted: bool) -> None:
        if self._consent is None or token != self._consent.token or self.shutdown.active:
            return
        self._consent = None
        self.translation.lifecycle.consent(accepted)
        if accepted:
            self.clear_english()
        else:
            self.refresh_routes()
        self.persist()

    def clear_english(self, *, force: bool = False) -> None:
        self.live.clear_english()
        if not (force or self.view.english or self.view.results):
            return
        self.view = replace(
            self.view, blocks=(), english=(), results=(), english_reset=self.view.english_reset + 1
        )

    def _reset_scene(self, *, invalidate: bool = False) -> None:
        if invalidate:
            self.live.invalidate(self.translation.lifecycle.publication)
        else:
            self.live.reset(self.translation.lifecycle.publication)
        self.view = reset_scene(self.view)

    def start_capture(self, target: WindowTarget, now: float) -> bool:
        if self.shutdown.active or self.live.capture:
            return False
        try:
            capture = self.capture.prepare(target, now, self.values)
        except (OSError, RuntimeError) as error:
            self.view = replace(self.view, status=str(error))
            return False
        inventory = self.inventory.snapshot()
        choice = self.capture.ocr_choice
        recognizer = (
            choice.create if choice and inventory.loaded and inventory.data.ocr_ready else None
        )
        self._reset_scene()
        self.view = replace(self.view, status="Starting capture…")
        self.set_window_title(target.title)
        self.live.start(capture, recognizer)
        return True

    def stop(self, message: str = "Capture stopped.") -> None:
        self.original = False
        self.translation.lifecycle.stop_capture(closing=self.shutdown.active)
        self._reset_scene()
        self.capture.stop(message)
        if self.live.capture:
            self.view = replace(self.view, status="Stopping capture, OCR and translation…")

    def refresh_models(self) -> None:
        if not self.shutdown.active:
            self.inventory.invalidate()

    def offer_first_run(self) -> None:
        self._first_run_requested = True

    def setup_skipped(self) -> None:
        self.values = replace(self.values, setup_seen=True)
        self._first_run_requested = False
        self.persist()
        self.refresh_models()

    def setup_completed(self, model: str, target: Path | None) -> None:
        self.values = replace(self.values, setup_seen=True, setup_model=model)
        self.persist()
        self.refresh_models()
        if target:
            self.request_close(target)
        else:
            self._first_run_requested = True

    def _first_run(self) -> None:
        if (
            not self._first_run_requested
            or not self.inventory.snapshot().loaded
            or self.shutdown.active
        ):
            return
        if self.values.setup_model:
            key = "local:" + self.values.setup_model
            if self.translation.resolve(key) is None:
                # Setup can finish before its asynchronous inventory refresh. Keep the
                # persisted intent and retry after discovery, including transient failures.
                return
            self.values = replace(self.values, setup_model="")
            self.persist()
            self.destination = "select:" + key
        elif not self.values.setup_seen:
            if self.inventory.snapshot().data.ocr_ready and any(
                f.present for f in self.setup.files if f.key != "ocr"
            ):
                self.setup_skipped()
            else:
                self.destination = "guide"
        self._first_run_requested = False

    def request_close(self, target: Path | None = None) -> None:
        self.original = False
        self._consent = None
        self.cloud.close()
        self.shutdown.request(target)

    @property
    def controls(self) -> ApplicationControls:
        capture = self.live.capture
        model = self.translation.lifecycle.snapshot()
        return ApplicationControls(
            self.translation.options(),
            self.translation.plan,
            model.preparing,
            model.message if model.preparing else "",
            capture is not None,
            self.capture.can_stop,
            self.capture.started_at,
            self.capture.rate,
        )

    @property
    def closing(self) -> bool:
        return self.shutdown.active

    @property
    def close_status(self) -> ShutdownSnapshot:
        return self.shutdown.snapshot()

    @property
    def history_turns(self) -> tuple[HistoryTurn, ...]:
        return self.live.history.turns

    @property
    def history_status(self) -> str:
        return self.live.history_status

    def clear_history(self) -> None:
        self.live.history.clear()

    def take_destination(self) -> str:
        destination, self.destination = self.destination, ""
        return destination

    def show_original(self, held: bool, *, modal: bool = False) -> bool:
        capture = self.live.capture
        self.original = bool(
            held
            and not modal
            and not self.closing
            and capture is not None
            and not capture.finished
            and self.windows.is_foreground(capture.target)
        )
        return self.original

    def foreground_target(self) -> WindowTarget | None:
        if self.closing or self.live.capture:
            return None
        try:
            target = self.windows.foreground_target()
            if not self.windows.is_foreground(target):
                raise RuntimeError("Focus changed. Press the capture hotkey again.")
            return target
        except (OSError, RuntimeError) as error:
            self.view = replace(self.view, status=str(error))
            return None

    def set_diagnostics(self, *, boxes: bool, debug: bool) -> None:
        self.raw_boxes, self.debug = boxes, debug

    @property
    def can_setup(self) -> bool:
        return not (
            self.shutdown.active
            or not self.inventory.snapshot().loaded
            or self.live.capture
            or self.setup.busy
            or self.cloud.busy
            or self.translation.lifecycle.snapshot().preparing
        )

    def notices(self) -> Notices:
        ocr = self.live.ocr.snapshot() if self.live.ocr else None
        model = self.translation.lifecycle.snapshot()
        translation = model.worker
        return project_notices(
            NoticeInput(
                self.translation.options(),
                self.translation.plan,
                self.inventory.snapshot().data.ocr_ready,
                self.preferences.error,
                self.setup.problem
                or self.cloud.snapshot().problem
                or self.inventory.snapshot().problem,
                self.setup.busy or self.cloud.busy,
                model.preparing,
                str(ocr.state) if ocr else "",
                self.view.ocr_status,
                str(translation.state) if translation else "",
                self.view.translation_status,
                bool(translation and translation.rejected),
                self._hardware(),
                self.capture.ocr_choice.key
                if self.live.capture and self.capture.ocr_choice
                else self.values.ocr_device,
                self.values.ocr_device,
                ocr.provider if ocr else "",
                ocr.message if ocr else "",
                self.live.capture is not None,
            )
        )

    def _advance_preparation(self) -> None:
        if not self.translation.lifecycle.snapshot().preparing:
            return
        outcome = self.translation.lifecycle.advance_preparation(closing=self.shutdown.active)
        if outcome is None:
            return
        if outcome.committed:
            self.remember_model()
        elif outcome.error:
            self.error, self.error_revision = outcome.error, self.error_revision + 1
            self.view = replace(
                self.view, translation_status=f"Preparation failed: {outcome.error}"
            )
        if not self.shutdown.active:
            self.refresh_routes(preserve_prepared=outcome.committed)
            self.persist()

    def _translate(self, running: bool, *, now: float) -> None:
        activity = self.translation.advance_activity(
            running=running,
            enabled=self.values.translation,
            probing=self.setup.probing,
        )
        history_ready = self.live.suspend_history(self.setup.probing)
        if activity.probe_ready and history_ready:
            self.setup.permit_probe()
        if activity.clears_english:
            self.clear_english()
        if activity.mode == TranslationMode.SWITCHING:
            self.view = replace(
                self.view,
                translation_mode=activity.mode,
                translation_status=translation_status(activity, None, now),
            )
            return
        snapshot = activity.snapshot
        if activity.worker is not None:
            scene = self.view.scene
            published = self.live.publish(
                activity.worker,
                scene.requests,
                scene.blocks,
                target=TARGET_LANGUAGES[self.values.output_language],
            )
            snapshot = published.snapshot
            self.view = replace(
                self.view,
                blocks=published.blocks,
                english=published.translations,
                results=snapshot.results,
            )
        if (
            activity.mode in (TranslationMode.ACTIVE, TranslationMode.STANDBY)
            and snapshot
            and snapshot.state == TranslationState.READY
        ):
            self.remember_model()
        self.view = replace(
            self.view,
            translation=snapshot
            if activity.mode not in (TranslationMode.PROBING, TranslationMode.PREPARING)
            else self.view.translation,
            translation_status=translation_status(activity, snapshot, now),
            translation_mode=activity.mode,
        )

    def _update_ocr(self, frame: CapturedFrame, now: float) -> None:
        if self.live.ocr is None:
            self.view = replace(
                self.view,
                frame=frame,
                ocr_status="Capture only. Open Settings and download MeikiOCR to recognize text.",
            )
            return
        snapshot = self.live.reconcile(frame, now)
        assert snapshot is not None
        if snapshot.state == OcrState.FAILED:
            self._reset_scene()
        self.view = replace(
            self.view,
            ocr=snapshot,
            ocr_status=ocr_status(snapshot, self.live.visual_state.message, now),
            frame=frame,
            observation=self.live.accepted,
            assignments=self.live.assignments,
        )

    def advance(self, now: float) -> ApplicationView:
        if self._advancing:
            self._again = True
            return self.view
        self._advancing = True
        try:
            self._advance(now)
            self.view = replace(
                self.view,
                capture=self.live.capture.snapshot() if self.live.capture else None,
                visual=self.live.visual_state,
            )
            self.view = replace(
                self.view,
                progress=processing_progress(
                    self.view, translation_enabled=self.values.translation
                ),
            )
            return self.view
        finally:
            self._advancing = False
            if self._again:
                self._again = False
                self._notify()

    def _advance(self, now: float) -> None:
        self.setup.advance()
        self.inventory.advance(now)
        self.cloud.advance()
        inventory = self.inventory.snapshot()
        cloud = self.cloud.snapshot()
        cloud_key = (cloud.profiles, cloud.available, cloud.revision)
        if inventory.revision != self._inventory_revision or cloud_key != self._cloud_revision:
            self._inventory_revision, self._cloud_revision = inventory.revision, cloud_key
            self.refresh_routes()
            self.capture.recognize_when_ready(
                inventory.loaded and inventory.data.ocr_ready,
                closing=self.shutdown.active,
            )
        if self.shutdown.active:
            self.shutdown.advance()
            if self.shutdown.snapshot().phase == ShutdownPhase.FAILED:
                self.inventory.resume()
                self.setup.resume()
                self.cloud.resume()
            return
        self._first_run()
        self._advance_preparation()
        try:
            self._advance_capture(now)
        except (OSError, RuntimeError) as error:
            self.stop(str(error))

    def _advance_capture(self, now: float) -> None:
        step = self.capture.poll()
        if step.phase == CapturePhase.IDLE:
            self.view = replace(self.view, overlay_bounds=None)
            self._translate(False, now=now)
            return
        if step.phase in (CapturePhase.STOPPING, CapturePhase.DRAINING):
            self._reset_scene()
            self._translate(False, now=now)
            if step.phase == CapturePhase.DRAINING:
                assert step.snapshot is not None
                message = self.capture.drain(
                    translation_drained=self.translation.lifecycle.capture_drained,
                    snapshot=step.snapshot,
                )
                self.view = replace(
                    self.view,
                    status=message,
                    ocr_status="OCR stopped. Start capture to load the local models again."
                    if self.live.capture is None
                    else self.view.ocr_status,
                )
            return
        assert step.snapshot is not None and step.geometry is not None
        snapshot, geometry, foreground = step.snapshot, step.geometry, step.foreground
        frame = snapshot.frame
        if step.phase == CapturePhase.ACTIVE:
            assert frame is not None
            if self.live.accept_size(geometry.client.size, self.translation.lifecycle.publication):
                self.view = replace(
                    self.view,
                    observation=None,
                    frame=None,
                    reset=self.view.reset + 1,
                )
            self._update_ocr(frame, now)
            message = (
                "Capturing. The overlay appears on the selected window when ready."
                if foreground and self.values.show_overlay
                else "Capturing. Switch to the selected window to see the overlay."
                if self.values.show_overlay
                else "Capturing. Game overlay is hidden."
            )
        else:
            self._reset_scene(invalidate=True)
            message = (
                "Window minimized. Restore it to resume."
                if step.phase == CapturePhase.MINIMIZED
                else "Waiting for a frame matching the window size…"
            )
        scene = self.live.scene(
            frame,
            now,
            grouping=self.values.group_dialogue,
            stabilize=self.values.stabilize or self.values.translation,
        )
        self.view = replace(self.view, scene=scene, status=message)
        if not self.values.translation:
            self.view = replace(self.view, blocks=scene.blocks)
        self._translate(True, now=now)
        bounds = (
            geometry.client
            if (
                self.values.show_overlay
                and not self.original
                and (self.values.translation or self.raw_boxes or self.debug)
                and (scene.tracks or self.debug)
                and frame is not None
                and overlay_ready(snapshot, geometry, foreground)
            )
            else None
        )
        self.view = replace(self.view, overlay_bounds=bounds)
