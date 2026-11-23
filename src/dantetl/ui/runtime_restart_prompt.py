"""Nonblocking confirmation for a user-selected, verified runtime."""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from dantetl.i18n import tr


def ask_restart(owner: QWidget, name: str, accept: Callable[[], None]) -> None:
    parent = owner.window()
    if not parent.isVisible() and (ancestor := parent.parentWidget()) is not None:
        parent = ancestor.window()
    box = QMessageBox(parent)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    box.setWindowTitle(tr("Runtime setup"))
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(tr("Restart DanteTL to use {name}.", name=tr(name)))
    box.setInformativeText(
        tr("Stops capture and waits for active workers, then opens the new runtime.")
    )
    restart = box.addButton(tr("Restart now"), QMessageBox.ButtonRole.AcceptRole)
    assert isinstance(restart, QPushButton)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(restart)
    box.finished.connect(lambda _: accept() if box.clickedButton() is restart else None)
    box.open()
