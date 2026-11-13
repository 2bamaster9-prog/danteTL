"""Skippable guided setup; one explicit action owns one cancellable background operation."""

from pathlib import Path
from threading import Event

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.first_run import SetupPlan, needs_runtime, run_setup
from jp_overlay.hardware import HardwareCheck, HardwareStatus, recommended_profile
from jp_overlay.model_store import ModelBundle, ModelOperation, ModelProgress, Progress
from jp_overlay.runtime_setup import PROFILES, RuntimeProfile, project_root
from jp_overlay.setup_progress import SetupProgressView


class SetupAssistant(QDialog):
    completed = Signal(str, object)  # desired model ID, optional verified runtime to restart
    skipped = Signal()

    def __init__(
        self,
        models: tuple[ModelBundle, ...],
        hardware: HardwareCheck | None,
        parent: QWidget,
        *,
        root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DanteJP · Welcome")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(640, 510)
        self.root = root or project_root()
        self.models = {model.key: model for model in models}
        self.hardware = hardware
        self.hardware_status: HardwareStatus | None = None
        self.operation: ModelOperation | None = None
        self.target: Path | None = None
        self._closing = self._finished = self._reported = False
        self._runtime_chosen = False
        self._plan: SetupPlan | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        self.heading = QLabel("Welcome to DanteJP")
        self.heading.setObjectName("heading")
        layout.addWidget(self.heading)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        page = self._page()
        page.addWidget(
            self._label(
                (
                    "Text recognition is included with DanteJP. This guide helps you choose "
                    "a translation model and optional GPU acceleration.\n\n"
                    if self.models["ocr"].included
                    else "Translate Japanese games locally. This guide sets up text recognition, "
                    "a translation model and optional GPU acceleration.\n\n"
                )
                + "You choose what to download before anything starts. "
                "CPU support works without a GPU. "
                "Processing stays on your PC after setup.\n\n"
                "You can skip this and reopen Setup assistant from Settings."
            )
        )
        page.addStretch()
        page = self._page()
        page.addWidget(
            self._label(
                "✓ MeikiOCR is included with the app. Choose a translation model:"
                if self.models["ocr"].included
                else "MeikiOCR reads the Japanese text (46 MB). Choose a translator:"
            )
        )
        self.model = QComboBox()
        for key in ("gemma", "sugoi"):
            if key in self.models:
                bundle = self.models[key]
                suffix = " · downloaded" if bundle.present() else f" · {bundle.size / 1e9:.2f} GB"
                self.model.addItem(bundle.name + suffix, key)
        page.addWidget(self.model)
        self.model_help = self._label("")
        page.addWidget(self.model_help)
        self.model.currentIndexChanged.connect(self._model_changed)
        self._model_changed()
        page.addStretch()
        page = self._page()
        self.hardware_label = self._label("Checking graphics hardware…")
        page.addWidget(self.hardware_label)
        self.runtime = QComboBox()
        for profile in (PROFILES[2], PROFILES[0], PROFILES[1]):
            self.runtime.addItem(profile.name, profile)
        page.addWidget(self.runtime)
        self.runtime_help = self._label("")
        page.addWidget(self.runtime_help)
        self.runtime.currentIndexChanged.connect(self._runtime_changed)
        self.runtime.activated.connect(self._runtime_changed)
        self._runtime_changed()
        self._runtime_chosen = False
        page.addWidget(
            self._label(
                "GPU acceleration is optional. Detection does not guarantee driver compatibility. "
                "We verify the libraries before offering a restart. Drivers are never changed."
            )
        )
        page.addStretch()
        page = self._page()
        self.review = self._label("")
        page.addWidget(self.review)
        page.addStretch()
        page = self._page()
        self.progress_view = SetupProgressView()
        page.addWidget(self.progress_view)
        self.result_note = self._label("")
        page.addWidget(self.result_note)
        page.addStretch()
        buttons = QHBoxLayout()
        self.skip = QPushButton("Skip for now")
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        self.next.setObjectName("primary")
        buttons.addWidget(self.skip)
        buttons.addStretch()
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        self.skip.clicked.connect(self._skip)
        self.back.clicked.connect(lambda: self._show(self.pages.currentIndex() - 1))
        self.next.clicked.connect(self._next)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._show(0)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    def _page(self) -> QVBoxLayout:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(16)
        self.pages.addWidget(widget)
        return layout

    def _model_changed(self) -> None:
        self.model_help.setText(
            "Gemma offers more natural dialogue and recent conversation context. "
            "It works on CPU; a GPU usually makes it faster."
            if self.model.currentData() == "gemma"
            else "Sugoi is fast and compact on CPU. Translation quality can be less natural. "
            "Review its upstream license before redistributing model files."
        )

    def _runtime_changed(self) -> None:
        self._runtime_chosen = True
        profile = self.runtime.currentData()
        self.runtime_help.setText(profile.description)

    def _show(self, page: int) -> None:
        self.pages.setCurrentIndex(page)
        self.heading.setText(
            (
                "Welcome to DanteJP",
                "Choose your translation model",
                "Choose acceleration",
                "Review setup",
                "Setting up DanteJP",
            )[page]
        )
        self.back.setVisible(0 < page < 4)
        self.next.setText("Download and set up" if page == 3 else "Next")
        self.next.setEnabled(page != 2 or self.hardware_status is not None)
        if page == 3:
            assert self.hardware_status is not None
            profile: RuntimeProfile = self.runtime.currentData()
            ocr = self.models["ocr"]
            self._plan = SetupPlan(
                (() if ocr.included else (ocr,)) + (self.models[self.model.currentData()],),
                profile if needs_runtime(profile, self.hardware_status) else None,
            )
            pending = sum(m.size for m in self._plan.models if not m.present())
            self.review.setText(
                f"Recognition: MeikiOCR{' · included, no download' if ocr.included else ''}\n"
                f"Translation: {self.model.currentText()}\n"
                f"Runtime: {profile.name}\n\n"
                f"Model downloads: up to {pending / 1e9:.2f} GB; "
                "existing files are verified and reused.\n"
                + (
                    "Runtime libraries and app dependencies will also be downloaded. "
                    "NVIDIA libraries add about 1.3 GB; CPU and Vulkan downloads are smaller. "
                    "Restart is offered when ready.\n"
                    if self._plan.runtime
                    else "Your current runtime provides this support; no runtime install needed.\n"
                )
                + "\nNothing has downloaded yet. Download and set up starts the selected work. "
                "You can cancel; completed verified files are kept."
            )

    def _next(self) -> None:
        page = self.pages.currentIndex()
        if page < 3:
            self._show(page + 1)
        elif page == 3 or (page == 4 and not self._finished):
            self._start()
        else:
            self._finish(self.target)

    def _start(self) -> None:
        if self.operation or self._plan is None:
            return
        plan = self._plan
        self.target = None
        self._show(4)
        self.next.setEnabled(False)
        self.skip.setText("Cancel setup")
        self.result_note.setText("")
        self.progress_view.update_progress(ModelProgress("Starting selected setup…"))

        def action(progress: Progress, cancel: Event) -> None:
            self.target = run_setup(plan, self.root, progress, cancel)

        self.operation = ModelOperation(action)
        self.operation.start()

    @property
    def busy(self) -> bool:
        return self.operation is not None

    def cancel(self) -> None:
        if self.operation:
            self.operation.cancel()
            self.skip.setEnabled(False)
            self.result_note.setText(
                "Cancelling… waiting for the current read or installer to stop."
            )

    def _poll(self) -> None:
        if self.hardware_status is None:
            status = (
                self.hardware.snapshot() if self.hardware else HardwareStatus(error="Unavailable")
            )
            if status is not None:
                self.hardware_status = status
                self.hardware_label.setText(
                    "Hardware detection failed. CPU is available; you can choose manually."
                    if status.error
                    else "Detected: " + "; ".join(a.name for a in status.adapters)
                    if status.adapters
                    else "No supported GPU detected. CPU is available."
                )
                if not self._runtime_chosen:
                    key = recommended_profile(status.adapters)
                    self.runtime.setCurrentIndex(
                        next(
                            i
                            for i in range(self.runtime.count())
                            if self.runtime.itemData(i).key == key
                        )
                    )
                if self.pages.currentIndex() == 2:
                    self.next.setEnabled(True)
        if self.operation is None:
            return
        value = self.operation.snapshot()
        self.progress_view.update_progress(value)
        if not value.done:
            return
        self.operation = None
        self.skip.setEnabled(True)
        self.next.setEnabled(True)
        self._finished = not (value.error or value.cancelled)
        self.skip.setText("Finish without restart" if self._finished and self.target else "Close")
        self.next.setText(
            "Restart now"
            if self._finished and self.target
            else "Finish"
            if self._finished
            else "Retry setup"
        )
        self.back.setVisible(not self._finished)
        self.result_note.setText(
            "Your chosen model will be selected next. Gemma asks before first-use preparation."
            if self._finished
            else "Verified files and your previous runtime were kept."
        )
        if self._closing:
            self.close()

    def _finish(self, target: Path | None) -> None:
        self._reported = True
        self._timer.stop()
        self.hide()
        key = "gemma" if self.model.currentData() == "gemma" else "sugoi-fast"
        self.completed.emit(key, target)
        self.accept()

    def _skip(self) -> None:
        if self.operation:
            self.cancel()
        elif self._finished:
            self._finish(None)
        else:
            self.close()

    def reject(self) -> None:
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.operation:
            self._closing = True
            self.cancel()
            event.ignore()
            return
        self._timer.stop()
        if not self._reported:
            self._reported = True
            if self._finished:
                key = "gemma" if self.model.currentData() == "gemma" else "sugoi-fast"
                self.completed.emit(key, None)
            else:
                self.skipped.emit()
        event.accept()
