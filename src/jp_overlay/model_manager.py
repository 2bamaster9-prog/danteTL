"""Small model download dialog; all I/O and hashing belong to its worker."""

from functools import partial

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

from jp_overlay.controls import InfoButton, set_tone
from jp_overlay.model_store import ModelBundle, ModelOperation, install_model, model_status


class ModelManager(QDialog):
    models_changed = Signal()
    runtime_requested = Signal()

    def __init__(
        self,
        bundles: tuple[ModelBundle, ...],
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(parent)
        self._embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("Local models")
        if not embedded:
            self.resize(640, 460)
            self.setMinimumSize(580, 420)
        self.error_message = ""
        self._bundles = bundles
        self.operation: ModelOperation | None = None
        self._closing = False
        self._cancelling = False
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("Model"))
        header.addWidget(
            InfoButton(
                "Model downloads",
                "Choose a model to download or verify. "
                "MeikiOCR reads Japanese text; Sugoi and Gemma translate it. "
                "Downloads need internet access; recognition and translation stay local.",
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.choice = QComboBox()
        for bundle in bundles:
            self.choice.addItem(bundle.name, bundle)
        layout.addWidget(self.choice)
        self.download_badge = QLabel()
        self.download_badge.setObjectName("modelBadge")
        self.download_badge.setWordWrap(True)
        layout.addWidget(self.download_badge)
        self.runtime_badge = QLabel()
        self.runtime_badge.setObjectName("modelBadge")
        self.runtime_badge.setWordWrap(True)
        set_tone(self.runtime_badge, "warning")
        layout.addWidget(self.runtime_badge)
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
        self.download.setEnabled(bool(bundles))
        self.download.clicked.connect(self._download)
        layout.addWidget(self.download)
        self.cancel_button = QPushButton("Cancel download")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        layout.addWidget(self.cancel_button)
        self.runtime_button = QPushButton("Set up acceleration…")
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
        self._refresh_badges()
        bundle = self.choice.currentData()
        if not isinstance(bundle, ModelBundle):
            return
        self.description.setText(
            f"{bundle.description}\nModel size: {bundle.size / 1e6:.1f} MB. "
            "Processing stays offline after setup."
        )
        self.status.setText(model_status(bundle))
        self.location.setText(f"Model folder: {bundle.directory}")
        self.download.setText("Verify / repair" if bundle.present() else "Download")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.cancel_button.hide()

    def _refresh_badges(self) -> None:
        for i in range(self.choice.count()):
            candidate = self.choice.itemData(i)
            if isinstance(candidate, ModelBundle):
                self.choice.setItemText(
                    i, f"{'✓' if candidate.present() else '↓'}  {candidate.name}"
                )
        bundle = self.choice.currentData()
        if not isinstance(bundle, ModelBundle):
            self.download_badge.hide()
            self.runtime_badge.hide()
            return
        downloaded = bundle.present()
        self.download_badge.setText("✓  Downloaded" if downloaded else "↓  Download required")
        self.download_badge.setAccessibleName(self.download_badge.text())
        self.download_badge.setToolTip("Model files are present. Integrity is checked before use.")
        set_tone(self.download_badge, "success" if downloaded else "warning")
        self.download_badge.show()
        from jp_overlay.gemma import installed_device

        missing_runtime = downloaded and bundle.key == "gemma" and installed_device() is None
        self.runtime_badge.setText("⚠  Acceleration setup required — model files are downloaded")
        self.runtime_badge.setVisible(missing_runtime)

    def _download(self) -> None:
        bundle = self.choice.currentData()
        if self.operation is not None or not isinstance(bundle, ModelBundle):
            return
        self._closing = self._cancelling = False
        self.error_message = ""
        self.operation = ModelOperation(partial(install_model, bundle))
        self.choice.setEnabled(False)
        self.download.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
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
            self.error_message = value.error
            self.operation = None
            self.choice.setEnabled(True)
            self.download.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.cancel_button.hide()
            self.progress.hide()
            bundle = self.choice.currentData()
            if not value.error and not value.cancelled and isinstance(bundle, ModelBundle):
                self.status.setText(model_status(bundle))
                self.download.setText("Verify / repair")
            self._refresh_badges()
            self.models_changed.emit()
            if self._closing:
                self.close()

    def reject(self) -> None:
        if self._embedded:
            self.window().close()
        else:
            self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.operation:
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            event.accept()
