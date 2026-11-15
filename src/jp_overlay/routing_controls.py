"""Model assignment presentation; committed choices survive disclosure and preparation."""

from dataclasses import replace

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jp_overlay.cloud_values import PROVIDERS
from jp_overlay.controls import InfoButton, StatusBanner, Switch, add_model_section
from jp_overlay.model_selection import AssignmentChange, ModelOption
from jp_overlay.preference_values import Preferences
from jp_overlay.translation_plan import TranslationPlan


def model_reference(choice: ModelOption | None) -> str:
    return choice.reference if choice else ""


class RoutingControls(QWidget):
    changed = Signal()
    model_requested = Signal(object)
    disclosure_changed = Signal()

    def __init__(self, preferences: Preferences) -> None:
        super().__init__()
        self.setObjectName("routingSurface")
        self._backends: tuple[ModelOption, ...] = ()
        self._profiles: tuple[ModelOption, ...] = ()
        self._view_plan = TranslationPlan()
        self._window_title = ""
        self._manual_game = preferences.game_hint
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(QLabel("Model assignment"))
        header.addWidget(
            InfoButton(
                "Model assignment",
                "Use one model for all enabled text, or assign a model to each category. Only "
                "recognized text and the game hint are sent to cloud models; images stay on "
                "this PC.",
            )
        )
        header.addStretch()
        self.advanced = Switch("Advanced routing")
        self.advanced.setChecked(preferences.advanced_routing)
        self.advanced.setToolTip(
            "Replace the single model selector with a model for each text category. Changing "
            "this view does not change your assignments."
        )
        header.addWidget(self.advanced)
        layout.addLayout(header)
        self.simple = self._combo("Translation model")
        self.simple.currentIndexChanged.connect(self._simple_changed)
        self.simple.activated.connect(self._simple_changed)
        layout.addWidget(self.simple)
        self.category_fields = QWidget()
        self.category_fields.setObjectName("routingSurface")
        categories = QGridLayout(self.category_fields)
        categories.setContentsMargins(0, 0, 0, 0)
        categories.setHorizontalSpacing(16)
        categories.setVerticalSpacing(10)
        self.short_enabled = Switch("Short labels")
        self.long_enabled = Switch("Long text & dialogue")
        self.short_enabled.setToolTip(
            "Translate short menus, buttons and names. Off leaves this text in Japanese and "
            "makes no translation requests for it."
        )
        self.long_enabled.setToolTip(
            "Translate grouped paragraphs and text over 40 characters, including dialogue, "
            "skill and item descriptions. This is a length/layout category, not a speaker "
            "detector."
        )
        self.short_model = self._combo("Model for short labels")
        self.long_model = self._combo("Model for long text and dialogue")
        for row, (toggle, picker) in enumerate(
            ((self.short_enabled, self.short_model), (self.long_enabled, self.long_model))
        ):
            categories.addWidget(toggle, row, 0)
            categories.addWidget(picker, row, 1)
        categories.setColumnStretch(1, 1)
        layout.addWidget(self.category_fields)
        self.short_model.currentIndexChanged.connect(lambda: self._category_changed(False))
        self.long_model.currentIndexChanged.connect(lambda: self._category_changed(True))
        self.short_model.activated.connect(lambda: self._category_changed(False))
        self.long_model.activated.connect(lambda: self._category_changed(True))
        self.short_enabled.toggled.connect(self._scope_changed)
        self.long_enabled.toggled.connect(self._scope_changed)
        self.memory_notice = StatusBanner()
        layout.addWidget(self.memory_notice)
        self.cloud_fields = QWidget()
        self.cloud_fields.setObjectName("routingSurface")
        fields = QVBoxLayout(self.cloud_fields)
        fields.setContentsMargins(0, 0, 0, 0)
        game_row = QHBoxLayout()
        game_row.addWidget(QLabel("Game name"))
        game_row.addWidget(
            InfoButton(
                "Game name",
                "Sent to cloud models as a terminology hint. The selected game window title is "
                "the default; switch this off to enter a clearer name or leave it blank. Local "
                "prompts are unchanged.",
            )
        )
        game_row.addStretch()
        self.game_from_window = Switch("Use window title")
        self.game_from_window.setChecked(preferences.game_from_window)
        game_row.addWidget(self.game_from_window)
        fields.addLayout(game_row)
        self.game = QLineEdit(preferences.game_hint)
        self.game.setAccessibleName("Game name sent to cloud")
        self.game.setMaxLength(120)
        self.game.setPlaceholderText("Optional game name")
        fields.addWidget(self.game)
        layout.addWidget(self.cloud_fields)
        self.plan_notice = QWidget()
        self.plan_notice.setObjectName("routingSurface")
        plan_row = QHBoxLayout(self.plan_notice)
        plan_row.setContentsMargins(0, 0, 0, 0)
        plan_row.addWidget(QLabel("Using ChatGPT plan"))
        manage = QPushButton("Manage usage ↗")
        manage.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://chatgpt.com/settings/usage"))
        )
        plan_row.addWidget(manage)
        plan_row.addStretch()
        layout.addWidget(self.plan_notice)
        self.game.editingFinished.connect(self._game_edited)
        self.game_from_window.toggled.connect(self._game_mode_changed)
        self.advanced.toggled.connect(self._disclosed)
        self._game_mode_changed()
        self._render()

    @staticmethod
    def _combo(name: str) -> QComboBox:
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setMinimumContentsLength(18)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setToolTip("Download or configure models in Settings → Models.")
        return combo

    @property
    def selection(self) -> TranslationPlan:
        return self._view_plan

    def set_selection(self, plan: TranslationPlan) -> None:
        self._view_plan = plan
        self._render()

    def resolve(self, reference: str) -> ModelOption | None:
        return next(
            (
                choice
                for choice in (*self._backends, *self._profiles)
                if model_reference(choice) == reference
            ),
            None,
        )

    @property
    def active_cloud(self) -> tuple[ModelOption, ...]:
        return tuple(
            c
            for key in self.selection.active_models
            if (c := self.resolve(key)) is not None and not c.local
        )

    @property
    def active_local(self) -> tuple[ModelOption, ...]:
        return tuple(
            c
            for key in self.selection.active_models
            if (c := self.resolve(key)) is not None and c.local
        )

    @property
    def game_hint(self) -> str:
        return " ".join(self.game.text().split())[:120]

    @property
    def manual_game_hint(self) -> str:
        return self._manual_game

    def set_window_title(self, title: str) -> None:
        title = " ".join(title.split())[:120]
        if title != self._window_title:
            self._window_title = title
            if self.game_from_window.isChecked():
                self.game.setText(title)
                self.changed.emit()

    def _game_mode_changed(self) -> None:
        automatic = self.game_from_window.isChecked()
        self.game.setReadOnly(automatic)
        self.game.setText(self._window_title if automatic else self._manual_game)
        self.changed.emit()

    def _game_edited(self) -> None:
        if not self.game_from_window.isChecked():
            self._manual_game = self.game_hint
            self.changed.emit()

    def set_models(self, options: tuple[ModelOption, ...], plan: TranslationPlan) -> None:
        local = tuple(c for c in options if c.local)
        cloud = tuple(c for c in options if not c.local)
        if (local, cloud, plan) == (self._backends, self._profiles, self._view_plan):
            return
        self._backends, self._profiles, self._view_plan = local, cloud, plan
        self._render()

    def _fill(self, combo: QComboBox, reference: str, *, custom: bool = False) -> None:
        combo.blockSignals(True)
        combo.clear()
        if self._backends:
            add_model_section(combo, "Local models")
            for backend in self._backends:
                combo.addItem(backend.name + " · Local", backend)
        for provider, label in PROVIDERS.items():
            profiles = tuple(p for p in self._profiles if p.provider == provider)
            if profiles:
                label = label.replace(" · API key", " API")
                add_model_section(combo, label)
                for profile in profiles:
                    combo.addItem(profile.name + " · " + label, profile)
        index = next(
            (
                i
                for i in range(combo.count())
                if isinstance(combo.itemData(i), ModelOption)
                and model_reference(combo.itemData(i)) == reference
            ),
            -1,
        )
        if custom:
            placeholder = "Different models · enable Advanced routing"
            index = -1
        elif reference and index < 0:
            placeholder = "Model unavailable · open Settings"
        else:
            placeholder = (
                "Choose a model" if combo.count() else "No models available · open Settings"
            )
        combo.setPlaceholderText(placeholder)
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _render(self) -> None:
        plan = self.selection
        self._fill(self.simple, plan.short, custom=plan.short != plan.long)
        self._fill(self.short_model, plan.short)
        self._fill(self.long_model, plan.long)
        for toggle, enabled in (
            (self.short_enabled, plan.short_enabled),
            (self.long_enabled, plan.long_enabled),
        ):
            toggle.blockSignals(True)
            toggle.setChecked(enabled)
            toggle.blockSignals(False)
        self.short_model.setEnabled(plan.short_enabled)
        self.long_model.setEnabled(plan.long_enabled)
        self.memory_notice.set_message(
            "Two local models stay loaded together. RAM / VRAM use can roughly double; choose "
            "the same model in both rows to share one copy."
            if plan.two_local_models
            else ""
        )
        self.cloud_fields.setVisible(bool(self.active_cloud))
        self.plan_notice.setVisible(any(p.provider == "chatgpt" for p in self.active_cloud))
        self._disclosed(notify=False)

    def _disclosed(self, *, notify: bool = True) -> None:
        advanced = self.advanced.isChecked()
        self.simple.setVisible(not advanced)
        self.short_model.setVisible(advanced)
        self.long_model.setVisible(advanced)
        if notify:
            self.disclosure_changed.emit()

    def _simple_changed(self) -> None:
        choice = self.simple.currentData()
        if not isinstance(choice, ModelOption):
            return
        key = model_reference(choice)
        self.model_requested.emit(
            AssignmentChange(replace(self.selection, short=key, long=key), key)
        )

    def _category_changed(self, long: bool) -> None:
        choice = (self.long_model if long else self.short_model).currentData()
        if not isinstance(choice, ModelOption):
            return
        plan = replace(self.selection, **{"long" if long else "short": model_reference(choice)})
        self.model_requested.emit(AssignmentChange(plan, choice.reference))

    def _scope_changed(self) -> None:
        plan = replace(
            self.selection,
            short_enabled=self.short_enabled.isChecked(),
            long_enabled=self.long_enabled.isChecked(),
        )
        self.model_requested.emit(AssignmentChange(plan))

    def focus_model(self) -> None:
        combo = self.long_model if self.advanced.isChecked() else self.simple
        combo.setFocus()
        combo.showPopup()

    @property
    def summary(self) -> str:
        return " / ".join(
            c.name for key in self.selection.active_models if (c := self.resolve(key))
        )
