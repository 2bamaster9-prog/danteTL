"""Explicit runtime installation UI; detection, processes and disk work stay on a worker."""

import sys
import threading
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.controls import InfoButton
from jp_overlay.hardware import Adapter, detect_adapters, recommended_profile
from jp_overlay.model_store import ModelOperation, ModelProgress, Progress
from jp_overlay.runtime_setup import (
    PROFILES,
    RuntimeProfile,
    install_runtime,
    project_root,
    ready_runtime,
    select_runtime,
)


class RuntimeSetupDialog(QDialog):
    restart_requested = Signal(object)

    def __init__(
        self, parent: QWidget | None = None, *, root: Path | None = None, embedded: bool = False
    ) -> None:
        super().__init__(parent)
        self._embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.error_message = ""
        self.root = root or project_root()
        self.setWindowTitle("Runtime setup")
        self.resize(660, 460)
        self._adapters: tuple[Adapter, ...] = ()
        self._detecting = True
        self._closing = False
        self._cancelling = False
        self.operation: ModelOperation | None = ModelOperation(self._detect)
        layout = QVBoxLayout(self)
        self.hardware = QLabel("Checking installed graphics adapters…")
        self.hardware.setWordWrap(True)
        layout.addWidget(self.hardware)
        header = QHBoxLayout()
        header.addWidget(QLabel("Runtime"))
        header.addWidget(
            InfoButton(
                "Runtime",
                "Installs local inference engines with CPU or GPU support. "
                "Compatible models share these engines. "
                "Does not download model weights or update system drivers. "
                "You can override the recommendation or choose CPU.",
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.choice = QComboBox()
        for profile in PROFILES:
            self.choice.addItem(profile.name, profile)
        self.choice.setEnabled(False)
        self.choice.setToolTip(
            "Recommended from detected hardware. You can choose a different runtime."
        )
        layout.addWidget(self.choice)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        note = QLabel(
            "Needs internet access and free disk space. Your model files are kept. "
            "Restart applies the new runtime. Models are selected separately "
            "and may need first-use preparation."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.install = QPushButton("Install runtime")
        self.install.setEnabled(False)
        self.install.clicked.connect(self._install)
        layout.addWidget(self.install)
        self.restart = QPushButton("Restart now")
        self.restart.setToolTip(
            "Stops capture and waits for active workers, then opens the new runtime."
        )
        self.restart.setEnabled(False)
        self.restart.clicked.connect(self._restart)
        layout.addWidget(self.restart)
        self.later = QPushButton("Use on next launch")
        self.later.setEnabled(False)
        self.later.clicked.connect(self._later)
        layout.addWidget(self.later)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_operation if embedded else self.close)
        if embedded:
            self.cancel_button.setText("Cancel setup")
        layout.addWidget(self.cancel_button)
        self.choice.currentIndexChanged.connect(self._selected)
        self._selected()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self.operation.start()
        self._timer.start()

    def _detect(self, progress: Progress, cancel: threading.Event) -> None:
        self._adapters = detect_adapters()
        progress(ModelProgress("Hardware check complete. Nothing has been installed."))

    def _selected(self) -> None:
        profile = self.choice.currentData()
        if not isinstance(profile, RuntimeProfile):
            return
        self.description.setText(profile.description)
        ready = ready_runtime(self.root, profile.key)
        current = ready == Path(sys.prefix).resolve()
        idle = self.operation is None
        self.install.setEnabled(idle)
        self.install.setText("Verify / repair runtime" if ready else "Install runtime")
        self.restart.setEnabled(idle and bool(ready) and not current)
        self.later.setEnabled(self.restart.isEnabled())
        self.restart.setVisible(self.restart.isEnabled())
        self.later.setVisible(self.later.isEnabled())
        self.progress.setVisible(not idle)
        if self._embedded:
            self.cancel_button.setEnabled(not idle)
            self.cancel_button.setVisible(not idle and not self._detecting)
        if idle:
            self.status.setText(
                "This runtime is in use."
                if current
                else "Installed and checked. Restart now, or use it on your next launch."
                if ready
                else "Ready to install. Your current app will keep working during setup."
            )

    def _install(self) -> None:
        profile = self.choice.currentData()
        if self.operation or not isinstance(profile, RuntimeProfile):
            return
        self._closing = self._cancelling = False
        self.error_message = ""
        self.operation = ModelOperation(partial(install_runtime, self.root, profile))
        self.choice.setEnabled(False)
        self.install.setEnabled(False)
        self.restart.setEnabled(False)
        self.later.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.operation.start()

    def _poll(self) -> None:
        if self.operation is None:
            return
        value = self.operation.snapshot()
        self.status.setText(
            "Cancelling… waiting for installer processes to exit."
            if self._cancelling and not value.done
            else (value.error or value.message)[-1800:]
        )
        if not value.done:
            return
        self.operation = None
        self.error_message = value.error
        self.progress.setRange(0, 1)
        self.progress.setValue(0 if value.error or value.cancelled else 1)
        self.choice.setEnabled(True)
        if self._detecting:
            self._detecting = False
            self.hardware.setText(
                "Detected: "
                + "; ".join(
                    f"{a.name} ({a.dedicated_bytes / 2**30:.1f} GB dedicated)"
                    for a in self._adapters
                )
                if self._adapters
                else "GPU detection unavailable. CPU is the default; you can choose manually."
            )
            key = recommended_profile(self._adapters)
            self.choice.setCurrentIndex(next(i for i, p in enumerate(PROFILES) if p.key == key))
        self._selected()
        if value.error or value.cancelled:
            self.status.setText(
                (value.error or "Setup cancelled. Your current runtime was kept.")[-1800:]
            )
        if self._closing:
            self.close()

    def _restart(self) -> None:
        profile = self.choice.currentData()
        ready = ready_runtime(self.root, profile.key)
        if ready and self.operation is None:
            if not self._embedded:
                self.hide()
            self.restart_requested.emit(ready)

    def _later(self) -> None:
        profile = self.choice.currentData()
        ready = ready_runtime(self.root, profile.key)
        if ready and self.operation is None:
            try:
                select_runtime(self.root, ready)
                self.status.setText("Selected for next launch. This session continues unchanged.")
            except (OSError, ValueError) as error:
                self.status.setText(str(error))

    def reject(self) -> None:
        if self._embedded:
            self.window().close()
        else:
            self.close()

    def cancel_operation(self) -> None:
        if self.operation:
            self._cancelling = True
            self.operation.cancel()
            self.cancel_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.operation:
            self._closing = True
            self.cancel_operation()
            event.ignore()
        else:
            event.accept()
