"""Shared setup progress view: setup stages and actual bytes for the active download."""

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from dantejp.i18n import tr
from dantejp.runtime.setup_values import ModelProgress


class SetupProgressView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.overall = QProgressBar()
        self.download_label = QLabel()
        self.download_label.setWordWrap(True)
        self.download = QProgressBar()
        for widget in (self.status, self.overall, self.download_label, self.download):
            layout.addWidget(widget)
        self.update_progress(ModelProgress())

    def update_progress(self, value: ModelProgress) -> None:
        self.status.setText((value.error or value.message)[-1800:])
        if value.done:
            self.overall.setRange(0, 1)
            self.overall.setValue(0 if value.error or value.cancelled else 1)
            self.overall.setFormat(
                tr("Stopped") if value.error or value.cancelled else tr("Complete")
            )
        elif value.stages:
            self.overall.setRange(0, value.stages)
            self.overall.setValue(value.stage)
            self.overall.setFormat(tr("Setup step %v of %m"))
        else:
            self.overall.setRange(0, 0)
        download = value.download
        self.download_label.setVisible(download is not None)
        self.download.setVisible(download is not None)
        if download:
            self.download_label.setText(download.name)
            self.download.setRange(0, 1000 if download.total else 0)
            if download.total:
                self.download.setValue(min(1000, round(download.received * 1000 / download.total)))
                self.download.setFormat(
                    tr(
                        "{value:.1f} / {value2:.1f} MB · %p%",
                        value=download.received / 1000000.0,
                        value2=download.total / 1000000.0,
                    )
                )
            else:
                self.download.setFormat(
                    tr("{value:.1f} MB · total unknown", value=download.received / 1000000.0)
                )
                self.download_label.setText(
                    tr(
                        "{name} · {value:.1f} MB received; total unknown",
                        name=download.name,
                        value=download.received / 1000000.0,
                    )
                )
