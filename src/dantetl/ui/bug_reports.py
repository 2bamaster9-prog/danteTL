"""User-initiated bug reports from About and error dialogs."""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from dantetl.i18n import tr
from dantetl.runtime.release_values import ISSUES_URL
from dantetl.ui.localization import localized


def bug_report_link() -> str:
    label = escape(tr("Report a bug on GitHub"))
    return f'<a href="{ISSUES_URL}" style="color: #5eead4">{label}</a>'


def error_dialog(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    icon: QMessageBox.Icon = QMessageBox.Icon.Warning,
    button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
) -> QMessageBox:
    box = QMessageBox(parent)
    box.setOption(QMessageBox.Option.DontUseNativeDialog)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setStandardButtons(button)
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    box.setText(escape(message).replace("\n", "<br>"))
    return localized(box, informativeText=bug_report_link)
