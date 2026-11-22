import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from dantetl.application.preference_values import Preferences  # noqa: E402
from dantetl.translation.cloud.values import CloudProfile  # noqa: E402
from dantetl.translation.plan import TranslationPlan  # noqa: E402
from dantetl.translation.selection import ModelOption  # noqa: E402
from dantetl.ui.routing_controls import RoutingControls  # noqa: E402


def test_independent_pickers_disclosure_scope_and_memory_warning(app):
    a, b = (
        ModelOption("local:gemma", "A", "gemma"),
        ModelOption("local:gemma-e4b", "B", "gemma-e4b"),
    )
    cloud = cloud_option("openai")
    controls = RoutingControls(Preferences())
    controls.set_models((a, b, cloud), TranslationPlan(a.reference, a.reference))
    controls.model_requested.connect(lambda change: controls.set_selection(change.plan))
    controls.show()
    try:
        controls.advanced.setChecked(True)
        assert controls.simple.isHidden() and not controls.short_model.isHidden()
        controls.long_model.setCurrentIndex(controls.long_model.findData(b))
        assert controls.selection == TranslationPlan("local:gemma", "local:gemma-e4b")
        assert not controls.memory_notice.isHidden()
        controls.short_enabled.setChecked(False)
        assert controls.memory_notice.isHidden() and not controls.short_model.isEnabled()
        plan = controls.selection
        for _ in range(4):
            controls.advanced.setChecked(not controls.advanced.isChecked())
            assert controls.selection == plan
        controls.long_model.setCurrentIndex(controls.long_model.findData(cloud))
        assert controls.selection.long == "cloud:" + cloud.key
        assert controls.cloud_fields.isVisible()
        controls.advanced.setChecked(False)
        controls.simple.setCurrentIndex(controls.simple.findData(a))
        assert controls.selection == TranslationPlan(
            "local:gemma", "local:gemma", short_enabled=False
        )
        assert controls.cloud_fields.isHidden() and controls.memory_notice.isHidden()
    finally:
        controls.close()
        controls.deleteLater()


def test_window_title_default_and_manual_override_survive_game_changes(app):
    controls = RoutingControls(Preferences(game_hint="Remember this"))
    try:
        controls.set_window_title("  Game A  \n 日本語 ")
        assert controls.game_hint == "Game A 日本語" and controls.game.isReadOnly()
        controls.game_from_window.setChecked(False)
        assert controls.game_hint == "Remember this"
        controls.game.setText("Honkai Star Rail")
        controls.game.editingFinished.emit()
        controls.set_window_title("Game B")
        assert controls.game_hint == "Honkai Star Rail"
        controls.game_from_window.setChecked(True)
        assert controls.game_hint == "Game B"
        controls.game_from_window.setChecked(False)
        assert controls.game_hint == "Honkai Star Rail"
    finally:
        controls.deleteLater()


def test_missing_cloud_option_preserves_projected_plan_and_game_hint(app):
    cloud = cloud_option("openai")
    local = ModelOption("local:gemma", "Local", "gemma")
    prefs = replace(
        Preferences(),
        translation_route="long",
        cloud_model=cloud.key,
        game_hint="Honkai",
        game_from_window=False,
    )
    controls = RoutingControls(prefs)
    try:
        controls.set_models((local, cloud), TranslationPlan(local.reference, cloud.reference))
        assert controls.selection == TranslationPlan("local:gemma", "cloud:" + cloud.key)
        assert controls.game_hint == "Honkai"
        # Discovery refresh is presentation, not permission to pick a replacement model.
        controls.set_models((local,), controls.selection)
        assert controls.selection.long == "cloud:" + cloud.key
    finally:
        controls.deleteLater()


def test_sections_skip_headings_and_only_model_choices_request_changes(app):
    local = ModelOption("local:gemma", "Gemma", "gemma")
    openai, deepseek = cloud_option("openai"), cloud_option("deepseek")
    controls = RoutingControls(Preferences())
    requests = []
    controls.model_requested.connect(requests.append)
    controls.set_models(
        (local, deepseek, openai), TranslationPlan(local.reference, local.reference)
    )
    controls.show()
    app.processEvents()
    try:
        combo = controls.simple
        assert [combo.itemText(i) for i in range(combo.count()) if combo.itemData(i) is None] == [
            "Local models",
            "OpenAI API",
            "DeepSeek API",
        ]
        assert combo.findText("No translation model") == -1
        assert not requests  # Filling/refreshing is never a model change.
        for i in range(combo.count()):
            if combo.itemData(i) is None:
                assert not combo.model().index(i, 0).flags() & Qt.ItemFlag.ItemIsSelectable
                assert not combo.model().index(i, 0).flags() & Qt.ItemFlag.ItemIsEnabled
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert combo.currentData() == openai and requests[-1].reference == openai.reference
        QTest.keyClick(combo, Qt.Key.Key_Down)
        assert combo.currentData() == deepseek and requests[-1].reference == deepseek.reference
        assert {request.reference for request in requests} == {openai.reference, deepseek.reference}
        count = len(requests)
        combo.setCurrentIndex(-1)
        combo.activated.emit(-1)
        assert len(requests) == count  # A placeholder cannot clear an assignment.
        controls.set_selection(TranslationPlan("local:gemma", "cloud:" + openai.key))
        assert combo.currentIndex() == -1 and "Different models" in combo.placeholderText()
        assert len(requests) == count
    finally:
        controls.close()
        controls.deleteLater()


def test_empty_and_missing_models_are_placeholders_without_implicit_replacement(app):
    controls = RoutingControls(Preferences(model="none"))
    requests = []
    controls.model_requested.connect(requests.append)
    try:
        controls.set_models((), controls.selection)
        assert controls.simple.count() == 0 and controls.simple.currentIndex() == -1
        assert "No models available" in controls.simple.placeholderText()
        local = ModelOption("local:gemma", "Gemma", "gemma")
        controls.set_models((local,), controls.selection)
        assert controls.simple.currentIndex() == -1
        assert controls.simple.placeholderText() == "Choose a model"
        controls.set_selection(TranslationPlan("local:missing", "local:missing"))
        assert controls.simple.currentIndex() == -1
        assert "Model unavailable" in controls.simple.placeholderText()
        assert controls.selection.short == "local:missing" and not requests
        controls.set_selection(TranslationPlan("local:gemma", "local:gemma"))
        controls.set_models((), controls.selection)
        assert controls.selection.short == "local:gemma" and not requests
        assert controls.simple.currentIndex() == -1
    finally:
        controls.deleteLater()


def cloud_option(provider):
    profile = CloudProfile.new(provider)
    return ModelOption("cloud:" + profile.key, profile.name, profile.key, provider=provider)
