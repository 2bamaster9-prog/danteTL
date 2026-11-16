"""Responsive, labelled main controls; diagnostics has its own expanding area."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


class MainSections(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)
        self.game, self.game_layout = self._card("Game & overlay")
        self.translation, self.translation_layout = self._card("Translation")
        self._wide: bool | None = None
        self._arrange(False)

    @staticmethod
    def _card(title: str) -> tuple[QWidget, QVBoxLayout]:
        card = QWidget()
        card.setObjectName("controlCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        return card, layout

    def _arrange(self, wide: bool) -> None:
        if self._wide == wide:
            return
        self._wide = wide
        self._grid.removeWidget(self.game)
        self._grid.removeWidget(self.translation)
        self._grid.addWidget(self.game, 0, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self._grid.addWidget(
            self.translation,
            0 if wide else 1,
            1 if wide else 0,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1 if wide else 0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange(event.size().width() >= 1040)
