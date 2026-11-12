"""Small model download dialog; all I/O and hashing belong to its worker."""

from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.model_store import ModelBundle, ModelOperation, install_model, model_status


class ModelManager(QDialog):
    models_changed = Signal()
    runtime_requested = Signal()

    def __init__(self, bundles: tuple[ModelBundle, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Local models")
        self.resize(640, 460)
        self.setMinimumSize(580, 420)
        self._bundles = bundles
        self.operation: ModelOperation | None = None
        self._closing = False
        self._cancelling = False
        layout = QVBoxLayout(self)
        self.choice = QComboBox()
        for bundle in bundles:
            self.choice.addItem(bundle.name, bundle)
        layout.addWidget(self.choice)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.location = QLabel()
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.location)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.download = QPushButton("Download")
        self.download.clicked.connect(self._download)
        layout.addWidget(self.download)
        self.cancel_button = QPushButton("Cancel download")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self.runtime_button = QPushButton("Runtime setup…")
        self.runtime_button.setToolTip(
            "Detect graphics cards and install acceleration inside the app."
        )
        self.runtime_button.clicked.connect(self.runtime_requested.emit)
        layout.addWidget(self.runtime_button)
        self.choice.currentIndexChanged.connect(self._selected)
        self._selected()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _selected(self) -> None:
        bundle = self.choice.currentData()
        if not isinstance(bundle, ModelBundle):
            return
        self.description.setText(
            f"{bundle.description}\nDownload: {bundle.size / 1e6:.1f} MB. "
            "Processing stays offline after setup."
        )
        self.status.setText(model_status(bundle))
        self.location.setText(f"Model folder: {bundle.directory}")
        self.download.setText("Verify / repair" if bundle.present() else "Download")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

    def _download(self) -> None:
        bundle = self.choice.currentData()
        if self.operation is not None or not isinstance(bundle, ModelBundle):
            return
        self._closing = self._cancelling = False
        self.operation = ModelOperation(partial(install_model, bundle))
        self.choice.setEnabled(False)
        self.download.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.operation.start()

    def _cancel(self) -> None:
        if self.operation:
            self._cancelling = True
            self.operation.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling… finishing the current network read.")

    def _poll(self) -> None:
        if self.operation is None:
            return
        value = self.operation.snapshot()
        self.status.setText(
            "Cancelling… finishing the current network read."
            if self._cancelling and not value.done
            else value.error or value.message
        )
        self.progress.setRange(0, 1000 if value.total else 0)
        if value.total:
            self.progress.setValue(round(value.received / value.total * 1000))
            self.progress.setFormat(f"{value.received / 1e6:.1f} / {value.total / 1e6:.1f} MB")
        if value.done:
            self.operation = None
            self.choice.setEnabled(True)
            self.download.setEnabled(True)
            self.cancel_button.setEnabled(False)
            bundle = self.choice.currentData()
            if not value.error and not value.cancelled and isinstance(bundle, ModelBundle):
                self.status.setText(model_status(bundle))
                self.download.setText("Verify / repair")
            self.models_changed.emit()
            if self._closing:
                self.close()

    def reject(self) -> None:
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.operation:
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            event.accept()
