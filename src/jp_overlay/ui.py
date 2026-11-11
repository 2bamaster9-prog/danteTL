"""Window picker, clean capture preview, and session coordination on the Qt thread."""

import logging
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.capture import CaptureSession
from jp_overlay.domain import CapturedFrame, CaptureState, WindowTarget, overlay_ready
from jp_overlay.overlay import OverlayWindow
from jp_overlay.windows import Windows, WindowUnavailable

logger = logging.getLogger(__name__)


def frame_image(frame: CapturedFrame) -> QImage:
    """Detach from the snapshot bytes so Qt owns the preview's pixel lifetime."""
    return QImage(
        frame.bgra, frame.width, frame.height, frame.width * 4, QImage.Format.Format_RGB32
    ).copy()


class CapturePreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(360, 220)
        self._image = QImage()

    def set_frame(self, frame: CapturedFrame | None) -> None:
        self._image = frame_image(frame) if frame else QImage()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image.isNull():
            painter.setPen(Qt.GlobalColor.gray)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Your capture appears here")
            return
        size = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(
            (self.width() - size.width()) / 2,
            (self.height() - size.height()) / 2,
            size.width(),
            size.height(),
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image)


class MainWindow(QMainWindow):
    """Coordinate one capture session. Slow operations remain owned by the service."""

    def __init__(self, windows: Windows) -> None:
        super().__init__()
        self._windows = windows
        self._session: CaptureSession | None = None
        self._overlay = OverlayWindow(windows)
        self._last_sequence = 0
        self._closing = False
        self._started_at = 0.0
        self._stopping_message = "Capture stopped."
        self._demo_processes: list[subprocess.Popen[bytes]] = []
        self.setWindowTitle("JP Overlay")
        self.resize(660, 640)
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
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        heading = QLabel("JP Overlay")
        heading.setObjectName("heading")
        layout.addWidget(heading)
        subtitle = QLabel("Local game translation · capture preview")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        layout.addWidget(QLabel("Game window"))
        selection = QHBoxLayout()
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
        self.overlay_check = QCheckBox("Show sample overlay")
        self.overlay_check.setChecked(True)
        self.overlay_check.toggled.connect(self._tick)
        options.addWidget(self.overlay_check)
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

        label = QLabel("ORIGINAL CAPTURE")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self.preview = CapturePreview()
        layout.addWidget(self.preview, 1)
        self.status = QLabel("Select a window, then start capture.")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Capture status")
        layout.addWidget(self.status)
        self.metrics = QLabel("Window capture · 4 samples/s target · all processing local")
        self.metrics.setObjectName("muted")
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)
        note = QLabel("Use windowed or borderless fullscreen. This milestone shows sample text.")
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
        self._stopping_message = "The capture source closed. Select a window to restart."
        self._last_sequence = 0
        self._started_at = time.monotonic()
        self.preview.set_frame(None)
        self.windows_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.start_button.setText("Stop capture")
        self.status.setText("Starting window capture…")
        self._session.start()

    def _stop(self, message: str) -> None:
        self._stopping_message = message
        self._overlay.hide()
        self.preview.set_frame(None)
        if self._session:
            self._session.request_stop()
            self.start_button.setEnabled(False)
            self.status.setText("Stopping capture…")

    def _tick(self) -> None:
        session = self._session
        if session is None:
            self._overlay.hide()
            return
        snapshot = session.snapshot()
        if session.finished:
            self._overlay.hide()
            self.preview.set_frame(None)
            self.status.setText(
                snapshot.message
                if snapshot.state == CaptureState.FAILED
                else self._stopping_message
            )
            self._session = None
            self.start_button.setText("Start capture")
            self.start_button.setEnabled(True)
            self.windows_combo.setEnabled(True)
            self.refresh_button.setEnabled(True)
            if self._closing:
                self.close()
            return
        if snapshot.state in (CaptureState.STOPPING, CaptureState.FAILED):
            self._overlay.hide()
            return
        try:
            geometry = self._windows.geometry(session.target)
            foreground = self._windows.is_foreground(session.target)
            frame = snapshot.frame
            if geometry.minimized:
                self.preview.set_frame(None)
                self._last_sequence = 0
                self.status.setText("Window minimized. Restore it to resume.")
            elif frame is not None and frame.geometry.client.size == geometry.client.size:
                if frame.sequence != self._last_sequence:
                    self.preview.set_frame(frame)
                    self._last_sequence = frame.sequence
                elapsed = max(0.1, time.monotonic() - self._started_at)
                self.metrics.setText(
                    f"{frame.width} × {frame.height} px · {frame.sequence / elapsed:.1f} samples/s "
                    f"average · DPI {geometry.dpi} · local"
                )
                self.status.setText(
                    "Capturing. Overlay is active on the selected window."
                    if foreground and self.overlay_check.isChecked()
                    else "Capturing. Switch to the selected window to see the overlay."
                    if self.overlay_check.isChecked()
                    else "Capturing. Sample overlay is hidden."
                )
            else:
                self.preview.set_frame(None)
                self.status.setText("Waiting for a frame matching the window size…")
            if self.overlay_check.isChecked() and overlay_ready(snapshot, geometry, foreground):
                self._overlay.align(geometry.client)
            else:
                self._overlay.hide()
        except (WindowUnavailable, OSError, RuntimeError) as error:
            logger.warning("Session display stopped: %s", error)
            self._stop(str(error))

    def _open_demo(self) -> None:
        python = Path(sys.executable).with_name("pythonw.exe")
        try:
            process = subprocess.Popen([str(python), "-m", "jp_overlay.demo"])
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
