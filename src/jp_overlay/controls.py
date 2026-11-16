"""Accessible native Qt controls with a small, consistent presentation."""

from html import escape

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QIcon,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionFocusRect,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


def add_model_section(combo: QComboBox, label: str) -> None:
    """A consistent, non-selectable category in any model selector."""
    model = combo.model()
    assert isinstance(model, QStandardItemModel)
    heading = QStandardItem(label)
    heading.setFlags(Qt.ItemFlag.NoItemFlags)
    font = combo.font()
    font.setBold(True)
    heading.setFont(font)
    heading.setForeground(QColor("#9baabc"))
    heading.setBackground(QColor("#101922"))
    heading.setSizeHint(QSize(0, max(32, combo.fontMetrics().height() + 14)))
    heading.setAccessibleDescription("Model category; not selectable")
    model.appendRow(heading)


def set_tone(widget: QWidget, tone: str) -> None:
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class StatusBanner(QWidget):
    """A visible symbol, short explanation and action; color is never the only cue."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("statusBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        body = QVBoxLayout(self)
        body.setContentsMargins(12, 10, 12, 10)
        layout = QHBoxLayout()
        body.addLayout(layout)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.action = QPushButton()
        layout.addWidget(self.action)
        self.detail = QLabel()
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        body.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setAccessibleName("Loading progress")
        body.addWidget(self.progress)
        self.detail.hide()
        self.progress.hide()
        self.hide()

    def set_message(
        self,
        text: str,
        *,
        tone: str = "warning",
        action: str = "",
        detail: str = "",
        busy: bool = False,
    ) -> None:
        symbol = "⚠" if tone in ("warning", "error") else "ⓘ"
        self.label.setText(f"{symbol}  {text[:400]}" if text else "")
        self.label.setToolTip(text)
        self.action.setText(action)
        self.action.setVisible(bool(action))
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.progress.setVisible(busy)
        set_tone(self, tone)
        self.setVisible(bool(text))


class Switch(QCheckBox):
    """Keep Qt's checkbox semantics, keyboard handling and signals; paint a switch indicator."""

    def sizeHint(self) -> QSize:
        return QSize(
            48 + self.fontMetrics().horizontalAdvance(self.text()),
            max(28, self.fontMetrics().height() + 8),
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        y = (self.height() - 20) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#4fd1bd" if self.isChecked() else "#58677a"))
        painter.drawRoundedRect(QRectF(2, y, 36, 20), 10, 10)
        painter.setBrush(QColor("#11232b" if self.isChecked() else "#edf2f7"))
        painter.drawEllipse(QRectF(20 if self.isChecked() else 4, y + 2, 16, 16))
        painter.setPen(self.palette().windowText().color())
        painter.drawText(
            QRect(48, 0, self.width() - 48, self.height()),
            Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        if self.hasFocus():
            option = QStyleOptionFocusRect()
            option.initFrom(self)
            option.rect = self.rect().adjusted(0, 1, -1, -1)
            self.style().drawPrimitive(
                QStyle.PrimitiveElement.PE_FrameFocusRect, option, painter, self
            )


class CaptureButton(QPushButton):
    """One capture action, with matching text, icon and running color."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("captureButton")
        self._icons = {}
        for running in (False, True):
            pixmap = QPixmap(36, 36)
            pixmap.setDevicePixelRatio(2)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            if running:
                painter.drawRoundedRect(QRectF(4, 4, 10, 10), 1, 1)
            else:
                painter.drawEllipse(QRectF(3, 3, 12, 12))
            painter.end()
            self._icons[running] = QIcon(pixmap)
        self.setIconSize(QSize(18, 18))
        self.set_capturing(False)

    def set_capturing(self, active: bool) -> None:
        self.setText("Stop capture" if active else "Start capture")
        self.setIcon(self._icons[active])
        set_tone(self, "recording" if active else "idle")


class OverlayToggles(QWidget):
    """Keep overlay controls together; wrap only when their labels won't fit."""

    def __init__(self, *controls: Switch) -> None:
        super().__init__()
        self._controls = controls
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(18)
        for control in self._controls:
            self._layout.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
        self._layout.addStretch(1)

    def minimumSizeHint(self) -> QSize:
        return QSize(
            max(c.minimumSizeHint().width() for c in self._controls),
            self._layout.minimumSize().height(),
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        width = sum(c.sizeHint().width() for c in self._controls) + self._layout.spacing() * (
            len(self._controls) - 1
        )
        self._layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if event.size().width() >= width
            else QBoxLayout.Direction.TopToBottom
        )
        super().resizeEvent(event)


class InfoButton(QToolButton):
    def __init__(self, name: str, explanation: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText("ⓘ")
        self.setObjectName("info")
        self.setAccessibleName(f"About {name}")
        self.setAccessibleDescription(explanation)
        self.setToolTip(f"<qt>{escape(explanation)}</qt>")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._show_help)

    def _show_help(self) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip(), self)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self._show_help()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        QToolTip.hideText()
        super().focusOutEvent(event)


class CopyTextButton(QToolButton):
    """Icon-only clipboard action with keyboard/tooltip semantics and brief feedback."""

    def __init__(self, label: str, text: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._label, self._text = label, text
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setAutoRaise(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(28, 28)
        self.setIconSize(QSize(18, 18))
        self.setStyleSheet(
            "QToolButton { border: 0; padding: 4px; background: transparent; }"
            "QToolButton:hover, QToolButton:focus { background: #304259; border-radius: 4px; }"
        )
        self._icons = {}
        for copied in (False, True):
            pixmap = QPixmap(36, 36)
            pixmap.setDevicePixelRatio(2)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#5eead4" if copied else "#9baabc"), 1.5))
            if copied:
                painter.drawLine(3, 9, 7, 13)
                painter.drawLine(7, 13, 15, 4)
            else:
                painter.drawRoundedRect(QRectF(3, 2, 9, 11), 1, 1)
                painter.setBrush(QColor("#172230"))
                painter.drawRoundedRect(QRectF(7, 6, 8, 10), 1, 1)
            painter.end()
            self._icons[copied] = QIcon(pixmap)
        self.setIcon(self._icons[False])
        self._feedback = QTimer(self)
        self._feedback.setSingleShot(True)
        self._feedback.timeout.connect(self._reset)
        self.clicked.connect(self._copy)

    def set_copy_text(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self._reset()

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self.setIcon(self._icons[True])
        self.setToolTip(self._label.replace("Copy", "Copied", 1))
        self._feedback.start(1200)

    def _reset(self) -> None:
        self._feedback.stop()
        self.setIcon(self._icons[False])
        self.setToolTip(self._label)
