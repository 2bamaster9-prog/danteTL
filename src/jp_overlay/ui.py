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
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.capture import CaptureSession
from jp_overlay.domain import CapturedFrame, CaptureState, WindowTarget, overlay_ready
from jp_overlay.grouping import DialogueGrouper, TextBlock
from jp_overlay.inspection import OcrInspector
from jp_overlay.overlay import OverlayWindow
from jp_overlay.recognition import OcrSession, OcrState, Recognizer, overlay_result_ready
from jp_overlay.tracking import TextTrack, TextTracker
from jp_overlay.translation import BackendChoice, TranslationSession, TranslationState
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
    ) -> None:
        super().__init__()
        self._windows = windows
        self._session: CaptureSession | None = None
        self._ocr: OcrSession | None = None
        self._translation: TranslationSession | None = None
        self._backends = backends
        self._cache_path = (
            cache_path or Path(__file__).resolve().parents[2] / "data/translations.sqlite3"
        )
        self._recognizer_factory = recognizer_factory
        self._valid_size: tuple[int, int] | None = None
        self._tracker = TextTracker()
        self._grouper = DialogueGrouper()
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
        subtitle = QLabel("Local Japanese → English · MeikiOCR + Sugoi V4")
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
        layout.addLayout(actions)

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
            "Wider search considers more candidates and may take longer; "
            "translation quality can vary."
        )
        for backend in self._backends:
            self.backend_combo.addItem(backend.name, backend)
        self.backend_combo.setEnabled(len(self._backends) > 1)
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
        self.metrics = QLabel("Window capture · 4 samples/s target · all processing local")
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
        self._session = CaptureSession(target, self._windows)
        self._ocr = OcrSession(self._recognizer_factory)
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
        self._ocr.start()

    def _stop(self, message: str) -> None:
        self._stopping_message = message
        self._overlay.hide()
        self._clear_tracking()
        self.inspector.clear()
        if self._ocr:
            self._ocr.request_stop()
        if self._translation:
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
        self._tracker.reset()
        self._grouper.reset()
        self._track_ids = ()
        self._overlay.set_tracks(())
        self._overlay.set_blocks(())
        self._overlay.set_translations(())
        if self._translation:
            self._translation.invalidate()

    def _grouping_changed(self) -> None:
        self._grouper.reset()
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

    def _backend_changed(self) -> None:
        choice = self.backend_combo.currentData()
        if self._translation and isinstance(choice, BackendChoice):
            if self._translation.finished:
                self._translation = None
            else:
                self._translation.switch_backend(choice.create)
        self._overlay.set_translations((), enabled=self.translate_check.isChecked())
        if not self.inspector.pause.isChecked():
            self.inspector.set_translations(())

    def _poll_translation(self, running: bool, tracks: tuple[TextBlock, ...] = ()) -> None:
        session = self._translation
        enabled = running and self.translate_check.isChecked()
        if not enabled:
            if session:
                session.request_stop()
                if session.finished:
                    self._translation = None
            self._overlay.set_translations(())
            if not self.inspector.pause.isChecked():
                self.inspector.set_translations(())
            self.translation_status.setText(
                "Unloading translation model…"
                if session and not session.finished
                else "English translation is off."
                if running
                else "Translation stopped."
            )
            return
        if session and session.finished and session.snapshot().state == TranslationState.STOPPED:
            self._translation = session = None
        if session is None:
            choice = self.backend_combo.currentData()
            if not isinstance(choice, BackendChoice):
                return
            session = TranslationSession(choice.create, self._cache_path)
            self._translation = session
            session.start()
        session.update(tracks)
        snapshot = session.snapshot()
        self._overlay.set_translations(snapshot.results, enabled=True)
        if not self.inspector.pause.isChecked():
            self.inspector.set_translations(snapshot.results)
        if snapshot.state == TranslationState.FAILED:
            self.translation_status.setText(
                f"Translation unavailable: {snapshot.message} Toggle English off/on to retry."
            )
        elif snapshot.state == TranslationState.LOADING:
            self.translation_status.setText("Loading the local translation model…")
        elif snapshot.state == TranslationState.STOPPING:
            self.translation_status.setText("Waiting for translation to finish unloading…")
        else:
            self.translation_status.setText(
                f"{len(snapshot.results)} English blocks · {snapshot.pending} pending · "
                f"{snapshot.last_batch_ms:.0f} ms last batch · local CPU. {snapshot.message}"
            )

    def _update_ocr(self, frame: CapturedFrame) -> None:
        ocr = self._ocr
        if ocr is None:
            return
        paused = self.inspector.pause.isChecked()
        if not paused:
            ocr.submit(frame)
        snapshot = ocr.snapshot()
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
            self.ocr_status.setText("Loading local MeikiOCR models on CPU…")
        elif snapshot.result is not None:
            result = snapshot.result
            self._track_ids = self._tracker.observe(result)
            self.inspector.set_result(result, self._track_ids)
            busy = (
                f" · current pass {time.monotonic() - snapshot.processing_since:.1f} s"
                if snapshot.processing_since is not None
                else ""
            )
            self.ocr_status.setText(
                f"{len(result.regions)} text regions · {result.duration_ms:.0f} ms OCR · "
                f"{snapshot.queue_ms:.0f} ms capture-to-start · "
                f"{snapshot.skipped_frames} waiting frames skipped{busy} · local CPU"
            )
            self.ocr_status.setToolTip(
                f"Average of the last 8 passes: {snapshot.mean_duration_ms:.0f} ms. "
                f"{snapshot.processed_frames} passes completed. Only the newest waiting frame "
                "is kept; skipped frames do not count as missing text. "
                "Existing English stays visible while the next pass runs."
            )
        else:
            self.ocr_status.setText("Reading the newest frame with MeikiOCR…")
        # Once OCR arrives, the inspector owns an exact source/result pair.
        if not paused and self.inspector.result is None and frame.sequence != self._last_sequence:
            self.inspector.preview.set_frame(frame)
        self._last_sequence = frame.sequence

    def _tick(self) -> None:
        session = self._session
        if session is None:
            self._overlay.hide()
            self._poll_translation(False)
            return
        snapshot = session.snapshot()
        if session.finished:
            self._overlay.hide()
            self._clear_tracking()
            self.inspector.clear()
            self._poll_translation(False)
            if self._ocr and not self._ocr.finished:
                self._ocr.request_stop()
            if self._translation is not None:
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
                tracks, ready, time.monotonic(), enabled=self.group_dialogue.isChecked()
            )
            self._overlay.set_blocks(grouped.blocks)
            self._poll_translation(True, grouped.ready)
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
                and tracks
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
        if self._session is not None:
            self._closing = True
            self._stop("Capture stopped.")
            event.ignore()
            return
        self._timer.stop()
        self._overlay.close()
        super().closeEvent(event)
