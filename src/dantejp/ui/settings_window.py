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

from dantejp.application.hotkeys import HotkeyAction, Hotkeys
from dantejp.application.preference_values import Preferences
from dantejp.application.services import CloudCommands, SetupCommands
from dantejp.runtime.setup_values import SetupLane
from dantejp.translation.selection import OcrOption
from dantejp.ui.controls import InfoButton, StatusBanner, Switch
from dantejp.ui.hotkey_settings import HotkeySettings
from dantejp.ui.model_manager import ModelManager
from dantejp.ui.runtime_dialog import RuntimeSetupDialog


class SettingsWindow(QDialog):
    changed = Signal()
    restart_requested = Signal(object)
    runtime_created = Signal(object)

    def __init__(
        self,
        preferences: Preferences,
        ocr_choices: tuple[OcrOption, ...],
        parent: QWidget,
        *,
        cloud: CloudCommands,
        setup: SetupCommands,
        hotkeys: Hotkeys | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DanteJP · Settings")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(680, 620)
        self.setMinimumSize(540, 440)
        self._setup = setup
        self._cloud = cloud
        self._ocr_key = preferences.ocr_device
        self.runtime: RuntimeSetupDialog | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.model_notice = StatusBanner()
        self.acceleration_notice = StatusBanner()
        layout.addWidget(self.model_notice)
        layout.addWidget(self.acceleration_notice)
        self.tabs = QTabWidget()
        self._pages: dict[str, QWidget] = {}
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
            "in the Acceleration tab. AMD currently uses CPU OCR.",
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

        self.models = ModelManager(setup, self, cloud=cloud, embedded=True)
        self.models.runtime_requested.connect(self.show_runtime)
        self._pages["Models"] = self.models
        self.tabs.addTab(self.models, "Models")
        self.runtime_layout = self._page("Acceleration")
        self.runtime_layout.addStretch()
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
        experimental = self._page("Experimental")
        note = QLabel("Features under development. Results may be inaccurate or incomplete.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        experimental.addWidget(note)
        self.history_enabled = Switch("Dialogue history")
        self.history_enabled.setChecked(preferences.history_enabled)
        self._setting(
            experimental,
            self.history_enabled,
            "Dialogue history",
            "Collect recent dialogue in a separate reader. Dialogue and speaker detection may "
            "be inaccurate. Disabled by default; your choice is saved.",
        )
        history_note = QLabel(
            "When enabled, open Dialogue beside the Settings gear to choose a classifier model "
            "and read recent turns. Cloud classifiers use your plan/API allowance."
        )
        history_note.setWordWrap(True)
        experimental.addWidget(history_note)
        experimental.addStretch()
        self.tabs.currentChanged.connect(self._tab_changed)
        footer = QHBoxLayout()
        self.setup_assistant = QPushButton("Setup assistant…")
        self.setup_assistant.setToolTip(
            "Guided model downloads and optional GPU setup. Stop capture first."
        )
        footer.addWidget(self.setup_assistant)
        self.save_note = QLabel(
            "Most settings save automatically. Save model edits; apply hotkeys."
        )
        self.save_note.setWordWrap(True)
        self.save_note.setObjectName("muted")
        footer.addWidget(self.save_note, 1)
        close = QPushButton("Close settings")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        for control in (
            self.stabilize,
            self.automatic_size,
            self.group_dialogue,
            self.history_enabled,
        ):
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
        self._pages[name] = scroll
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
            history_enabled=self.history_enabled.isChecked(),
        )

    def show_hotkeys(self) -> None:
        self.tabs.setCurrentWidget(self._pages["Hotkeys"])
        self.show()
        self.raise_()

    def set_capture_active(self, active: bool) -> None:
        self.capture_note.setText(
            "Capture is running. Device and capture rate changes apply next time you start capture."
            if active
            else "Device and capture rate apply when capture starts."
        )

    def show_models(self) -> None:
        self.models.refresh()
        self.models.show()
        self.tabs.setCurrentWidget(self._pages["Models"])
        self.show()
        self.raise_()

    def show_recognition(self) -> None:
        self.tabs.setCurrentWidget(self._pages["Recognition"])
        self.show()
        self.raise_()

    def show_runtime(self) -> None:
        self.tabs.setCurrentWidget(self._pages["Acceleration"])
        if self.runtime:
            self.runtime.show()
        self.show()
        self.raise_()

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self._pages["Models"]:
            self.models.refresh()
        if self.tabs.widget(index) is self._pages["Acceleration"] and self.runtime is None:
            self.runtime = RuntimeSetupDialog(self._setup, self, embedded=True)
            self.runtime.restart_requested.connect(self.restart_requested.emit)
            self.runtime_layout.insertWidget(0, self.runtime)
            self.runtime_created.emit(self.runtime)

    @property
    def busy(self) -> bool:
        return bool(
            self._setup.job(SetupLane.MODELS).busy
            or self._setup.job(SetupLane.RUNTIME).busy
            or self._cloud.snapshot().busy
        )

    @property
    def problem(self) -> str:
        return (
            self._setup.job(SetupLane.MODELS).progress.error
            or self._cloud.snapshot().problem
            or self._setup.job(SetupLane.RUNTIME).progress.error
        )

    def cancel_operations(self) -> None:
        self._setup.cancel(SetupLane.MODELS)
        self._setup.cancel(SetupLane.RUNTIME)
        self._cloud.cancel()

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
