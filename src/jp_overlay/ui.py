"""Window picker, clean capture preview, and session coordination on the Qt thread."""

import logging
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.capture import CaptureSession
from jp_overlay.diagnostics import debug_display
from jp_overlay.domain import CapturedFrame, CaptureState, WindowTarget, overlay_ready
from jp_overlay.grouping import DialogueGrouper, TextBlock
from jp_overlay.inspection import OcrInspector
from jp_overlay.model_manager import ModelManager
from jp_overlay.model_store import ModelBundle, is_prepared, mark_prepared
from jp_overlay.overlay import OverlayWindow
from jp_overlay.presentation import EnglishPresentation
from jp_overlay.recognition import OcrChoice, OcrSession, OcrState, Recognizer, overlay_result_ready
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
    ) -> None:
        super().__init__()
        self._windows = windows
        self._session: CaptureSession | None = None
        self._ocr: OcrSession | None = None
        self._visual: VisualSession | None = None
        self._visual_state = VisualState()
        self._translation: TranslationSession | None = None
        self._backends = backends
        self._models, self._backend_provider = models, backend_provider
        self._model_manager: ModelManager | None = None
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
        self._started_at = 0.0
        self._stopping_message = "Capture stopped."
        self._demo_processes: list[subprocess.Popen[bytes]] = []
        self.setWindowTitle("JP Overlay")
        self.resize(1280, 840)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.refresh_windows()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel("JP Overlay")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subtitle = QLabel("Local Japanese → English · MeikiOCR · selectable translation model")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        selection = QHBoxLayout()
        selection.addWidget(QLabel("Game window"))
        self.windows_combo = QComboBox()
        self.windows_combo.setAccessibleName("Game window")
        self.windows_combo.setMinimumWidth(200)
        self.windows_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_windows)
        selection.addWidget(self.windows_combo, 1)
        selection.addWidget(self.refresh_button)
        layout.addLayout(selection)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Start capture")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._toggle_capture)
        self.demo_button = QPushButton("Open demo window")
        self.demo_button.clicked.connect(self._open_demo)
        actions.addWidget(self.start_button, 1)
        actions.addWidget(self.demo_button)
        self.models_button = QPushButton("Models…")
        self.models_button.setEnabled(bool(self._models))
        self.models_button.clicked.connect(self._manage_models)
        actions.addWidget(self.models_button)
        layout.addLayout(actions)

        processing = QHBoxLayout()
        processing.addWidget(QLabel("OCR device"))
        self.ocr_device = QComboBox()
        for choice in self._ocr_backends:
            self.ocr_device.addItem(choice.name, choice)
        self.ocr_device.setToolTip(
            "Choices reflect this app's installed runtimes, not Meiki model files. "
            "For Automatic NVIDIA OCR, close the app and run Setup GPU OCR.cmd, then restart "
            "with Run JP Overlay.cmd. Choose the OCR device before starting capture."
        )
        self.capture_rate = QSpinBox()
        self.capture_rate.setRange(2, 12)
        self.capture_rate.setSuffix(" samples/s")
        self.capture_rate.setValue(self._ocr_backends[0].capture_fps)
        self.capture_rate.setToolTip(
            "Capture feeds cheap visual checks. OCR runs on changes and periodic refreshes."
        )
        self.ocr_device.currentIndexChanged.connect(self._ocr_choice_changed)
        processing.addWidget(self.ocr_device)
        processing.addWidget(QLabel("Capture rate"))
        processing.addWidget(self.capture_rate)
        processing.addStretch()
        layout.addLayout(processing)

        options = QHBoxLayout()
        self.overlay_check = QCheckBox("Show game overlay")
        self.overlay_check.setChecked(True)
        self.overlay_check.toggled.connect(self._tick)
        options.addWidget(self.overlay_check)
        self.stabilize_check = QCheckBox("Stabilize game boxes")
        self.stabilize_check.setChecked(True)
        self.stabilize_check.setToolTip(
            "Hold small OCR shifts, confirm text changes, and bridge one missed detection. "
            "Disable to compare raw boxes. The inspector always shows raw OCR."
        )
        self.stabilize_check.toggled.connect(self._tick)
        options.addWidget(self.stabilize_check)
        self.debug_check = QCheckBox("Debug overlay")
        self.debug_check.setToolTip(
            "Amber: significant visual changes. Cyan: last completed OCR coverage. "
            "Shows local worker timings and queue waits; does not change scheduling."
        )
        self.debug_check.toggled.connect(self._tick)
        options.addWidget(self.debug_check)
        options.addStretch()
        options.addWidget(QLabel("Opacity"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setAccessibleName("Overlay opacity")
        slider.setRange(20, 100)
        slider.setValue(85)
        slider.setMaximumWidth(120)
        slider.valueChanged.connect(self._overlay.set_opacity)
        options.addWidget(slider)
        layout.addLayout(options)

        translation = QHBoxLayout()
        self.translate_check = QCheckBox("English overlay")
        self.translate_check.setChecked(bool(self._backends))
        self.translate_check.setEnabled(bool(self._backends))
        self.translate_check.toggled.connect(self._tick)
        self.translate_check.toggled.connect(self.stabilize_check.setDisabled)
        self.stabilize_check.setDisabled(bool(self._backends))
        self.stabilize_check.setToolTip(
            "English always uses stable tracks. Turn English off to compare raw game boxes."
        )
        translation.addWidget(self.translate_check)
        self.backend_combo = QComboBox()
        self.backend_combo.setAccessibleName("Translation backend")
        self.backend_combo.setToolTip(
            "Downloaded models appear here. Entries marked 'runtime setup needed' explain "
            "which setup to run before use. "
            "Sugoi runs on CPU; Gemma uses NVIDIA CUDA or AMD-compatible Vulkan. "
            "Switching unloads the previous model. Quality and latency vary."
        )
        for backend in self._backends:
            self.backend_combo.addItem(backend.name, backend)
        self.backend_combo.addItem("No translation", None)
        # An unprepared model is never loaded implicitly on the first launch.
        if (
            not self._backends
            or self._backends[0].unavailable_reason
            or not is_prepared(self._backends[0].preparation_id)
        ):
            self.backend_combo.setCurrentIndex(self.backend_combo.count() - 1)
        self._selected_backend = self.backend_combo.currentData()
        self.backend_combo.setEnabled(bool(self._backends))
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        translation.addWidget(self.backend_combo)
        self.group_dialogue = QCheckBox("Group dialogue lines")
        self.group_dialogue.setChecked(True)
        self.group_dialogue.setToolTip(
            "Translate likely wrapped dialogue as one passage. Disable if unrelated lines group."
        )
        self.group_dialogue.toggled.connect(self._grouping_changed)
        translation.addWidget(self.group_dialogue)
        translation.addStretch()
        self.automatic_font = QCheckBox("Automatic text size")
        self.automatic_font.setChecked(True)
        translation.addWidget(self.automatic_font)
        self.font_size = QSpinBox()
        self.font_size.setRange(10, 60)
        self.font_size.setValue(20)
        self.font_size.setSuffix(" px")
        self.font_size.setAccessibleName("English font size in physical pixels")
        self.font_size.setEnabled(False)
        self.automatic_font.toggled.connect(self._font_style_changed)
        self.font_size.valueChanged.connect(self._font_style_changed)
        translation.addWidget(self.font_size)
        layout.addLayout(translation)

        label = QLabel("RAW OCR FRAME + DETECTED TEXT · PERSISTENT IDS")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.inspector = OcrInspector()
        self.inspector.pause.toggled.connect(self._pause_inspection)
        layout.addWidget(self.inspector, 1)
        self.ocr_status = QLabel("OCR starts with capture. Models stay on this PC.")
        self.ocr_status.setWordWrap(True)
        layout.addWidget(self.ocr_status)
        self.translation_status = QLabel("English translation starts with capture.")
        self.translation_status.setWordWrap(True)
        layout.addWidget(self.translation_status)
        self.status = QLabel("Select a window, then start capture.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.metrics = QLabel("Window capture · all processing local")
        self.metrics.setObjectName("muted")
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)
        note = QLabel(
            "Preview shows raw OCR. Hover English cells to review the source used for translation. "
            "English wraps to fit; an ellipsis means the full text is available in the table."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #111923; color: #e7edf5; font: 10pt 'Segoe UI'; }
            QLabel#heading { font-size: 23pt; font-weight: 600; }
            QLabel#muted { color: #9baabc; font-size: 9pt; }
            QLabel#eyebrow { color: #92a4b7; font-size: 8pt; font-weight: 600; }
            QPushButton, QComboBox { background: #243142; border: 1px solid #3c4c60;
                border-radius: 6px; padding: 9px 12px; }
            QPushButton:hover { background: #304259; }
            QPushButton:disabled, QComboBox:disabled { color: #64748b; }
            QPushButton#primary { background: #257c73; border-color: #359c90; }
            QPushButton#primary:hover { background: #2d9185; }
            QComboBox QAbstractItemView { background: #1d2938;
                selection-background-color: #257c73; }
            QTableWidget { background: #172230; gridline-color: #304259;
                selection-background-color: #31544f; }
            QHeaderView::section { background: #243142; padding: 6px; border: 0; }
            QSlider::groove:horizontal { height: 4px; background: #35475c; }
            QSlider::handle:horizontal { background: #5eead4; width: 12px; margin: -4px 0;
                border-radius: 6px; }
            QProgressBar { border: 1px solid #3c4c60; border-radius: 4px;
                background: #172230; min-height: 18px; text-align: center; }
            QProgressBar::chunk { background: #257c73; border-radius: 3px; }
        """)

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
        if self._session:
            self._stop("Capture stopped.")
            return
        target = self.windows_combo.currentData()
        if not isinstance(target, WindowTarget):
            return
        self._session = CaptureSession(target, self._windows, fps=self.capture_rate.value())
        choice = self.ocr_device.currentData()
        if self._ocr_models_ready():
            self._ocr = OcrSession(
                choice.create if isinstance(choice, OcrChoice) else self._recognizer_factory,
                require_ack=True,
            )
            self._visual = VisualSession()
        self.ocr_device.setEnabled(False)
        self.capture_rate.setEnabled(False)
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

    def _pause_inspection(self, paused: bool) -> None:
        if self._ocr:
            self._ocr.invalidate()
        self._overlay.hide()
        self._clear_tracking()
        if paused:
            self.ocr_status.setText("Inspection paused · frame and text frozen · game boxes hidden")
        else:
            self.inspector.clear()
            self._last_sequence = 0

    def _invalidate_ocr(self) -> None:
        if self._valid_size is not None and self._ocr:
            self._ocr.invalidate()
        self._valid_size = None
        self._last_sequence = 0
        self.inspector.clear()
        self._clear_tracking()

    def _clear_tracking(self) -> None:
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
        if not self.inspector.pause.isChecked():
            self.inspector.set_translations(())
        self._tick()

    def _font_style_changed(self) -> None:
        automatic = self.automatic_font.isChecked()
        self.font_size.setEnabled(not automatic)
        self._overlay.set_text_style(automatic, self.font_size.value())

    def _ocr_choice_changed(self) -> None:
        choice = self.ocr_device.currentData()
        if isinstance(choice, OcrChoice):
            self.capture_rate.setValue(choice.capture_fps)

    def _backend_changed(self) -> None:
        choice = self.backend_combo.currentData()
        if isinstance(choice, BackendChoice) and choice.unavailable_reason:
            self._select_backend(self._selected_backend)
            QMessageBox.information(
                self, "Model downloaded — runtime setup needed", choice.unavailable_reason
            )
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
        self._presentation.reset()
        self._standby = isinstance(choice, BackendChoice)
        if self._preparing:
            self._overlay.set_translations((), enabled=True)
            return
        if self._translation and isinstance(choice, BackendChoice):
            if self._translation.finished:
                self._translation = None
            else:
                self._translation.switch_backend(choice.create)
        elif self._translation:
            self._translation.request_stop()
        self._overlay.set_translations((), enabled=self.translate_check.isChecked())
        if not self.inspector.pause.isChecked():
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
        self.backend_combo.setEnabled(bool(self._backends))
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None

    def _manage_models(self) -> None:
        if self._model_manager is None:
            self._model_manager = ModelManager(self._models, self)
            self._model_manager.models_changed.connect(self._refresh_models)
        self._model_manager.show()
        self._model_manager.raise_()

    def _ocr_models_ready(self) -> bool:
        return all(bundle.present() for bundle in self._models if bundle.key == "ocr")

    def _refresh_models(self) -> None:
        if self._closing:
            return
        if self._backend_provider:
            choice = self.backend_combo.currentData()
            previously_available = bool(self._backends)
            self._backends = self._backend_provider()
            self.backend_combo.blockSignals(True)
            self.backend_combo.clear()
            for backend in self._backends:
                self.backend_combo.addItem(backend.name, backend)
            self.backend_combo.addItem("No translation", None)
            self._select_backend(choice)
            self.backend_combo.setEnabled(bool(self._backends) and not self._preparing)
            self.translate_check.setEnabled(bool(self._backends))
            if self._backends and not previously_available:
                self.translate_check.setChecked(True)
        if self._session and self._ocr is None and self._ocr_models_ready():
            choice = self.ocr_device.currentData()
            self._ocr = OcrSession(choice.create, require_ack=True)
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
            if not self.inspector.pause.isChecked():
                self.inspector.set_translations(())
            self.translation_status.setText(
                "Unloading translation model…"
                if session and not session.finished
                else "Gemma needs runtime setup. Select Gemma for instructions."
                if self._backends and all(b.unavailable_reason for b in self._backends)
                else "English translation is off."
                if running
                else "No translation model selected. Open Models to download one."
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
        published = self._presentation.update(
            retain, snapshot.results, self._tracker.display_predecessors()
        )
        hidden_ids = {t.track_id for t in self._visual_state.hidden}
        showing = tuple(
            p for p in published if not any(t.track_id in hidden_ids for t in p.accepted.lines)
        )
        self._overlay.set_blocks(tuple(p.painted for p in showing))
        self._overlay.set_translations(tuple(p.translation for p in showing), enabled=True)
        if not self.inspector.pause.isChecked():
            self.inspector.set_translations(snapshot.results)
        if snapshot.state == TranslationState.FAILED:
            self.translation_status.setText(
                f"Translation unavailable: {snapshot.message} Toggle English off/on to retry."
            )
        elif snapshot.state == TranslationState.LOADING:
            self.translation_status.setText(
                "Loading/preparing the local translation model… "
                "Gemma's first GPU use may take about a minute; "
                "later launches reuse the CUDA cache."
            )
        elif snapshot.state == TranslationState.STOPPING:
            self.translation_status.setText("Waiting for translation to finish unloading…")
        else:
            self.translation_status.setText(
                f"{len(snapshot.results)} English blocks · {snapshot.pending} pending · "
                f"{snapshot.last_batch_ms:.0f} ms last batch · local. {snapshot.message}"
            )

    def _update_ocr(self, frame: CapturedFrame) -> None:
        ocr = self._ocr
        if ocr is None:
            self.inspector.preview.set_frame(frame)
            self.ocr_status.setText(
                "Capture only. Open Models and download MeikiOCR to recognize text."
            )
            return
        paused = self.inspector.pause.isChecked()
        snapshot = ocr.snapshot()
        if not paused and self._visual and snapshot.state != OcrState.FAILED:
            state = self._visual.poll()
            accepted = self.inspector.result
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
            if self.inspector.result is not None:
                self.inspector.clear()
                self._last_sequence = 0
        elif paused:
            self.ocr_status.setText("Inspection paused · frame and text frozen · game boxes hidden")
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
        if not paused and self.inspector.result is None and frame.sequence != self._last_sequence:
            self.inspector.preview.set_frame(frame)
        self._last_sequence = frame.sequence

    def _tick(self) -> None:
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
            self.ocr_device.setEnabled(True)
            self.capture_rate.setEnabled(True)
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
            result = self.inspector.result
            tracks = self._tracker.visible(frame, time.monotonic()) if frame is not None else ()
            ready = (
                self._tracker.translation_tracks(frame, time.monotonic())
                if frame is not None and not self.inspector.pause.isChecked()
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
            if (
                not self.stabilize_check.isChecked()
                and not self.inspector.pause.isChecked()
                and not self.translate_check.isChecked()
            ):
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
                and not self.inspector.pause.isChecked()
                and (tracks or self.debug_check.isChecked())
                and frame is not None
                and overlay_ready(snapshot, geometry, foreground)
            ):
                self._overlay.set_tracks(tracks)
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
        if self._model_manager and self._model_manager.operation:
            self._model_manager.close()
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
        self._timer.stop()
        self._overlay.close()
        super().closeEvent(event)
