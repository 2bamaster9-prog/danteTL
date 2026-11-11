"""Frame-matched OCR inspection: zoomable image, numbered boxes, and copyable text."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.recognition import OcrResult, TextRegion


def frame_image(frame: CapturedFrame) -> QImage:
    """Detach from snapshot bytes so Qt owns the preview's pixel lifetime."""
    return QImage(
        frame.bgra, frame.width, frame.height, frame.width * 4, QImage.Format.Format_RGB32
    ).copy()


def image_target(image_size: tuple[int, int], viewport: tuple[int, int]) -> QRectF:
    """A single transform for both image and annotations, including letterboxing."""
    width, height = image_size
    scale = min(viewport[0] / width, viewport[1] / height)
    return QRectF(
        (viewport[0] - width * scale) / 2,
        (viewport[1] - height * scale) / 2,
        width * scale,
        height * scale,
    )


class CapturePreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self._regions: tuple[TextRegion, ...] = ()
        self._zoom = 0.0
        self.selected = -1
        self.characters = False
        self._resize_canvas()

    def set_frame(self, frame: CapturedFrame | None, regions: tuple[TextRegion, ...] = ()) -> None:
        self._image = frame_image(frame) if frame else QImage()
        self._regions = regions
        self._resize_canvas()
        self.update()

    def set_zoom(self, scale: float) -> None:
        self._zoom = scale
        self._resize_canvas()
        self.update()

    def _resize_canvas(self) -> None:
        if self._zoom and not self._image.isNull():
            self.setMinimumSize(
                round(self._image.width() * self._zoom), round(self._image.height() * self._zoom)
            )
        else:
            self.setMinimumSize(320, 220)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image.isNull():
            painter.setPen(Qt.GlobalColor.gray)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Your capture appears here")
            return
        target = image_target(
            (self._image.width(), self._image.height()), (self.width(), self.height())
        )
        if self._zoom:
            width, height = self._image.width() * self._zoom, self._image.height() * self._zoom
            target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image)
        scale = target.width() / self._image.width()

        def mapped(box: Rect) -> QRectF:
            return QRectF(
                target.x() + box.x * scale,
                target.y() + box.y * scale,
                box.width * scale,
                box.height * scale,
            )

        font = QFont("Segoe UI")
        font.setPixelSize(12)
        painter.setFont(font)
        for index, region in enumerate(self._regions):
            color = QColor("#fbbf24" if index == self.selected else "#5eead4")
            painter.setPen(QPen(color, 2 if index == self.selected else 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            area = mapped(region.bounds)
            painter.drawRect(area)
            if self.characters:
                painter.setPen(QPen(QColor(150, 190, 255, 160), 1))
                for char in region.characters:
                    painter.drawRect(mapped(char.bounds))
            # Put IDs beside the text so tightly spaced dialogue lines remain readable.
            badge = QRectF(max(target.x(), area.x() - 28), area.y(), 26, 18)
            painter.fillRect(badge, color)
            painter.setPen(QColor("#111923"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index + 1))


class OcrInspector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.result: OcrResult | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        self.pause = QCheckBox("Pause inspection")
        self.pause.setToolTip("Freeze this frame and its text. Capture continues; OCR work pauses.")
        toolbar.addWidget(self.pause)
        characters = QCheckBox("Character boxes")
        characters.toggled.connect(self._characters_changed)
        toolbar.addWidget(characters)
        toolbar.addStretch()
        zoom = QComboBox()
        zoom.setAccessibleName("Preview zoom")
        for label, scale in (("Fit", 0.0), ("100%", 1.0), ("200%", 2.0)):
            zoom.addItem(label, scale)
        zoom.currentIndexChanged.connect(lambda: self.preview.set_zoom(zoom.currentData()))
        toolbar.addWidget(zoom)
        self.copy_button = QPushButton("Copy text")
        self.copy_button.setToolTip("Copy the selected row, or all text when no row is selected.")
        self.copy_button.clicked.connect(self._copy_text)
        toolbar.addWidget(self.copy_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.preview = CapturePreview()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.preview)
        splitter.addWidget(scroll)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["#", "Recognized text", "Confidence"])
        self.table.setAccessibleName("Detected Japanese text")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumWidth(310)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        splitter.addWidget(self.table)
        splitter.setSizes([620, 360])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        self.details = QLabel("Select a row to highlight its box. Pause to review a stable result.")
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        layout.addWidget(self.details)
        self.clear()

    def set_result(self, result: OcrResult) -> None:
        if self.result is result:
            return
        self.result = result
        self.preview.selected = -1
        self.preview.set_frame(result.frame, result.regions)
        self.table.clearSelection()
        self.table.setRowCount(len(result.regions))
        for row, region in enumerate(result.regions):
            confidence = region.confidence
            values = (
                str(row + 1),
                region.text or "(detected, no characters recognized)",
                f"{confidence:.0%}" if confidence is not None else "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.copy_button.setEnabled(bool(result.regions))
        self._selection_changed()

    def clear(self) -> None:
        self.result = None
        self.preview.set_frame(None)
        self.table.setRowCount(0)
        self.copy_button.setEnabled(False)
        self._selection_changed()

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        row = rows[0].row() if rows else -1
        self.preview.selected = row
        self.preview.update()
        if self.result is None or not 0 <= row < len(self.result.regions):
            self.details.setText(
                "Select a row to highlight its box. Confidence is the mean character score, "
                "not a probability that the sentence is correct."
            )
            return
        region = self.result.regions[row]
        box = region.bounds
        self.details.setText(
            f"Box {row + 1}: x={box.x}, y={box.y}, {box.width} × {box.height} physical px · "
            f"{'vertical' if region.vertical else 'horizontal'} · "
            f"{len(region.characters)} recognized characters"
        )

    def _characters_changed(self, enabled: bool) -> None:
        self.preview.characters = enabled
        self.preview.update()

    def _copy_text(self) -> None:
        if self.result is None:
            return
        regions = self.result.regions
        rows = self.table.selectionModel().selectedRows()
        text = regions[rows[0].row()].text if rows else "\n".join(r.text for r in regions)
        QGuiApplication.clipboard().setText(text)
