"""Recognition files are a separate settings section, with no inference or worker ownership."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.controls import InfoButton, set_tone
from jp_overlay.model_values import ModelFile


class OcrModelSettings(QWidget):
    install_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        heading = QLabel("Text recognition (OCR)")
        heading.setObjectName("sectionTitle")
        header.addWidget(heading)
        header.addWidget(
            InfoButton(
                "Text recognition models",
                "OCR reads text from game images. Translation models turn that text into "
                "English. The standalone app includes MeikiOCR for Japanese; "
                "no download is needed.",
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.badge = self._label(layout)
        self.badge.setObjectName("modelBadge")
        self.summary = self._label(layout)
        self.manage = QToolButton()
        self.manage.setText("Manage OCR files")
        self.manage.setCheckable(True)
        self.manage.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.manage.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.manage)
        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.choice = QComboBox()
        self.choice.setAccessibleName("Text recognition model files")
        self.choice.setMinimumContentsLength(20)
        self.choice.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        details.addWidget(self.choice)
        self.status = self._label(details)
        self.location = self._label(details)
        self.download = QPushButton()
        self.download.clicked.connect(
            lambda: self.install_requested.emit(self.choice.currentData())
        )
        details.addWidget(self.download)
        layout.addWidget(self.details)
        self.details.hide()
        self.manage.toggled.connect(self._expanded)
        self.choice.currentIndexChanged.connect(self._selected)

    @staticmethod
    def _label(layout: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def refresh(self, bundles: tuple[ModelFile, ...]) -> None:
        selected = self.choice.currentData()
        self.choice.blockSignals(True)
        self.choice.clear()
        for bundle in bundles:
            if bundle.category == "recognition":
                self.choice.addItem(bundle.name, bundle)
                if selected and bundle.key == selected.key:
                    self.choice.setCurrentIndex(self.choice.count() - 1)
        self.choice.blockSignals(False)
        self.setVisible(self.choice.count() > 0)
        self._selected()

    def set_busy(self, busy: bool) -> None:
        self.choice.setEnabled(not busy)
        self.download.setEnabled(not busy)

    def _expanded(self, expanded: bool) -> None:
        self.manage.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.details.setVisible(expanded)

    def _selected(self) -> None:
        bundle = self.choice.currentData()
        if not isinstance(bundle, ModelFile):
            return
        present = bundle.present
        self.badge.setText(
            f"✓  {bundle.name.split(' · ')[0]} · Included with app"
            if bundle.included
            else f"✓  {bundle.name.split(' · ')[0]} · Downloaded"
            if present
            else f"↓  {bundle.name.split(' · ')[0]} · Download required"
        )
        set_tone(self.badge, "success" if present else "warning")
        self.summary.setText(
            "Reads Japanese text from game images; it does not translate it. "
            "Already included — no download needed."
            if bundle.included
            else bundle.description
        )
        self.status.setText(bundle.status)
        self.location.setText(
            f"Model folder: {bundle.local_directory}"
            + (f"\nRepairs folder: {bundle.directory}" if bundle.bundled_directory else "")
        )
        self.download.setText("Verify / repair OCR files" if present else "Download OCR files")
