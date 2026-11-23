"""Small explicit shortcut editor: choosing keys cannot accidentally trigger an action."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dantetl.application.hotkeys import KEYS, MODIFIERS, HotkeyAction, Hotkeys
from dantetl.i18n import mark, tr
from dantetl.ui.controls import InfoButton, StatusBanner, Switch
from dantetl.ui.localization import localized, localized_item, on_language_change


class _ShortcutRow(QWidget):
    def __init__(self, name: str, help: str, value: str) -> None:
        super().__init__()
        self.committed = value
        self.error = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(localized(QLabel(), text=name))
        header.addWidget(InfoButton(name, help))
        header.addStretch()
        layout.addLayout(header)
        fields = QHBoxLayout()
        self.modifiers = QComboBox()
        self.modifiers.addItems(list(MODIFIERS))
        localized(self.modifiers, accessibleName=lambda: tr("{name} modifiers", name=tr(name)))
        self.key = QComboBox()
        localized_item(self.key, mark("Disabled"), "")
        for key in KEYS:
            self.key.addItem(key, key)
        localized(self.key, accessibleName=lambda: tr("{name} key", name=tr(name)))
        self.apply = localized(QPushButton(), text=mark("Apply"))
        localized(self.apply, accessibleName=lambda: tr("Apply {name} shortcut", name=tr(name)))
        fields.addWidget(self.modifiers)
        fields.addWidget(self.key)
        fields.addWidget(self.apply)
        fields.addStretch()
        layout.addLayout(fields)
        self.status = StatusBanner()
        layout.addWidget(self.status)
        modifiers, _, key = value.rpartition("+")
        if value:
            self.modifiers.setCurrentText(modifiers)
            self.key.setCurrentIndex(self.key.findData(key))
        self.modifiers.setEnabled(bool(value))
        self.key.currentIndexChanged.connect(
            lambda _: self.modifiers.setEnabled(bool(self.key.currentData()))
        )

    @property
    def draft(self) -> str:
        key = self.key.currentData()
        return f"{self.modifiers.currentText()}+{key}" if key else ""


class HotkeySettings(QWidget):
    changed = Signal()

    def __init__(
        self,
        overlay: str,
        capture: str,
        capture_focused: bool,
        service: Hotkeys | None,
    ) -> None:
        super().__init__()
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        focused = QHBoxLayout()
        self.capture_focused = localized(Switch(), text=mark("Capture the focused window"))
        self.capture_focused.setChecked(capture_focused)
        help = mark(
            "When starting with the capture hotkey, select the focused window automatically. "
            "Turn off to use the main page's selection. "
            "The Start button always uses that selection. "
            "While capturing, the hotkey always stops the current session."
        )
        localized(self.capture_focused, toolTip=help)
        localized(self.capture_focused, accessibleName=mark("Capture the focused window"))
        self.capture_focused.toggled.connect(lambda _: self.changed.emit())
        focused.addWidget(self.capture_focused)
        focused.addWidget(InfoButton(mark("Capture the focused window"), help))
        focused.addStretch()
        layout.addLayout(focused)
        self.rows = {
            HotkeyAction.OVERLAY: _ShortcutRow(
                mark("Show / hide overlay"),
                mark(
                    "Toggles Show game overlay. Capture and translations keep running while hidden."
                ),
                overlay,
            ),
            HotkeyAction.CAPTURE: _ShortcutRow(
                mark("Start / stop capture"),
                mark(
                    "Starts the focused window when automatic selection is enabled above; "
                    "otherwise "
                    "uses the window selected on the main page. "
                    "Stopping ends processing; hiding the overlay keeps it running."
                ),
                capture,
            ),
        }
        for action, row in self.rows.items():
            layout.addWidget(row)
            row.apply.clicked.connect(lambda _, action=action: self._apply(action))
            row.apply.setEnabled(service is not None)
        layout.addStretch()
        on_language_change(self, self._refresh_status)

    def _refresh_status(self) -> None:
        for action, row in self.rows.items():
            self._show_status(row, action, row.committed)

    @property
    def problem(self) -> str:
        if not self._service:
            return ""
        unavailable = [
            row.committed
            for action, row in self.rows.items()
            if row.committed and self._service.shortcut(action) != row.committed
        ]
        return (
            tr(
                "Hotkey unavailable: {value}. Choose another shortcut in Settings.",
                value=", ".join(unavailable),
            )
            if unavailable
            else ""
        )

    def activate(self) -> None:
        for action, row in self.rows.items():
            self._bind(action, row.committed)

    def _bind(self, action: HotkeyAction, value: str) -> bool:
        row = self.rows[action]
        if self._service:
            try:
                self._service.bind(action, value)
                row.error = ""
            except (OSError, ValueError) as error:
                row.error = str(error)
        self._show_status(row, action, value)
        return self._service is not None and not row.error

    def _show_status(self, row: _ShortcutRow, action: HotkeyAction, value: str) -> None:
        if not self._service:
            row.status.set_message(
                tr("Global shortcuts are unavailable in this session."), tone="info"
            )
            return
        if row.error:
            current = self._service.shortcut(action)
            retained = (
                tr(" Still active: {current}.", current=current)
                if current
                else tr(" This action has no active shortcut.")
            )
            row.status.set_message(f"{row.error}{retained}")
            return
        row.status.set_message(
            tr("Active · {value}", value=value) if value else tr("Disabled"), tone="info"
        )

    def _apply(self, action: HotkeyAction) -> None:
        row = self.rows[action]
        if self._bind(action, row.draft):
            row.committed = row.draft
        self.changed.emit()
