"""Small explicit shortcut editor: choosing keys cannot accidentally trigger an action."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dantejp.application.hotkeys import KEYS, MODIFIERS, HotkeyAction, Hotkeys
from dantejp.ui.controls import InfoButton, StatusBanner, Switch


class _ShortcutRow(QWidget):
    def __init__(self, name: str, help: str, value: str) -> None:
        super().__init__()
        self.committed = value
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel(name))
        header.addWidget(InfoButton(name, help))
        header.addStretch()
        layout.addLayout(header)
        fields = QHBoxLayout()
        self.modifiers = QComboBox()
        self.modifiers.addItems(list(MODIFIERS))
        self.modifiers.setAccessibleName(f"{name} modifiers")
        self.key = QComboBox()
        self.key.addItem("Disabled", "")
        for key in KEYS:
            self.key.addItem(key, key)
        self.key.setAccessibleName(f"{name} key")
        self.apply = QPushButton("Apply")
        self.apply.setAccessibleName(f"Apply {name} shortcut")
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
        original: str,
        capture_focused: bool,
        service: Hotkeys | None,
    ) -> None:
        super().__init__()
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "Shortcuts work while the game has focus or DanteJP is minimized. "
            "Choose a combination, then Apply. Select Disabled to turn an action off."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        focused = QHBoxLayout()
        self.capture_focused = Switch("Capture the focused window")
        self.capture_focused.setChecked(capture_focused)
        help = (
            "When starting with the capture hotkey, select the focused window automatically. "
            "Turn off to use the main page's selection. "
            "The Start button always uses that selection. "
            "While capturing, the hotkey always stops the current session."
        )
        self.capture_focused.setToolTip(help)
        self.capture_focused.setAccessibleName("Capture the focused window")
        self.capture_focused.toggled.connect(lambda _: self.changed.emit())
        focused.addWidget(self.capture_focused)
        focused.addWidget(InfoButton("Capture the focused window", help))
        focused.addStretch()
        layout.addLayout(focused)
        self.rows = {
            HotkeyAction.OVERLAY: _ShortcutRow(
                "Show / hide overlay",
                "Toggles Show game overlay. Capture and translations keep running while hidden.",
                overlay,
            ),
            HotkeyAction.CAPTURE: _ShortcutRow(
                "Start / stop capture",
                "Starts the focused window when automatic selection is enabled above; otherwise "
                "uses the window selected on the main page. "
                "Stopping ends processing; hiding the overlay keeps it running.",
                capture,
            ),
            HotkeyAction.ORIGINAL: _ShortcutRow(
                "Hold to show original",
                "Temporarily hides the overlay while the shortcut is held. Releasing any key "
                "restores its current visibility setting immediately. "
                "OCR and translation continue; "
                "nothing is restarted. Focus loss cancels the hold.",
                original,
            ),
        }
        for action, row in self.rows.items():
            layout.addWidget(row)
            row.apply.clicked.connect(lambda _, action=action: self._apply(action))
            row.apply.setEnabled(service is not None)
        note = QLabel(
            "Avoid combinations used by your game. Windows shortcuts and F12 are reserved. "
            "Toggle shortcuts do not repeat while held."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        layout.addStretch()

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
            f"Hotkey unavailable: {', '.join(unavailable)}. Choose another shortcut in Settings."
            if unavailable
            else ""
        )

    def activate(self) -> None:
        for action, row in self.rows.items():
            self._bind(action, row.committed)

    def _bind(self, action: HotkeyAction, value: str) -> bool:
        row = self.rows[action]
        if not self._service:
            row.status.set_message("Global shortcuts are unavailable in this session.", tone="info")
            return False
        try:
            self._service.bind(action, value)
        except (OSError, ValueError) as error:
            current = self._service.shortcut(action)
            retained = (
                f" Still active: {current}." if current else " This action has no active shortcut."
            )
            row.status.set_message(f"{error}{retained}")
            return False
        row.status.set_message(f"Active · {value}" if value else "Disabled", tone="info")
        return True

    def _apply(self, action: HotkeyAction) -> None:
        row = self.rows[action]
        if self._bind(action, row.draft):
            row.committed = row.draft
        self.changed.emit()
