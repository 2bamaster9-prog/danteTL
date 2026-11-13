"""Local import review. All model inspection, testing and registration runs off Qt."""

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.gguf_models import PROFILES, ImportedModel, save_registration
from jp_overlay.gguf_probe import ImportTest
from jp_overlay.llama_runtime import installed_device
from jp_overlay.model_store import ModelOperation


class ModelImportDialog(QDialog):
    models_changed = Signal()

    def __init__(
        self, parent: QWidget | None = None, *, expected: ImportedModel | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Locate imported model" if expected else "Import local GGUF model")
        self.resize(670, 600)
        self.setMinimumSize(540, 450)
        self.expected = expected
        self.operation: ModelOperation | None = None
        self.test: ImportTest | None = None
        self.gate = threading.Event()
        self.testing = False
        self._saving = False
        self._closing = False
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose a single-file GGUF chat model. The file stays in its current folder; "
            "DanteJP saves only a reference. Japanese → English remains the translation language."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.file = QLineEdit(expected.path if expected else "")
        self.file.setPlaceholderText("Path to a local .gguf file")
        self.file.setAccessibleName("Model file")
        row.addWidget(self.file, 1)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.name = QLineEdit(expected.name if expected else "")
        self.name.setMaxLength(100)
        self.name.setPlaceholderText("Use the model filename")
        self.name.setAccessibleName("Display name")
        layout.addWidget(QLabel("Display name (optional)"))
        layout.addWidget(self.name)
        self.profile = QComboBox()
        for key, label in PROFILES.items():
            self.profile.addItem(label, key)
        if expected:
            self.profile.setCurrentIndex(self.profile.findData(expected.profile))
        self.profile.setToolTip(
            "Automatic uses Gemma 4's native format or the GGUF's embedded chat template. "
            "Only choose another format when the model's documentation specifies it."
        )
        layout.addWidget(QLabel("Prompt format"))
        layout.addWidget(self.profile)
        self.status = QLabel(
            "Test the model to check this app's runtime and view sample translations."
        )
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText(
            "Test translations and timings appear here. "
            "Passing a test does not guarantee translation quality."
        )
        layout.addWidget(self.results, 1)
        note = QLabel(
            "Testing temporarily pauses translation to free model memory; capture continues. "
            "Your previous selection resumes after testing. First GPU use may take a minute."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        self.test_button = QPushButton("Test compatibility")
        self.test_button.clicked.connect(self.start_test)
        self.add_button = QPushButton("Update location" if expected else "Add model")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add)
        self.cancel_button = QPushButton("Close")
        self.cancel_button.clicked.connect(self._cancel_or_close)
        for button in (self.test_button, self.add_button, self.cancel_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.file.textChanged.connect(self._invalidate)
        self.profile.currentIndexChanged.connect(self._invalidate)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _browse(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Choose local model", self.file.text(), "GGUF models (*.gguf)"
        )
        if filename:
            self.file.setText(filename)

    def _invalidate(self) -> None:
        self.test = None
        self.add_button.setEnabled(False)
        self.results.clear()

    def start_test(self) -> None:
        if self.operation:
            return
        device = installed_device()
        if not device:
            self.status.setText(
                "A language-model engine is needed. "
                "Open Settings → Acceleration and select CPU or GPU."
            )
            return
        self.gate.clear()
        self.testing = True
        self.test = ImportTest(
            Path(self.file.text()), self.profile.currentData(), device, self.gate
        )
        self.operation = ModelOperation(self.test.run)
        self._set_busy(True)
        self.results.clear()
        self.operation.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.file, self.name, self.browse, self.profile, self.test_button):
            widget.setEnabled(not busy)
        self.add_button.setEnabled(False)
        self.cancel_button.setText("Cancel" if busy else "Close")
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)

    def _add(self) -> None:
        if self.operation or not self.test or not self.test.result:
            return
        model = replace(
            self.test.result.model,
            name=" ".join(self.name.text().split()) or Path(self.test.result.model.path).stem[:100],
        )
        self._saving = True
        self.operation = ModelOperation(lambda progress, cancel: save_registration(model))
        self._set_busy(True)
        self.operation.start()

    def cancel(self) -> None:
        if self.operation:
            self.operation.cancel()
            self.status.setText("Cancelling… waiting for the test process to stop.")

    def _cancel_or_close(self) -> None:
        if self.operation:
            self.cancel()
        else:
            self.close()

    def _poll(self) -> None:
        if not self.operation:
            return
        value = self.operation.snapshot()
        self.status.setText(value.error or value.message)
        self.progress.setRange(0, 1000 if value.total else 0)
        if value.total:
            self.progress.setValue(round(value.received / value.total * 1000))
        if not value.done:
            return
        self.operation = None
        self.testing = False
        self._set_busy(False)
        succeeded = not value.error and not value.cancelled
        if self._saving:
            self._saving = False
            if succeeded:
                self.models_changed.emit()
                self.accept()
        elif succeeded and self.test and self.test.result:
            result = self.test.result
            if self.expected and result.model.key != self.expected.key:
                self.status.setText(
                    "This is a different model. Import it separately; "
                    "the original registration was kept."
                )
                return
            self.results.setPlainText(
                f"{result.model.name}\nArchitecture: {result.model.architecture} · "
                f"Format: {PROFILES[result.model.profile]}\n"
                f"{result.model.size / 2**30:.2f} GiB on disk · Tested: {result.device.upper()}"
                + (f" · {result.offloaded_layers} GPU layers" if result.offloaded_layers else "")
                + f"\nLoad + warm-up: {result.load_ms / 1000:.1f} s\n\n"
                + "\n\n".join(
                    f"{source}\n{english}\n{ms:.0f} ms" for source, english, ms in result.samples
                )
            )
            self.add_button.setEnabled(True)
        if self._closing:
            self.close()

    def reject(self) -> None:
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.operation:
            self._closing = True
            self.cancel()
            event.ignore()
        else:
            event.accept()
