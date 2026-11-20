"""Account controls for the Models page; authentication lives outside Qt."""

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dantetl.i18n import mark, tr
from dantetl.translation.cloud.values import USAGE_URL, ChatGPTAccount
from dantetl.ui.localization import localized


class ChatGPTControls(QWidget):
    account_changed = Signal()
    sign_in_requested = Signal()
    sign_out_requested = Signal()
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.account = QComboBox()
        localized(self.account, accessibleName=mark("ChatGPT account"))
        self.account.setMinimumContentsLength(16)
        self.account.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        layout.addWidget(self.account)
        actions = QHBoxLayout()
        self.sign_in = localized(QPushButton(), text=mark("Continue with ChatGPT"))
        self.sign_out = localized(QPushButton(), text=mark("Sign out"))
        self.refresh_models = localized(QPushButton(), text=mark("Refresh models"))
        for button in (self.sign_in, self.sign_out, self.refresh_models):
            actions.addWidget(button)
        layout.addLayout(actions)
        note = localized(
            QLabel(),
            text=mark(
                "Use your ChatGPT plan. To use only its included allowance, disable credit use "
                "for DanteTL in ChatGPT's usage settings. No automatic API-key fallback."
            ),
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.manage = localized(QPushButton(), text=mark("Manage ChatGPT usage ↗"))
        self.manage.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(USAGE_URL)))
        layout.addWidget(self.manage)
        self.account.currentIndexChanged.connect(self._changed)
        self.sign_in.clicked.connect(self.sign_in_requested.emit)
        self.sign_out.clicked.connect(self.sign_out_requested.emit)
        self.refresh_models.clicked.connect(self.refresh_requested.emit)
        self.refresh(())

    @property
    def selected(self) -> ChatGPTAccount | None:
        account = self.account.currentData()
        return account if isinstance(account, ChatGPTAccount) else None

    def refresh(self, accounts: tuple[ChatGPTAccount, ...], selected: str = "") -> None:
        if not selected and self.selected:
            selected = self.selected.key
        self.account.blockSignals(True)
        self.account.clear()
        for account in accounts:
            self.account.addItem(("✓ " if account.enabled else "○ ") + account.label, account)
            if account.key == selected:
                self.account.setCurrentIndex(self.account.count() - 1)
        self.account.addItem(tr("＋ Add ChatGPT account"), None)
        self.account.blockSignals(False)
        self._update_buttons()

    def _changed(self) -> None:
        self._update_buttons()
        self.account_changed.emit()

    def _update_buttons(self) -> None:
        self.sign_out.setEnabled(bool(self.selected and self.selected.enabled))
        self.refresh_models.setEnabled(bool(self.selected and self.selected.enabled))
