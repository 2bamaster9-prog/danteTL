"""Accessible native Qt controls with a small, consistent presentation."""

from html import escape

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFocusEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOptionFocusRect,
    QToolButton,
    QToolTip,
    QWidget,
)


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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.action = QPushButton()
        layout.addWidget(self.action)
        self.hide()

    def set_message(self, text: str, *, tone: str = "warning", action: str = "") -> None:
        symbol = "⚠" if tone in ("warning", "error") else "ⓘ"
        self.label.setText(f"{symbol}  {text[:400]}" if text else "")
        self.label.setToolTip(text)
        self.action.setText(action)
        self.action.setVisible(bool(action))
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
