"""Qt overlay rendering; receives geometry and never owns capture state."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from jp_overlay.domain import Rect, sample_box
from jp_overlay.windows import Windows


class OverlayWindow(QWidget):
    def __init__(self, windows: Windows) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setWindowTitle("JP Overlay surface")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._windows = windows
        self._bounds = Rect(0, 0, 1, 1)
        self._opacity = 0.85
        self._configured = False

    def set_opacity(self, value: int) -> None:
        self._opacity = max(0.2, min(value / 100, 1.0))
        self.update()

    def align(self, bounds: Rect) -> None:
        """Place the native window without activating it, then draw in physical pixels."""
        hwnd = int(self.winId())
        if not self._configured:
            self._windows.configure_overlay(hwnd)
            self._configured = True
        changed = self._bounds != bounds
        self._bounds = bounds
        if not self.isVisible():
            self._windows.place_overlay(hwnd, bounds)
            self.show()
            # Qt may apply its pending show geometry; enforce physical bounds afterwards.
            self._windows.place_overlay(hwnd, bounds)
        elif changed:
            self._windows.place_overlay(hwnd, bounds)
        if changed:
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ratio = self.devicePixelRatioF()
        painter.scale(1 / ratio, 1 / ratio)
        width, height = self._bounds.size
        painter.setPen(QPen(QColor("#5eead4"), max(2, ratio)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(2, 2, max(0, width - 4), max(0, height - 4)))

        box = sample_box(width, height)
        area = QRectF(box.x, box.y, box.width, box.height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 20, 31, round(255 * self._opacity)))
        painter.drawRoundedRect(area, 8 * ratio, 8 * ratio)
        font = QFont("Segoe UI")
        font.setPixelSize(max(12, round(min(height * 0.035, box.height * 0.24))))
        painter.setFont(font)
        painter.setPen(QColor("#f1f5f9"))
        painter.drawText(
            area.adjusted(12 * ratio, 4 * ratio, -12 * ratio, -4 * ratio),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            "Sample overlay · clicks pass through\nTranslation arrives in a later milestone",
        )
