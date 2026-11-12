"""Qt overlay rendering; receives geometry and never owns capture state."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from jp_overlay.diagnostics import DebugDisplay
from jp_overlay.domain import Rect, sample_box
from jp_overlay.grouping import TextBlock
from jp_overlay.text_layout import layout_english
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslatedText, TranslationRequest
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
        self._tracks: tuple[TextTrack, ...] | None = None
        self._translations: tuple[TranslatedText, ...] = ()
        self._english_mode = False
        self._blocks: tuple[TextBlock, ...] | None = None
        self._automatic_size = True
        self._manual_size = 20
        self._debug: DebugDisplay | None = None

    def set_debug(self, display: DebugDisplay | None) -> None:
        if display != self._debug:
            self._debug = display
            self.update()

    def set_translations(
        self, results: tuple[TranslatedText, ...], *, enabled: bool = False
    ) -> None:
        if results != self._translations or enabled != self._english_mode:
            self._translations = results
            self._english_mode = enabled
            self.update()

    def set_text_style(self, automatic: bool, pixels: int) -> None:
        if (automatic, pixels) != (self._automatic_size, self._manual_size):
            self._automatic_size, self._manual_size = automatic, pixels
            self.update()

    def set_blocks(self, blocks: tuple[TextBlock, ...]) -> None:
        if blocks != self._blocks:
            self._blocks = blocks
            self.update()

    def set_tracks(self, tracks: tuple[TextTrack, ...]) -> None:
        # Fresh OCR objects do not imply changed display state. Ignore confidence,
        # timestamps and character-box noise when deciding whether to repaint.
        if tracks != self._tracks:
            self._tracks = tracks
            self.update()

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
        if self._tracks is not None:
            english = {value.request: value.english for value in self._translations}
            if self._english_mode:
                blocks = self._blocks
                if blocks is None:
                    blocks = tuple(TextBlock((track,)) for track in self._tracks)
                for block in blocks:
                    text = english.get(TranslationRequest.from_block(block))
                    if text:
                        self._paint_english(painter, block, text)
                self._paint_debug(painter, ratio)
                return  # Pending regions leave the original game text visible.
            font = QFont("Segoe UI")
            font.setPixelSize(round(13 * ratio))
            painter.setFont(font)
            for track in self._tracks:
                box = track.bounds
                painter.setOpacity(self._opacity)
                painter.setPen(QPen(QColor("#5eead4"), max(2, ratio)))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(box.x, box.y, box.width, box.height))
                label = str(track.track_id)
                badge_width = max(
                    28 * ratio, painter.fontMetrics().horizontalAdvance(label) + 8 * ratio
                )
                badge = QRectF(
                    max(0, box.x - badge_width - 2 * ratio), box.y, badge_width, 20 * ratio
                )
                painter.fillRect(badge, QColor("#123a35"))
                painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
                painter.setOpacity(1.0)
            self._paint_debug(painter, ratio)
            return
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
            "Sample overlay · clicks pass through\nNative capture and alignment check",
        )
        self._paint_debug(painter, ratio)

    def _paint_debug(self, painter: QPainter, ratio: float) -> None:
        if self._debug is None:
            return
        painter.save()
        painter.setOpacity(1)
        painter.setPen(Qt.PenStyle.NoPen)
        for box in self._debug.changed:
            painter.fillRect(QRectF(box.x, box.y, box.width, box.height), QColor(255, 180, 50, 55))
        painter.setPen(QPen(QColor("#22d3ee"), max(2, ratio), Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for box in self._debug.scanned:
            painter.drawRect(
                QRectF(box.x + 1, box.y + 1, max(0, box.width - 2), max(0, box.height - 2))
            )
        font = QFont("Consolas")
        font.setPixelSize(round(12 * ratio))
        painter.setFont(font)
        metrics = painter.fontMetrics()
        lines = self._debug.text.splitlines()
        width = min(self._bounds.width - 16, max(metrics.horizontalAdvance(s) for s in lines) + 16)
        area = QRectF(8, 8, max(1, width), len(lines) * metrics.height() + 12)
        painter.fillRect(area, QColor(8, 14, 23, 230))
        painter.setPen(QColor("#e7edf5"))
        painter.setClipRect(area)
        painter.drawText(area.adjusted(8, 6, -8, -6), Qt.AlignmentFlag.AlignLeft, self._debug.text)
        painter.restore()

    def _paint_english(self, painter: QPainter, block: TextBlock, text: str) -> None:
        layout = layout_english(
            text,
            block.bounds,
            self._bounds.size,
            automatic=self._automatic_size,
            manual_pixels=self._manual_size,
            vertical=block.lines[0].vertical,
            source_line_height=block.line_height if len(block.lines) > 1 else None,
        )
        area = QRectF(layout.bounds.x, layout.bounds.y, layout.bounds.width, layout.bounds.height)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 20, 31, round(255 * self._opacity)))
        painter.drawRoundedRect(area, 4, 4)
        english_font = QFont("Segoe UI")
        english_font.setPixelSize(layout.pixel_size)
        painter.setFont(english_font)
        painter.setPen(QColor("#f1f5f9"))
        painter.setClipRect(area)
        for index, line in enumerate(layout.lines):
            painter.drawText(
                QPointF(area.x() + 4, area.y() + 4 + layout.ascent + index * layout.line_height),
                line,
            )
        painter.restore()
