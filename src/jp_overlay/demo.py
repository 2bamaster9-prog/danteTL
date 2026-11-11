"""An interactive animated target for checking capture, resize, and click-through."""

import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from jp_overlay.domain import sample_box
from jp_overlay.windows import Windows


class DemoWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JP Overlay Demo")
        self.resize(900, 580)
        self.setMinimumSize(440, 330)
        self.clicks = 0
        self.phase = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(35, 35, 35, 35)
        heading = QLabel("Capture & overlay playground")
        heading.setStyleSheet("font-size: 22px; font-weight: 600; color: #eff6ff;")
        layout.addWidget(heading)
        hint = QLabel(
            "Move or resize this window. The teal overlay should follow the client edges."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b1c6dc;")
        layout.addWidget(hint)
        self.counter = QLabel("Clicks received: 0")
        self.counter.setStyleSheet("color: #5eead4; font-size: 18px;")
        layout.addWidget(self.counter)
        layout.addStretch()
        self.button = QPushButton("Click through the overlay")
        self.button.setStyleSheet("background: #365d77; color: white; padding: 12px;")
        self.button.clicked.connect(self._clicked)
        self.button.setParent(self)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._animate)
        self.timer.start()

    def _clicked(self) -> None:
        self.clicks += 1
        self.counter.setText(f"Clicks received: {self.clicks}")

    def _animate(self) -> None:
        self.phase = (self.phase + 1) % 100
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172d42"))
        # Solid corner markers let live checks verify client cropping independently.
        painter.fillRect(0, 0, 16, 16, QColor("#ff00ff"))
        painter.fillRect(self.width() - 16, self.height() - 16, 16, 16, QColor("#ffff00"))
        painter.fillRect(
            35, 180, round((self.width() - 70) * self.phase / 100), 6, QColor("#5eead4")
        )
        box = sample_box(self.width(), self.height())
        painter.fillRect(box.x, box.y, box.width, box.height, QColor("#29465e"))
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Yu Gothic UI", 16))
        painter.drawText(
            QRectF(box.x, box.y, box.width, box.height / 2),
            Qt.AlignmentFlag.AlignCenter,
            "新しい冒険が、ここから始まる。",
        )
        self.button.setGeometry(
            box.x + 20, box.y + box.height // 2, box.width - 40, box.height // 2 - 8
        )


def main() -> None:
    Windows().enable_dpi_awareness()
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
