"""Explicit runtime installation UI; detection, processes and disk work stay on a worker."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dantetl.application.services import SetupCommands
from dantetl.i18n import mark, tr
from dantetl.runtime.setup_values import SetupLane
from dantetl.ui.controls import InfoButton
from dantetl.ui.localization import localized, localized_item, on_language_change
from dantetl.ui.setup_progress import SetupProgressView


class RuntimeSetupDialog(QDialog):
    restart_requested = Signal(object)

    def __init__(
        self, service: SetupCommands, parent: QWidget | None = None, *, embedded: bool = False
    ) -> None:
        super().__init__(parent)
        self._embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.error_message = ""
        self.service = service
        self._completion = 0
        localized(self, windowTitle=mark("Runtime setup"))
        self.resize(660, 460)
        self._closing = False
        if not service.job(SetupLane.RUNTIME).token:
            service.detect_runtime()
        layout = QVBoxLayout(self)
        self.hardware = localized(QLabel(), text=mark("Checking installed graphics adapters…"))
        self.hardware.setWordWrap(True)
        layout.addWidget(self.hardware)
        header = QHBoxLayout()
        header.addWidget(localized(QLabel(), text=mark("Runtime")))
        header.addWidget(
            InfoButton(
                mark("Runtime"),
                mark("Switching runtimes keeps your models and requires a restart."),
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.choice = QComboBox()
        for profile in service.profiles:
            localized_item(self.choice, profile.name, profile)
        self.choice.setEnabled(False)
        localized(
            self.choice,
            toolTip=mark("Recommended from detected hardware. You can choose a different runtime."),
        )
        layout.addWidget(self.choice)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.progress_view = SetupProgressView()
        self.status = self.progress_view.status
        self.progress = self.progress_view.overall
        layout.addWidget(self.progress_view)
        self.install = localized(QPushButton(), text=mark("Install runtime"))
        self.install.setEnabled(False)
        self.install.clicked.connect(self._install)
        layout.addWidget(self.install)
        self.restart = localized(QPushButton(), text=mark("Restart now"))
        localized(
            self.restart,
            toolTip=mark("Stops capture and waits for active workers, then opens the new runtime."),
        )
        self.restart.setEnabled(False)
        self.restart.clicked.connect(self._restart)
        layout.addWidget(self.restart)
        self.later = localized(QPushButton(), text=mark("Use on next launch"))
        self.later.setEnabled(False)
        self.later.clicked.connect(self._later)
        layout.addWidget(self.later)
        self.cancel_button = localized(QPushButton(), text=mark("Cancel"))
        self.cancel_button.clicked.connect(self.cancel_operation if embedded else self.close)
        if embedded:
            localized(self.cancel_button, text=mark("Cancel setup"))
        layout.addWidget(self.cancel_button)
        self.choice.currentIndexChanged.connect(self._selected)
        active = service.job(SetupLane.RUNTIME)
        if active.key:
            for index, profile in enumerate(service.profiles):
                if profile.key == active.key:
                    self.choice.setCurrentIndex(index)
                    break
        self._selected()
        self.refresh_view()
        on_language_change(self, self._refresh_language)

    def _show_hardware(self) -> None:
        adapters = self.service.runtime.adapters
        self.hardware.setText(
            tr("Detected: ")
            + "; ".join(
                tr(
                    "{name} ({value:.1f} GB dedicated)",
                    name=a.name,
                    value=a.dedicated_bytes / 2**30,
                )
                for a in adapters
            )
            if adapters
            else tr("GPU detection unavailable. CPU is the default; you can choose manually.")
        )

    def _refresh_language(self) -> None:
        if self.choice.isEnabled():
            self._show_hardware()
        self._selected()

    @property
    def busy(self) -> bool:
        return self.service.job(SetupLane.RUNTIME).busy

    def _selected(self) -> None:
        profile = self.choice.currentData()
        if profile is None:
            return
        self.description.setText(tr(profile.description))
        ready = self.service.runtime.target(profile.key)
        current = ready is not None and ready == self.service.runtime.current
        idle = not self.busy
        self.install.setEnabled(idle)
        self.install.setText(tr("Verify / repair runtime") if ready else tr("Install runtime"))
        self.restart.setEnabled(idle and bool(ready) and not current)
        self.later.setEnabled(self.restart.isEnabled())
        self.restart.setVisible(self.restart.isEnabled())
        self.later.setVisible(self.later.isEnabled())
        self.progress.setVisible(not idle)
        if idle:
            self.progress_view.download.hide()
            self.progress_view.download_label.hide()
        if self._embedded:
            self.cancel_button.setEnabled(not idle)
            self.cancel_button.setVisible(
                not idle and self.service.job(SetupLane.RUNTIME).action != "detect"
            )
        if idle:
            self.status.setText(
                tr("✓ Supported · In use")
                if current
                else tr("✓ Supported · Restart to use")
                if ready
                else tr("Ready to install")
            )

    def _install(self) -> None:
        profile = self.choice.currentData()
        if profile is None or not self.service.install_runtime(profile.key):
            return
        self._closing = False
        self.error_message = ""
        self.choice.setEnabled(False)
        self.install.setEnabled(False)
        self.restart.setEnabled(False)
        self.later.setEnabled(False)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()

    def refresh_view(self) -> None:
        job = self.service.job(SetupLane.RUNTIME)
        if not job.token or self._completion == job.token:
            return
        value = job.progress
        self.progress_view.update_progress(value)
        self.status.setText(
            tr("Cancelling… waiting for installer processes to exit.")
            if job.cancelling and job.busy
            else (value.error or value.message)[-1800:]
        )
        if job.busy:
            return
        self._completion = job.token
        self.error_message = value.error
        self.progress.setRange(0, 1)
        self.progress.setValue(0 if value.error or value.cancelled else 1)
        self.choice.setEnabled(True)
        if job.action == "detect":
            self._show_hardware()
            key = self.service.runtime.recommendation
            self.choice.setCurrentIndex(
                next(i for i, p in enumerate(self.service.profiles) if p.key == key)
            )
        self._selected()
        if value.error or value.cancelled or job.action == "select":
            self.status.setText(
                (
                    value.error
                    or (
                        tr("Setup cancelled. Your current runtime was kept.")
                        if value.cancelled
                        else value.message
                    )
                )[-1800:]
            )
        if self._closing:
            self.close()

    def _restart(self) -> None:
        profile = self.choice.currentData()
        ready = self.service.runtime.target(profile.key)
        if ready and not self.busy:
            if not self._embedded:
                self.hide()
            self.restart_requested.emit(ready)

    def _later(self) -> None:
        profile = self.choice.currentData()
        if profile is not None and self.service.use_next_launch(profile.key):
            self._selected()

    def reject(self) -> None:
        if self._embedded:
            self.window().close()
        else:
            self.close()

    def cancel_operation(self) -> None:
        if self.busy:
            self.service.cancel(SetupLane.RUNTIME)
            self.cancel_button.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.busy:
            self._closing = True
            self.cancel_operation()
            event.ignore()
        else:
            event.accept()
