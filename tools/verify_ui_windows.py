"""Native layout/settings check with our own demo; no game capture or model downloads."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from verification_isolation import app_owner
from verification_isolation import create_window as MainWindow

from dantejp.application.model_factories import (
    create_recognizer,
    ocr_backends,
    translation_backends,
)
from dantejp.application.preferences import PreferenceStore
from dantejp.capture.windows import Windows
from dantejp.runtime.hardware import HardwareCheck
from dantejp.runtime.model_store import model_catalog
from dantejp.ui.controls import InfoButton
from dantejp.ui.demo import DemoWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui"))
    parser.add_argument("--missing-models", action="store_true", help="Show first-run warnings")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow(dialogue=True)
    preferences_path = args.output / f"preferences-{time.time_ns()}.json"
    hardware = HardwareCheck()
    hardware.start()
    models = model_catalog()
    if args.missing_models:
        models = tuple(
            replace(b, directory=args.output / "not-installed" / b.key, bundled_directory=None)
            for b in models
        )
    window = MainWindow(
        windows,
        create_recognizer,
        () if args.missing_models else translation_backends(),
        models=models,
        ocr_backends=ocr_backends(),
        preferences_path=preferences_path,
        hardware=hardware,
    )
    application = app_owner(window)
    # Show only our fixture name in screenshots, never another application's title.
    window.windows_combo.clear()
    window.windows_combo.addItem("DanteJP Demo · 日本語のテスト")
    window.show()
    started, stage = time.monotonic(), 0
    failed = False
    evidence = {}

    def tick():
        nonlocal stage, failed
        try:
            assert time.monotonic() - started < 20, "UI verification timed out"
            settings = window._settings
            if stage == 0:
                if not hardware.finished:
                    return
                assert not window.advanced.isChecked() and not window.advanced_panel.isVisible()
                assert window.translate_check.text() == "Translation overlay"
                QTest.keyClick(window.overlay_check, Qt.Key.Key_Space)
                assert not window.overlay_check.isChecked()
                QTest.keyClick(window.overlay_check, Qt.Key.Key_Space)
                assert window.overlay_check.isChecked()
                evidence["keyboard_switch_toggle"] = True
                assert window.border_check.isChecked()
                QTest.keyClick(window.border_check, Qt.Key.Key_Space)
                assert not window.border_check.isChecked()
                assert window.capture_overlay_check.isChecked()
                QTest.keyClick(window.capture_overlay_check, Qt.Key.Key_Space)
                assert not window.capture_overlay_check.isChecked()
                evidence["compact_size"] = [window.width(), window.height()]
                assert window.sections.game.isAncestorOf(window.status)
                assert window.start_button.property("tone") == "idle"
                assert not window.start_button.icon().isNull()
                evidence["capture_icon_and_idle_state"] = True
                window.grab().save(str(args.output / "main.png"))
                if args.missing_models:
                    assert (
                        window.onboarding.isVisible() and "not downloaded" in window.notice.text()
                    )
                    assert window.onboarding.property("tone") == "warning"
                gear = window.settings_button
                accessible = QAccessible.queryAccessibleInterface(gear)
                assert accessible and accessible.text(QAccessible.Text.Name) == "Settings"
                assert not gear.text() and gear.toolTip() and not gear.icon().pixmap(16).isNull()
                QTest.keyClick(gear, Qt.Key.Key_Space)
                stage = 1
            elif stage == 1:
                assert settings.isVisible() and not settings.isModal()
                assert [settings.tabs.tabText(i) for i in range(settings.tabs.count())] == [
                    "Appearance",
                    "Recognition",
                    "Models",
                    "Acceleration",
                    "Hotkeys",
                    "Experimental",
                ]
                assert settings.runtime is None  # Merely opening Settings does not start setup.
                assert window.stabilize_check.isChecked() and window.automatic_font.isChecked()
                settings.grab().save(str(args.output / "appearance.png"))
                settings.tabs.setCurrentIndex(settings.tabs.count() - 1)
                assert not settings.history_enabled.isChecked()
                assert not window.history_button.isVisible()
                settings.grab().save(str(args.output / "experimental.png"))
                QTest.keyClick(settings.history_enabled, Qt.Key.Key_Space)
                assert window.history_button.isVisible() and application.live.history_enabled
                dialogue = window.history_button
                accessible = QAccessible.queryAccessibleInterface(dialogue)
                assert accessible and accessible.text(QAccessible.Text.Name) == "Dialogue history"
                assert dialogue.text() == "Dialogue" and not dialogue.icon().pixmap(16).isNull()
                window.grab().save(str(args.output / "main-dialogue.png"))
                QTest.keyClick(dialogue, Qt.Key.Key_Space)
                assert window.history_panel.isVisible()
                QTest.keyClick(settings.history_enabled, Qt.Key.Key_Space)
                assert (
                    not window.history_panel.isVisible() and not window.history_button.isVisible()
                )
                assert not application.live.history_enabled
                evidence["experimental_history_opt_in"] = True
                settings.opacity.setValue(62)
                window.automatic_font.setChecked(False)
                window.font_size.setValue(24)
                settings.tabs.setCurrentIndex(1)
                stage = 2
            elif stage == 2:
                settings.set_capture_active(True)
                assert settings.ocr_device.isEnabled() and settings.capture_rate.isEnabled()
                assert "next time" in settings.capture_note.text()
                settings.grab().save(str(args.output / "recognition.png"))
                window._manage_models()
                stage = 3
            elif stage == 3:
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Models"
                assert settings.models.choice.currentData().key == "gemma"
                assert all(
                    settings.models.choice.itemData(i).key != "ocr"
                    for i in range(settings.models.choice.count())
                )
                assert settings.models.ocr.choice.currentData().key == "ocr"
                assert not settings.models.ocr.details.isVisible()
                expected = (
                    "Download required"
                    if args.missing_models
                    else "Included with app"
                    if settings.models.choice.currentData().included
                    else "Downloaded"
                )
                assert expected in settings.models.download_badge.text()
                settings.grab().save(str(args.output / "models.png"))
                gemma = next(
                    (
                        i
                        for i in range(settings.models.choice.count())
                        if settings.models.choice.itemData(i).key == "gemma"
                    ),
                    None,
                )
                if gemma is not None:
                    settings.models.choice.setCurrentIndex(gemma)
                stage = 31
            elif stage == 31:
                description = settings.models.description
                assert description.height() >= description.heightForWidth(description.width()), (
                    "Model description is clipped after changing selection"
                )
                key = settings.models.choice.currentData().key
                summary = settings.models.summary
                assert summary.isVisible() and summary.cpu.text() == "✓ CPU support"
                if key.startswith("plamo-"):
                    assert summary.values[1].property("tone") == "error"
                if key == "qwen35-4b":
                    assert summary.values[2].text() == "✕ Slow"
                settings.grab().save(str(args.output / f"{key}-status.png"))
                following = {
                    "gemma": "plamo-2b",
                    "plamo-2b": "plamo-0.8b",
                    "plamo-0.8b": "qwen35-4b",
                    "qwen35-4b": "gemma-e4b",
                }.get(key)
                index = next(
                    (
                        i
                        for i in range(settings.models.choice.count())
                        if settings.models.choice.itemData(i).key == following
                    ),
                    -1,
                )
                if index >= 0:
                    settings.models.choice.setCurrentIndex(index)
                    return
                settings.resize(550, 470)
                stage = 32
            elif stage == 32:
                description = settings.models.description
                assert description.height() >= description.heightForWidth(description.width()), (
                    "Model description is clipped in compact Settings"
                )
                settings.grab().save(str(args.output / "model-small.png"))
                settings.resize(680, 620)
                settings.models.category.setCurrentIndex(1)
                settings.models.ocr.manage.click()
                stage = 33
            elif stage == 33:
                assert settings.models.ocr.details.isVisible()
                settings.models.ocr_page.ensureWidgetVisible(settings.models.ocr.download)
                stage = 34
            elif stage == 34:
                assert "does not translate" in settings.models.ocr.summary.text()
                assert settings.models.pages.currentWidget() is settings.models.ocr_page
                assert not settings.models.choice.isVisible()
                assert settings.models.category.isVisible()
                settings.grab().save(str(args.output / "ocr-models.png"))
                evidence["separate_model_pages_with_fixed_menu"] = True
                settings.models.category.setCurrentIndex(0)
                settings.models.runtime_button.click()
                stage = 4
            elif stage == 4:
                if settings.busy:
                    return
                assert window._runtime_dialog and window._runtime_dialog.isVisible()
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Acceleration"
                assert (
                    not application.translation.lifecycle.publication and not application.live.ocr
                )
                settings.grab().save(str(args.output / "runtime.png"))
                runtime = settings.runtime
                settings.show_hotkeys()
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Hotkeys"
                settings.show_models()
                settings.show_runtime()
                assert (
                    settings.runtime is runtime
                )  # Navigating never replaces an active setup view.
                evidence["separate_setup_tabs_and_navigation"] = True
                settings.resize(550, 470)
                stage = 5
            elif stage == 5:
                assert settings.width() <= 550, "Settings minimum width broke the compact layout"
                settings.grab().save(str(args.output / "settings-small.png"))
                assert all(
                    b.accessibleName() and b.toolTip() for b in settings.findChildren(InfoButton)
                )
                settings.close()
                # Background setup notices may have enlarged the main window since startup.
                evidence["before_expansion_height"] = window.height()
                window.advanced.setChecked(True)
                stage = 6
            elif stage == 6:
                assert window.advanced_panel.isVisible()
                assert window.processing.isVisible()
                assert all(
                    card.isVisible()
                    for card in (
                        window.processing.capture,
                        window.processing.ocr,
                        window.processing.translation,
                    )
                )
                window.processing.grab().save(str(args.output / "processing.png"))
                window.grab().save(str(args.output / "advanced.png"))
                window.advanced.setChecked(False)
                if not application.preferences.idle:
                    return
                saved = PreferenceStore(preferences_path).initial
                assert saved.opacity == 62 and saved.text_size == 24 and not saved.automatic_size
                assert not saved.show_border
                assert not saved.include_overlay_in_capture
                evidence["capture_inclusion_preference_saved"] = True
                evidence["border_preference_saved"] = True
                evidence.update(
                    settings_saved=True, info_controls=len(settings.findChildren(InfoButton))
                )
                window.showMaximized()
                stage = 8
            elif stage == 8:
                assert window.isMaximized()
                assert window.control_panel.width() > 760 and window.control_panel.height() < 850
                assert window.sections.translation.x() > window.sections.game.x()
                assert window.control_panel.mapTo(window, QPoint()).y() <= 24
                assert window.translate_check.mapTo(window, QPoint()).x() < 450
                assert window.border_check.y() == window.translate_check.y()
                assert window.border_check.x() > window.translate_check.x()
                assert window.windows_combo.mapTo(window, QPoint()).y() < 200
                window.grab().save(str(args.output / "maximized.png"))
                window.advanced.setChecked(True)
                stage = 9
            elif stage == 9:
                assert window.isMaximized() and window.advanced_panel.isVisible()
                window.grab().save(str(args.output / "maximized-advanced.png"))
                window.advanced.setChecked(False)
                stage = 10
            elif stage == 10:
                assert window.isMaximized() and not window.advanced_panel.isVisible()
                evidence["maximized_controls_stay_compact_and_left"] = True
                evidence["advanced_preserves_maximized_state"] = True
                window.showNormal()
                stage = 11
            elif stage == 11:
                window.close()
                stage = 7
            elif stage == 7:
                if window.isVisible():
                    return
                assert window.height() <= evidence["before_expansion_height"], (
                    "Collapsing Advanced did not restore its previous compact height"
                )
                evidence["shutdown_finished"] = True
                (args.output / "results.json").write_text(json.dumps(evidence, indent=2), "utf-8")
                print(json.dumps(evidence), flush=True)
                timer.stop()
                app.quit()
        except Exception as error:
            failed = True
            print(f"FAIL at stage {stage}: {error!r}", flush=True)
            timer.stop()
            window._settings.cancel_operations()
            window.hide()
            app.quit()

    timer = QTimer()
    timer.setInterval(180)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    demo.close()
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    from verification_isolation import run_isolated

    run_isolated(main)
