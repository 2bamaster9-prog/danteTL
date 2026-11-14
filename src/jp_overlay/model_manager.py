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
from jp_overlay.gguf_models import ImportedModel, read_registry, save_registration
from jp_overlay.model_import_dialog import ModelImportDialog
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
        self._operation: ModelOperation | None = None
        self.import_dialog: ModelImportDialog | None = None
        self._closing = False
        self._cancelling = False
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        header.addWidget(QLabel("Model"))
        header.addWidget(
            InfoButton(
                "Model downloads",
                "Choose a model to download or verify. "
                "MeikiOCR reads Japanese text; translation models turn it into English. "
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
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.location = QLabel()
        self.location.setTextFormat(Qt.TextFormat.PlainText)
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
        imports = QHBoxLayout()
        self.import_button = QPushButton("Import GGUF…")
        self.import_button.clicked.connect(lambda: self._import())
        self.locate_button = QPushButton("Locate file…")
        self.locate_button.clicked.connect(self._locate)
        self.remove_button = QPushButton("Remove from list")
        self.remove_button.setToolTip(
            "Removes the registration only. Your model file is never deleted."
        )
        self.remove_button.clicked.connect(self._remove)
        for button in (self.import_button, self.locate_button, self.remove_button):
            imports.addWidget(button)
        layout.addLayout(imports)
        self.choice.currentIndexChanged.connect(self._selected)
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def refresh(self) -> None:
        """Refresh files installed by another setup view without disturbing active downloads."""
        if self.operation is None:
            selected = self.choice.currentData()
            try:
                imported = read_registry()
            except (OSError, ValueError) as error:
                self.error_message = f"Could not read imported models: {error}"
                self.status.setText(self.error_message)
                return
            self.choice.blockSignals(True)
            self.choice.clear()
            for item in (*self._bundles, *imported):
                self.choice.addItem(item.name, item)
                if selected and item.key == selected.key:
                    self.choice.setCurrentIndex(self.choice.count() - 1)
            self.choice.blockSignals(False)
            self._selected()

    @property
    def operation(self) -> ModelOperation | None:
        return self._operation or (self.import_dialog.operation if self.import_dialog else None)

    @property
    def probe_active(self) -> bool:
        return bool(self.import_dialog and self.import_dialog.testing)

    def allow_probe(self) -> None:
        if self.import_dialog:
            self.import_dialog.gate.set()

    def _import(self, expected: ImportedModel | None = None) -> None:
        if self.operation:
            return
        self.error_message = ""
        if self.import_dialog and self.import_dialog.isVisible():
            self.import_dialog.raise_()
            return
        if self.import_dialog:
            self.import_dialog.deleteLater()
        self.import_dialog = ModelImportDialog(self, expected=expected)
        self.import_dialog.models_changed.connect(self._imported)
        self.import_dialog.show()

    def _imported(self) -> None:
        self.refresh()
        self.models_changed.emit()

    def _locate(self) -> None:
        value = self.choice.currentData()
        if isinstance(value, ImportedModel):
            self._import(value)

    def _remove(self) -> None:
        value = self.choice.currentData()
        if self.operation or not isinstance(value, ImportedModel):
            return
        self._operation = ModelOperation(
            lambda progress, cancel: save_registration(value, remove=True)
        )
        self.choice.setEnabled(False)
        self._operation.start()

    def _selected(self) -> None:
        self._refresh_badges()
        bundle = self.choice.currentData()
        imported = isinstance(bundle, ImportedModel)
        self.locate_button.setVisible(imported)
        self.remove_button.setVisible(imported)
        self.download.setVisible(not imported)
        if isinstance(bundle, ImportedModel):
            from jp_overlay.llama_runtime import installed_device

            self.description.setText(
                f"Imported · {bundle.architecture} · {bundle.size / 2**30:.2f} GiB on disk. "
                "Local Japanese → English translation. Quality depends on the model."
            )
            self.location.setText(f"Referenced file: {bundle.path}")
            self.status.setText(
                "File is missing or changed size. Use Locate file to check its new location."
                if not bundle.available()
                else "Language-model engine missing. Open Acceleration to set up CPU or GPU."
                if installed_device() is None
                else "Local model registered. Select it on the main screen to prepare and use it."
            )
            return
        if not isinstance(bundle, ModelBundle):
            return
        self.description.setText(
            f"{bundle.description}\nModel size: {bundle.size / 1e6:.1f} MB. "
            "Processing stays offline after setup."
        )
        self.status.setText(model_status(bundle))
        self.location.setText(
            f"Model folder: {bundle.local_directory}"
            + (f"\nRepairs folder: {bundle.directory}" if bundle.bundled_directory else "")
        )
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
            elif isinstance(candidate, ImportedModel):
                self.choice.setItemText(
                    i, f"{'✓' if candidate.available() else '⚠'}  {candidate.name} · Imported"
                )
        bundle = self.choice.currentData()
        if isinstance(bundle, ImportedModel):
            present = bundle.available()
            self.download_badge.setText(
                "✓  Local file registered" if present else "⚠  Locate model file"
            )
            self.download_badge.setToolTip(
                "Compatibility was tested during import; integrity is checked on load."
            )
            set_tone(self.download_badge, "success" if present else "warning")
            self.download_badge.show()
            self.runtime_badge.hide()
            return
        if not isinstance(bundle, ModelBundle):
            self.download_badge.hide()
            self.runtime_badge.hide()
            return
        downloaded = bundle.present()
        self.download_badge.setText(
            "✓  Included with app"
            if bundle.included
            else "✓  Downloaded"
            if downloaded
            else "↓  Download required"
        )
        self.download_badge.setAccessibleName(self.download_badge.text())
        self.download_badge.setToolTip("Model files are present. Integrity is checked before use.")
        set_tone(self.download_badge, "success" if downloaded else "warning")
        self.download_badge.show()
        from jp_overlay.llama_runtime import installed_device

        device = installed_device() if downloaded and bundle.language_model else None
        self.runtime_badge.setText(
            "⚠  CPU ready — translations may be slower; GPU optional"
            if device == "cpu"
            else "⚠  Engine setup required — choose CPU or GPU"
        )
        self.runtime_badge.setVisible(
            downloaded and bundle.language_model and device in (None, "cpu")
        )

    def _download(self) -> None:
        bundle = self.choice.currentData()
        if self.operation is not None or not isinstance(bundle, ModelBundle):
            return
        self._closing = self._cancelling = False
        self.error_message = ""
        self._operation = ModelOperation(partial(install_model, bundle))
        self.choice.setEnabled(False)
        self.download.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self._operation.start()

    def _cancel(self) -> None:
        if self.import_dialog:
            self.import_dialog.cancel()
        if self._operation:
            self._cancelling = True
            self._operation.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling… finishing the current network read.")

    def _poll(self) -> None:
        busy = self.operation is not None
        self.import_button.setEnabled(not busy)
        self.locate_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy)
        self.download.setEnabled(not busy)
        if self._operation is None:
            if self._closing and not busy:
                self.close()
            return
        value = self._operation.snapshot()
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
            self._operation = None
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
            if isinstance(bundle, ImportedModel) and not value.error:
                self.refresh()
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
