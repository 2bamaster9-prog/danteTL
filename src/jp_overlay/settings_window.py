"""One nonmodal settings window owns appearance, recognition and background setup views."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.controls import InfoButton, StatusBanner, Switch
from jp_overlay.hotkey_settings import HotkeySettings
from jp_overlay.hotkeys import HotkeyAction, Hotkeys
from jp_overlay.model_manager import ModelManager
from jp_overlay.model_store import ModelBundle
from jp_overlay.preferences import Preferences
from jp_overlay.recognition import OcrChoice
from jp_overlay.runtime_dialog import RuntimeSetupDialog


class SettingsWindow(QDialog):
    changed = Signal()
    models_changed = Signal()
    restart_requested = Signal(object)
    runtime_created = Signal(object)

    def __init__(
        self,
        preferences: Preferences,
        ocr_choices: tuple[OcrChoice, ...],
        models: tuple[ModelBundle, ...],
        parent: QWidget,
        *,
        hotkeys: Hotkeys | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("JP Overlay · Settings")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(680, 620)
        self.setMinimumSize(540, 440)
        self._ocr_key = preferences.ocr_device
        self.runtime: RuntimeSetupDialog | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.model_notice = StatusBanner()
        self.acceleration_notice = StatusBanner()
        layout.addWidget(self.model_notice)
        layout.addWidget(self.acceleration_notice)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        appearance = self._page("Appearance")
        self.stabilize = Switch("Stabilize game boxes")
        self.stabilize.setChecked(preferences.stabilize)
        self._setting(
            appearance,
            self.stabilize,
            "Stabilize game boxes",
            "Keeps detected boxes steady when OCR jitters. Turn off only to inspect raw OCR boxes. "
            "Translation always uses stable tracking.",
        )
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(preferences.opacity)
        self.opacity_value = QLabel(f"{preferences.opacity}%")
        self._setting(
            appearance,
            self.opacity,
            "Background opacity",
            "Higher values hide more of the original text. Lower values reveal more of the game "
            "behind the translation.",
            self.opacity_value,
        )
        self.automatic_size = Switch("Automatic text size")
        self.automatic_size.setChecked(preferences.automatic_size)
        self._setting(
            appearance,
            self.automatic_size,
            "Automatic text size",
            "Starts near the original text height, then wraps and shrinks within limits "
            "to fit the English.",
        )
        self.text_size = QSpinBox()
        self.text_size.setRange(10, 60)
        self.text_size.setValue(preferences.text_size)
        self.text_size.setSuffix(" px")
        self.text_size.setMaximumWidth(160)
        self.text_size.setEnabled(not preferences.automatic_size)
        self._setting(
            appearance,
            self.text_size,
            "Text size",
            "Fixed English font size in physical pixels. "
            "Used only when Automatic text size is off.",
        )
        appearance.addStretch()

        recognition = self._page("Recognition")
        self.group_dialogue = Switch("Group dialogue lines")
        self.group_dialogue.setChecked(preferences.group_dialogue)
        self._setting(
            recognition,
            self.group_dialogue,
            "Group dialogue lines",
            "Translates nearby lines from the same dialogue panel together. Turn off if unrelated "
            "text is being joined.",
        )
        self.ocr_device = QComboBox()
        for choice in ocr_choices:
            self.ocr_device.addItem(choice.name, choice)
        for index, choice in enumerate(ocr_choices):
            if choice.key == preferences.ocr_device:
                self.ocr_device.setCurrentIndex(index)
                break
        self._setting(
            recognition,
            self.ocr_device,
            "OCR device",
            "Chooses the device that reads Japanese text, separately from the translation model. "
            "Automatic reports CPU fallback when acceleration cannot be used. Install acceleration "
            "under Models & runtime. AMD currently uses CPU OCR.",
        )
        self.capture_rate = QSpinBox()
        self.capture_rate.setRange(2, 12)
        self.capture_rate.setSuffix(" samples/s")
        self.capture_rate.setMaximumWidth(200)
        self.capture_rate.setValue(preferences.capture_rate)
        self._setting(
            recognition,
            self.capture_rate,
            "Capture rate",
            "How often the app checks the game image for changes, not OCR calls per second. "
            "Higher rates use more resources and cannot speed up a busy OCR worker.",
        )
        self.capture_note = QLabel("Device and capture rate apply when capture starts.")
        self.capture_note.setWordWrap(True)
        self.capture_note.setObjectName("muted")
        recognition.addWidget(self.capture_note)
        recognition.addStretch()

        setup = self._page("Models & runtime")
        self.setup_tabs = QTabWidget()
        self.models = ModelManager(models, self, embedded=True)
        self.models.models_changed.connect(self.models_changed.emit)
        self.models.runtime_requested.connect(self.show_runtime)
        self.setup_tabs.addTab(self.models, "Models")
        self.runtime_host = QWidget()
        self.runtime_layout = QVBoxLayout(self.runtime_host)
        self.runtime_layout.setContentsMargins(0, 0, 0, 0)
        self.setup_tabs.addTab(self.runtime_host, "Acceleration")
        self.setup_tabs.currentChanged.connect(self._setup_tab_changed)
        setup.addWidget(self.setup_tabs)
        setup.addStretch()
        shortcuts = self._page("Hotkeys")
        self.hotkeys = HotkeySettings(
            preferences.overlay_hotkey,
            preferences.capture_hotkey,
            preferences.original_hotkey,
            preferences.capture_focused_window,
            hotkeys,
        )
        self.hotkeys.changed.connect(self.changed.emit)
        shortcuts.addWidget(self.hotkeys)
        footer = QHBoxLayout()
        self.save_note = QLabel(
            "Changes save automatically; hotkeys save when applied. Downloads require your action."
        )
        self.save_note.setWordWrap(True)
        self.save_note.setObjectName("muted")
        footer.addWidget(self.save_note, 1)
        close = QPushButton("Close settings")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        for control in (self.stabilize, self.automatic_size, self.group_dialogue):
            control.toggled.connect(lambda _: self.changed.emit())
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.text_size.valueChanged.connect(lambda _: self.changed.emit())
        self.capture_rate.valueChanged.connect(lambda _: self.changed.emit())
        self.automatic_size.toggled.connect(lambda enabled: self.text_size.setEnabled(not enabled))
        self.ocr_device.currentIndexChanged.connect(self._ocr_changed)

    def _page(self, name: str) -> QVBoxLayout:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return layout

    def _setting(
        self,
        layout: QVBoxLayout,
        control: QWidget,
        name: str,
        help: str,
        suffix: QWidget | None = None,
    ) -> None:
        control.setAccessibleName(name)
        control.setToolTip(help)
        header = QHBoxLayout()
        if isinstance(control, Switch):
            header.addWidget(control)
        else:
            label = QLabel(name)
            label.setBuddy(control)
            header.addWidget(label)
        header.addWidget(InfoButton(name, help))
        header.addStretch()
        if suffix:
            header.addWidget(suffix)
        layout.addLayout(header)
        if not isinstance(control, Switch):
            layout.addWidget(control)

    def _opacity_changed(self, value: int) -> None:
        self.opacity_value.setText(f"{value}%")
        self.changed.emit()

    def _ocr_changed(self) -> None:
        choice = self.ocr_device.currentData()
        self._ocr_key = choice.key or "cpu"
        self.changed.emit()

    def values(self, *, show_overlay: bool, translation: bool, model: str) -> Preferences:
        return Preferences(
            show_overlay=show_overlay,
            translation=translation,
            stabilize=self.stabilize.isChecked(),
            opacity=self.opacity.value(),
            automatic_size=self.automatic_size.isChecked(),
            text_size=self.text_size.value(),
            group_dialogue=self.group_dialogue.isChecked(),
            ocr_device=self._ocr_key,
            capture_rate=self.capture_rate.value(),
            model=model,
            overlay_hotkey=self.hotkeys.rows[HotkeyAction.OVERLAY].committed,
            capture_hotkey=self.hotkeys.rows[HotkeyAction.CAPTURE].committed,
            original_hotkey=self.hotkeys.rows[HotkeyAction.ORIGINAL].committed,
            capture_focused_window=self.hotkeys.capture_focused.isChecked(),
        )

    def show_hotkeys(self) -> None:
        self.tabs.setCurrentIndex(3)
        self.show()
        self.raise_()

    def set_capture_active(self, active: bool) -> None:
        self.capture_note.setText(
            "Capture is running. Device and capture rate changes apply next time you start capture."
            if active
            else "Device and capture rate apply when capture starts."
        )

    def show_models(self) -> None:
        if self.models.operation is None:
            self.models._selected()
        self.models.show()
        self.tabs.setCurrentIndex(2)
        self.setup_tabs.setCurrentIndex(0)
        self.show()
        self.raise_()

    def show_recognition(self) -> None:
        self.tabs.setCurrentIndex(1)
        self.show()
        self.raise_()

    def show_runtime(self) -> None:
        self.tabs.setCurrentIndex(2)
        self.setup_tabs.setCurrentIndex(1)
        self._setup_tab_changed(1)
        if self.runtime:
            self.runtime.show()
        self.show()
        self.raise_()

    def _setup_tab_changed(self, index: int) -> None:
        if index == 1 and self.runtime is None:
            self.runtime = RuntimeSetupDialog(self, embedded=True)
            self.runtime.restart_requested.connect(self.restart_requested.emit)
            self.runtime_layout.addWidget(self.runtime)
            self.runtime_created.emit(self.runtime)

    @property
    def busy(self) -> bool:
        return bool(self.models.operation or (self.runtime and self.runtime.operation))

    @property
    def problem(self) -> str:
        return self.models.error_message or (self.runtime.error_message if self.runtime else "")

    def cancel_operations(self) -> None:
        self.models._cancel()
        if self.runtime and self.runtime.operation:
            self.runtime.cancel_operation()

    def reject(self) -> None:
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.busy:
            question = QMessageBox(self)
            question.setWindowTitle("Setup is still running")
            question.setText("Keep setup running after closing Settings?")
            background = question.addButton(
                "Continue in background", QMessageBox.ButtonRole.AcceptRole
            )
            question.addButton("Cancel operation", QMessageBox.ButtonRole.DestructiveRole)
            question.setDefaultButton(background)
            question.exec()
            if question.clickedButton() != background:
                self.cancel_operations()
        event.accept()
