"""Window picker, clean capture preview, and session coordination on the Qt thread."""

import logging
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.capture import CaptureSession
from jp_overlay.controls import InfoButton, StatusBanner, Switch
from jp_overlay.diagnostics import debug_display
from jp_overlay.domain import CapturedFrame, CaptureState, WindowTarget, overlay_ready
from jp_overlay.grouping import DialogueGrouper, TextBlock
from jp_overlay.hardware import HardwareCheck
from jp_overlay.hotkeys import HotkeyAction, Hotkeys
from jp_overlay.inspection import OcrInspector
from jp_overlay.model_manager import ModelManager
from jp_overlay.model_store import ModelBundle, is_prepared, mark_prepared
from jp_overlay.overlay import OverlayWindow
from jp_overlay.preferences import PreferenceStore
from jp_overlay.presentation import EnglishPresentation
from jp_overlay.recognition import (
    OcrChoice,
    OcrResult,
    OcrSession,
    OcrState,
    Recognizer,
    overlay_result_ready,
)
from jp_overlay.runtime_dialog import RuntimeSetupDialog
from jp_overlay.runtime_restart import RuntimeRestart
from jp_overlay.runtime_setup import project_root
from jp_overlay.settings_window import SettingsWindow
from jp_overlay.setup_status import SetupAdvice, acceleration_advice
from jp_overlay.theme import STYLE
from jp_overlay.tracking import TextTrack, TextTracker
from jp_overlay.translation import BackendChoice, TranslationSession, TranslationState
from jp_overlay.visual import VisualSession, VisualState
from jp_overlay.windows import Windows, WindowUnavailable

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Coordinate one capture session. Slow operations remain owned by the service."""

    def __init__(
        self,
        windows: Windows,
        recognizer_factory: Callable[[], Recognizer],
        backends: tuple[BackendChoice, ...] = (),
        *,
        cache_path: Path | None = None,
        ocr_backends: tuple[OcrChoice, ...] = (),
        models: tuple[ModelBundle, ...] = (),
        backend_provider: Callable[[], tuple[BackendChoice, ...]] | None = None,
        preferences_path: Path | None = None,
        hardware: HardwareCheck | None = None,
        hotkeys: Hotkeys | None = None,
    ) -> None:
        super().__init__()
        self._windows = windows
        self._hardware = hardware
        self._hotkeys = hotkeys
        self._notice_destination = "models"
        self._acceleration_advice = SetupAdvice()
        self._session: CaptureSession | None = None
        self._ocr: OcrSession | None = None
        self._visual: VisualSession | None = None
        self._visual_state = VisualState()
        self._translation: TranslationSession | None = None
        self._backends = backends
        self._models, self._backend_provider = models, backend_provider
        self._model_manager: ModelManager | None = None
        self._runtime_dialog: RuntimeSetupDialog | None = None
        self._preferences = PreferenceStore(preferences_path)
        self._saved_model = self._preferences.initial.model
        self._accepted_ocr: OcrResult | None = None
        self._capture_ocr_choice: OcrChoice | None = None
        self._compact_size = QSize(720, 430)
        self._restart_target: Path | None = None
        self._restart: RuntimeRestart | None = None
        self._selected_backend: BackendChoice | None = None
        self._preparing: BackendChoice | None = None
        self._preparation_started = False
        self._previous_backend: BackendChoice | None = None
        self._standby = False
        self._progress_dialog: QProgressDialog | None = None
        self._context_reset_sequence = 0
        self._prepared_this_run: set[str] = set()
        self._cache_path = (
            cache_path or Path(__file__).resolve().parents[2] / "data/translations.sqlite3"
        )
        self._recognizer_factory = recognizer_factory
        self._ocr_backends = ocr_backends or (OcrChoice("CPU", recognizer_factory),)
        self._valid_size: tuple[int, int] | None = None
        self._tracker = TextTracker()
        self._grouper = DialogueGrouper()
        self._presentation = EnglishPresentation()
        self._track_ids: tuple[int | None, ...] = ()
        self._overlay = OverlayWindow(windows)
        self._overlay.set_tracks(())
        self._last_sequence = 0
        self._closing = False
        self._showing_original = False
        self._started_at = 0.0
        self._stopping_message = "Capture stopped."
        self._demo_processes: list[subprocess.Popen[bytes]] = []
        self.setWindowTitle("JP Overlay")
        self.resize(self._compact_size)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.refresh_windows()
        if self._hotkeys:
            self._hotkeys.activated = self._hotkey_activated
            self._hotkeys.hold_changed = self._original_changed
        self._settings.hotkeys.activate()
        self._update_notice()

    def _build_ui(self) -> None:
        preferences = self._preferences.initial
        self._settings = SettingsWindow(
            preferences, self._ocr_backends, self._models, self, hotkeys=self._hotkeys
        )
        self._model_manager = self._settings.models
        self._model_manager.models_changed.connect(self._refresh_models)
        self._settings.restart_requested.connect(self._request_restart)
        self._settings.runtime_created.connect(self._runtime_created)
        self._settings.model_notice.action.clicked.connect(self._choose_or_download_model)
        self._settings.acceleration_notice.action.clicked.connect(self._show_acceleration_advice)
        # Session coordination uses the same controls owned by the Settings window.
        self.stabilize_check = self._settings.stabilize
        self.ocr_device = self._settings.ocr_device
        self.capture_rate = self._settings.capture_rate
        self.group_dialogue = self._settings.group_dialogue
        self.automatic_font = self._settings.automatic_size
        self.font_size = self._settings.text_size
        self.group_dialogue.toggled.connect(self._grouping_changed)
        self.automatic_font.toggled.connect(self._font_style_changed)
        self.font_size.valueChanged.connect(self._font_style_changed)
        self._settings.opacity.valueChanged.connect(self._overlay.set_opacity)
        central = QWidget()
        self.setCentralWidget(central)
        body = QVBoxLayout(central)
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(14)
        self.control_panel = QWidget()
        self.control_panel.setMaximumWidth(760)
        self.control_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        controls_row = QHBoxLayout()
        controls_row.addWidget(self.control_panel, 1)
        controls_row.addStretch()
        body.addLayout(controls_row)
        layout = QVBoxLayout(self.control_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QVBoxLayout()
        heading = QLabel("JP Overlay")
        heading.setObjectName("heading")
        title.addWidget(heading)
        subtitle = QLabel("Japanese → English · Local")
        subtitle.setObjectName("muted")
        title.addWidget(subtitle)
        header.addLayout(title, 1)
        self.settings_button = QPushButton("Settings…")
        self.settings_button.clicked.connect(self._show_settings)
        header.addWidget(self.settings_button)
        layout.addLayout(header)
        layout.addWidget(QLabel("Game window"))
        selection = QHBoxLayout()
        self.windows_combo = QComboBox()
        self.windows_combo.setAccessibleName("Game window")
        self.windows_combo.setMinimumContentsLength(16)
        self.windows_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_windows)
        selection.addWidget(self.windows_combo, 1)
        selection.addWidget(self.refresh_button)
        layout.addLayout(selection)
        self.start_button = QPushButton("Start capture")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._toggle_capture)
        layout.addWidget(self.start_button)
        overlays = QHBoxLayout()
        self.overlay_check = Switch("Show game overlay")
        self.overlay_check.setChecked(preferences.show_overlay)
        self.overlay_check.setToolTip(
            "Show or hide game rendering. Capture and translation keep their state."
        )
        self.translate_check = Switch("Translation overlay")
        self.translate_check.setChecked(preferences.translation)
        self.translate_check.setToolTip(
            "Translate and cover recognized text. Turn off to leave the original game text visible."
        )
        overlays.addWidget(self.overlay_check)
        overlays.addSpacing(24)
        overlays.addWidget(self.translate_check)
        overlays.addStretch()
        layout.addLayout(overlays)
        label = QHBoxLayout()
        label.addWidget(QLabel("Translation model"))
        label.addWidget(
            InfoButton(
                "Translation model",
                "Choose a downloaded local translator. Sugoi is compact and CPU friendly; "
                "Gemma uses a supported GPU and requires preparation. "
                "Switching unloads the previous model.",
            )
        )
        label.addStretch()
        layout.addLayout(label)
        self.backend_combo = QComboBox()
        self.backend_combo.setAccessibleName("Translation model")
        self.backend_combo.setMinimumContentsLength(20)
        self.backend_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.backend_combo.setToolTip(
            "Download models and install acceleration in Settings → Models & runtime."
        )
        for backend in self._backends:
            self.backend_combo.addItem(backend.name, backend)
        self.backend_combo.addItem("No translation", None)
        initial = next((b for b in self._backends if self._model_key(b) == preferences.model), None)
        if preferences.model == "auto" and self._backends:
            initial = self._backends[0]
        if initial and not self._model_prepared(initial):
            initial = None
        self._select_backend(initial)
        self._selected_backend = initial
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        layout.addWidget(self.backend_combo)
        self.onboarding = StatusBanner()
        self.notice = self.onboarding.label
        self.models_button = self.onboarding.action
        self.models_button.clicked.connect(self._show_setup_status)
        layout.addWidget(self.onboarding)
        self.acceleration_notice = StatusBanner()
        self.acceleration_notice.action.clicked.connect(self._show_acceleration_advice)
        layout.addWidget(self.acceleration_notice)
        self.hotkey_notice = StatusBanner()
        self.hotkey_notice.action.clicked.connect(self._settings.show_hotkeys)
        layout.addWidget(self.hotkey_notice)
        self.advanced = QToolButton()
        self.advanced.setText("Advanced")
        self.advanced.setCheckable(True)
        self.advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.advanced)
        self.advanced_panel = QWidget()
        inspection = QVBoxLayout(self.advanced_panel)
        inspection.setContentsMargins(0, 0, 0, 0)
        diagnostics = QHBoxLayout()
        self.raw_boxes_check = Switch("Show OCR boxes")
        self.raw_boxes_check.setToolTip(
            "Numbered OCR boxes on the game. Turn Translation overlay off to compare them."
        )
        self.raw_boxes_check.setEnabled(not self.translate_check.isChecked())
        self.debug_check = Switch("Debug overlay")
        self.debug_check.setToolTip(
            "Amber: visual changes. Cyan: completed OCR coverage. "
            "Timings and diagnostics do not change processing."
        )
        diagnostics.addWidget(self.raw_boxes_check)
        diagnostics.addWidget(self.debug_check)
        diagnostics.addStretch()
        self.demo_button = QPushButton("Open demo window")
        self.demo_button.clicked.connect(self._open_demo)
        diagnostics.addWidget(self.demo_button)
        inspection.addLayout(diagnostics)
        label = QLabel("RAW FRAME + DETECTED TEXT · PERSISTENT IDS")
        label.setObjectName("eyebrow")
        inspection.addWidget(label)
        self.inspector = OcrInspector()
        self.inspector.set_active(False)
        inspection.addWidget(self.inspector, 1)
        self.ocr_status = QLabel("OCR starts with capture. Models stay on this PC.")
        self.translation_status = QLabel("Translation starts with capture.")
        self.metrics = QLabel("Window capture · all processing local")
        self.metrics.setObjectName("muted")
        for value in (self.ocr_status, self.translation_status, self.metrics):
            value.setWordWrap(True)
            inspection.addWidget(value)
        note = QLabel(
            "Preview shows raw OCR. Hover English cells to review their source. "
            "Pause freezes only the inspector; capture and translation continue."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        inspection.addWidget(note)
        self.advanced_panel.hide()
        body.addWidget(self.advanced_panel, 1)
        self._compact_space = QWidget()
        body.addWidget(self._compact_space, 1)
        self.status = QLabel("Select a window, then start capture.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.advanced.toggled.connect(self._advanced_changed)
        self.overlay_check.toggled.connect(self._settings_changed)
        self.translate_check.toggled.connect(self._settings_changed)
        self.translate_check.toggled.connect(self.raw_boxes_check.setDisabled)
        self.raw_boxes_check.toggled.connect(self._tick)
        self.debug_check.toggled.connect(self._tick)
        self._settings.changed.connect(self._settings_changed)
        self.setStyleSheet(STYLE)
        self._overlay.set_opacity(preferences.opacity)
        self._font_style_changed()
        self._update_notice()

    @staticmethod
    def _model_key(choice: BackendChoice | None) -> str:
        return (
            "gemma"
            if choice and choice.key.startswith("gemma")
            else choice.key
            if choice
            else "none"
        )

    def _remember_model(self) -> None:
        key = self._model_key(self._selected_backend)
        if key != self._saved_model:
            self._saved_model = key
            self._save_preferences()

    def _save_preferences(self) -> None:
        self._preferences.save(
            self._settings.values(
                show_overlay=self.overlay_check.isChecked(),
                translation=self.translate_check.isChecked(),
                model=self._saved_model,
            )
        )

    def _settings_changed(self) -> None:
        self._save_preferences()
        self._tick()

    def _show_settings(self) -> None:
        if not self._closing:
            self._settings.show()
            self._settings.raise_()

    def _hotkey_activated(self, action: HotkeyAction) -> None:
        if self._closing or QApplication.activeModalWidget() is not None:
            return
        if action == HotkeyAction.OVERLAY:
            self.overlay_check.setChecked(not self.overlay_check.isChecked())
        elif action == HotkeyAction.CAPTURE:
            if self._session is None and self._settings.hotkeys.capture_focused.isChecked():
                try:
                    target = self._windows.foreground_target()
                    # Resolve only on this explicit hotkey action; do not follow focus continuously.
                    if not self._windows.is_foreground(target):
                        raise WindowUnavailable("Focus changed. Press the capture hotkey again.")
                except (WindowUnavailable, OSError) as error:
                    self.status.setText(str(error))
                    return
                index = -1
                for i in range(self.windows_combo.count()):
                    candidate = self.windows_combo.itemData(i)
                    if isinstance(candidate, WindowTarget) and (
                        candidate.hwnd,
                        candidate.process_id,
                    ) == (target.hwnd, target.process_id):
                        index = i
                        break
                label = f"{target.title} · PID {target.process_id}"
                if index == -1:
                    self.windows_combo.addItem(label, target)
                    index = self.windows_combo.count() - 1
                else:
                    self.windows_combo.setItemText(index, label)
                    self.windows_combo.setItemData(index, target)
                self.windows_combo.setCurrentIndex(index)
                self.start_button.setEnabled(True)
            # Use the button's existing lifecycle guard, including asynchronous stop/drain.
            self.start_button.click()

    def _original_changed(self, held: bool) -> None:
        if held and (
            self._closing
            or self._session is None
            or self._session.finished
            or QApplication.activeModalWidget() is not None
            or not self._windows.is_foreground(self._session.target)
        ):
            return
        if self._showing_original == held:
            return
        self._showing_original = held
        if held:
            self._overlay.hide()
        elif not self._closing:
            self._tick()  # Restore current valid English immediately, without touching workers.

    def _cancel_original(self) -> None:
        # Clear before notifying the service, so stop/close cannot re-enter rendering.
        self._showing_original = False
        if self._hotkeys:
            self._hotkeys.end_hold()

    def _advanced_changed(self, expanded: bool) -> None:
        maximized = self.isMaximized() or self.isFullScreen()
        if expanded and not maximized:
            self._compact_size = self.size()
        self.advanced.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.advanced_panel.setVisible(expanded)
        self._compact_space.setVisible(not expanded)
        self.inspector.set_active(expanded)
        # Recompute minimum sizes before restoring the compact geometry.
        if (central := self.centralWidget()) and (layout := central.layout()):
            layout.activate()
        if layout := self.layout():
            layout.activate()
        if maximized:
            return
        if expanded:
            screen = self.screen()
            area = screen.availableGeometry() if screen else self.geometry()
            self.resize(min(1100, area.width() - 40), min(840, area.height() - 80))
        else:
            self.resize(self._compact_size)

    def _show_setup_status(self) -> None:
        if self._notice_destination == "selection":
            self.backend_combo.setFocus()
            self.backend_combo.showPopup()
        elif self._notice_destination == "settings":
            self._show_settings()
        elif self._notice_destination == "runtime" or (
            self._settings.runtime
            and (self._settings.runtime.operation or self._settings.runtime.error_message)
        ):
            self._manage_runtime()
        else:
            self._manage_models()

    def _show_acceleration_advice(self) -> None:
        if self._acceleration_advice.destination == "recognition":
            self._settings.show_recognition()
        else:
            self._manage_runtime()

    def _choose_or_download_model(self) -> None:
        if self._ocr_models_ready() and self._backends and self._selected_backend is None:
            self._settings.hide()
            self.raise_()
            self.backend_combo.setFocus()
            self.backend_combo.showPopup()
        else:
            self._manage_models()

    def _update_notice(self) -> None:
        self.hotkey_notice.set_message(self._settings.hotkeys.problem, action="Hotkeys")
        if self._hotkeys:
            capture_key = self._hotkeys.shortcut(HotkeyAction.CAPTURE) or "disabled"
            overlay_key = self._hotkeys.shortcut(HotkeyAction.OVERLAY) or "disabled"
            source = (
                "focused window"
                if self._settings.hotkeys.capture_focused.isChecked()
                else "selected window"
            )
            self.start_button.setToolTip(
                "Button: start / stop the selected window. "
                f"Hotkey {capture_key}: start the {source}, or stop the current capture."
            )
            self.overlay_check.setToolTip(
                "Show or hide game rendering. Capture and translation keep their state. "
                f"Hotkey: {overlay_key}"
            )
        message = ""
        action = "Open settings"
        tone = "warning"
        self._notice_destination = "models"
        missing = []
        ocr_ready = self._ocr_models_ready()
        if not ocr_ready:
            missing.append("MeikiOCR is not downloaded")
        if not self._backends:
            missing.append("No translation model is downloaded")
        elif self._selected_backend is None and not self._preparing:
            missing.append("No translation model is selected")
        model_warning = ". ".join(missing)
        if model_warning:
            model_warning += ". Capture can continue, but translation needs setup."
        self._settings.model_notice.set_message(
            model_warning,
            action="Choose model" if ocr_ready and self._backends else "Models",
        )
        self._settings.save_note.setText(
            "Settings could not be saved. Changes still apply to this session. "
            + self._preferences.error
            if self._preferences.error
            else "Changes save automatically; apply hotkeys to save. Downloads require your action."
        )
        if self._preferences.error:
            message = self._preferences.error
            tone, self._notice_destination = "error", "settings"
        elif self._settings.problem:
            message = "Setup needs attention: " + self._settings.problem
            tone = "error"
        elif self._settings.busy:
            message = "Setup is running in the background. Open Settings for progress."
            action, tone = "View setup", "info"
        elif not ocr_ready or not self._backends:
            message, action = model_warning, "Download models"
        elif self._preparing:
            message = "Preparing the translation model. Capture can continue."
            action, tone = "", "info"
        elif self._ocr and self._ocr.snapshot().state in (OcrState.FAILED, OcrState.LOADING):
            message = self.ocr_status.text()
            tone = "error" if self._ocr.snapshot().state == OcrState.FAILED else "info"
            action = ""
        elif self._translation and self._translation.snapshot().state in (
            TranslationState.FAILED,
            TranslationState.LOADING,
        ):
            message = self.translation_status.text()
            tone = (
                "error" if self._translation.snapshot().state == TranslationState.FAILED else "info"
            )
            action = ""
        elif self._selected_backend is None:
            message = model_warning
            action, self._notice_destination = "Choose model", "selection"
        self.onboarding.set_message(message, tone=tone, action=action)
        choice = self._capture_ocr_choice if self._session else self.ocr_device.currentData()
        ocr = self._ocr.snapshot() if self._ocr else None
        self._acceleration_advice = acceleration_advice(
            self._hardware.snapshot() if self._hardware else None,
            choice.key if isinstance(choice, OcrChoice) else "cpu",
            actual_provider=ocr.provider if ocr else "",
            fallback=ocr.message if ocr else "",
        )
        pending = self.ocr_device.currentData()
        if (
            self._session
            and self._acceleration_advice.destination == "recognition"
            and isinstance(pending, OcrChoice)
            and pending != choice
        ):
            self._acceleration_advice = SetupAdvice(
                "CPU OCR is still active. Your new OCR device applies after restarting capture.",
                "recognition",
                "OCR settings",
            )
        for banner in (self.acceleration_notice, self._settings.acceleration_notice):
            banner.set_message(
                self._acceleration_advice.message, action=self._acceleration_advice.action
            )

    def refresh_windows(self) -> None:
        if self._session:
            return
        current = self.windows_combo.currentData()
        self.windows_combo.clear()
        try:
            targets = self._windows.list_targets()
            for target in targets:
                label = f"{target.title}  ·  PID {target.process_id}"
                if (
                    sum(
                        item.title == target.title and item.process_id == target.process_id
                        for item in targets
                    )
                    > 1
                ):
                    label += f"  ·  HWND {target.hwnd:#x}"
                self.windows_combo.addItem(label, target)
                if isinstance(current, WindowTarget) and current.hwnd == target.hwnd:
                    self.windows_combo.setCurrentIndex(self.windows_combo.count() - 1)
            self.start_button.setEnabled(bool(targets))
            if not targets:
                self.status.setText("No windows found. Open a game or the demo, then refresh.")
        except OSError as error:
            self.status.setText(f"Could not list windows: {error}")
            self.start_button.setEnabled(False)

    def _toggle_capture(self) -> None:
        if self._closing or not self.start_button.isEnabled():
            return
        if self._session:
            self._stop("Capture stopped.")
            return
        target = self.windows_combo.currentData()
        if not isinstance(target, WindowTarget):
            return
        if not self._windows.is_target(target):
            self.status.setText("The selected game window closed. Refresh and select it again.")
            return
        self._session = CaptureSession(target, self._windows, fps=self.capture_rate.value())
        choice = self.ocr_device.currentData()
        self._capture_ocr_choice = choice if isinstance(choice, OcrChoice) else None
        if self._ocr_models_ready():
            self._ocr = OcrSession(
                choice.create if isinstance(choice, OcrChoice) else self._recognizer_factory,
                require_ack=True,
            )
            self._visual = VisualSession()
        self._settings.set_capture_active(True)
        self._stopping_message = "The capture source closed. Select a window to restart."
        self._last_sequence = 0
        self._started_at = time.monotonic()
        self._valid_size = None
        self._clear_tracking()
        self.inspector.clear()
        self.inspector.pause.setChecked(False)
        self.windows_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.start_button.setText("Stop capture")
        self.status.setText("Starting window capture…")
        self._session.start()
        if self._ocr:
            self._ocr.start()
        if self._visual:
            self._visual.start()

    def _stop(self, message: str) -> None:
        self._cancel_original()
        self._standby = bool(self._preparing) and not self._closing
        self._stopping_message = message
        self._overlay.hide()
        self._clear_tracking()
        self.inspector.clear()
        if self._ocr:
            self._ocr.request_stop()
        if self._visual:
            self._visual.request_stop()
        if self._translation and not self._preparing:
            self._translation.request_stop()
        if self._session:
            self._session.request_stop()
            self.start_button.setEnabled(False)
            self.status.setText("Stopping capture, OCR, and translation…")

    def _invalidate_ocr(self) -> None:
        if self._valid_size is not None and self._ocr:
            self._ocr.invalidate()
        self._valid_size = None
        self._last_sequence = 0
        self.inspector.clear()
        self._clear_tracking()

    def _clear_tracking(self) -> None:
        self._accepted_ocr = None
        if self._visual:
            self._visual.invalidate()
        self._visual_state = VisualState()
        self._tracker.reset()
        self._grouper.reset()
        self._presentation.reset()
        self._track_ids = ()
        self._overlay.set_tracks(())
        self._overlay.set_blocks(())
        self._overlay.set_translations(())
        self._overlay.set_debug(None)
        if self._translation:
            self._translation.invalidate()

    def _grouping_changed(self) -> None:
        self._grouper.reset()
        self._presentation.reset()
        if self._translation:
            self._translation.invalidate()
        self._overlay.set_blocks(())
        self.inspector.set_translations(())
        self._tick()

    def _font_style_changed(self) -> None:
        automatic = self.automatic_font.isChecked()
        self.font_size.setEnabled(not automatic)
        self._overlay.set_text_style(automatic, self.font_size.value())

    def _backend_changed(self) -> None:
        choice = self.backend_combo.currentData()
        if isinstance(choice, BackendChoice) and choice.unavailable_reason:
            self._select_backend(self._selected_backend)
            self._manage_runtime()
            return
        if isinstance(choice, BackendChoice) and not self._model_prepared(choice):
            answer = QMessageBox.question(
                self,
                "Prepare Gemma for this PC?",
                "Gemma needs first-use GPU preparation before translating. "
                "This may take about a minute. Capture can continue while it prepares.\n\n"
                "Prepare now? Choosing No keeps your previous model.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._select_backend(self._selected_backend)
                return
            self._previous_backend = self._selected_backend
            self._preparing = choice
            self._preparation_started = False
            if self._translation:
                self._translation.request_stop()
            self.backend_combo.setEnabled(False)
            self._show_preparation("Finishing the previous model…")
        else:
            self._selected_backend = choice if isinstance(choice, BackendChoice) else None
            if self._selected_backend is None:
                self._remember_model()
        self._presentation.reset()
        self._standby = isinstance(choice, BackendChoice)
        self._overlay.set_blocks(())
        self._overlay.set_translations((), enabled=self.translate_check.isChecked())
        self.inspector.clear_translations()
        if self._preparing:
            return
        if self._translation and isinstance(choice, BackendChoice):
            if self._translation.finished:
                self._translation = None
            else:
                self._translation.switch_backend(choice.create)
        elif self._translation:
            self._translation.request_stop()
        self._overlay.set_translations((), enabled=self.translate_check.isChecked())
        self.inspector.set_translations(())

    def _select_backend(self, choice: BackendChoice | None) -> None:
        self.backend_combo.blockSignals(True)
        index = self.backend_combo.count() - 1
        for candidate in range(self.backend_combo.count()):
            value = self.backend_combo.itemData(candidate)
            if (
                isinstance(value, BackendChoice)
                and choice
                and (value.key == choice.key if choice.key else value == choice)
            ):
                index = candidate
                break
        self.backend_combo.setCurrentIndex(index)
        self.backend_combo.blockSignals(False)

    def _show_preparation(self, message: str) -> None:
        if self._progress_dialog is None:
            dialog = QProgressDialog(message, "", 0, 0, self)
            dialog.setWindowTitle("Preparing local translation")
            dialog.setCancelButton(None)
            dialog.setMinimumDuration(0)
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.setMinimumWidth(470)
            self._progress_dialog = dialog
        self._progress_dialog.setLabelText(message)
        self._progress_dialog.show()

    def _model_prepared(self, choice: BackendChoice) -> bool:
        return not choice.unavailable_reason and (
            choice.preparation_id in self._prepared_this_run or is_prepared(choice.preparation_id)
        )

    def _advance_preparation(self) -> None:
        choice = self._preparing
        if choice is None:
            return
        session = self._translation
        if self._closing:
            if session and not session.finished:
                session.request_stop()
                return
        elif not self._preparation_started:
            if session and not session.finished:
                return
            self._translation = TranslationSession(choice.create, self._cache_path)
            self._preparation_started = True
            self._translation.start()
            self._show_preparation(
                "Checking model files and preparing the GPU…\n"
                "First use may take about a minute. The app stays responsive."
            )
            return
        elif session:
            snapshot = session.snapshot()
            if snapshot.state not in (TranslationState.READY, TranslationState.FAILED):
                return
            if snapshot.state == TranslationState.FAILED and not session.finished:
                return
            if snapshot.state == TranslationState.READY:
                self._prepared_this_run.add(choice.preparation_id)
                try:
                    mark_prepared(choice.preparation_id)
                except OSError as error:
                    logger.warning("Could not save preparation receipt: %s", error)
                self._selected_backend = choice
                self._remember_model()
                self._standby = True
            else:
                self._translation = None
                self._select_backend(self._previous_backend)
                self._selected_backend = self.backend_combo.currentData()
                self._standby = False
                self.translation_status.setText(f"Preparation failed: {snapshot.message}")
                QMessageBox.warning(self, "Model preparation failed", snapshot.message)
        self._preparing = None
        self._preparation_started = False
        self.backend_combo.setEnabled(True)
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    def _manage_models(self) -> None:
        if not self._closing:
            self._settings.show_models()

    def _runtime_created(self, panel: RuntimeSetupDialog) -> None:
        self._runtime_dialog = panel

    def _manage_runtime(self) -> None:
        if self._closing:
            return
        self._settings.show_runtime()

    def _request_restart(self, target: Path) -> None:
        self._restart_target = target
        self._closing = True
        self._settings.hide()
        if central := self.centralWidget():
            central.setEnabled(False)
        self.status.setText("Finishing active work before restarting. Capture will be stopped.")
        self.close()

    def _ocr_models_ready(self) -> bool:
        return all(bundle.present() for bundle in self._models if bundle.key == "ocr")

    def _refresh_models(self) -> None:
        if self._closing:
            return
        if self._backend_provider:
            choice = self.backend_combo.currentData()
            self._backends = self._backend_provider()
            self.backend_combo.blockSignals(True)
            self.backend_combo.clear()
            for backend in self._backends:
                self.backend_combo.addItem(backend.name, backend)
            self.backend_combo.addItem("No translation", None)
            self._select_backend(choice)
            self.backend_combo.setEnabled(not self._preparing)
        if self._session and self._ocr is None and self._ocr_models_ready():
            choice = self._capture_ocr_choice
            self._ocr = OcrSession(
                choice.create if choice else self._recognizer_factory, require_ack=True
            )
            self._visual = VisualSession()
            self.inspector.clear()
            self._ocr.start()
            self._visual.start()

    def _poll_translation(
        self, running: bool, tracks: tuple[TextBlock, ...] = (), retain: tuple[TextBlock, ...] = ()
    ) -> None:
        session = self._translation
        if self._preparing:
            self.translation_status.setText("Preparing Gemma for this PC…")
            return
        # QMessageBox runs a nested event loop. Until consent is resolved, keep
        # using the committed selection, including the already displayed English.
        choice = self._selected_backend
        if (
            not running
            and self._standby
            and self.translate_check.isChecked()
            and session
            and not session.finished
        ):
            if session.snapshot().state == TranslationState.READY:
                self._remember_model()
            self.translation_status.setText(
                "Model ready. Start capture to translate."
                if session.snapshot().state == TranslationState.READY
                else "Loading the local model…"
            )
            return
        enabled = (
            running
            and self.translate_check.isChecked()
            and isinstance(choice, BackendChoice)
            and self._model_prepared(choice)
        )
        if not enabled:
            self._presentation.reset()
            if session:
                session.request_stop()
                if session.finished:
                    self._translation = None
            self._overlay.set_translations((), enabled=self.translate_check.isChecked())
            self.inspector.set_translations(())
            self.translation_status.setText(
                "Unloading translation model…"
                if session and not session.finished
                else "Gemma needs runtime setup. Select Gemma for instructions."
                if self._backends and all(b.unavailable_reason for b in self._backends)
                else "English translation is off."
                if running
                else "No translation model selected. Open Settings to download one."
                if not isinstance(choice, BackendChoice)
                else "Translation stopped."
            )
            return
        if session and session.finished and session.snapshot().state == TranslationState.STOPPED:
            self._translation = session = None
        if session is None:
            if not isinstance(choice, BackendChoice):
                return
            session = TranslationSession(choice.create, self._cache_path)
            self._translation = session
            session.start()
        state = self._visual_state
        broad_change = bool(
            state.frame
            and state.frame.sequence != self._context_reset_sequence
            and sum(b.width * b.height for b in state.changed_areas)
            > state.frame.width * state.frame.height * 0.65
        )
        if broad_change and state.frame:
            self._context_reset_sequence = state.frame.sequence
        session.update(tracks, retain=retain, reset_context=broad_change)
        snapshot = session.snapshot()
        if snapshot.state == TranslationState.READY:
            self._remember_model()
        published = self._presentation.update(
            retain,
            snapshot.results,
            self._tracker.display_predecessors(),
            scope=(session, snapshot.backend_generation),
        )
        hidden_ids = {t.track_id for t in self._visual_state.hidden}
        showing = tuple(
            p for p in published if not any(t.track_id in hidden_ids for t in p.accepted.lines)
        )
        self._overlay.set_blocks(tuple(p.painted for p in showing))
        self._overlay.set_translations(tuple(p.translation for p in showing), enabled=True)
        self.inspector.set_translations(snapshot.results)
        if snapshot.state == TranslationState.FAILED:
            self.translation_status.setText(
                f"Translation unavailable: {snapshot.message} "
                "Toggle Translation overlay off/on to retry."
            )
        elif snapshot.state == TranslationState.LOADING:
            self.translation_status.setText(
                f"Loading/preparing {choice.name if choice else 'the translation model'}… "
                "Gemma's first GPU use may take about a minute; "
                "later launches reuse the CUDA cache."
            )
        elif snapshot.state == TranslationState.STOPPING:
            self.translation_status.setText("Waiting for translation to finish unloading…")
        else:
            self.translation_status.setText(
                f"{choice.name if choice else 'Translation'} · "
                f"{len(snapshot.results)} English blocks · {snapshot.pending} pending · "
                f"{snapshot.last_batch_ms:.0f} ms last batch · local. {snapshot.message}"
            )

    def _update_ocr(self, frame: CapturedFrame) -> None:
        ocr = self._ocr
        if ocr is None:
            self.inspector.set_frame(frame)
            self.ocr_status.setText(
                "Capture only. Open Settings and download MeikiOCR to recognize text."
            )
            return
        snapshot = ocr.snapshot()
        if self._visual and snapshot.state != OcrState.FAILED:
            state = self._visual.poll()
            accepted = self._accepted_ocr
            if snapshot.result and (
                state.message or state.checked_sequence == snapshot.result.frame.sequence
            ):
                self._track_ids = self._tracker.observe(
                    snapshot.result,
                    visually_absent=state.absent,
                    visual_sequence=state.frame.sequence if state.frame else 0,
                    unchanged=state.unchanged,
                    visual_checked=state.checked,
                    checked_sequence=state.checked_sequence,
                )
                accepted = snapshot.result
                self._accepted_ocr = accepted
                self.inspector.set_result(accepted, self._track_ids)
                ocr.acknowledge(accepted.frame.sequence)
            if state.frame is not None:
                self._visual_state = state
                if state.request_ocr:
                    ocr.submit(state.frame, state.scan_areas)
                self._tracker.confirm_observations(state.stable_tracks, state.frame.captured_at)
            self._visual.submit(
                frame,
                accepted,
                self._tracker.visible(frame, time.monotonic()),
                self._track_ids,
                self._tracker.translation_activity(),
                snapshot.result,
            )
        if snapshot.state == OcrState.FAILED:
            self._clear_tracking()
            self.ocr_status.setText(
                f"OCR unavailable: {snapshot.message} Stop and restart to retry."
            )
            self.inspector.clear()
            self._last_sequence = 0
        elif snapshot.state == OcrState.LOADING:
            self.ocr_status.setText(
                "Loading local MeikiOCR models… GPU initialization can take longer."
            )
        elif snapshot.result is not None:
            result = snapshot.result
            busy = (
                f" · current pass {time.monotonic() - snapshot.processing_since:.1f} s"
                if snapshot.processing_since is not None
                else ""
            )
            scan = "full scan" if result.scanned is None else f"{len(result.scanned)} area scan"
            device = {"CUDAExecutionProvider": "NVIDIA GPU", "DmlExecutionProvider": "DirectML GPU"}
            self.ocr_status.setText(
                f"{len(result.regions)} text regions · {result.duration_ms:.0f} ms OCR · "
                f"{scan} · "
                f"{snapshot.queue_ms:.0f} ms capture-to-start · "
                f"{snapshot.skipped_frames} waiting frames skipped{busy} · "
                f"{device.get(snapshot.provider, 'CPU')}"
                f"{(' · ' + snapshot.message) if snapshot.message else ''}"
                f" · visual {self._visual_state.duration_ms:.1f} ms · "
                f"{self._visual_state.avoided} captures skipped for OCR"
                f" · {len(self._visual_state.unchanged)} unchanged regions held"
                f"{(' · ' + self._visual_state.message) if self._visual_state.message else ''}"
            )
            self.ocr_status.setToolTip(
                f"Average of the last 8 passes: {snapshot.mean_duration_ms:.0f} ms. "
                f"{snapshot.processed_frames} passes completed. Only the newest waiting frame "
                "is kept; skipped frames do not count as missing text. "
                "Existing English stays visible while the next pass runs."
                " The inspector shows only this scan's actual detections; unscanned regions "
                "remain tracked on the overlay."
            )
        else:
            elapsed = (
                f" {time.monotonic() - snapshot.processing_since:.0f} s."
                if snapshot.processing_since is not None
                else ""
            )
            self.ocr_status.setText(
                f"Reading the first frame…{elapsed}"
                + (
                    " First GPU use may compile kernels; later launches reuse the local cache."
                    if snapshot.provider == "CUDAExecutionProvider"
                    else ""
                )
            )
        # Once OCR arrives, the inspector owns an exact source/result pair.
        if self._accepted_ocr is None and frame.sequence != self._last_sequence:
            self.inspector.set_frame(frame)
        self._last_sequence = frame.sequence

    def _tick(self) -> None:
        if self._showing_original and (
            self._closing
            or self._session is None
            or self._session.finished
            or QApplication.activeModalWidget() is not None
            or not self._windows.is_foreground(self._session.target)
        ):
            self._cancel_original()
        self._advance_session()
        self._update_notice()

    def _advance_session(self) -> None:
        self._advance_preparation()
        session = self._session
        if session is None:
            self._overlay.hide()
            self._poll_translation(False)
            if (
                self._closing
                and not self._preparing
                and (self._translation is None or self._translation.finished)
                and not (self._model_manager and self._model_manager.operation)
                and not (self._runtime_dialog and self._runtime_dialog.operation)
                and not self._settings.busy
            ):
                self.close()
            return
        snapshot = session.snapshot()
        if session.finished:
            self._overlay.hide()
            self._clear_tracking()
            self.inspector.clear()
            self._poll_translation(False)
            if self._visual:
                self._visual.request_stop()
                if not self._visual.finished:
                    return
                self._visual = None
            if self._ocr and not self._ocr.finished:
                self._ocr.request_stop()
            if self._translation is not None and not (self._preparing or self._standby):
                self.status.setText("Waiting for the current translation operation to finish…")
                return
            if self._ocr and not self._ocr.finished:
                self._ocr.request_stop()
                self.status.setText("Waiting for the current OCR operation to finish…")
                return
            self.status.setText(
                snapshot.message
                if snapshot.state == CaptureState.FAILED
                else self._stopping_message
            )
            self._session = None
            self._ocr = None
            self.ocr_status.setText("OCR stopped. Start capture to load the local models again.")
            self.start_button.setText("Start capture")
            self.start_button.setEnabled(True)
            self.windows_combo.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self._settings.set_capture_active(False)
            if self._closing:
                self.close()
            return
        if snapshot.state in (CaptureState.STOPPING, CaptureState.FAILED):
            self._overlay.hide()
            self._clear_tracking()
            if self._ocr:
                self._ocr.request_stop()
            self.inspector.clear()
            self._poll_translation(False)
            return
        try:
            geometry = self._windows.geometry(session.target)
            foreground = self._windows.is_foreground(session.target)
            frame = snapshot.frame
            if geometry.minimized:
                self._invalidate_ocr()
                self.status.setText("Window minimized. Restore it to resume.")
            elif frame is not None and frame.geometry.client.size == geometry.client.size:
                if self._valid_size != geometry.client.size:
                    self._invalidate_ocr()
                    self._valid_size = geometry.client.size
                self._update_ocr(frame)
                elapsed = max(0.1, time.monotonic() - self._started_at)
                self.metrics.setText(
                    f"{frame.width} × {frame.height} px · {frame.sequence / elapsed:.1f} samples/s "
                    f"average · DPI {geometry.dpi} · local"
                )
                self.status.setText(
                    "Capturing. The overlay appears on the selected window when ready."
                    if foreground and self.overlay_check.isChecked()
                    else "Capturing. Switch to the selected window to see the overlay."
                    if self.overlay_check.isChecked()
                    else "Capturing. Game overlay is hidden."
                )
            else:
                self._invalidate_ocr()
                self.status.setText("Waiting for a frame matching the window size…")
            result = self._accepted_ocr
            tracks = self._tracker.visible(frame, time.monotonic()) if frame is not None else ()
            ready = (
                self._tracker.translation_tracks(frame, time.monotonic())
                if frame is not None
                else ()
            )
            grouped = self._grouper.update(
                tracks,
                ready,
                time.monotonic(),
                enabled=self.group_dialogue.isChecked(),
                activity=self._tracker.translation_activity(),
            )
            if not self.translate_check.isChecked():
                self._overlay.set_blocks(grouped.blocks)
            self._poll_translation(
                True,
                tuple(
                    block
                    for block in grouped.ready
                    if not any(t.track_id in self._visual_state.blocked for t in block.lines)
                    and (
                        self._visual_state.message
                        or (result and self._visual_state.ocr_sequence == result.frame.sequence)
                    )
                ),
                grouped.blocks,
            )
            tracks = tuple(t for t in tracks if t not in self._visual_state.hidden)
            self._overlay.set_debug(
                debug_display(
                    self._visual_state,
                    self._ocr.snapshot(),
                    self._translation.snapshot() if self._translation else None,
                    time.monotonic(),
                    waiting_blocks=len(grouped.blocks) - len(grouped.ready),
                )
                if self.debug_check.isChecked() and self._ocr
                else None
            )
            if not self.stabilize_check.isChecked() and not self.translate_check.isChecked():
                tracks = (
                    tuple(
                        TextTrack(key, region.text, region.bounds, region.vertical)
                        for key, region in zip(self._track_ids, result.regions, strict=True)
                        if key is not None
                    )
                    if result is not None
                    and frame is not None
                    and overlay_result_ready(result, frame, time.monotonic())
                    else ()
                )
            if (
                self.overlay_check.isChecked()
                and not self._showing_original
                and (
                    self.translate_check.isChecked()
                    or self.raw_boxes_check.isChecked()
                    or self.debug_check.isChecked()
                )
                and (tracks or self.debug_check.isChecked())
                and frame is not None
                and overlay_ready(snapshot, geometry, foreground)
            ):
                self._overlay.set_tracks(
                    tracks
                    if self.translate_check.isChecked() or self.raw_boxes_check.isChecked()
                    else ()
                )
                self._overlay.align(geometry.client)
            else:
                self._overlay.hide()
        except (WindowUnavailable, OSError, RuntimeError) as error:
            logger.warning("Session display stopped: %s", error)
            self._stop(str(error))

    def _open_demo(self) -> None:
        python = Path(sys.executable).with_name("pythonw.exe")
        try:
            process = subprocess.Popen([str(python), "-m", "jp_overlay.demo", "--dialogue"])
            self._demo_processes.append(process)
            self.status.setText("Demo opened. Refresh the window list and select JP Overlay Demo.")
            QTimer.singleShot(1200, self.refresh_windows)
        except OSError as error:
            self.status.setText(f"Could not open the demo: {error}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_original()
        setup_dialogs = (self._model_manager, self._runtime_dialog)
        if self._settings.busy or any(dialog and dialog.operation for dialog in setup_dialogs):
            self._settings.cancel_operations()
            for dialog in setup_dialogs:
                if dialog and dialog.operation:
                    dialog.operation.cancel()
            self._closing = True
            self._standby = False
            if self._translation:
                self._translation.request_stop()
            if self._session:
                self._stop("Capture stopped.")
            event.ignore()
            return
        if self._preparing or (self._translation and not self._translation.finished):
            self._closing = True
            self._standby = False
            if self._translation:
                self._translation.request_stop()
            if self._session:
                self._stop("Capture stopped.")
            event.ignore()
            return
        if self._session is not None:
            self._closing = True
            self._stop("Capture stopped.")
            event.ignore()
            return
        if not self._preferences.idle:
            self._closing = True
            event.ignore()
            return
        if self._hardware and not self._hardware.finished:
            self._closing = True
            self.status.setText("Finishing the graphics hardware check…")
            event.ignore()
            return
        if self._restart_target:
            try:
                if self._hotkeys:
                    self._hotkeys.release()
                if self._restart is None:
                    self._restart = RuntimeRestart(project_root(), self._restart_target)
                if not self._restart.poll():
                    self.status.setText("Opening JP Overlay with the installed runtime…")
                    event.ignore()
                    return
            except (OSError, ValueError, RuntimeError) as error:
                self._restart_target = None
                self._restart = None
                self._closing = False
                self._settings.hotkeys.activate()
                if central := self.centralWidget():
                    central.setEnabled(True)
                self.status.setText(str(error))
                QMessageBox.warning(self, "Restart failed", str(error))
                event.ignore()
                return
            self._restart_target = None
            self._restart = None
        self._timer.stop()
        self._closing = True
        if self._hotkeys:
            self._hotkeys.release()
        self._settings.hide()
        self._overlay.close()
        super().closeEvent(event)
